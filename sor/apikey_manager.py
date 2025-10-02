"""
utils/apikey_manager.py

Async, secure managers:
- APIKeyManager
- AlarmManager
- TradeSettingsManager

Her biri SQLite + Fernet şifreleme kullanır.
"""

import json
import logging
from typing import Optional, Tuple, List

import aiosqlite
from cryptography.fernet import Fernet
from binance import AsyncClient

from config import get_apikey_config

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ============================================================
# BASE CLASS (DB + Encryption altyapısı)
# ============================================================

class BaseManager:
    _db_path: str = None
    _fernet: Fernet = None

    def __init__(self):
        config = get_apikey_config()
        if not BaseManager._db_path:
            BaseManager._db_path = config.DATABASE_URL or "data/apikeys.db"

        if not config.MASTER_KEY:
            raise RuntimeError("❌ MASTER_KEY tanımlı olmalı (.env)!")

        if not BaseManager._fernet:
            try:
                BaseManager._fernet = Fernet(config.MASTER_KEY)
                # test encryption
                test_data = BaseManager._fernet.decrypt(
                    BaseManager._fernet.encrypt(b"test")
                ).decode()
                assert test_data == "test"
            except Exception as e:
                raise RuntimeError(f"Invalid MASTER_KEY: {e}")

    @property
    def db_path(self) -> str:
        return BaseManager._db_path

    @property
    def fernet(self) -> Fernet:
        return BaseManager._fernet

    def _encrypt(self, data: str) -> str:
        return self.fernet.encrypt(data.encode()).decode()

    def _decrypt(self, data: str) -> str:
        return self.fernet.decrypt(data.encode()).decode()

    async def init_db(self) -> None:
        """Tabloları oluşturur (idempotent)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS apikeys (
                    user_id INTEGER PRIMARY KEY,
                    api_key TEXT NOT NULL,
                    alarm_settings TEXT,
                    trade_settings TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS alarms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    alarm_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES apikeys (user_id)
                )
                """
            )
            await db.commit()
            logger.info("✅ Veritabanı tabloları oluşturuldu.")


# ============================================================
# API KEY MANAGER
# ============================================================

class APIKeyManager(BaseManager):
    _instance: Optional["APIKeyManager"] = None

    def __init__(self):
        super().__init__()

    @classmethod
    def get_instance(cls) -> "APIKeyManager":
        if cls._instance is None:
            cls._instance = APIKeyManager()
        return cls._instance

    async def add_or_update_apikey(self, user_id: int, api_key: str, secret_key: str) -> None:
        encrypted = self._encrypt(f"{api_key}:{secret_key}")
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO apikeys (user_id, api_key)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET api_key=excluded.api_key
                """,
                (user_id, encrypted),
            )
            await db.commit()
            logger.info(f"🔐 API key updated for user {user_id}")

    async def get_apikey(self, user_id: int) -> Optional[Tuple[str, str]]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT api_key FROM apikeys WHERE user_id=?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    decrypted = self._decrypt(row[0])
                    return tuple(decrypted.split(":", 1))
                return None

    async def validate_binance_credentials(self, user_id: int) -> bool:
        try:
            creds = await self.get_apikey(user_id)
            if not creds:
                return False
            api_key, secret_key = creds
            client = await AsyncClient.create(api_key, secret_key)
            await client.get_account()
            await client.close_connection()
            return True
        except Exception as e:
            logger.error(f"❌ Binance API validation failed for user {user_id}: {e}")
            return False

    async def rotate_keys(self, user_id: int, new_api_key: str, new_secret: str) -> bool:
        try:
            await self.add_or_update_apikey(user_id, new_api_key, new_secret)
            return await self.validate_binance_credentials(user_id)
        except Exception as e:
            logger.error(f"❌ Key rotation failed for user {user_id}: {e}")
            return False


# ============================================================
# ALARM MANAGER
# ============================================================

class AlarmManager(BaseManager):
    _instance: Optional["AlarmManager"] = None

    def __init__(self):
        super().__init__()

    @classmethod
    def get_instance(cls) -> "AlarmManager":
        if cls._instance is None:
            cls._instance = AlarmManager()
        return cls._instance

    async def set_alarm_settings(self, user_id: int, settings: dict) -> None:
        settings_json = json.dumps(settings)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE apikeys SET alarm_settings=? WHERE user_id=?", (settings_json, user_id))
            await db.commit()

    async def get_alarm_settings(self, user_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT alarm_settings FROM apikeys WHERE user_id=?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                if row and row[0]:
                    return json.loads(row[0])
                return None

    async def add_alarm(self, user_id: int, alarm_data: dict) -> None:
        alarm_json = json.dumps(alarm_data)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("INSERT INTO alarms (user_id, alarm_data) VALUES (?, ?)", (user_id, alarm_json))
            await db.commit()

    async def get_alarms(self, user_id: int) -> List[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT alarm_data FROM alarms WHERE user_id=?", (user_id,)) as cursor:
                return [json.loads(row[0]) async for row in cursor]

    async def delete_alarm(self, alarm_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM alarms WHERE id=?", (alarm_id,))
            await db.commit()

    async def cleanup_old_alarms(self, days: int = 30) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM alarms WHERE created_at < datetime('now', ?)", (f'-{days} days',))
            await db.commit()


# ============================================================
# TRADE SETTINGS MANAGER
# ============================================================

class TradeSettingsManager(BaseManager):
    _instance: Optional["TradeSettingsManager"] = None

    def __init__(self):
        super().__init__()

    @classmethod
    def get_instance(cls) -> "TradeSettingsManager":
        if cls._instance is None:
            cls._instance = TradeSettingsManager()
        return cls._instance

    async def set_trade_settings(self, user_id: int, settings: dict) -> None:
        settings_json = json.dumps(settings)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE apikeys SET trade_settings=? WHERE user_id=?", (settings_json, user_id))
            await db.commit()

    async def get_trade_settings(self, user_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT trade_settings FROM apikeys WHERE user_id=?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                if row and row[0]:
                    return json.loads(row[0])
                return None

    async def cleanup_old_apikeys(self, days: int = 90) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM apikeys WHERE created_at < datetime('now', ?)", (f'-{days} days',))
            await db.commit()


