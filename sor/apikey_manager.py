"""
utils/apikey_manager.py

Async, secure API key manager using SQLite + Fernet encryption.
Aiogram 3.x ve async uyumludur.

# .env İÇERİĞİ
# 🔐 ZORUNLU - 32-byte Base64 encoded Fernet key. Şöyle oluşturabilirsin:
# from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())
MASTER_KEY=abc123examplekey==
# 🗂️ OPSİYONEL - Veritabanı dosya yolu
DATABASE_URL=data/apikeys.db
# 🗂️Fernet Key Oluşturma (Python ile)
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())


not:
bot/config.py
apikey_manager.py içinde şöyle kullanırsın:

from config import get_apikey_config
config = get_apikey_config()
self.db_path = config.DATABASE_URL


✅ Kullanım Örneği (main.py ya da handler içinde)
from utils.apikey_manager import APIKeyManager

db = APIKeyManager.get_instance()

async def startup():
    await db.init_db()
    await db.add_or_update_apikey(user_id=12345, api_key="demo", secret_key="secret")
    creds = await db.get_apikey(user_id=12345)
    print(creds)
    
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple, List

import aiosqlite
from cryptography.fernet import Fernet

from config import get_apikey_config

config = get_apikey_config()
#self.db_path = config.DATABASE_URL

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class APIKeyManager:
    """Singleton Async API Key + Alarm + Trade Settings Manager."""

    _instance: Optional["APIKeyManager"] = None

    def __init__(self):
        config = get_config_sync()
        self.db_path = config.DATABASE_URL or "data/apikeys.db"

        master_key = config.MASTER_KEY
        if not master_key:
            raise RuntimeError("❌ .env dosyasında MASTER_KEY tanımlanmalı. Aksi halde şifrelenmiş veriler okunamaz!")
        self.fernet = Fernet(master_key.encode())

    @classmethod
    def get_instance(cls) -> "APIKeyManager":
        if cls._instance is None:
            cls._instance = APIKeyManager()
        return cls._instance

    async def init_db(self) -> None:
        """Veritabanı tablolarını oluşturur."""
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

    def _encrypt(self, data: str) -> str:
        return self.fernet.encrypt(data.encode()).decode()

    def _decrypt(self, data: str) -> str:
        return self.fernet.decrypt(data.encode()).decode()

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

    async def set_alarm_settings(self, user_id: int, settings: dict) -> None:
        settings_json = json.dumps(settings)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE apikeys SET alarm_settings=? WHERE user_id=?",
                (settings_json, user_id),
            )
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
            await db.execute(
                "INSERT INTO alarms (user_id, alarm_data) VALUES (?, ?)",
                (user_id, alarm_json),
            )
            await db.commit()

    async def get_alarms(self, user_id: int) -> List[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT alarm_data FROM alarms WHERE user_id=?", (user_id,)) as cursor:
                return [json.loads(row[0]) async for row in cursor]

    async def delete_alarm(self, alarm_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM alarms WHERE id=?", (alarm_id,))
            await db.commit()

    async def set_trade_settings(self, user_id: int, settings: dict) -> None:
        settings_json = json.dumps(settings)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE apikeys SET trade_settings=? WHERE user_id=?",
                (settings_json, user_id),
            )
            await db.commit()

    async def get_trade_settings(self, user_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT trade_settings FROM apikeys WHERE user_id=?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                if row and row[0]:
                    return json.loads(row[0])
                return None

    async def cleanup_old_alarms(self, days: int = 30) -> None:
        cutoff = datetime.now() - timedelta(days=days)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM alarms WHERE created_at < ?", (cutoff,))
            await db.commit()

    async def cleanup_old_apikeys(self, days: int = 90) -> None:
        cutoff = datetime.now() - timedelta(days=days)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM apikeys WHERE created_at < ?", (cutoff,))
            await db.commit()


# EKSİK OLAN ÖNEMLİ FONKSİYONLAR:

async def validate_binance_credentials(self, user_id: int) -> bool:
    """Binance API test ederek geçerliliği kontrol et"""
    try:
        api_key, secret_key = await self.get_apikey(user_id)
        if not api_key or not secret_key:
            return False
            
        # Binance API test isteği
        client = AsyncClient(api_key, secret_key)
        await client.get_account()
        await client.close_connection()
        return True
    except Exception as e:
        logger.error(f"Binance API validation failed for user {user_id}: {e}")
        return False

async def rotate_keys(self, user_id: int, new_api_key: str, new_secret: str) -> bool:
    """Key rotation with validation"""
    if not await self.validate_binance_credentials(user_id):
        return False
    
    await self.add_or_update_apikey(user_id, new_api_key, new_secret)
    return True

async def get_encrypted_keys_for_usage(self, user_id: int) -> Optional[Tuple[str, str]]:
    """Usage için decrypt edilmiş key'leri döndürür (geçici olarak)"""
    # Burada ek güvenlik önlemleri eklenebilir
    return await self.get_apikey(user_id)

# GÜVENLİK İYİLEŞTİRMELERİ:
def __init__(self):
    config = get_apikey_config()
    self.db_path = config.DATABASE_URL or "data/apikeys.db"
    
    # Key validation
    if not config.MASTER_KEY:
        raise RuntimeError("MASTER_KEY required")
    
    try:
        self.fernet = Fernet(config.MASTER_KEY.encode())
        # Test encryption
        test_data = self._decrypt(self._encrypt("test"))
        assert test_data == "test"
    except Exception as e:
        raise RuntimeError(f"Invalid MASTER_KEY: {e}")
