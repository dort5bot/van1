# utils/binance/binance_circuit_breaker.py
"""
Geliştirilmiş Circuit Breaker implementation.

Özellikler:
- Async / sync uyumluluğu (sync fonksiyonlar executor'da çalıştırılır)
- Configurable failure_predicate: hangi hataların 'failure' sayılacağını belirler
- Half-open test concurrency kontrolü (max_half_open_calls)
- Manual record_failure / record_success hook'ları
- Metrics / hooks (on_open, on_half_open, on_close, on_failure, on_success)
- Detailed typing ve docstrings
"""
from __future__ import annotations

import asyncio
import time
import logging
import inspect
from dataclasses import dataclass
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Optional, Dict, Tuple


# Kullanıcı tarafı özel exception'larınızdan biri (var sayılıyor)
from .binance_exceptions import BinanceCircuitBreakerError

logger = logging.getLogger(__name__)


@dataclass
class CircuitBreakerState:
    failures: int = 0
    last_failure_time: float = 0.0
    state: str = "CLOSED"  # "CLOSED", "OPEN", "HALF_OPEN"


# Tipler
AsyncCallable = Callable[..., Awaitable[Any]]
SyncOrAsyncCallable = Callable[..., Any]
FailurePredicate = Callable[[Exception], bool]
HookCallable = Callable[[Dict[str, Any]], None]


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout: float = 60.0,
        half_open_timeout: float = 30.0,
        max_half_open_calls: int = 1,
        name: str = "binance_circuit_breaker",
        failure_predicate: Optional[FailurePredicate] = None,
        on_open: Optional[HookCallable] = None,
        on_half_open: Optional[HookCallable] = None,
        on_close: Optional[HookCallable] = None,
        on_failure: Optional[HookCallable] = None,
        on_success: Optional[HookCallable] = None,
    ):
        """
        Args:
            failure_threshold: arka arkaya başarısız çağrı sayısı -> OPEN
            reset_timeout: OPEN durumundan HALF_OPEN'a geçiş için bekleme (saniye)
            half_open_timeout: HALF_OPEN durumunda test süresi (saniye)
            max_half_open_calls: HALF_OPEN durumunda eş zamanlı izin verilen test çağrı sayısı
            name: isim (log için)
            failure_predicate: Exception -> bool. True ise o exception failure olarak sayılır.
            on_open/on_half_open/on_close/on_failure/on_success: opsiyonel hook fonksiyonları.
        """
        self.failure_threshold = int(failure_threshold)
        self.reset_timeout = float(reset_timeout)
        self.half_open_timeout = float(half_open_timeout)
        self.max_half_open_calls = int(max_half_open_calls)
        self.name = name

        self.state = CircuitBreakerState()
        self._lock = asyncio.Lock()
        # half-open test concurrency kontrolü
        self._half_open_semaphore = asyncio.Semaphore(self.max_half_open_calls)

        # Hooks
        self.failure_predicate = failure_predicate or self._default_failure_predicate
        self.on_open = on_open
        self.on_half_open = on_half_open
        self.on_close = on_close
        self.on_failure = on_failure
        self.on_success = on_success

        logger.info(f"✅ CircuitBreaker '{self.name}' initialized")

    # ---------- Public API ----------
    async def execute(self, func: SyncOrAsyncCallable, *args, **kwargs) -> Any:
        """
        Execute the callable under circuit breaker protection.

        func can be a coroutine function or a sync function. Sync functions
        will be executed in the default executor.
        """
        # İlk state kontrolü (kısa, lock'un gereksiz tutulmasını engellemek için)
        await self._pre_execute_check()

        # Eğer fonksiyon sync ise executor'da çalıştır (non-blocking)
        is_coro = inspect.iscoroutinefunction(func)
        try:
            if is_coro:
                result = await self._invoke_async(func, *args, **kwargs)
            else:
                # sync fonksiyon -> executor
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, lambda: func(*args, **kwargs))
            # başarı işlemleri
            await self.record_success()
            return result
        except Exception as ex:
            # hata sayılacak mı kontrolü
            is_failure = False
            try:
                is_failure = self.failure_predicate(ex)
            except Exception as pred_ex:
                # predicate kendi içinde hata verirse, güvenlik nedeniyle "failure" say
                logger.exception("Failure predicate raised an exception; counting as failure", exc_info=pred_ex)
                is_failure = True

            if is_failure:
                await self.record_failure(ex)
            # Hook: yine de kullanıcıya hatayı fırlat
            raise

    async def _invoke_async(self, coro_func: AsyncCallable, *args, **kwargs) -> Any:
        """
        İç çağırı: HALF_OPEN durumunda semaphore ile test sayısını sınırla.
        """
        # Eğer HALF_OPEN ise semaphore'ya bağlan (max_half_open_calls)
        if self.is_half_open():
            # try to acquire a slot for testing
            acquired = await self._half_open_semaphore.acquire()  # acquires
            try:
                # çağrıyı yap
                return await coro_func(*args, **kwargs)
            finally:
                # serbest bırak
                self._half_open_semaphore.release()
        else:
            # normal durumda doğrudan çağır
            return await coro_func(*args, **kwargs)

    # ---------- State management ----------
    async def _pre_execute_check(self) -> None:
        """Check current state and possibly transition to HALF_OPEN or raise."""
        async with self._lock:
            now = time.time()
            st = self.state.state
            if st == "OPEN":
                elapsed = now - self.state.last_failure_time
                if elapsed >= self.reset_timeout:
                    # OPEN -> HALF_OPEN
                    self.state.state = "HALF_OPEN"
                    # reset failures for half-open testing but keep last_failure_time for metrics
                    # not resetting failures to 0 allows us to keep historical count if needed
                    logger.warning(f"⚠️ CircuitBreaker '{self.name}' transitioned OPEN -> HALF_OPEN (elapsed {elapsed:.1f}s)")
                    if self.on_half_open:
                        self._safe_call_hook(self.on_half_open, self.get_state())
                else:
                    retry_in = max(0.0, self.reset_timeout - elapsed)
                    raise BinanceCircuitBreakerError(
                        f"Circuit breaker '{self.name}' is OPEN. Retry in {retry_in:.1f}s"
                    )
            # if HALF_OPEN we allow execution but concurrency limited in _invoke_async

    async def record_failure(self, error: Optional[Exception] = None) -> None:
        """Record a failure and update state if threshold reached."""
        async with self._lock:
            self.state.failures += 1
            self.state.last_failure_time = time.time()
            now = self.state.last_failure_time

            # Eğer HALF_OPEN ise, bir başarısızlık direkt OPEN yapar
            if self.state.state == "HALF_OPEN":
                self.state.state = "OPEN"
                logger.error(f"❌ CircuitBreaker '{self.name}' moved HALF_OPEN -> OPEN due to failure (error: {error})")
                if self.on_open:
                    self._safe_call_hook(self.on_open, self.get_state())
            elif self.state.state == "CLOSED" and self.state.failures >= self.failure_threshold:
                self.state.state = "OPEN"
                logger.error(f"❌ CircuitBreaker '{self.name}' opened (failures={self.state.failures})")
                if self.on_open:
                    self._safe_call_hook(self.on_open, self.get_state())
            # çağrıya özel hook
            if self.on_failure:
                self._safe_call_hook(self.on_failure, {"error": error, **self.get_state()})

    async def record_success(self) -> None:
        """Record a success: HALF_OPEN -> CLOSED (reset), or decrement/reset failures in CLOSED."""
        async with self._lock:
            if self.state.state == "HALF_OPEN":
                # Başarı: circuit'i kapat
                self.state.failures = 0
                self.state.state = "CLOSED"
                self.state.last_failure_time = 0.0
                logger.info(f"✅ CircuitBreaker '{self.name}' HALF_OPEN -> CLOSED (successful test)")
                if self.on_close:
                    self._safe_call_hook(self.on_close, self.get_state())
            else:
                # Normal başarı: failures sıfırlanabilir veya azaltılabilir (burada sıfırlıyoruz)
                self.state.failures = 0
                if self.on_success:
                    self._safe_call_hook(self.on_success, self.get_state())

    async def reset(self) -> None:
        """Manual reset to CLOSED."""
        async with self._lock:
            self.state.failures = 0
            self.state.state = "CLOSED"
            self.state.last_failure_time = 0.0
            logger.info(f"🔄 CircuitBreaker '{self.name}' manually reset to CLOSED")
            if self.on_close:
                self._safe_call_hook(self.on_close, self.get_state())

    async def force_open(self) -> None:
        async with self._lock:
            self.state.state = "OPEN"
            self.state.last_failure_time = time.time()
            logger.warning(f"⚠️ CircuitBreaker '{self.name}' manually forced OPEN")
            if self.on_open:
                self._safe_call_hook(self.on_open, self.get_state())

    # ---------- Queries ----------
    def is_closed(self) -> bool:
        return self.state.state == "CLOSED"

    def is_open(self) -> bool:
        return self.state.state == "OPEN"

    def is_half_open(self) -> bool:
        return self.state.state == "HALF_OPEN"

    def get_state(self) -> Dict[str, Any]:
        return {
            "state": self.state.state,
            "failures": self.state.failures,
            "last_failure_time": self.state.last_failure_time,
            "time_since_last_failure": (time.time() - self.state.last_failure_time) if self.state.last_failure_time else 0.0,
            "name": self.name,
        }

    # ---------- Utilities ----------
    @staticmethod
    def _default_failure_predicate(exc: Exception) -> bool:
        """
        Default failure predicate: çoğu durumda exception bir HTTP response wrapper ise
        'status_code' attribute'u kontrol edilir. Yoksa genel olarak True döner
        (yani exception failure sayılır). Kullanıcı bunu overwrite etmelidir.
        """
        # Eğer HTTP response içeren özel exception'ınız varsa burada parse edin.
        # Örnek: kullanıcı kendi BinanceHTTPError sınıfını kullanıyorsa, onun .status_code'una bakarak
        # 400'leri failure ya da non-failure olarak kategorize edebilir.
        status = getattr(exc, "status_code", None)
        if isinstance(status, int):
            # 5xx ve 429'ı failure say (sunucu hatası ve rate-limit)
            if status >= 500 or status == 429:
                return True
            # 401 (unauthorized) -> genelde authentication hatası: circuit breaker için
            # opsiyonel olarak başarısız sayılabilir; burada False döndürüyoruz, çünkü
            # auth hatası farklı yol izlemeli (ör: anahtar yenileme).
            if status == 401:
                return False
            # diğer 4xx'ler tipik olarak kullanıcı hatası => genelde failure sayılmaz
            return False
        # Eğer exception tipi belirli ise (örnek: TimeoutError)
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            return True
        # Default: say
        return True

    def _safe_call_hook(self, hook: HookCallable, payload: Dict[str, Any]) -> None:
        try:
            hook(payload)
        except Exception:
            logger.exception("CircuitBreaker hook raised an exception", exc_info=True)




