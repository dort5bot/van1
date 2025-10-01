# handlers/apikey_handler.py
"""
Telegram handler for managing API keys, alarms, and trade settings
Kullanıcı /apikey <API_KEY> <SECRET_KEY> yazınca:
DB'ye şifreli olarak kaydediliyor.
Kullanıcının yazdığı mesaj Telegram geçmişinden siliniyor.
Bot kullanıcıya yeni bir bilgi mesajı gönderiyor: API key kaydedildi (mesajınız silindi).
"""
# handlers/apikey_handler.py

import json
import logging
import os
from aiogram import Router, types
from aiogram.filters import Command
from dotenv import set_key

from utils.apikey_manager import APIKeyManager

logger = logging.getLogger(__name__)

router = Router()

db = APIKeyManager.get_instance()

# Yetkili kullanıcı listesi (örnek)
AUTHORIZED_USERS = [123456789]  # Kendi user_id'lerinizi buraya ekleyin


# --- /apikey komutu: API key + secret kaydet ---
@router.message(Command("apikey"))
async def apikey_command(message: types.Message) -> None:
    user_id = message.from_user.id
    args = message.get_args().split()

    if len(args) < 2:
        await message.reply("❌ Kullanım: /apikey <API_KEY> <SECRET_KEY>")
        return

    api_key, secret_key = args[0], args[1]

    try:
        await db.add_or_update_apikey(user_id, api_key, secret_key)

        # Güvenlik için kullanıcının mesajını sil
        try:
            await message.delete()
        except Exception as e:
            logger.warning(f"Mesaj silinemedi: {e}")

        await message.answer("✅ API key başarıyla kaydedildi (mesajınız güvenlik için silindi).")

        # Yetkili kullanıcı ise .env dosyasını da güncelle
        if user_id in AUTHORIZED_USERS:
            env_path = os.path.join(os.getcwd(), ".env")
            set_key(env_path, "BINANCE_API_KEY", api_key)
            set_key(env_path, "BINANCE_SECRET_KEY", secret_key)
            await message.answer("🔑 Global API key de güncellendi.")

    except Exception as e:
        logger.error(f"API key kaydedilemedi: {e}")
        await message.reply("❌ API key kaydedilirken hata oluştu.")


# --- /getapikey komutu: Maskelenmiş API key göster ---
@router.message(Command("getapikey"))
async def get_apikey_command(message: types.Message) -> None:
    user_id = message.from_user.id
    try:
        creds = await db.get_apikey(user_id)
        if creds:
            api_key, _ = creds
            masked = api_key[:4] + "*" * (len(api_key) - 8) + api_key[-4:]
            await message.reply(f"🔐 Kayıtlı API Key: `{masked}`", parse_mode="Markdown")
        else:
            await message.reply("❌ Henüz API key kaydetmediniz.")
    except Exception as e:
        logger.error(f"API key okunamadı: {e}")
        await message.reply("❌ API key okunurken hata oluştu.")


# --- Alarm Ayarları ---

@router.message(Command("set_alarm"))
async def set_alarm_command(message: types.Message) -> None:
    user_id = message.from_user.id
    args_text = message.get_args()
    if not args_text:
        await message.reply("❌ Lütfen JSON formatında alarm ayarları girin.\nÖrnek: /set_alarm {\"threshold\": 100}")
        return

    try:
        data = json.loads(args_text)
        await db.set_alarm_settings(user_id, data)
        await message.reply("✅ Alarm ayarları kaydedildi.")
    except Exception as e:
        logger.error(f"Alarm ayarı hatası: {e}")
        await message.reply("❌ Alarm ayarları geçersiz. JSON formatında gönderin.")


@router.message(Command("get_alarm"))
async def get_alarm_command(message: types.Message) -> None:
    user_id = message.from_user.id
    try:
        settings = await db.get_alarm_settings(user_id)
        if settings:
            pretty = json.dumps(settings, indent=2, ensure_ascii=False)
            await message.reply(f"🔔 Alarm ayarları:\n<pre>{pretty}</pre>", parse_mode="HTML")
        else:
            await message.reply("❌ Alarm ayarınız bulunamadı.")
    except Exception as e:
        logger.error(f"Alarm ayarları alınamadı: {e}")
        await message.reply("❌ Alarm ayarları okunurken hata oluştu.")


# --- Trade Ayarları ---

@router.message(Command("set_trade"))
async def set_trade_command(message: types.Message) -> None:
    user_id = message.from_user.id
    args_text = message.get_args()
    if not args_text:
        await message.reply("❌ Lütfen JSON formatında trade ayarları girin.\nÖrnek: /set_trade {\"max_trade\": 10}")
        return

    try:
        data = json.loads(args_text)
        await db.set_trade_settings(user_id, data)
        await message.reply("✅ Trade ayarları kaydedildi.")
    except Exception as e:
        logger.error(f"Trade ayarı hatası: {e}")
        await message.reply("❌ Trade ayarları geçersiz. JSON formatında gönderin.")


@router.message(Command("get_trade"))
async def get_trade_command(message: types.Message) -> None:
    user_id = message.from_user.id
    try:
        settings = await db.get_trade_settings(user_id)
        if settings:
            pretty = json.dumps(settings, indent=2, ensure_ascii=False)
            await message.reply(f"📊 Trade ayarları:\n<pre>{pretty}</pre>", parse_mode="HTML")
        else:
            await message.reply("❌ Trade ayarınız bulunamadı.")
    except Exception as e:
        logger.error(f"Trade ayarları alınamadı: {e}")
        await message.reply("❌ Trade ayarları okunurken hata oluştu.")
