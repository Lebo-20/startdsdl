import os
import asyncio
import logging
import shutil
import tempfile
import random
import re
import psycopg2
from telethon import TelegramClient, events, Button
from dotenv import load_dotenv

load_dotenv()

# Local imports
from api import (
    get_drama_detail, get_all_episodes, get_latest_dramas,
    search_dramas
)
from downloader import download_all_episodes
from merge import merge_episodes
from uploader import upload_drama

# Configuration
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
AUTO_CHANNEL = int(os.environ.get("AUTO_CHANNEL", "-1003857149032"))
AUTO_THREAD = int(os.environ.get("AUTO_THREAD", "6"))
DATABASE_URL = os.environ.get("DATABASE_URL")

# Initialize logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Database logic
class Database:
    def __init__(self, db_url):
        self.db_url = db_url
        self.create_tables()
        
    def get_conn(self):
        return psycopg2.connect(self.db_url)
        
    def create_tables(self):
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS processed_dramas (
                book_id TEXT PRIMARY KEY,
                title TEXT,
                status TEXT,
                attempts INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        cursor.close()
        conn.close()
        logger.info("✅ Database check completed.")
        
    def is_processed(self, book_id, title=None):
        conn = self.get_conn()
        cursor = conn.cursor()
        
        # Check by book_id
        cursor.execute("SELECT status, attempts FROM processed_dramas WHERE book_id = %s", (str(book_id),))
        row = cursor.fetchone()
        
        # Also check by title if provided (to prevent duplicates even with different IDs)
        if not row and title:
            cursor.execute("SELECT status, attempts FROM processed_dramas WHERE title = %s AND status = 'success'", (title,))
            row = cursor.fetchone()
            
        cursor.close()
        conn.close()
        
        if not row:
            return False
            
        status, attempts = row
        if status == 'success':
            return True # Skip permanently if success
            
        if status == 'failed' and attempts >= 2:
            return True # Skip permanently if failed twice
            
        return False

    def mark_success(self, book_id, title):
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO processed_dramas (book_id, title, status, attempts, created_at) 
            VALUES (%s, %s, 'success', 1, CURRENT_TIMESTAMP)
            ON CONFLICT(book_id) DO UPDATE SET 
                status = 'success', 
                attempts = processed_dramas.attempts + 1,
                created_at = CURRENT_TIMESTAMP
        """, (str(book_id), title))
        conn.commit()
        cursor.close()
        conn.close()
        
    def mark_failed(self, book_id, title):
        conn = self.get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO processed_dramas (book_id, title, status, attempts, created_at) 
            VALUES (%s, %s, 'failed', 1, CURRENT_TIMESTAMP)
            ON CONFLICT(book_id) DO UPDATE SET 
                status = 'failed', 
                attempts = processed_dramas.attempts + 1,
                created_at = CURRENT_TIMESTAMP
        """, (str(book_id), title))
        conn.commit()
        cursor.close()
        conn.close()

db = Database(DATABASE_URL)

# Initialize Bot State
class BotState:
    is_auto_running = True
    active_tasks = 0
    current_auto_task = None

