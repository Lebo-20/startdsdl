from telethon.sync import TelegramClient
from telethon.sessions import StringSession
import os
from dotenv import load_dotenv

# Load existing .env
load_dotenv()

API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")

if not API_ID or not API_HASH:
    print("❌ API_ID atau API_HASH tidak ditemukan di .env!")
    print("Pastikan Anda sudah mengisi API_ID dan API_HASH di file .env lokal.")
    exit(1)

print("🚀 Memulai generate String Session...")
print("Silakan ikuti instruksi login di bawah ini.")

try:
    with TelegramClient(StringSession(), int(API_ID), API_HASH) as client:
        session_string = client.session.save()
        print("\n✅ GENERATE BERHASIL!")
        print("-" * 60)
        print(session_string)
        print("-" * 60)
        
        # Opsi: Coba simpan ke .env lokal otomatis
        if os.path.exists(".env"):
            with open(".env", "a") as f:
                f.write(f"\n# Generated on startup\nSESSION_STRING={session_string}\n")
            print("💾 KODE SUDAH DITAMBAHKAN ke file .env lokal Anda.")
        
        print("\n⚠️  SILAKAN SALIN KODE DI ATAS (yang sangat panjang itu)")
        print("Lalu masukkan ke file .env di VPS Anda sebagai SESSION_STRING.")
except Exception as e:
    print(f"❌ Terjadi kesalahan: {e}")
