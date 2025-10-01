# utils/binance/binance_metrics.py
"""
Metrics and monitoring for Binance API.

Özellikler:
- Tamamen async / thread-safe / atomic operations
- HTTP status code, Binance-specific error code parsing
- Rate-limit weight parsing (örn. X-MBX-USED-WEIGHT-1m, X-MBX-USED-WEIGHT-1s)
- Granular error counters (http_429, binance_code_-2015, TimeoutError, etc.)
- Prometheus exposition helper
- aiogram 3.x router örneği (opsiyonel, aiogram yüklüyse kullanılabilir)
- Singleton pattern (thread-safe) + logging
"""

from __future__ import annotations

import time
import asyncio
from typing import Dict, List, Any, Optional, Tuple, Union
from dataclasses import dataclass, field
from collections import deque, Counter
from threading import Lock
import statistics
import logging
import json

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class RequestMetrics:
    """API request metrics snapshot."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_response_time: float = 0.0
    response_times: deque = field(default_factory=lambda: deque(maxlen=5000))  # recent latencies
    errors_by_type: Counter = field(default_factory=Counter)
    status_counters: Counter = field(default_factory=Counter)  # e.g. http_200, http_429
    binance_code_counters: Counter = field(default_factory=Counter)  # e.g. binance_code_-2015

@dataclass
class RateLimitMetrics:
    """Rate limit usage counters."""
    weight_used_1m: int = 0
    weight_limit_1m: int = 1200
    last_reset_time_1m: float = field(default_factory=time.time)
    weight_used_1s: int = 0
    weight_limit_1s: int = 20
    last_reset_time_1s: float = field(default_factory=time.time)

# ---------------------------------------------------------------------------
# AdvancedMetrics singleton
# ---------------------------------------------------------------------------

class AdvancedMetrics:
    """
    Thread-safe advanced async metrics collection.

    Usage:
        metrics = AdvancedMetrics.get_instance()
        await metrics.record_response(response_obj, start_time=ts)
        await metrics.get_metrics()
    """
    _instance: Optional["AdvancedMetrics"] = None
    _class_lock: Lock = Lock()

    def __new__(cls, *args, **kwargs) -> "AdvancedMetrics":
        # Enforce singleton
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                # initialize instance attributes
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, window_size: int = 5000) -> None:
        # __init__ may be called multiple times on singleton; guard initialization
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        self.window_size = window_size
        self.request_metrics = RequestMetrics()
        self.rate_limit_metrics = RateLimitMetrics()
        self.start_time = time.time()

        # Async lock for coroutine safety
        self._async_lock = asyncio.Lock()
        logger.info("AdvancedMetrics initialized (async thread-safe)")

    # ---------- Internal helpers ----------

    @staticmethod
    def _safe_percentile(values: List[float], pct: float) -> float:
        """Return percentile using statistics.quantiles (robust)."""
        try:
            if not values:
                return 0.0
            # statistics.quantiles returns (n-1) cut points; use method='inclusive' for compatibility >=3.8
            n = 100
            q = statistics.quantiles(values, n=n, method="inclusive")
            index = min(max(int(pct * (n - 1)), 0), n - 2)
            return q[index]
        except Exception:
            # Fallback simple approach
            try:
                vals = sorted(values)
                k = max(0, min(len(vals) - 1, int(len(vals) * pct)))
                return vals[k]
            except Exception:
                return 0.0

    @staticmethod
    def _now() -> float:
        return time.time()

    @staticmethod
    def _parse_binance_error_code_from_body(body: Union[str, bytes, Dict[str, Any], None]) -> Optional[int]:
        """
        Try to parse binance-specific error code from response body.
        Binance often returns: {"code": -2015, "msg": "..." } or nested structures.
        """
        if body is None:
            return None
        try:
            if isinstance(body, (bytes, bytearray)):
                body = body.decode("utf-8", errors="ignore")
            if isinstance(body, str):
                parsed = json.loads(body)
            else:
                parsed = body  # assume dict-like

            if isinstance(parsed, dict):
                code = parsed.get("code")
                if isinstance(code, int):
                    return code
                # sometimes nested error
                for k in ("error", "error_code", "err"):
                    if k in parsed and isinstance(parsed[k], int):
                        return parsed[k]
        except Exception:
            return None
        return None

    # ---------- Public API ----------

    async def record_response(
        self,
        *,
        status_code: Optional[int] = None,
        response_body: Union[str, bytes, Dict[str, Any], None] = None,
        headers: Optional[Dict[str, Any]] = None,
        start_time: Optional[float] = None,
        error: Optional[Exception] = None,
        weight_hint: Optional[int] = None,
    ) -> None:
        """
        Record a request/response.

        Args:
            status_code: HTTP status code if available
            response_body: body content (may contain Binance 'code')
            headers: response headers (for weight parsing)
            start_time: epoch seconds when request started (for response_time calc)
            error: Exception instance if raised
            weight_hint: optional explicit weight (if client computed it)
        """
        if start_time is None:
            response_time = 0.0
        else:
            response_time = max(0.0, self._now() - start_time)

        # parse useful info
        binance_code = self._parse_binance_error_code_from_body(response_body)
        http_status = int(status_code) if status_code is not None else None

        # weight parsing from headers (many libs provide these keys on Binance)
        weight_1m = None
        weight_1s = None
        if headers:
            # common headers used by Binance variants (case-insensitive)
            # e.g. 'x-mbx-used-weight-1m', 'x-mbx-used-weight-1s'
            for k, v in headers.items():
                lk = k.lower()
                try:
                    if "used-weight-1m" in lk:
                        weight_1m = int(v)
                    elif "used-weight-1s" in lk:
                        weight_1s = int(v)
                except Exception:
                    continue

        # If caller passed a weight_hint, prefer it for 1m
        if weight_hint is not None:
            weight_1m = weight_hint

        # Compose error_type string for counters
        if error is not None:
            err_type = type(error).__name__
        elif binance_code is not None:
            err_type = f"binance_code_{binance_code}"
        elif http_status is not None and (http_status < 200 or http_status >= 300):
            err_type = f"http_{http_status}"
        else:
            err_type = "unknown"

        # Now perform atomic update
        async with self._async_lock:
            rm = self.request_metrics
            rm.total_requests += 1
            rm.total_response_time += response_time
            rm.response_times.append(response_time)

            # status handling
            if http_status is not None:
                rm.status_counters[f"http_{http_status}"] += 1
            # success if 2xx and no error provided
            if error is None and (http_status is None or 200 <= http_status < 300):
                rm.successful_requests += 1
            else:
                rm.failed_requests += 1
                if err_type:
                    rm.errors_by_type[err_type] += 1

            # binance code counter
            if binance_code is not None:
                rm.binance_code_counters[f"binance_code_{binance_code}"] += 1

            # parse common critical statuses for quick access (duplicate with counters but useful)
            if http_status == 429:
                rm.errors_by_type["http_429"] += 1
            if http_status == 418:
                rm.errors_by_type["http_418"] += 1
            if http_status == 401:
                rm.errors_by_type["http_401"] += 1

            # rate limit update (1m and 1s)
            if weight_1m is not None:
                # treat header as current used weight (absolute)
                self.rate_limit_metrics.weight_used_1m = int(weight_1m)
                self.rate_limit_metrics.last_reset_time_1m = self.rate_limit_metrics.last_reset_time_1m or self._now()
            if weight_1s is not None:
                self.rate_limit_metrics.weight_used_1s = int(weight_1s)
                self.rate_limit_metrics.last_reset_time_1s = self.rate_limit_metrics.last_reset_time_1s or self._now()

            # if caller provided an explicit weight_hint and no header, accumulate
            if weight_hint is not None and weight_1m is None:
                self.rate_limit_metrics.weight_used_1m += int(weight_hint)

    async def record_rate_limit_increment(self, *, weight_1m_inc: int = 0, weight_1s_inc: int = 0) -> None:
        """Manual increment of rate limit usage (useful if client calculates weight before response)."""
        async with self._async_lock:
            if weight_1m_inc:
                self.rate_limit_metrics.weight_used_1m += int(weight_1m_inc)
            if weight_1s_inc:
                self.rate_limit_metrics.weight_used_1s += int(weight_1s_inc)

    async def reset_rate_limits(self, *, reset_1m: bool = True, reset_1s: bool = True, new_limits: Optional[Dict[str, int]] = None) -> None:
        """Reset rate limit windows (call when your cron detects bucket reset)."""
        async with self._async_lock:
            now = self._now()
            if reset_1m:
                self.rate_limit_metrics.weight_used_1m = 0
                self.rate_limit_metrics.last_reset_time_1m = now
            if reset_1s:
                self.rate_limit_metrics.weight_used_1s = 0
                self.rate_limit_metrics.last_reset_time_1s = now
            if new_limits:
                if "1m" in new_limits:
                    self.rate_limit_metrics.weight_limit_1m = new_limits["1m"]
                if "1s" in new_limits:
                    self.rate_limit_metrics.weight_limit_1s = new_limits["1s"]

    async def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics snapshot."""
        async with self._async_lock:
            rm = self.request_metrics
            rates = self.rate_limit_metrics
            values = list(rm.response_times)
            total = rm.total_requests
            success = rm.successful_requests
            failed = rm.failed_requests

            avg = (rm.total_response_time / total) if total > 0 else 0.0
            p95 = self._safe_percentile(values, 0.95)
            p99 = self._safe_percentile(values, 0.99)

            uptime = self._now() - self.start_time
            uptime_minutes = uptime / 60 if uptime > 0 else 1.0

            current_rpm = total / uptime_minutes if uptime_minutes > 0 else 0.0

            weight_used = rates.weight_used_1m
            weight_limit = rates.weight_limit_1m

            metrics = {
                "uptime_seconds": uptime,
                "total_requests": total,
                "successful_requests": success,
                "failed_requests": failed,
                "success_rate": (success / total * 100.0) if total > 0 else 100.0,
                "average_response_time": avg,
                "min_response_time": min(values) if values else 0.0,
                "max_response_time": max(values) if values else 0.0,
                "p95_response_time": p95,
                "p99_response_time": p99,
                "current_rpm": current_rpm,
                "weight_used_1m": weight_used,
                "weight_limit_1m": weight_limit,
                "weight_remaining_1m": max(0, weight_limit - weight_used),
                "weight_percentage_1m": (weight_used / weight_limit * 100.0) if weight_limit > 0 else 0.0,
                "errors_by_type": dict(rm.errors_by_type),
                "status_counters": dict(rm.status_counters),
                "binance_code_counters": dict(rm.binance_code_counters),
                "last_rate_limit_reset_seconds_ago_1m": self._now() - rates.last_reset_time_1m,
            }
            return metrics

    async def get_health_status(self) -> Dict[str, Any]:
        """Return health status summary derived from metrics."""
        metrics = await self.get_metrics()
        success_rate = metrics["success_rate"]
        avg_rt = metrics["average_response_time"]
        p95 = metrics["p95_response_time"]
        weight_pct = metrics["weight_percentage_1m"]

        status = "HEALTHY"
        issues: List[str] = []
        warnings: List[str] = []

        if success_rate < 90.0:
            status = "CRITICAL"
            issues.append(f"Low success rate: {success_rate:.1f}%")
        elif success_rate < 95.0:
            status = "DEGRADED"
            warnings.append(f"Low success rate: {success_rate:.1f}%")

        if avg_rt > 3.0:
            status = "CRITICAL"
            issues.append(f"High avg response time: {avg_rt:.2f}s")
        elif avg_rt > 1.5:
            if status == "HEALTHY":
                status = "DEGRADED"
            warnings.append(f"Elevated avg response time: {avg_rt:.2f}s")

        if p95 > 5.0:
            status = "CRITICAL"
            issues.append(f"High p95 response time: {p95:.2f}s")
        elif p95 > 2.5:
            if status == "HEALTHY":
                status = "DEGRADED"
            warnings.append(f"High p95 response time: {p95:.2f}s")

        if weight_pct > 95.0:
            status = "CRITICAL"
            issues.append(f"Rate limit near exhausted: {weight_pct:.1f}%")
        elif weight_pct > 80.0:
            if status == "HEALTHY":
                status = "DEGRADED"
            warnings.append(f"High rate limit usage: {weight_pct:.1f}%")

        return {
            "status": status,
            "issues": issues,
            "warnings": warnings,
            "metrics": metrics,
            "timestamp": self._now(),
        }

    async def get_performance_summary(self) -> Dict[str, Any]:
        """Return a human-friendly performance summary and recommendations."""
        metrics = await self.get_metrics()
        grade = self._calculate_performance_grade(metrics)
        recs = self._generate_recommendations(metrics)
        return {
            "performance_grade": grade,
            "recommendations": recs,
            "key_metrics": {
                "success_rate": metrics["success_rate"],
                "average_response_time": metrics["average_response_time"],
                "p95_response_time": metrics["p95_response_time"],
                "current_rpm": metrics["current_rpm"],
                "weight_utilization": metrics["weight_percentage_1m"],
            },
            "detailed_metrics": metrics,
        }

    def _calculate_performance_grade(self, metrics: Dict[str, Any]) -> str:
        score = 0
        sr = metrics.get("success_rate", 100.0)
        avg = metrics.get("average_response_time", 0.0)
        weight_pct = metrics.get("weight_percentage_1m", 0.0)
        if sr >= 99.0:
            score += 2
        elif sr >= 95.0:
            score += 1
        if avg <= 0.5:
            score += 2
        elif avg <= 1.0:
            score += 1
        if weight_pct <= 50.0:
            score += 1
        grades = {5: "A", 4: "B", 3: "C", 2: "D", 1: "E", 0: "F"}
        return grades.get(score, "F")

    def _generate_recommendations(self, metrics: Dict[str, Any]) -> List[str]:
        recs: List[str] = []
        if metrics["success_rate"] < 95.0:
            recs.append("Investigate high failure types; implement retries with exponential backoff.")
        if metrics["average_response_time"] > 1.0:
            recs.append("Optimize request frequency and batching; check slow endpoints.")
        if metrics["weight_percentage_1m"] > 70.0:
            recs.append("Reduce weight usage, add request spreading or multiple API keys.")
        if not recs:
            recs.append("System performing within acceptable bounds.")
        return recs

    async def reset(self) -> None:
        """Reset all counters and rate-limit usage."""
        async with self._async_lock:
            self.request_metrics = RequestMetrics()
            self.rate_limit_metrics = RateLimitMetrics()
            self.start_time = self._now()
            logger.info("AdvancedMetrics reset completed")

    # ---------- Helpers for external systems ----------

    async def as_prometheus(self) -> str:
        """
        Return a Prometheus-compatible exposition string (text format).
        Not a full Prometheus client implementation - simple exporter for scraping.
        """
        m = await self.get_metrics()
        lines: List[str] = []
        # Basic gauges
        lines.append(f"# HELP binance_uptime_seconds Uptime in seconds")
        lines.append(f"# TYPE binance_uptime_seconds gauge")
        lines.append(f"binance_uptime_seconds {m['uptime_seconds']:.3f}")

        lines.append("# HELP binance_total_requests Total number of requests")
        lines.append("binance_total_requests_total %d" % m["total_requests"])

        lines.append("# HELP binance_success_rate Success rate (percent)")
        lines.append("binance_success_rate_percent %.3f" % m["success_rate"])

        lines.append("# HELP binance_average_response_time_seconds Average response time seconds")
        lines.append("binance_average_response_time_seconds %.6f" % m["average_response_time"])

        lines.append("# HELP binance_p95_response_time_seconds P95 response time seconds")
        lines.append("binance_p95_response_time_seconds %.6f" % m["p95_response_time"])

        lines.append("# HELP binance_weight_used_1m Current used weight (1m)")
        lines.append("binance_weight_used_1m %d" % m["weight_used_1m"])

        # errors_by_type as labels
        for name, cnt in m["errors_by_type"].items():
            safe_name = name.replace('"', "'")
            lines.append(f'binance_errors_total{{type="{safe_name}"}} {cnt}')

        # status counters
        for name, cnt in m["status_counters"].items():
            lines.append(f'binance_status_total{{status="{name}"}} {cnt}')

        # binance codes
        for name, cnt in m["binance_code_counters"].items():
            lines.append(f'binance_binance_code_total{{code="{name}"}} {cnt}')

        return "\n".join(lines) + "\n"

    # ---------- class-level accessors ----------

    @classmethod
    def get_instance(cls) -> "AdvancedMetrics":
        """Return singleton instance (synchronous accessor)."""
        return cls()

