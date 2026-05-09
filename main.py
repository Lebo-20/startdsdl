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
from uploader import upload_drama, get_progress_bar

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
        import time
        max_retries = 3
        for i in range(max_retries):
            try:
                return psycopg2.connect(self.db_url)
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                if i == max_retries - 1:
                    raise e
                logger.warning(f"Database connection failed (attempt {i+1}/{max_retries}): {e}. Retrying in 2s...")
                time.sleep(2)
        
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
    processing_lock = asyncio.Lock()
    manual_interrupt = False

# Initialize client
client = TelegramClient('stardust_bot', API_ID, API_HASH)

def get_panel_buttons():
    status_text = "🟢 RUNNING" if BotState.is_auto_running else "🔴 STOPPED"
    return [
        [Button.inline("▶️ Start Auto", b"start_auto"), Button.inline("⏹ Stop Auto", b"stop_auto")],
        [Button.inline(f"📊 Status: {status_text}", b"status")]
    ]

@client.on(events.NewMessage(pattern='/stardustv update'))
async def update_bot(event):
    if event.sender_id != ADMIN_ID:
        return
    import subprocess
    import sys
    
    status_msg = await event.reply("🔄 Menarik pembaruan dari GitHub...\n\n**Note:** Bot akan otomatis restart setelah proses update selesai.")
    try:
        # Run git pull
        result = subprocess.run(["git", "pull", "origin", "main"], capture_output=True, text=True)
        await status_msg.edit(f"✅ Repositori berhasil di-pull:\n```\n{result.stdout}\n```\n\nSedang memulai ulang sistem (Restarting)...")
        
        # Restart the script
        os.execl(sys.executable, sys.executable, *sys.argv)
    except Exception as e:
        await status_msg.edit(f"❌ Gagal melakukan update: {e}")

@client.on(events.CallbackQuery())
async def panel_callback(event):
    if event.sender_id != ADMIN_ID:
        return
        
    data = event.data
    try:
        if data == b"start_auto":
            BotState.is_auto_running = True
            await event.answer("Auto-mode started!", alert=True)
            await event.edit("🎛 **StardustTV Control Panel**\n\nNote: Auto-mode aktif, bot akan scan drama baru setiap 15 menit.", buttons=get_panel_buttons())
        elif data == b"stop_auto":
            BotState.is_auto_running = False
            await event.answer("Auto-mode stopped!", alert=True)
            await event.edit("🎛 **StardustTV Control Panel**\n\nNote: Auto-mode dimatikan. Bot hanya akan memproses perintah manual.", buttons=get_panel_buttons())
        elif data == b"status":
            status = 'Running' if BotState.is_auto_running else 'Stopped'
            await event.answer(f"Status: {status}", alert=False)
            await event.edit("🎛 **StardustTV Control Panel**", buttons=get_panel_buttons())
        elif data == b"bot_active_status":
            status = "Aktif" if BotState.is_auto_running else "Standby"
            await event.answer(f"🚀 Bot dalam keadaan {status}!", alert=True)
    except Exception as e:
        logger.error(f"Callback error: {e}")

@client.on(events.NewMessage(pattern='/stardustv panel'))
async def panel(event):
    if event.sender_id != ADMIN_ID:
        return
    note = "\n\n**Note:** Gunakan panel ini untuk mengatur mode otomatis bot."
    await event.reply("🎛 **StardustTV Control Panel**" + note, buttons=get_panel_buttons())

@client.on(events.NewMessage(pattern='/stardustv start'))
@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    status_text = "🟢 Bot Aktif" if BotState.is_auto_running else "🟡 Bot Standby"
    note = f"\n\n**Note:** {status_text} dan siap menerima perintah. Bot akan otomatis memantau drama baru setiap beberapa menit."
    
    buttons = [
        [Button.inline(f"🤖 Status: {'Aktif' if BotState.is_auto_running else 'Standby'}", b"bot_active_status")]
    ]
    
    await event.reply(
        "Welcome to StardustTV Downloader Bot! 🎉\n\n"
        "Gunakan perintah `/stardustv download {slug} {id}` untuk mulai manual.\n"
        "Contoh: `/stardustv download rahasia-di-balik-mata-kembar 15203`" + note,
        buttons=buttons
    )

