
# Panduan Instalasi Bot Dramabox di Linux (vía Putty)

### 1. Update & Install FFmpeg
Ketik perintah ini di Putty:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv ffmpeg git screen
```

### 2. Pindahkan Folder
Pastikan file Anda sudah ada di server (via WinSCP/Git), masuk ke folder:
```bash
cd stardusttv
```

### 3. Setup Virtual Environment (PENTING)
Agar library tidak berantakan:
```bash
python3 -m venv venv
source venv/bin/activate
```

### 4. Install Dependensi
```bash
pip install -r requirements.txt
```

### 5. Jalankan Bot 24/7 (via Screen)
Agar bot tidak mati saat Putty ditutup:
1. Ketik: `screen -S bot`
2. Jalankan bot: `python3 main.py`
3. Keluar dari screen (biarkan bot jalan): Tekan **CTRL + A** lalu tekan **D**.
4. Untuk cek lagi: `screen -r bot`