# Module-level convenience functions
async def record_response(
    *,
    status_code: Optional[int] = None,
    response_body: Union[str, bytes, Dict[str, Any], None] = None,
    headers: Optional[Dict[str, Any]] = None,
    start_time: Optional[float] = None,
    error: Optional[Exception] = None,
    weight_hint: Optional[int] = None,
) -> None:
    """Convenience function to record a response using global singleton."""
    metrics = AdvancedMetrics.get_instance()
    await metrics.record_response(
        status_code=status_code,
        response_body=response_body,
        headers=headers,
        start_time=start_time,
        error=error,
        weight_hint=weight_hint,
    )

async def get_current_metrics() -> Dict[str, Any]:
    metrics = AdvancedMetrics.get_instance()
    return await metrics.get_metrics()

async def get_health_status() -> Dict[str, Any]:
    metrics = AdvancedMetrics.get_instance()
    return await metrics.get_health_status()

async def reset_metrics() -> None:
    metrics = AdvancedMetrics.get_instance()
    await metrics.reset()

# ---------------------------------------------------------------------------
# aiogram 3.x Router integration (opsiyonel)
# ---------------------------------------------------------------------------
# Eğer aiogram projende metrics'i bot üzerinden göstermek istersen, aşağıdaki
# router'ı doğrudan import edip main router'ına include edebilirsin.
try:
    from aiogram import Router, F
    from aiogram.types import Message
    from aiogram.filters import Command

    metrics_router = Router()

    @metrics_router.message(Command(commands=["metrics", "metrics_status"]))
    async def _metrics_status_handler(message: Message) -> None:
        """
        /metrics veya /metrics_status komutu ile anlık health status döner.
        Aiogram 3.x ile uyumludur.
        """
        metrics = await get_current_metrics()
        health = await get_health_status()
        # Özet bir cevap - detay için user'a raw metrics verilebilir veya Prometheus endpoint'e yönlendirilebilir.
        txt = (
            f"Status: {health['status']}\n"
            f"Success rate: {metrics['success_rate']:.2f}%\n"
            f"Avg RT: {metrics['average_response_time']:.3f}s | p95: {metrics['p95_response_time']:.3f}s\n"
            f"Weight 1m: {metrics['weight_used_1m']}/{metrics['weight_limit_1m']} ({metrics['weight_percentage_1m']:.1f}%)\n"
            f"Issues: {', '.join(health['issues']) if health['issues'] else 'None'}\n"
            f"Warnings: {', '.join(health['warnings']) if health['warnings'] else 'None'}"
        )
        await message.answer(txt)

