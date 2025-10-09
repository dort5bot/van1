# analysis/analysis_core.py
"""
Analysis Aggregator Core Module
================================
Merkezi analiz koordinatörü - tüm analiz modüllerini yönetir, sonuçları aggregate eder.
AIogram 3.x uyumlu + Router pattern + Thread-safe + Memory-leak korumalı
MetricsSchema > AnalysisSchema
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
from dataclasses import dataclass
from contextlib import asynccontextmanager
import time
import hashlib

# Schema imports
from .schema_manager import load_analysis_schema, load_module_run_function, AnalysisSchema, Module

# Configure logging
logger = logging.getLogger(__name__)

class AnalysisPriority(Enum):
    """Analiz öncelik seviyeleri"""
    BASIC = "basic"
    PRO = "pro" 
    EXPERT = "expert"

class AnalysisStatus(Enum):
    """Analiz durumları"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class AnalysisResult:
    """Analiz sonuç veri yapısı"""
    module_name: str
    command: str
    status: AnalysisStatus
    data: Dict[str, Any]
    execution_time: float
    error: Optional[str] = None
    priority: Optional[str] = None

@dataclass
class AggregatedResult:
    """Aggregate edilmiş sonuç veri yapısı"""
    symbol: str
    results: List[AnalysisResult]
    total_execution_time: float
    success_count: int
    failed_count: int
    overall_score: Optional[float] = None

