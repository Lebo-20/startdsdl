import os
import asyncio
import logging
import shutil
import tempfile
import random
import re
import psycopg2
import sys
import glob
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from dotenv import load_dotenv

load_dotenv()

# Initialize logging first
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Local imports
from api import (
    get_drama_detail, get_all_episodes, get_latest_dramas,
    search_dramas
)
from downloader import download_all_episodes
from merge import merge_episodes
from uploader import upload_drama, get_progress_bar
from database import db
from firebase_db import is_already_uploaded, mark_as_uploaded

# Critical check for database
if db is None:
    logger.critical("❌ CRITICAL ERROR: Database initialization failed! Check DATABASE_URL.")
    sys.exit(1)

# Configuration
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
AUTO_CHANNEL = int(os.environ.get("AUTO_CHANNEL", "-1003857149032"))
AUTO_THREAD = int(os.environ.get("AUTO_THREAD", "6"))
DATABASE_URL = os.environ.get("DATABASE_URL")
SESSION_STRING = os.environ.get("SESSION_STRING", "")

# Initialize client with session logic
SESSION_STRING = SESSION_STRING.strip().strip('"').strip("'")
if SESSION_STRING and len(SESSION_STRING) > 10:
    logger.info("🔐 Menggunakan StringSession untuk menghindari masalah SQLite.")
    session = StringSession(SESSION_STRING)
else:
    SESSION_PATH = '/root/startdsdl/stardust'
    logger.info(f"📂 Menggunakan FileSession di path: {SESSION_PATH}")
    
    # Pre-startup check: Pastikan folder bisa ditulis
    session_dir = os.path.dirname(SESSION_PATH)
    if not os.path.exists(session_dir):
        try:
            os.makedirs(session_dir, exist_ok=True)
        except Exception as e:
            logger.error(f"❌ ERROR: Gagal membuat direktori session: {e}")
            sys.exit(1)
            
    if not os.access(session_dir, os.W_OK):
        logger.error(f"❌ ERROR: Direktori {session_dir} tidak memiliki izin tulis. SQLite akan gagal.")
        sys.exit(1)
    session = SESSION_PATH

client = TelegramClient(session, API_ID, API_HASH)
# Optimasi: Menonaktifkan penyimpanan entities untuk mengurangi beban tulis SQLite
client.session.save_entities = False

# Initialize Bot State
class BotState:
    is_auto_running = True
    active_tasks = 0
    current_auto_task = None
    processing_lock = asyncio.Lock()
    manual_interrupt = False

def get_panel_buttons():
    status_text = "🟢 RUNNING" if BotState.is_auto_running else "🔴 STOPPED"
    return [
        [Button.inline("▶️ Start Auto", b"start_auto"), Button.inline("⏹ Stop Auto", b"stop_auto")],
        [Button.inline("📥 Manual Download", b"manual_download"), Button.inline("🔄 Update Bot", b"update_bot")],
        [Button.inline(f"📊 Status: {status_text}", b"status")]
    ]

@client.on(events.NewMessage(pattern='/stardustv update'))
async def update_bot(event):
    if event.sender_id != ADMIN_ID:
        return
    import subprocess
    status_msg = await event.reply("🔄 Menarik pembaruan dari GitHub...")
    try:
        result = subprocess.run(["git", "pull", "origin", "main"], capture_output=True, text=True)
        await status_msg.edit(f"✅ Repositori berhasil di-pull:\n```\n{result.stdout}\n```\n\nRestarting...")
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
            await event.edit("🎛 **StardustTV Control Panel**", buttons=get_panel_buttons())
        elif data == b"stop_auto":
            BotState.is_auto_running = False
            await event.answer("Auto-mode stopped!", alert=True)
            await event.edit("🎛 **StardustTV Control Panel**", buttons=get_panel_buttons())
        elif data == b"status":
            status = 'Running' if BotState.is_auto_running else 'Stopped'
            await event.answer(f"Status: {status}", alert=False)
        elif data == b"show_panel":
            await event.edit("🎛 **StardustTV Control Panel**", buttons=get_panel_buttons())
    except Exception as e:
        logger.error(f"Callback error: {e}")

@client.on(events.NewMessage(pattern='/stardustv panel'))
async def panel(event):
    if event.sender_id != ADMIN_ID: return
    await event.reply("🎛 **StardustTV Control Panel**", buttons=get_panel_buttons())

@client.on(events.NewMessage(pattern='/stardustv start'))
@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    buttons = [[Button.inline("🎛 Control Panel", b"show_panel")]]
    await event.reply("Welcome to StardustTV Downloader Bot! 🎉", buttons=buttons)

