"""
utils/apikey_manager.py

Async, secure API key manager using SQLite + Fernet encryption.
Aiogram 3.x ve async uyumludur.

Geliştirmeler:
- Thread safety için asyncio locks
- Connection pool management
- Input validation
- Comprehensive error handling
- Cache cleanup
"""
import asyncio
import json
import logging
from typing import Optional, Tuple, List, Dict, Any

import aiosqlite
from cryptography.fernet import Fernet, InvalidToken
from cryptography.exceptions import InvalidKey
from binance import AsyncClient
from binance.exceptions import BinanceAPIException, BinanceRequestException

from config import get_apikey_config

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# BASE CLASS (DB + Encryption altyapısı)
# ============================================================

class BaseManager:
    _db_path: str = None
    _fernet: Fernet = None
    _init_lock: asyncio.Lock = asyncio.Lock()
    _db_connections: Dict[str, Any] = {}

    def __init__(self):
        config = get_apikey_config()
        
        if not BaseManager._db_path:
            BaseManager._db_path = config.DATABASE_URL or "data/apikeys.db"

        if not config.MASTER_KEY:
            raise RuntimeError("❌ MASTER_KEY tanımlı olmalı (.env)!")

        if not BaseManager._fernet:
            try:
                BaseManager._fernet = Fernet(config.MASTER_KEY.encode())
                # Test encryption/decryption
                test_data = BaseManager._fernet.decrypt(
                    BaseManager._fernet.encrypt(b"test")
                ).decode()
                assert test_data == "test"
                logger.info("✅ Fernet encryption initialized successfully")
            except (InvalidKey, InvalidToken, AssertionError) as e:
                raise RuntimeError(f"❌ Invalid MASTER_KEY: {e}")

    @property
    def db_path(self) -> str:
        return BaseManager._db_path

    @property
    def fernet(self) -> Fernet:
        return BaseManager._fernet

    def _encrypt(self, data: str) -> str:
        """Encrypt sensitive data"""
        if not data or not isinstance(data, str):
            raise ValueError("Encryption data must be non-empty string")
        return self.fernet.encrypt(data.encode()).decode()

    def _decrypt(self, data: str) -> str:
        """Decrypt sensitive data"""
        if not data or not isinstance(data, str):
            raise ValueError("Decryption data must be non-empty string")
        try:
            return self.fernet.decrypt(data.encode()).decode()
        except InvalidToken:
            logger.error("❌ Invalid token during decryption - possible key mismatch")
            raise
        except Exception as e:
            logger.error(f"❌ Decryption failed: {e}")
            raise

    async def get_db_connection(self) -> aiosqlite.Connection:
        """Get database connection with connection pool"""
        async with BaseManager._init_lock:
            if self.db_path not in BaseManager._db_connections:
                BaseManager._db_connections[self.db_path] = await aiosqlite.connect(
                    self.db_path,
                    check_same_thread=False,
                    timeout=30.0
                )
                # Enable WAL mode for better concurrent performance
                await BaseManager._db_connections[self.db_path].execute("PRAGMA journal_mode=WAL")
                await BaseManager._db_connections[self.db_path].commit()
                logger.info(f"✅ Database connection pool created for {self.db_path}")
            
            return BaseManager._db_connections[self.db_path]

    async def init_db(self) -> None:
        """Tabloları oluşturur (idempotent)."""
        async with BaseManager._init_lock:
            db = await self.get_db_connection()
            try:
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS apikeys (
                        user_id INTEGER PRIMARY KEY,
                        api_key TEXT NOT NULL,
                        alarm_settings TEXT,
                        trade_settings TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS alarms (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        alarm_data TEXT NOT NULL,
                        is_active BOOLEAN DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES apikeys (user_id) ON DELETE CASCADE
                    )
                    """
                )
                
                # Indexes for better performance
                await db.execute("CREATE INDEX IF NOT EXISTS idx_alarms_user_id ON alarms(user_id)")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_alarms_created_at ON alarms(created_at)")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_alarms_active ON alarms(is_active)")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_apikeys_updated ON apikeys(updated_at)")
                
                await db.commit()
                logger.info("✅ Veritabanı tabloları ve index'ler oluşturuldu.")
            except Exception as e:
                logger.error(f"❌ Database initialization failed: {e}")
                raise

    async def close_connections(self) -> None:
        """Close all database connections"""
        for path, conn in BaseManager._db_connections.items():
            try:
                await conn.close()
                logger.info(f"✅ Database connection closed: {path}")
            except Exception as e:
                logger.error(f"❌ Error closing connection {path}: {e}")
        BaseManager._db_connections.clear()


# ============================================================
# API KEY MANAGER
# ============================================================

class APIKeyManager(BaseManager):
    _instance: Optional["APIKeyManager"] = None
    _validation_lock: asyncio.Lock = asyncio.Lock()
    _cache: Dict[int, Tuple[str, str]] = {}
    _cache_lock: asyncio.Lock = asyncio.Lock()

    def __init__(self):
        super().__init__()

    @classmethod
    def get_instance(cls) -> "APIKeyManager":
        if cls._instance is None:
            cls._instance = APIKeyManager()
        return cls._instance

    async def add_or_update_apikey(self, user_id: int, api_key: str, secret_key: str) -> None:
        """Add or update API key with validation and encryption"""
        if not all([user_id, api_key, secret_key]):
            raise ValueError("User ID, API key and secret key are required")
        
        if len(api_key) < 10 or len(secret_key) < 10:
            raise ValueError("API key and secret key are too short")

        encrypted = self._encrypt(f"{api_key}:{secret_key}")
        db = await self.get_db_connection()
        
        try:
            async with db.cursor() as cursor:
                await cursor.execute(
                    """INSERT INTO apikeys (user_id, api_key, updated_at) 
                       VALUES (?, ?, CURRENT_TIMESTAMP)
                       ON CONFLICT(user_id) DO UPDATE SET 
                       api_key=excluded.api_key, updated_at=CURRENT_TIMESTAMP""",
                    (user_id, encrypted)
                )
                await db.commit()
                
                # Update cache
                async with self._cache_lock:
                    self._cache[user_id] = (api_key, secret_key)
                
                logger.info(f"🔐 API key updated for user {user_id}")
        except Exception as e:
            await db.rollback()
            logger.error(f"❌ Failed to update API key for user {user_id}: {e}")
            raise

    async def get_apikey(self, user_id: int) -> Optional[Tuple[str, str]]:
        """Get API key from cache or database"""
        # Check cache first
        async with self._cache_lock:
            if user_id in self._cache:
                return self._cache[user_id]
        
        # Query database
        db = await self.get_db_connection()
        try:
            async with db.execute("SELECT api_key FROM apikeys WHERE user_id=?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    decrypted = self._decrypt(row[0])
                    api_key, secret_key = tuple(decrypted.split(":", 1))
                    
                    # Update cache
                    async with self._cache_lock:
                        self._cache[user_id] = (api_key, secret_key)
                    
                    return api_key, secret_key
                return None
        except Exception as e:
            logger.error(f"❌ Failed to get API key for user {user_id}: {e}")
            return None

    async def validate_binance_credentials(self, user_id: int) -> bool:
        """Validate Binance credentials with proper error handling"""
        async with self._validation_lock:
            try:
                creds = await self.get_apikey(user_id)
                if not creds:
                    logger.warning(f"⚠️ No credentials found for user {user_id}")
                    return False
                    
                api_key, secret_key = creds
                
                # Basic validation
                if not api_key.startswith(('api_key_', 'binance_')) and len(api_key) < 16:
                    logger.warning(f"⚠️ Invalid API key format for user {user_id}")
                    return False
                
                client = await AsyncClient.create(api_key, secret_key)
                
                try:
                    # Test API connectivity with account info
                    account_info = await client.get_account()
                    if account_info and 'canTrade' in account_info:
                        logger.info(f"✅ Binance credentials validated for user {user_id}")
                        return True
                    return False
                    
                except BinanceAPIException as e:
                    logger.error(f"❌ Binance API error for user {user_id}: {e.code} - {e.message}")
                    return False
                except BinanceRequestException as e:
                    logger.error(f"❌ Binance request error for user {user_id}: {e}")
                    return False
                except Exception as e:
                    logger.error(f"❌ Unexpected Binance error for user {user_id}: {e}")
                    return False
                finally:
                    await client.close_connection()
                    
            except Exception as e:
                logger.error(f"❌ Validation process failed for user {user_id}: {e}")
                return False

    async def rotate_keys(self, user_id: int, new_api_key: str, new_secret: str) -> bool:
        """Rotate API keys with validation"""
        try:
            await self.add_or_update_apikey(user_id, new_api_key, new_secret)
            return await self.validate_binance_credentials(user_id)
        except Exception as e:
            logger.error(f"❌ Key rotation failed for user {user_id}: {e}")
            return False

    async def cleanup_cache(self, max_size: int = 1000) -> None:
        """Cleanup cache to prevent memory leaks"""
        async with self._cache_lock:
            if len(self._cache) > max_size:
                # Remove oldest entries (simple FIFO)
                keys_to_remove = list(self._cache.keys())[:len(self._cache) - max_size]
                for key in keys_to_remove:
                    del self._cache[key]
                logger.info(f"🧹 Cache cleaned up, removed {len(keys_to_remove)} entries")

    async def delete_apikey(self, user_id: int) -> bool:
        """Delete API key for user"""
        db = await self.get_db_connection()
        try:
            async with db.cursor() as cursor:
                await cursor.execute("DELETE FROM apikeys WHERE user_id=?", (user_id,))
                await db.commit()
                
                # Remove from cache
                async with self._cache_lock:
                    self._cache.pop(user_id, None)
                
                logger.info(f"🗑️ API key deleted for user {user_id}")
                return True
        except Exception as e:
            await db.rollback()
            logger.error(f"❌ Failed to delete API key for user {user_id}: {e}")
            return False


# ============================================================
# ALARM MANAGER
# ============================================================

class AlarmManager(BaseManager):
    _instance: Optional["AlarmManager"] = None
    _cache: Dict[int, Dict[str, Any]] = {}
    _cache_lock: asyncio.Lock = asyncio.Lock()

    def __init__(self):
        super().__init__()

    @classmethod
    def get_instance(cls) -> "AlarmManager":
        if cls._instance is None:
            cls._instance = AlarmManager()
        return cls._instance

    async def set_alarm_settings(self, user_id: int, settings: dict) -> None:
        """Set alarm settings with validation"""
        if not isinstance(settings, dict):
            raise ValueError("Settings must be a dictionary")
            
        settings_json = json.dumps(settings, ensure_ascii=False)
        db = await self.get_db_connection()
        
        try:
            await db.execute(
                "UPDATE apikeys SET alarm_settings=?, updated_at=CURRENT_TIMESTAMP WHERE user_id=?", 
                (settings_json, user_id)
            )
            await db.commit()
            
            # Update cache
            async with self._cache_lock:
                self._cache[user_id] = settings
                
            logger.info(f"🔔 Alarm settings updated for user {user_id}")
        except Exception as e:
            await db.rollback()
            logger.error(f"❌ Failed to update alarm settings for user {user_id}: {e}")
            raise

    async def get_alarm_settings(self, user_id: int) -> Optional[dict]:
        """Get alarm settings from cache or database"""
        # Check cache first
        async with self._cache_lock:
            if user_id in self._cache:
                return self._cache[user_id]
        
        # Query database
        db = await self.get_db_connection()
        try:
            async with db.execute("SELECT alarm_settings FROM apikeys WHERE user_id=?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                if row and row[0]:
                    settings = json.loads(row[0])
                    
                    # Update cache
                    async with self._cache_lock:
                        self._cache[user_id] = settings
                    
                    return settings
                return None
        except Exception as e:
            logger.error(f"❌ Failed to get alarm settings for user {user_id}: {e}")
            return None

    async def add_alarm(self, user_id: int, alarm_data: dict) -> int:
        """Add new alarm and return alarm ID"""
        if not isinstance(alarm_data, dict):
            raise ValueError("Alarm data must be a dictionary")
            
        alarm_json = json.dumps(alarm_data, ensure_ascii=False)
        db = await self.get_db_connection()
        
        try:
            async with db.cursor() as cursor:
                await cursor.execute(
                    "INSERT INTO alarms (user_id, alarm_data) VALUES (?, ?)", 
                    (user_id, alarm_json)
                )
                await db.commit()
                alarm_id = cursor.lastrowid
                logger.info(f"🔔 Alarm added for user {user_id}, alarm_id: {alarm_id}")
                return alarm_id
        except Exception as e:
            await db.rollback()
            logger.error(f"❌ Failed to add alarm for user {user_id}: {e}")
            raise

    async def get_alarms(self, user_id: int, active_only: bool = True) -> List[dict]:
        """Get alarms for user with optional active filter"""
        db = await self.get_db_connection()
        try:
            if active_only:
                query = "SELECT id, alarm_data FROM alarms WHERE user_id=? AND is_active=1 ORDER BY created_at DESC"
            else:
                query = "SELECT id, alarm_data FROM alarms WHERE user_id=? ORDER BY created_at DESC"
                
            async with db.execute(query, (user_id,)) as cursor:
                results = []
                async for row in cursor:
                    try:
                        alarm_data = json.loads(row[1])
                        alarm_data['id'] = row[0]  # Include alarm ID
                        results.append(alarm_data)
                    except json.JSONDecodeError as e:
                        logger.error(f"❌ Invalid alarm data for user {user_id}, alarm_id {row[0]}: {e}")
                return results
        except Exception as e:
            logger.error(f"❌ Failed to get alarms for user {user_id}: {e}")
            return []

    async def delete_alarm(self, alarm_id: int) -> bool:
        """Delete specific alarm by ID"""
        db = await self.get_db_connection()
        try:
            async with db.cursor() as cursor:
                result = await cursor.execute("DELETE FROM alarms WHERE id=?", (alarm_id,))
                await db.commit()
                deleted = result.rowcount > 0
                if deleted:
                    logger.info(f"🗑️ Alarm deleted: {alarm_id}")
                return deleted
        except Exception as e:
            await db.rollback()
            logger.error(f"❌ Failed to delete alarm {alarm_id}: {e}")
            return False

    async def cleanup_old_alarms(self, days: int = 30) -> int:
        """Cleanup old alarms and return count of deleted records"""
        db = await self.get_db_connection()
        try:
            async with db.cursor() as cursor:
                result = await cursor.execute(
                    "DELETE FROM alarms WHERE created_at < datetime('now', ?)", 
                    (f'-{days} days',)
                )
                await db.commit()
                deleted_count = result.rowcount
                logger.info(f"🧹 Cleaned up {deleted_count} old alarms (older than {days} days)")
                return deleted_count
        except Exception as e:
            await db.rollback()
            logger.error(f"❌ Failed to cleanup old alarms: {e}")
            return 0


# ============================================================
# TRADE SETTINGS MANAGER  
# ============================================================

class TradeSettingsManager(BaseManager):
    _instance: Optional["TradeSettingsManager"] = None
    _cache: Dict[int, Dict[str, Any]] = {}
    _cache_lock: asyncio.Lock = asyncio.Lock()

    def __init__(self):
        super().__init__()

    @classmethod
    def get_instance(cls) -> "TradeSettingsManager":
        if cls._instance is None:
            cls._instance = TradeSettingsManager()
        return cls._instance

    async def set_trade_settings(self, user_id: int, settings: dict) -> None:
        """Set trade settings with validation"""
        if not isinstance(settings, dict):
            raise ValueError("Settings must be a dictionary")
            
        # Basic validation for common trade settings
        if 'max_trade' in settings and settings['max_trade'] <= 0:
            raise ValueError("Max trade must be positive")
            
        settings_json = json.dumps(settings, ensure_ascii=False)
        db = await self.get_db_connection()
        
        try:
            await db.execute(
                "UPDATE apikeys SET trade_settings=?, updated_at=CURRENT_TIMESTAMP WHERE user_id=?", 
                (settings_json, user_id)
            )
            await db.commit()
            
            # Update cache
            async with self._cache_lock:
                self._cache[user_id] = settings
                
            logger.info(f"📊 Trade settings updated for user {user_id}")
        except Exception as e:
            await db.rollback()
            logger.error(f"❌ Failed to update trade settings for user {user_id}: {e}")
            raise

    async def get_trade_settings(self, user_id: int) -> Optional[dict]:
        """Get trade settings from cache or database"""
        # Check cache first
        async with self._cache_lock:
            if user_id in self._cache:
                return self._cache[user_id]
        
        # Query database
        db = await self.get_db_connection()
        try:
            async with db.execute("SELECT trade_settings FROM apikeys WHERE user_id=?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                if row and row[0]:
                    settings = json.loads(row[0])
                    
                    # Update cache
                    async with self._cache_lock:
                        self._cache[user_id] = settings
                    
                    return settings
                return None
        except Exception as e:
            logger.error(f"❌ Failed to get trade settings for user {user_id}: {e}")
            return None

    async def cleanup_old_apikeys(self, days: int = 90) -> int:
        """Cleanup old API keys and return count of deleted records"""
        db = await self.get_db_connection()
        try:
            async with db.cursor() as cursor:
                result = await cursor.execute(
                    "DELETE FROM apikeys WHERE updated_at < datetime('now', ?)", 
                    (f'-{days} days',)
                )
                await db.commit()
                deleted_count = result.rowcount
                
                # Cleanup cache for deleted users
                async with self._cache_lock:
                    self._cache.clear()
                
                logger.info(f"🧹 Cleaned up {deleted_count} old API keys (older than {days} days)")
                return deleted_count
        except Exception as e:
            await db.rollback()
            logger.error(f"❌ Failed to cleanup old API keys: {e}")
            return 0

    async def cleanup_cache(self) -> None:
        """Cleanup trade settings cache"""
        async with self._cache_lock:
            self._cache.clear()
            logger.info("🧹 Trade settings cache cleaned up")