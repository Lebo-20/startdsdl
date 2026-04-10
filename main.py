import os
import asyncio
import logging
import shutil
import tempfile
import random
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
from firebase_db import is_already_uploaded, mark_as_uploaded

# Configuration (Use environment variables or replace these directly)
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
AUTO_CHANNEL = int(os.environ.get("AUTO_CHANNEL", "-1003857149032"))
AUTO_THREAD = int(os.environ.get("AUTO_THREAD", "6"))
PROCESSED_FILE = "processed.json"

# Initialize state
def load_processed():
    if os.path.exists(PROCESSED_FILE):
        import json
        with open(PROCESSED_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_processed(data):
    import json
    with open(PROCESSED_FILE, "w") as f:
        json.dump(list(data), f)

processed_ids = load_processed()

# Initialize logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize Bot State
class BotState:
    is_auto_running = True
    is_processing = False

# Initialize client
client = TelegramClient('dramabox_bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

def get_panel_buttons():
    status_text = "🟢 RUNNING" if BotState.is_auto_running else "🔴 STOPPED"
    return [
        [Button.inline("▶️ Start Auto", b"start_auto"), Button.inline("⏹ Stop Auto", b"stop_auto")],
        [Button.inline(f"📊 Status: {status_text}", b"status")]
    ]

@client.on(events.NewMessage(pattern='/update'))
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
        
        # Restart the script forcefully replacing the current process image
        os.execl(sys.executable, sys.executable, *sys.argv)
    except Exception as e:
        await status_msg.edit(f"❌ Gagal melakukan update: {e}")

@client.on(events.NewMessage(pattern='/panel'))
async def panel(event):
    if event.chat_id != ADMIN_ID:
        return
    await event.reply("🎛 **Dramabox Control Panel**", buttons=get_panel_buttons())

@client.on(events.CallbackQuery())
async def panel_callback(event):
    if event.sender_id != ADMIN_ID:
        return
        
    data = event.data
    
    try:
        if data == b"start_auto":
            BotState.is_auto_running = True
            await event.answer("Auto-mode started!")
            await event.edit("🎛 **Dramabox Control Panel**", buttons=get_panel_buttons())
        elif data == b"stop_auto":
            BotState.is_auto_running = False
            await event.answer("Auto-mode stopped!")
            await event.edit("🎛 **Dramabox Control Panel**", buttons=get_panel_buttons())
        elif data == b"status":
            await event.answer(f"Status: {'Running' if BotState.is_auto_running else 'Stopped'}")
            await event.edit("🎛 **Dramabox Control Panel**", buttons=get_panel_buttons())
    except Exception as e:
        if "message is not modified" in str(e).lower() or "Message string and reply markup" in str(e):
            pass # Ignore if button is already in that state
        else:
            logger.error(f"Callback error: {e}")

@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    await event.reply("Welcome to Dramabox Downloader Bot! 🎉\n\nGunakan perintah `/download {slug} {id}` untuk mulai.\nContoh: `/download rahasia-di-balik-mata-kembar 15203`")

@client.on(events.NewMessage(pattern=r'/download (.+) (\d+)'))
async def on_download(event):
    chat_id = event.chat_id
    
    # Check admin
    if chat_id != ADMIN_ID and chat_id != AUTO_CHANNEL:
        await event.reply("❌ Maaf, perintah ini hanya untuk admin.")
        return
        
    if BotState.is_processing:
        await event.reply("⚠️ Sedang memproses drama lain. Tunggu hingga selesai (Anti bentrok).")
        return
        
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
    
    status_msg = await event.reply(f"🎬 Drama: **{title}**\n📽 Total Episodes: {len(episodes)}\n\n⏳ Sedang mendownload dan memproses...")
    
    BotState.is_processing = True
    success = await process_drama_full(slug, drama_id, chat_id, status_msg, thread_id=thread_id)
    
    if success:
        processed_ids.add(drama_id)
        save_processed(processed_ids)
        mark_as_uploaded(title) # Save to Firebase
        logger.info(f"✅ Berhasil memproses manual: {slug}/{drama_id}")
    else:
        logger.error(f"❌ Gagal memproses manual: {slug}/{drama_id}")
        
    BotState.is_processing = False

async def process_drama_full(slug, drama_id, chat_id, status_msg=None, thread_id=None):
    """Refactored logic to be reusable for auto-mode."""
    detail = await get_drama_detail(slug, drama_id)
    episodes = await get_all_episodes(slug, drama_id)
    
    if not detail or not episodes:
        if status_msg: await status_msg.edit(f"❌ Detail atau Episode `{slug}/{drama_id}` tidak ditemukan.")
        return False

    title = detail.get("title") or f"Drama_{drama_id}"
    description = detail.get("intro") or "No description available."
    poster = detail.get("poster") or ""
    
    # 2. Setup temp directory
    temp_dir = tempfile.mkdtemp(prefix=f"dramabox_{drama_id}_")
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
        # If thread_id is not provided, check if we are sending to AUTO_CHANNEL
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
    global processed_ids
    
    logger.info("🚀 Full Auto-Mode Started (StardustTV).")
    
    # Run immediately on startup
    is_initial_run = True
    
    while True:
        if not BotState.is_auto_running:
            await asyncio.sleep(5)
            continue
            
        try:
            interval = 5 if is_initial_run else 15 # Check every 15 mins after first run
            logger.info(f"🔍 Scanning StardustTV for new dramas (Next scan in {interval}m)...")
            
            # --- SOURCE: StardustTV List ---
            logger.info("🔍 Scanning StardustTV list...")
            dramas = await get_latest_dramas(pages=3 if is_initial_run else 1) or []
            new_dramas = [d for d in dramas if str(d.get("id", "")) not in processed_ids]
            
            # --- Build queue ---
            queue = [(d,) for d in new_dramas]
            
            # --- FALLBACK: Popular Search (when list is empty) ---
            if not queue and not is_initial_run:
                logger.info("ℹ️ List up to date. Fetching Popular Search fallback...")
                pop_dramas = await search_dramas("populer") or []
                pop_new = [d for d in pop_dramas if str(d.get("id", "")) not in processed_ids]
                if pop_new:
                    random_drama = random.choice(pop_new)
                    queue = [(random_drama,)]
                    logger.info(f"🎲 Random popular picked: {random_drama.get('title')}")
                else:
                    logger.info("😴 No new dramas found in any source.")
            
            new_found = 0
            
            for (drama,) in queue:
                if not BotState.is_auto_running:
                    break
                    
                drama_id = str(drama.get("id", ""))
                slug = drama.get("slug", "")
                title = drama.get("title") or "Unknown"
                
                if not drama_id or not slug:
                    continue
                    
                if drama_id in processed_ids:
                    logger.info(f"⏭ Skipping {title}: Already in processed.json")
                    continue
                
                if is_already_uploaded(title):
                    logger.info(f"⏭ Skipping {title}: Already in Firebase")
                    # Sync to local processed_ids if missing
                    processed_ids.add(drama_id)
                    save_processed(processed_ids)
                    continue
                
                logger.info(f"✨ [STARDUSTTV] New drama: {title} ({slug}/{drama_id}). Starting process...")
                
                # Notify admin
                try:
                    await client.send_message(ADMIN_ID, f"🆕 **Auto-System Mendeteksi Drama Baru!**\n🎬 `{title}`\n🆔 `{slug}/{drama_id}`\n⏳ Memproses download & merge...")
                except: pass
                
                BotState.is_processing = True
                new_found += 1
                # Process to target channel
                success = await process_drama_full(slug, drama_id, AUTO_CHANNEL)
                BotState.is_processing = False
                
                if success:
                    # Mark as processed ONLY on success
                    processed_ids.add(drama_id)
                    save_processed(processed_ids)
                    mark_as_uploaded(title) # Save to Firebase
                    
                    logger.info(f"✅ Finished {title}")
                    try:
                        await client.send_message(ADMIN_ID, f"✅ Sukses Auto-Post: **{title}** ke channel.")
                    except: pass
                else:
                    logger.error(f"❌ Failed to process {title}. Will retry in next scan.")
                    try:
                        await client.send_message(ADMIN_ID, f"⚠️ **WARNING**: Proses `{title}` gagal dan akan dicoba lagi nanti.")
                    except: pass
                
                # Prevent hitting API/Telegram rate limits too hard
                await asyncio.sleep(15)
            
            if new_found == 0:
                logger.info("😴 No new dramas found in this scan.")
            
            is_initial_run = False
            
            # Wait for next interval but break early if auto_running is changed
            for _ in range(interval * 60):
                if not BotState.is_auto_running:
                    break
                await asyncio.sleep(1)
            
        except Exception as e:
            logger.error(f"⚠️ Error in auto_mode_loop: {e}")
            await asyncio.sleep(60) # retry after 1 min

if __name__ == '__main__':
    logger.info("Initializing Dramabox Auto-Bot (StardustTV)...")
    
    # Start auto loop and keep the client running
    client.loop.create_task(auto_mode_loop())
    
    logger.info("Bot is active and monitoring.")
    client.run_until_disconnected()
