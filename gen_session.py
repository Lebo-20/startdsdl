from telethon.sync import TelegramClient
from telethon.sessions import StringSession
import os
from dotenv import load_dotenv

load_dotenv()

API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")

if not API_ID or not API_HASH:
    print("❌ API_ID atau API_HASH tidak ditemukan di .env!")
    exit(1)

print("🚀 Memulai generate String Session...")
print("Silakan masukkan detail akun Telegram Anda jika diminta.")

with TelegramClient(StringSession(), int(API_ID), API_HASH) as client:
    session_string = client.session.save()
    print("\n✅ GENERATE BERHASIL!")
    print("-" * 50)
    print(session_string)
    print("-" * 50)
    print("\n⚠️ SALIN KODE DI ATAS ke file .env di VPS Anda sebagai SESSION_STRING.")
