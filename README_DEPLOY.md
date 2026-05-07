# Panduan Pemasangan Bot di VPS (PuTTY + PM2)

Panduan ini menjelaskan cara menginstal dan menjalankan bot StardustTV (dan FlickReels) di Linux VPS menggunakan PM2 agar berjalan 24/7 di latar belakang.

## 1. Persiapan Awal di VPS (via PuTTY)
Login ke VPS Anda menggunakan PuTTY, lalu jalankan perintah berikut untuk menginstal dependensi sistem yang diperlukan:

```bash
# Update sistem
sudo apt update && sudo apt upgrade -y

# Instal Python dan Pip
sudo apt install python3 python3-pip -y

# Instal FFmpeg (Penting untuk penggabungan video)
sudo apt install ffmpeg -y

# Instal Git
sudo apt install git -y

# Instal Node.js dan PM2 (Untuk manajemen proses)
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs
sudo npm install pm2 -g
```

## 2. Kloning Repositori
Masuk ke folder tempat Anda ingin menyimpan bot, lalu klon dari GitHub:

```bash
git clone https://github.com/Lebo-20/startdsdl.git
cd startdsdl
```

## 3. Instalasi Dependensi Python
Instal semua library yang dibutuhkan bot:

```bash
pip3 install -r requirements.txt
```

## 4. Konfigurasi Environment
Buat file `.env` di dalam folder bot dan masukkan konfigurasi Anda (API_ID, BOT_TOKEN, DATABASE_URL, dll):

```bash
nano .env
```
*Gunakan CTRL+O, ENTER, lalu CTRL+X untuk menyimpan dan keluar dari editor nano.*

## 5. Menjalankan Bot dengan PM2
Agar bot tidak mati saat jendela PuTTY ditutup, gunakan PM2:

### Untuk StardustTV:
```bash
pm2 start main.py --name "stardust-bot" --interpreter python3
```

### Untuk FlickReels:
```bash
# Masuk ke folder flickreels terlebih dahulu
pm2 start main.py --name "flickreels-bot" --interpreter python3
```

### Perintah Penting PM2:
- **Melihat status bot:** `pm2 list`
- **Melihat log (error/progress):** `pm2 logs stardust-bot`
- **Menghentikan bot:** `pm2 stop stardust-bot`
- **Memulai ulang bot:** `pm2 restart stardust-bot`
- **Agar bot auto-start saat VPS restart:**
  ```bash
  pm2 save
  pm2 startup
  ```
  *(Ikuti instruksi perintah yang muncul di layar setelah menjalankan `pm2 startup`)*

## 6. Update Bot di Masa Depan
Jika ada perubahan di GitHub dan Anda ingin memperbarui bot di VPS:

```bash
pm2 stop stardust-bot
git pull
pm2 start stardust-bot
```