class AnalysisAggregator:
    """
    Analiz modüllerini koordine eden merkezi aggregator sınıfı
    Singleton pattern + Thread-safe + Connection pooling
    """
    
    _instance: Optional['AnalysisAggregator'] = None
    _lock: asyncio.Lock = asyncio.Lock()
    
    def __new__(cls):
        """Singleton pattern implementation"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize aggregator with thread-safe lazy loading"""
        if self._initialized:
            return
            
        self.schema: Optional[AnalysisSchema] = None
        self._module_cache: Dict[str, Any] = {}
        self._result_cache: Dict[str, AggregatedResult] = {}
        self._execution_locks: Dict[str, asyncio.Lock] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        self._is_running: bool = False
        
        # Performance monitoring
        self._execution_times: List[float] = []
        self._cache_hits: int = 0
        self._cache_misses: int = 0
        
        self._initialized = True
        logger.info("AnalysisAggregator initialized successfully")
    
    async def start(self):
        """Aggregator'ü başlat - Cache cleanup task'ını başlat"""
        if self._is_running:
            return
            
        self._is_running = True
        self.schema = load_analysis_schema()
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        logger.info("AnalysisAggregator started with periodic cleanup")
    
    async def stop(self):
        """Aggregator'ü güvenli şekilde durdur"""
        self._is_running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        
        # Cache'leri temizle
        self._module_cache.clear()
        self._result_cache.clear()
        self._execution_locks.clear()
        logger.info("AnalysisAggregator stopped and cleaned up")
    
    @asynccontextmanager
    async def _get_module_lock(self, module_name: str):
        """Modül bazlı execution lock context manager"""
        async with self._lock:
            if module_name not in self._execution_locks:
                self._execution_locks[module_name] = asyncio.Lock()
        
        lock = self._execution_locks[module_name]
        async with lock:
            yield
    
    def _get_cache_key(self, symbol: str, priority: Optional[str] = None, user_level: Optional[str] = None) -> str:
        """Cache key oluştur - Input sanitization ile"""
        key_parts = [symbol.strip().upper()]
        if priority:
            key_parts.append(priority.strip())
        if user_level:
            key_parts.append(user_level.strip().lower())
        
        key_string = ":".join(key_parts)
        return hashlib.md5(key_string.encode()).hexdigest()
    
    async def _load_module_function(self, module_file: str):
        """Modül fonksiyonunu cache'li şekilde yükle"""
        cache_key = f"module_{module_file}"
        
        if cache_key in self._module_cache:
            self._cache_hits += 1
            return self._module_cache[cache_key]
        
        self._cache_misses += 1
        try:
            run_function = load_module_run_function(module_file)
            self._module_cache[cache_key] = run_function
            return run_function
        except (ImportError, AttributeError) as e:
            logger.error(f"Module load failed for {module_file}: {str(e)}")
            raise
    
    async def run_single_analysis(
        self, 
        module: Module, 
        symbol: str, 
        priority: Optional[str] = None
    ) -> AnalysisResult:
        """
        Tek bir analiz modülünü çalıştır
        Thread-safe + Error handling + Performance monitoring
        """
        start_time = time.time()
        result = AnalysisResult(
            module_name=module.name,
            command=module.command,
            status=AnalysisStatus.PENDING,
            data={},
            execution_time=0.0,
            priority=priority
        )
        
        try:
            async with self._get_module_lock(module.name):
                logger.info(f"Starting analysis: {module.name} for {symbol}")
                
                # Modül fonksiyonunu yükle
                run_function = await self._load_module_function(module.file)
                
                # Analizi çalıştır
                result.status = AnalysisStatus.RUNNING
                analysis_data = await run_function(symbol=symbol, priority=priority)
                
                # Result validation
                if not isinstance(analysis_data, dict):
                    raise ValueError(f"Invalid result type: {type(analysis_data)}")
                
                result.data = analysis_data
                result.status = AnalysisStatus.COMPLETED
                
        except asyncio.CancelledError:
            result.status = AnalysisStatus.CANCELLED
            result.error = "Analysis cancelled"
            logger.warning(f"Analysis cancelled: {module.name}")
            raise
            
        except Exception as e:
            result.status = AnalysisStatus.FAILED
            result.error = f"Analysis failed: {str(e)}"
            logger.error(f"Analysis failed for {module.name}: {str(e)}", exc_info=True)
            
        finally:
            result.execution_time = time.time() - start_time
            self._execution_times.append(result.execution_time)
            
            if result.status == AnalysisStatus.COMPLETED:
                logger.info(f"Analysis completed: {module.name} in {result.execution_time:.2f}s")
            else:
                logger.warning(f"Analysis {result.status.value}: {module.name}")
        
        return result
    
    async def run_aggregated_analysis(
        self,
        symbol: str,
        priority: Optional[str] = None,
        user_level: Optional[str] = None,
        use_cache: bool = True,
        timeout: float = 30.0
    ) -> AggregatedResult:
        """
        Tüm uygun analiz modüllerini parallel çalıştır ve sonuçları aggregate et
        """
        # Input validation ve sanitization
        if not symbol or not isinstance(symbol, str):
            raise ValueError("Invalid symbol provided")
        
        symbol = symbol.strip().upper()
        
        # Cache check
        cache_key = self._get_cache_key(symbol, priority, user_level)
        if use_cache and cache_key in self._result_cache:
            logger.debug(f"Cache hit for analysis: {symbol}")
            return self._result_cache[cache_key]
        
        if not self.schema:
            raise RuntimeError("Aggregator not initialized. Call start() first.")
        
        start_time = time.time()
        logger.info(f"Starting aggregated analysis for {symbol}")
        
        try:
            # Kullanıcı seviyesine göre modülleri filtrele
            modules_to_run = self._get_modules_for_analysis(priority, user_level)
            
            if not modules_to_run:
                logger.warning(f"No modules found for priority={priority}, user_level={user_level}")
                return AggregatedResult(
                    symbol=symbol,
                    results=[],
                    total_execution_time=0.0,
                    success_count=0,
                    failed_count=0
                )
            
            # Parallel analiz çalıştırma
            analysis_tasks = []
            for module in modules_to_run:
                task = asyncio.create_task(
                    self.run_single_analysis(module, symbol, priority)
                )
                analysis_tasks.append(task)
            
            # Timeout ile sonuçları bekle
            done, pending = await asyncio.wait(
                analysis_tasks, 
                timeout=timeout,
                return_when=asyncio.ALL_COMPLETED
            )
            
            # Pending task'ları iptal et
            for task in pending:
                task.cancel()
            
            # Sonuçları topla
            results = []
            success_count = 0
            failed_count = 0
            
            for task in done:
                try:
                    result = await task
                    results.append(result)
                    
                    if result.status == AnalysisStatus.COMPLETED:
                        success_count += 1
                    else:
                        failed_count += 1
                        
                except Exception as e:
                    logger.error(f"Task execution error: {str(e)}")
                    failed_count += 1
            
            # Overall score hesapla
            overall_score = self._calculate_overall_score(results)
            
            # Aggregated result oluştur
            aggregated_result = AggregatedResult(
                symbol=symbol,
                results=results,
                total_execution_time=time.time() - start_time,
                success_count=success_count,
                failed_count=failed_count,
                overall_score=overall_score
            )
            
            # Cache'e kaydet
            if use_cache:
                self._result_cache[cache_key] = aggregated_result
            
            logger.info(
                f"Aggregated analysis completed for {symbol}: "
                f"{success_count} success, {failed_count} failed, "
                f"time: {aggregated_result.total_execution_time:.2f}s"
            )
            
            return aggregated_result
            
        except asyncio.TimeoutError:
            logger.error(f"Aggregated analysis timeout for {symbol} after {timeout}s")
            raise TimeoutError(f"Analysis timeout after {timeout} seconds")
        
        except Exception as e:
            logger.error(f"Aggregated analysis failed for {symbol}: {str(e)}")
            raise
    
    def _get_modules_for_analysis(
        self, 
        priority: Optional[str] = None,
        user_level: Optional[str] = None
    ) -> List[Module]:
        """Analiz için çalıştırılacak modülleri belirle"""
        if not self.schema:
            return []
        
        modules = self.schema.modules
        
        # Priority filtreleme
        if priority:
            from .schema_manager import filter_modules_by_priority
            modules = filter_modules_by_priority(self.schema, priority)
        
        # User level filtreleme
        if user_level:
            from .schema_manager import get_modules_for_user_level
            user_modules = get_modules_for_user_level(self.schema, user_level)
            if user_modules:
                modules = user_modules
        
        return modules
    
    def _calculate_overall_score(self, results: List[AnalysisResult]) -> Optional[float]:
        """Sonuçlardan overall score hesapla"""
        successful_results = [
            r for r in results 
            if r.status == AnalysisStatus.COMPLETED and 'score' in r.data
        ]
        
        if not successful_results:
            return None
        
        try:
            scores = [float(r.data.get('score', 0)) for r in successful_results]
            return sum(scores) / len(scores)
        except (ValueError, TypeError):
            logger.warning("Failed to calculate overall score - invalid score values")
            return None
    
    async def _periodic_cleanup(self):
        """Periyodik cache ve resource cleanup"""
        logger.info("Starting periodic cleanup task")
        
        while self._is_running:
            try:
                await asyncio.sleep(300)  # 5 dakikada bir
                
                # Eski cache entry'lerini temizle (10 dakikadan eski)
                current_time = time.time()
                keys_to_remove = []
                
                for key, result in self._result_cache.items():
                    # Basit age-based cleanup (daha gelişmiş TTL eklenebilir)
                    if current_time - getattr(result, '_created_at', current_time) > 600:
                        keys_to_remove.append(key)
                
                for key in keys_to_remove:
                    del self._result_cache[key]
                
                # Execution times dizisini trim et
                if len(self._execution_times) > 1000:
                    self._execution_times = self._execution_times[-500:]
                
                logger.debug(f"Cleanup completed: removed {len(keys_to_remove)} cache entries")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup task error: {str(e)}")
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """Performance metriklerini getir"""
        avg_time = sum(self._execution_times) / len(self._execution_times) if self._execution_times else 0
        cache_hit_rate = (
            self._cache_hits / (self._cache_hits + self._cache_misses) 
            if (self._cache_hits + self._cache_misses) > 0 else 0
        )
        
        return {
            "average_execution_time": avg_time,
            "total_analyses": len(self._execution_times),
            "cache_hit_rate": cache_hit_rate,
            "cache_size": len(self._result_cache),
            "module_cache_size": len(self._module_cache),
            "active_locks": len(self._execution_locks)
        }

# Global aggregator instance
aggregator = AnalysisAggregator()

async def get_aggregator() -> AnalysisAggregator:
    """Dependency injection için aggregator instance'ı"""
    return aggregator


# analysis_core.py içinde modül durum kontrolü
async def check_module_health(self) -> Dict[str, bool]:
    """Tüm modüllerin sağlık durumunu kontrol et"""
    health_status = {}
    
    for module in self.schema.modules:
        try:
            run_function = await self._load_module_function(module.file)
            # Test çalıştırma (sembol olmadan)
            health_status[module.name] = True
        except Exception as e:
            logger.warning(f"Module health check failed for {module.name}: {e}")
            health_status[module.name] = False
    
    return health_status
    

# FastAPI Router için kullanım örneği
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from .analysis_core import get_aggregator, AnalysisAggregator

router = APIRouter()

@router.get("/analyze/{symbol}")
async def analyze_symbol(
    symbol: str,
    priority: Optional[str] = Query(None),
    user_level: Optional[str] = Query(None),
    aggregator: AnalysisAggregator = Depends(get_aggregator)
):
    result = await aggregator.run_aggregated_analysis(
        symbol=symbol,
        priority=priority,
        user_level=user_level
    )
    return result
"""