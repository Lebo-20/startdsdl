import os
import asyncio
import logging

logger = logging.getLogger(__name__)


async def download_file_aria2(url: str, filepath: str, retries: int = 3):
    """Downloads a direct file using aria2c with multi-connection support."""
    for attempt in range(1, retries + 1):
        try:
            command = [
                "aria2c",
                "-x", "16", # 16 connections
                "-s", "16",
                "-k", "1M",
                "--retry-wait", "2",
                "--max-tries", "5",
                "-o", os.path.basename(filepath),
                "-d", os.path.dirname(filepath),
                url
            ]

            logger.info(f"Downloading with aria2c attempt {attempt}/{retries}...")
            
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.communicate()

            if process.returncode == 0 and os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                logger.info(f"Successfully downloaded with aria2c: {os.path.basename(filepath)}")
                return True
        except Exception as e:
            logger.error(f"Aria2c error: {e}")
        
        if attempt < retries:
            await asyncio.sleep(2)
    return False

async def download_hls_episode(url: str, filepath: str, retries: int = 3):
    """Downloads an HLS/M3U8 stream to an MP4 file using ffmpeg with retries."""
    # Use aria2c if it's a direct mp4 (rare for Stardust but good to have)
    if url.endswith(".mp4"):
        return await download_file_aria2(url, filepath, retries)
        
    for attempt in range(1, retries + 1):
        try:
            command = [
                "ffmpeg", "-y",
                "-timeout", "10000000",
                "-i", url,
                "-c", "copy",
                "-bsf:a", "aac_adtstoasc",
                filepath,
            ]

            logger.info(f"Downloading HLS attempt {attempt}/{retries} to {os.path.basename(filepath)}...")

            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.communicate()

            if process.returncode == 0 and os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                return True
        except Exception as e:
            logger.error(f"FFmpeg error: {e}")
        
        if attempt < retries:
            await asyncio.sleep(2 * attempt)

    return False


async def download_all_episodes(episodes, download_dir: str, semaphore_count: int = 3, progress_callback=None):
    """
    Downloads all episodes concurrently using ffmpeg for HLS streams.
    episodes: list of dicts with 'episode', 'h264', 'h265' keys
    """
    os.makedirs(download_dir, exist_ok=True)
    semaphore = asyncio.Semaphore(semaphore_count)
    total = len(episodes)
    completed = 0
    success_count = 0

    async def limited_download(ep):
        nonlocal completed, success_count
        async with semaphore:
            ep_num = str(ep.get('episode', 'unk')).zfill(3)
            filename = f"episode_{ep_num}.mp4"
            filepath = os.path.join(download_dir, filename)

            # Prefer h264 for wider compatibility, fallback to h265
            url = ep.get('h264') or ep.get('h265')

            if not url:
                logger.error(f"No URL found for episode {ep_num}")
                completed += 1
                return False

            success = await download_hls_episode(url, filepath)
            completed += 1
            if success:
                success_count += 1
            
            if progress_callback:
                await progress_callback(completed, total, success_count)
                
            return success

    results = await asyncio.gather(*(limited_download(ep) for ep in episodes))
    return all(results)