@client.on(events.NewMessage(pattern=r'/stardustv download (.+) (\d+)'))
async def on_download(event):
    chat_id = event.chat_id
    
    # Check admin
    if event.sender_id != ADMIN_ID:
        await event.reply("❌ Maaf, perintah ini hanya untuk admin.")
        return
        
    slug = event.pattern_match.group(1).strip()
    drama_id = event.pattern_match.group(2).strip()
    
    # PRIORITAS MANUAL: Hentikan auto task jika sedang berjalan
    if BotState.current_auto_task and not BotState.current_auto_task.done():
        logger.info("⚔️ Manual command received. Cancelling current auto-task...")
        BotState.manual_interrupt = True
        BotState.current_auto_task.cancel()
        try:
            await BotState.current_auto_task
        except asyncio.CancelledError:
            pass
        # Wait a bit for cleanup
        await asyncio.sleep(2)

    # Check if we are in a topic/thread
    thread_id = None
    if event.reply_to:
        # If user replied to a message in a topic, use that topic's ID
        thread_id = event.reply_to.reply_to_msg_id
    elif chat_id == AUTO_CHANNEL:
        # Default to configured thread if in the auto channel
        thread_id = AUTO_THREAD
        
    logger.info(f"Manual download request for {slug}/{drama_id} in chat {chat_id} (Topic: {thread_id})")
        
    async with BotState.processing_lock:
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
        
        note = "\n\n**Note:** Download manual diprioritaskan. Tugas otomatis (jika ada) akan dihentikan sementara."
        status_msg = await event.reply(f"🎬 **Manual Download: {title}**\n📽 Total Episodes: {len(episodes)}\n\n⏳ Sedang mendownload dan memproses..." + note)
        
        success = await process_drama_full(slug, drama_id, chat_id, status_msg, thread_id=thread_id)
        
        if success:
            db.mark_success(drama_id, title)
            logger.info(f"✅ Berhasil memproses manual: {slug}/{drama_id}")
        else:
            db.mark_failed(drama_id, title)
            logger.error(f"❌ Gagal memproses manual: {slug}/{drama_id}")
        
        # Reset interrupt flag after manual finished
        BotState.manual_interrupt = False