@client.on(events.NewMessage(pattern=r'/stardustv download (.+) (\d+)'))
async def on_download(event):
    if event.sender_id != ADMIN_ID:
        await event.reply("❌ Maaf, perintah ini hanya untuk admin.")
        return
    slug = event.pattern_match.group(1).strip()
    drama_id = event.pattern_match.group(2).strip()
    
    if BotState.current_auto_task and not BotState.current_auto_task.done():
        logger.info("⚔️ Manual command received. Cancelling current auto-task...")
        BotState.manual_interrupt = True
        BotState.current_auto_task.cancel()
        try: await BotState.current_auto_task
        except asyncio.CancelledError: pass
        await asyncio.sleep(2)

    chat_id = event.chat_id
    thread_id = event.reply_to.reply_to_msg_id if event.reply_to else (AUTO_THREAD if chat_id == AUTO_CHANNEL else None)
        
    async with BotState.processing_lock:
        detail = await get_drama_detail(slug, drama_id)
        if not detail:
            await event.reply("❌ Gagal mendapatkan detail drama.")
            return
        episodes = await get_all_episodes(slug, drama_id)
        title = re.sub(r'\s+(Episode|Eps|Ep)\s+\d+$', '', detail.get("title", ""), flags=re.IGNORECASE).strip()
        
        if db.is_processed(drama_id, title=title):
            await event.reply(f"ℹ️ **{title}** sudah pernah di-upload.")
            return

        status_msg = await event.reply(f"🎬 **Manual Download: {title}**\n⏳ Memproses...")
        success = await process_drama_full(slug, drama_id, chat_id, status_msg, thread_id=thread_id)
        if success: db.mark_success(drama_id, title)
        else: db.mark_failed(drama_id, title)
        BotState.manual_interrupt = False

async def process_drama_full(slug, drama_id, chat_id, status_msg=None, thread_id=None):
    if thread_id is None and chat_id == AUTO_CHANNEL: thread_id = AUTO_THREAD
    detail = await get_drama_detail(slug, drama_id)
    episodes = await get_all_episodes(slug, drama_id)
    if not detail or not episodes: return False

    title = re.sub(r'\s+(Episode|Eps|Ep)\s+\d+$', '', detail.get("title", ""), flags=re.IGNORECASE).strip()
    if db.is_processed(drama_id, title=title): return True

    temp_dir = tempfile.mkdtemp(prefix=f"stardust_{drama_id}_")
    video_dir = os.path.join(temp_dir, "episodes")
    os.makedirs(video_dir, exist_ok=True)
    
    if not status_msg:
        status_msg = await client.send_message(chat_id, f"🎬 **[AUTO] Processing: {title}**", reply_to=thread_id)
    
    async def update_download_progress(completed, total, success_count):
        if not status_msg: return
        percentage = (completed / total) * 100
        bar = get_progress_bar(percentage)
        try: await status_msg.edit(f"🎬 **Download: {title}**\n`{bar}` {percentage:.1f}%\n✅ {success_count}/{total}")
        except: pass

    try:
        success = await download_all_episodes(episodes, video_dir, progress_callback=update_download_progress)
        if not success and not [f for f in os.listdir(video_dir) if f.endswith(".mp4")]: return False
        
        output_video_path = os.path.join(temp_dir, f"{title}.mp4")
        if not merge_episodes(video_dir, output_video_path): return False

        return await upload_drama(
            client, chat_id, title, detail.get("intro", ""), detail.get("poster", ""), 
            output_video_path, episodes_count=len(episodes), thread_id=thread_id
        )
    except Exception as e:
        logger.error(f"Error: {e}")
        return False
    finally:
        if os.path.exists(temp_dir): shutil.rmtree(temp_dir)

async def auto_mode_loop():
    logger.info("🚀 Full Auto-Mode Started.")
    is_initial_run = True
    while True:
        if not BotState.is_auto_running:
            await asyncio.sleep(5)
            continue
        try:
            if BotState.manual_interrupt:
                await asyncio.sleep(10)
                continue
            dramas = await get_latest_dramas(pages=3 if is_initial_run else 1) or []
            for d in dramas:
                if not BotState.is_auto_running or BotState.manual_interrupt: break
                drama_id = str(d.get("id"))
                title = re.sub(r'\s+(Episode|Eps|Ep)\s+\d+$', '', d.get("title", ""), flags=re.IGNORECASE).strip()
                if db.is_processed(drama_id, title=title): continue
                
                async with BotState.processing_lock:
                    BotState.current_auto_task = asyncio.create_task(process_drama_full(d.get("slug"), drama_id, AUTO_CHANNEL))
                    if await BotState.current_auto_task: db.mark_success(drama_id, title)
                    else: db.mark_failed(drama_id, title)
                await asyncio.sleep(15)
            is_initial_run = False
            await asyncio.sleep(15 * 60)
        except Exception as e:
            logger.error(f"Auto error: {e}")
            await asyncio.sleep(60)

async def startup_check():
    # Cleanup only for FileSession
    if not SESSION_STRING:
        for s_file in [f"{SESSION_PATH}.session", f"{SESSION_PATH}.session-journal", f"{SESSION_PATH}.session-wal"]:
            if os.path.exists(s_file):
                try: os.remove(s_file)
                except: pass

    # Clean Temp
    temp_base = tempfile.gettempdir()
    for pattern in ["stardust_*", "thumb_*.jpg", "poster_*.jpg"]:
        for f in glob.glob(os.path.join(temp_base, pattern)):
            try: 
                if os.path.isdir(f): shutil.rmtree(f)
                else: os.remove(f)
            except: pass
    
    # Start client (login)
    try:
        await client.start(bot_token=BOT_TOKEN)
        me = await client.get_me()
        logger.info(f"✅ Bot logged in as: @{me.username}")
    except Exception as e:
        logger.critical(f"❌ Startup login failed: {e}")
        raise e

if __name__ == '__main__':
    try:
        client.loop.run_until_complete(startup_check())
        client.loop.create_task(auto_mode_loop())
        client.run_until_disconnected()
    except Exception as e:
        logger.critical(f"💥 FATAL ERROR: {e}")
        sys.exit(1)