# Initialize client
client = TelegramClient('stardust_bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

def get_panel_buttons():
    status_text = "🟢 RUNNING" if BotState.is_auto_running else "🔴 STOPPED"
    return [
        [Button.inline("▶️ Start Auto", b"start_auto"), Button.inline("⏹ Stop Auto", b"stop_auto")],
        [Button.inline(f"📊 Status: {status_text}", b"status")]
    ]

@client.on(events.NewMessage(pattern='/stardust update'))
async def update_bot(event):
    if event.sender_id != ADMIN_ID:
        return
    import subprocess
    import sys
    
    status_msg = await event.reply("🔄 Menarik pembaruan dari GitHub...")
    try:
        # Run git pull
        result = subprocess.run(["git", "pull", "origin", "main"], capture_output=True, text=True)
        await status_msg.edit(f"✅ Repositori berhasil di-pull:\n```\n{result.stdout}\n```\n\nSedang memulai ulang sistem (Restarting)...")
        
        # Restart the script
        os.execl(sys.executable, sys.executable, *sys.argv)
    except Exception as e:
        await status_msg.edit(f"❌ Gagal melakukan update: {e}")

@client.on(events.NewMessage(pattern='/stardust panel'))
async def panel(event):
    if event.sender_id != ADMIN_ID:
        return
    await event.reply("🎛 **StardustTV Control Panel**", buttons=get_panel_buttons())

@client.on(events.CallbackQuery())
async def panel_callback(event):
    if event.sender_id != ADMIN_ID:
        return
        
    data = event.data
    try:
        if data == b"start_auto":
            BotState.is_auto_running = True
            await event.answer("Auto-mode started!")
            await event.edit("🎛 **StardustTV Control Panel**", buttons=get_panel_buttons())
        elif data == b"stop_auto":
            BotState.is_auto_running = False
            await event.answer("Auto-mode stopped!")
            await event.edit("🎛 **StardustTV Control Panel**", buttons=get_panel_buttons())
        elif data == b"status":
            await event.answer(f"Status: {'Running' if BotState.is_auto_running else 'Stopped'}")
            await event.edit("🎛 **StardustTV Control Panel**", buttons=get_panel_buttons())
    except Exception as e:
        logger.error(f"Callback error: {e}")

@client.on(events.NewMessage(pattern='/stardust start'))
@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    await event.reply("Welcome to StardustTV Downloader Bot! 🎉\n\nGunakan perintah `/stardust download {slug} {id}` untuk mulai.\nContoh: `/stardust download rahasia-di-balik-mata-kembar 15203`")

@client.on(events.NewMessage(pattern=r'/stardust download (.+) (\d+)'))
async def on_download(event):
    chat_id = event.chat_id
    
    # Check admin
    if event.sender_id != ADMIN_ID:
        await event.reply("❌ Maaf, perintah ini hanya untuk admin.")
        return
        
    # PRIORITAS MANUAL: Hentikan auto task jika sedang berjalan
    if BotState.current_auto_task and not BotState.current_auto_task.done():
        logger.info("⚔️ Manual command received. Stopping current auto-task...")
        BotState.current_auto_task.cancel()
        try:
            await BotState.current_auto_task
        except asyncio.CancelledError:
            pass
        
    slug = event.pattern_match.group(1).strip()
    drama_id = event.pattern_match.group(2).strip()
    
    # Check if we are in a topic
    thread_id = None
    if event.is_group and event.reply_to:
        thread_id = event.reply_to.reply_to_msg_id
    elif chat_id == AUTO_CHANNEL:
        thread_id = AUTO_THREAD
        
    # 1. Fetch data
    detail = await get_drama_detail(slug, drama_id)
    if not detail:
        await event.reply(f"❌ Gagal mendapatkan detail drama `{slug}/{drama_id}`.")
        return
        
    episodes = await get_all_episodes(slug, drama_id)
    if not episodes:
        await event.reply(f"❌ Drama `{slug}/{drama_id}` tidak memiliki episode.")
        return

    title = detail.get("title") or f"Drama_{drama_id}"
    title = re.sub(r'\s+(Episode|Eps|Ep)\s+\d+$', '', title, flags=re.IGNORECASE).strip()
    
    status_msg = await event.reply(f"🎬 Drama: **{title}**\n📽 Total Episodes: {len(episodes)}\n\n⏳ Sedang mendownload dan memproses...")
    
    success = await process_drama_full(slug, drama_id, chat_id, status_msg, thread_id=thread_id)
    
    if success:
        db.mark_success(drama_id, title)
        logger.info(f"✅ Berhasil memproses manual: {slug}/{drama_id}")
    else:
        db.mark_failed(drama_id, title)
        logger.error(f"❌ Gagal memproses manual: {slug}/{drama_id}")

async def process_drama_full(slug, drama_id, chat_id, status_msg=None, thread_id=None):
    """Refactored logic to be reusable for auto-mode."""
    detail = await get_drama_detail(slug, drama_id)
    episodes = await get_all_episodes(slug, drama_id)
    
    if not detail or not episodes:
        if status_msg: await status_msg.edit(f"❌ Detail atau Episode `{slug}/{drama_id}` tidak ditemukan.")
        return False

    title = detail.get("title") or f"Drama_{drama_id}"
    title = re.sub(r'\s+(Episode|Eps|Ep)\s+\d+$', '', title, flags=re.IGNORECASE).strip()
    description = detail.get("intro") or "No description available."
    poster = detail.get("poster") or ""
    
    # Setup temp directory
    temp_dir = tempfile.mkdtemp(prefix=f"stardust_{drama_id}_")
    video_dir = os.path.join(temp_dir, "episodes")
    os.makedirs(video_dir, exist_ok=True)
    
    try:
        if status_msg: await status_msg.edit(f"🎬 Processing **{title}**...")
        
        # 3. Download
        success = await download_all_episodes(episodes, video_dir)
        if not success:
            if status_msg: await status_msg.edit("❌ Download Gagal.")
            return False

        # 4. Merge
        output_video_path = os.path.join(temp_dir, f"{title}.mp4")
        merge_success = merge_episodes(video_dir, output_video_path)
        if not merge_success:
            if status_msg: await status_msg.edit("❌ Merge Gagal.")
            return False

        # 5. Upload
        if thread_id is None and chat_id == AUTO_CHANNEL:
            thread_id = AUTO_THREAD
            
        upload_success = await upload_drama(
            client, chat_id, 
            title, description, 
            poster, output_video_path,
            episodes_count=len(episodes),
            thread_id=thread_id
        )
        
        if upload_success:
            if status_msg: await status_msg.delete()
            # JEDA SETELAH UPLOAD (Sesuai permintaan user)
            logger.info(f"⏳ Berhasil upload {title}. Menunggu 10 detik...")
            await asyncio.sleep(10)
            return True
        else:
            if status_msg: await status_msg.edit("❌ Upload Gagal.")
            return False
            
    except Exception as e:
        logger.error(f"Error processing {drama_id}: {e}")
        if status_msg: await status_msg.edit(f"❌ Error: {e}")
        return False
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

async def auto_mode_loop():
    """Loop to find and process new dramas automatically from StardustTV."""
    logger.info("🚀 Full Auto-Mode Started (StardustTV).")
    
    is_initial_run = True
    
    while True:
        if not BotState.is_auto_running:
            await asyncio.sleep(5)
            continue
            
        try:
            interval = 5 if is_initial_run else 15
            logger.info(f"🔍 Scanning StardustTV (Next scan in {interval}m)...")
            
            dramas = await get_latest_dramas(pages=3 if is_initial_run else 1) or []
            new_dramas = []
            
            for d in dramas:
                drama_id = str(d.get("id", ""))
                title = d.get("title") or "Unknown"
                title = re.sub(r'\s+(Episode|Eps|Ep)\s+\d+$', '', title, flags=re.IGNORECASE).strip()
                
                if not db.is_processed(drama_id, title=title):
                    new_dramas.append(d)
            
            # --- Build queue ---
            queue = [(d,) for d in new_dramas]
            
            for (drama,) in queue:
                if not BotState.is_auto_running:
                    break
                    
                drama_id = str(drama.get("id", ""))
                slug = drama.get("slug", "")
                title = drama.get("title") or "Unknown"
                title = re.sub(r'\s+(Episode|Eps|Ep)\s+\d+$', '', title, flags=re.IGNORECASE).strip()
                
                if db.is_processed(drama_id, title=title):
                    continue
                
                logger.info(f"✨ [AUTO] New drama: {title} ({slug}/{drama_id}).")
                
                try:
                    await client.send_message(ADMIN_ID, f"🆕 **Auto-System Detection!**\n🎬 `{title}`\n🆔 `{slug}/{drama_id}`\n⏳ Processing...")
                except: pass
                
                # Gunakan create_task agar bisa dibatalkan jika ada perintah manual
                BotState.current_auto_task = asyncio.create_task(
                    process_drama_full(slug, drama_id, AUTO_CHANNEL)
                )
                
                try:
                    success = await BotState.current_auto_task
                    if success:
                        db.mark_success(drama_id, title)
                        logger.info(f"✅ Finished {title}")
                        try:
                            await client.send_message(ADMIN_ID, f"✅ Sukses Auto-Post: **{title}**")
                        except: pass
                    else:
                        db.mark_failed(drama_id, title)
                        logger.error(f"❌ Failed to process {title}")
                except asyncio.CancelledError:
                    logger.info(f"🛑 Auto-task untuk '{title}' dihentikan karena prioritas manual.")
                    # Tidak ditandai sukses/gagal agar bisa dicoba lagi nanti
                    break # Keluar dari batch ini untuk memproses manual
                
                await asyncio.sleep(15)
            
            is_initial_run = False
            for _ in range(interval * 60):
                if not BotState.is_auto_running:
                    break
                await asyncio.sleep(1)
            
        except Exception as e:
            logger.error(f"⚠️ Error in auto_mode_loop: {e}")
            await asyncio.sleep(60)

if __name__ == '__main__':
    logger.info("Initializing StardustTV Bot...")
    client.loop.create_task(auto_mode_loop())
    logger.info("Bot is active and monitoring.")
    client.run_until_disconnected()