class CircuitBreakerManager:
    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout: float = 60.0,
        half_open_timeout: float = 30.0,
        max_half_open_calls: int = 1,
        failure_predicate: Optional[FailurePredicate] = None,
        on_open: Optional[HookCallable] = None,
        on_half_open: Optional[HookCallable] = None,
        on_close: Optional[HookCallable] = None,
        on_failure: Optional[HookCallable] = None,
        on_success: Optional[HookCallable] = None,
        max_cache_size: int = 1000,  # 🔁 LRU cache için maksimum breaker sayısı
        ttl_seconds: int = 3600,     # 🔁 TTL: circuit breaker 1 saat boyunca kullanılmazsa silinir
    ):
        """
        Args:
            max_cache_size: CircuitBreaker cache'inde tutulacak maksimum kullanıcı+endpoint sayısı.
            ttl_seconds: Son erişimden itibaren bu saniye kadar kullanılmayan circuit breaker temizlenir.
            Diğer args CircuitBreaker config ile aynıdır.
        """
        self._lock = asyncio.Lock()
        self._breaker_map: "OrderedDict[Tuple[str,str], Tuple[CircuitBreaker, float]]" = OrderedDict()
        # key -> (breaker, last_access_time)

        self._config = {
            "failure_threshold": failure_threshold,
            "reset_timeout": reset_timeout,
            "half_open_timeout": half_open_timeout,
            "max_half_open_calls": max_half_open_calls,
            "failure_predicate": failure_predicate,
            "on_open": on_open,
            "on_half_open": on_half_open,
            "on_close": on_close,
            "on_failure": on_failure,
            "on_success": on_success,
        }

        self.max_cache_size = max_cache_size
        self.ttl_seconds = ttl_seconds

    async def _evict_expired_and_lru(self):
        """
        TTL süresi geçen veya LRU sınırını aşan breaker'ları sil.
        """
        now = time.time()
        keys_to_delete = []

        # TTL kontrolü
        for key, (_, last_access) in self._breaker_map.items():
            if now - last_access > self.ttl_seconds:
                keys_to_delete.append(key)

        for key in keys_to_delete:
            del self._breaker_map[key]

        # LRU kontrolü: max_cache_size aşıyorsa en eski(ilk) elemanları sil
        while len(self._breaker_map) > self.max_cache_size:
            self._breaker_map.popitem(last=False)  # first (en eski) elemanı çıkar

    async def get_breaker(self, user_id: str, endpoint: str = "default") -> CircuitBreaker:
        """
        Kullanıcı+endpoint bazında breaker objesini döner.
        Yoksa oluşturur, varsa erişimi günceller (LRU).
        """
        key = (user_id, endpoint)
        async with self._lock:
            await self._evict_expired_and_lru()

            if key in self._breaker_map:
                # LRU için order güncelle
                breaker, _ = self._breaker_map.pop(key)
                self._breaker_map[key] = (breaker, time.time())
                return breaker

            # Yeni breaker oluştur
            name = f"cb:{user_id}:{endpoint}"
            breaker = CircuitBreaker(name=name, **self._config)
            self._breaker_map[key] = (breaker, time.time())
            return breaker

    async def execute(self, user_id: str, endpoint: str, func: Callable[..., Any], *args, **kwargs):
        """
        Tek satırda breaker'lı fonksiyon çağrısı (async/sync farketmez)
        """
        breaker = await self.get_breaker(user_id, endpoint)
        return await breaker.execute(func, *args, **kwargs)

    async def force_open(self, user_id: str, endpoint: str = "default"):
        breaker = await self.get_breaker(user_id, endpoint)
        await breaker.force_open()

    async def reset(self, user_id: str, endpoint: str = "default"):
        breaker = await self.get_breaker(user_id, endpoint)
        await breaker.reset()

    async def remove(self, user_id: str, endpoint: str = "default"):
        """
        İsteğe bağlı: belirli bir breaker'ı cache'den tamamen çıkar.
        """
        key = (user_id, endpoint)
        async with self._lock:
            self._breaker_map.pop(key, None)

    async def cleanup(self):
        """
        İsteğe bağlı: dışardan manuel cache temizleme tetiklemesi.
        """
        async with self._lock:
            await self._evict_expired_and_lru()

    def get_all_states(self) -> Dict[str, Dict]:
        """
        Breaker durumlarının anlık snapshot'u (sync)
        """
        return {
            f"{user_id}:{endpoint}": breaker.get_state()
            for (user_id, endpoint), (breaker, _) in self._breaker_map.items()
        }
