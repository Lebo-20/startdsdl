import os
import asyncio
import time
import logging
from telethon import TelegramClient, events
from telethon.tl.types import DocumentAttributeVideo

logger = logging.getLogger(__name__)

last_update_time = 0

def get_progress_bar(percentage):
    """Generates a visual progress bar."""
    filled_len = int(percentage / 10)
    bar = "■" * filled_len + "□" * (10 - filled_len)
    return f"|{bar}| {percentage:.0f}%"

def format_time(seconds):
    """Formats seconds into human-readable time."""
    if seconds < 60:
        return f"{int(seconds)}s"
    minutes = int(seconds // 60)
    seconds = int(seconds % 60)
    return f"{minutes}m {seconds}s"

async def upload_progress(current, total, event, title, episodes_count, start_time):
    """Callback function for upload progress with rich formatting."""
    global last_update_time
    now = time.time()
    
    # Update every 5 seconds to avoid flood
    if now - last_update_time < 5:
        return
        
    last_update_time = now
    percentage = (current / total) * 100
    progress_bar = get_progress_bar(percentage)
    
    # Calculate estimation
    elapsed_time = now - start_time
    if current > 0:
        speed = current / elapsed_time # bytes per second
        remaining_bytes = total - current
        eta_seconds = remaining_bytes / speed
        eta_text = format_time(eta_seconds)
    else:
        eta_text = "Menghitung..."

    status_text = (
        f"🎬 **{title}**\n"
        f"🔥 Status: upload...\n"
        f"🎞 Episode {episodes_count}/{episodes_count}\n"
        f"{progress_bar}\n"
        f"⏳ Estimasi Selesai: {eta_text}"
    )

    try:
        await event.edit(status_text)
    except Exception:
        pass

async def upload_drama(client: TelegramClient, chat_id: int, 
                       title: str, description: str, 
                       poster_url: str, video_path: str,
                       episodes_count: int = 0,
                       thread_id: int = None):
    """
    Uploads the drama information and merged video to Telegram.
    """
    import subprocess
    import tempfile
    
    logger.info(f"Uploading '{title}' to {chat_id} (Topic: {thread_id or 'General'})")
    
    try:
        # 1. Send Poster + Description as PHOTO
        caption = f"🎬 **{title}**\n\n📝 **Sinopsis:**\n{description[:800]}..."
        
        import httpx
        poster_path = None
        if poster_url:
            try:
                async with httpx.AsyncClient(timeout=30) as http_client:
                    resp = await http_client.get(poster_url)
                    if resp.status_code == 200:
                        poster_path = os.path.join(tempfile.gettempdir(), f"poster_{int(time.time())}.jpg")
                        with open(poster_path, "wb") as pf:
                            pf.write(resp.content)
            except Exception as e:
                logger.warning(f"Failed to download poster: {e}")
        
        # Send poster
        await client.send_file(
            chat_id,
            poster_path or poster_url if poster_url else None,
            caption=caption,
            parse_mode='md',
            force_document=False,
            reply_to=thread_id
        )
        
        if poster_path and os.path.exists(poster_path):
            os.remove(poster_path)
        
        # 2. Information Extraction
        status_msg = await client.send_message(
            chat_id, 
            "📤 **Menyiapkan Video...**\nEkstraksi metadata video.",
            reply_to=thread_id
        )
        
        duration = 0
        width = 0
        height = 0
        try:
            ffprobe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height", "-of", "default=noprint_wrappers=1:nokey=1", video_path]
            output = subprocess.check_output(ffprobe_cmd, text=True).strip().split('\n')
            if len(output) >= 3:
                width = int(output[0])
                height = int(output[1])
                duration = int(float(output[2]))
        except Exception as e:
            logger.warning(f"Failed to extract video info: {e}")

        # 3. Extract Thumbnail
        thumb_path = os.path.join(tempfile.gettempdir(), f"thumb_{int(time.time())}.jpg")
        try:
            subprocess.run(["ffmpeg", "-y", "-i", video_path, "-ss", "00:00:01.000", "-vframes", "1", thumb_path], capture_output=True)
            if not os.path.exists(thumb_path):
                thumb_path = None
        except Exception as e:
            logger.warning(f"Failed to generate thumbnail: {e}")
            thumb_path = None

        await status_msg.edit(f"🎬 **{title}**\n🔥 Status: Mengunggah ke Telegram...\n🎞 Total {episodes_count} Episode")
        
        start_time = time.time()
        video_attributes = [
            DocumentAttributeVideo(
                duration=duration,
                w=width,
                h=height,
                supports_streaming=True
            )
        ]
        
        # 4. Upload Video
        await client.send_file(
            chat_id,
            video_path,
            caption=f"🎥 **Full Episode: {title}**",
            force_document=False, 
            thumb=thumb_path,
            attributes=video_attributes,
            progress_callback=lambda c, t: upload_progress(c, t, status_msg, title, episodes_count, start_time),
            supports_streaming=True,
            reply_to=thread_id
        )
        
        await status_msg.delete()
        if thumb_path and os.path.exists(thumb_path):
            os.remove(thumb_path)
            
        logger.info(f"Successfully uploaded {title} to Telegram topic {thread_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to upload to Telegram: {e}")
        return False