async def process_drama_full(slug, drama_id, chat_id, status_msg=None, thread_id=None):
    """Refactored logic to be reusable for auto-mode with rich progress."""
    # Ensure thread_id is set if posting to the AUTO_CHANNEL (Forum support)
    if thread_id is None and chat_id == AUTO_CHANNEL:
        thread_id = AUTO_THREAD
        
    detail = await get_drama_detail(slug, drama_id)
    episodes = await get_all_episodes(slug, drama_id)
    
    if not detail or not episodes:
        if status_msg: await status_msg.edit(f"❌ Detail atau Episode `{slug}/{drama_id}` tidak ditemukan.")
        return False

    title = detail.get("title") or f"Drama_{drama_id}"
    title = re.sub(r'\s+(Episode|Eps|Ep)\s+\d+$', '', title, flags=re.IGNORECASE).strip()
    description = detail.get("intro") or "No description available."
    poster = detail.get("poster") or ""
    total_eps = len(episodes)
    
    # Setup temp directory
    temp_dir = tempfile.mkdtemp(prefix=f"stardust_{drama_id}_")
    video_dir = os.path.join(temp_dir, "episodes")
    os.makedirs(video_dir, exist_ok=True)
    
    # Create a status message if not provided (for auto-mode)
    if not status_msg:
        try:
            status_msg = await client.send_message(
                chat_id, 
                f"🎬 **[AUTO] Processing: {title}**\n⏳ Menyiapkan tugas...",
                reply_to=thread_id
            )
        except Exception as e:
            logger.warning(f"Failed to create status message in {chat_id} (topic {thread_id}): {e}")
    
    async def update_download_progress(completed, total, success_count):
        if not status_msg: return
        percentage = (completed / total) * 100
        bar = get_progress_bar(percentage)
        text = (
            f"🎬 **Download: {title}**\n"
            f"⏳ Downloading episodes...\n"
            f"`{bar}` {percentage:.1f}%\n"
            f"✅ Success: {success_count} / {total}"
        )
        try:
            await status_msg.edit(text)
        except: pass

    try:
        if status_msg:
            await status_msg.edit(f"🎬 **Download: {title}**\n⏳ Initializing...")
        
        # 3. Download
        success = await download_all_episodes(episodes, video_dir, progress_callback=update_download_progress)
        if not success:
            # We still continue if some episodes failed but at least one succeeded?
            # Actually the user example showed 78/85 success, so it implies partial success is okay for them.
            # But downloader.py returns all(results). Let's see.
            files = [f for f in os.listdir(video_dir) if f.endswith(".mp4")]
            if not files:
                if status_msg: await status_msg.edit(f"❌ **{title}**: Download Gagal (Semua episode gagal).")
                return False
            logger.warning(f"Some episodes failed for {title}, but continuing with {len(files)} files.")

        # 4. Merge
        if status_msg:
            await status_msg.edit(f"🎬 **Merge: {title}**\n⏳ Merging {len(os.listdir(video_dir))} episodes into one file...")
            
        output_video_path = os.path.join(temp_dir, f"{title}.mp4")
        merge_success = merge_episodes(video_dir, output_video_path)
        if not merge_success:
            if status_msg: await status_msg.edit(f"❌ **{title}**: Merge Gagal.")
            return False

        # 5. Upload
        if status_msg:
            await status_msg.edit(f"🎬 **Upload: {title}**\n📤 Sending to Telegram...")

        upload_success = await upload_drama(
            client, chat_id, 
            title, description, 
            poster, output_video_path,
            episodes_count=total_eps,
            thread_id=thread_id
        )
        
        if upload_success:
            if status_msg: await status_msg.delete()
            logger.info(f"⏳ Berhasil upload {title}. Menunggu 10 detik...")
            await asyncio.sleep(10)
            return True
        else:
            if status_msg: await status_msg.edit(f"❌ **{title}**: Upload Gagal.")
            return False
            
    except Exception as e:
        logger.error(f"Error processing {drama_id}: {e}")
        if status_msg: await status_msg.edit(f"❌ **Error {title}**: {e}")
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
            # Jika baru saja ada interupsi manual, tunggu sebentar sebelum scan lagi
            if BotState.manual_interrupt:
                await asyncio.sleep(10)
                continue

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
            
            if not new_dramas:
                logger.info("ℹ️ No new dramas found to process.")
            else:
                logger.info(f"✨ Found {len(new_dramas)} new dramas to process.")
            
            # --- Build queue ---
            queue = [(d,) for d in new_dramas]
            
            for (drama,) in queue:
                if not BotState.is_auto_running or BotState.manual_interrupt:
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
                
                # Gunakan lock untuk memastikan tidak ada konflik dengan manual download
                async with BotState.processing_lock:
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
                if not BotState.is_auto_running or BotState.manual_interrupt:
                    break
                await asyncio.sleep(1)
            
        except Exception as e:
            logger.error(f"⚠️ Error in auto_mode_loop: {e}")
            await asyncio.sleep(60)

if __name__ == '__main__':
    logger.info("Initializing StardustTV Bot...")
    
    async def startup_check():
        try:
            await client.start(bot_token=BOT_TOKEN)
            me = await client.get_me()
            logger.info(f"✅ Bot logged in as: @{me.username} ({me.id})")
            
            # Check access to AUTO_CHANNEL
            try:
                entity = await client.get_entity(AUTO_CHANNEL)
                logger.info(f"✅ Access to AUTO_CHANNEL ({AUTO_CHANNEL}) confirmed: {getattr(entity, 'title', 'Private Chat')}")
            except Exception as e:
                logger.error(f"❌ CANNOT access AUTO_CHANNEL ({AUTO_CHANNEL}). Make sure bot is an admin: {e}")
                
        except Exception as e:
            logger.error(f"❌ Startup error: {e}")

    client.loop.run_until_complete(startup_check())
    client.loop.create_task(auto_mode_loop())
    logger.info("Bot is active and monitoring.")
    client.run_until_disconnected()