except Exception:
    # aiogram yüklü değilse veya farklı versiyon sorun çıkarsa sessizce geç.
    metrics_router = None

# ---------------------------------------------------------------------------
# Usage helpers for HTTP clients (examples)
# ---------------------------------------------------------------------------
# Aşağıdaki örnek fonksiyonlar, popüler async HTTP istemcileri için nasıl
# metrics kaydı yapılacağını gösterir. Bunları client kodunda çağırabilirsin.
#
# Example for aiohttp:
#
#   start = time.time()
#   async with session.get(url, headers=...) as resp:
#       body = await resp.text()
#       await record_response(status_code=resp.status, response_body=body,
#                             headers=resp.headers, start_time=start)
#
# Example for httpx:
#
#   start = time.time()
#   resp = await client.get(url)
#   await record_response(status_code=resp.status_code, response_body=resp.text,
#                         headers=resp.headers, start_time=start)
#
# Eğer hata fırlatılırsa:
#
#   try:
#       ...
#   except Exception as e:
#       await record_response(status_code=None, response_body=None,
#                             headers=None, start_time=start, error=e)
#
# Bu modülün amacı: client'lara minimal invaziv olmak. İstersen client wrapper
# seviyesinde helper fonksiyonlar yazıp otomatik çağırılmasını sağlayabilirsin.

# ---------------------------------------------------------------------------
# End of file
# ---------------------------------------------------------------------------
