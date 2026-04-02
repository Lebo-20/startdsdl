import os
import asyncio
import logging

logger = logging.getLogger(__name__)


async def download_hls_episode(url: str, filepath: str):
    """Downloads an HLS/M3U8 stream to an MP4 file using ffmpeg."""
    try:
        command = [
            "ffmpeg", "-y",
            "-i", url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            filepath,
        ]

        logger.info(f"Downloading HLS stream to {os.path.basename(filepath)}...")

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(f"FFmpeg failed for {filepath}: {stderr.decode()[-500:]}")
            return False

        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            logger.info(f"Downloaded {os.path.basename(filepath)}")
            return True
        else:
            logger.error(f"Output file missing or empty: {filepath}")
            return False

    except Exception as e:
        logger.error(f"Failed to download {url}: {e}")
        return False


async def download_all_episodes(episodes, download_dir: str, semaphore_count: int = 3):
    """
    Downloads all episodes concurrently using ffmpeg for HLS streams.
    episodes: list of dicts with 'episode', 'h264', 'h265' keys
    """
    os.makedirs(download_dir, exist_ok=True)
    semaphore = asyncio.Semaphore(semaphore_count)

    async def limited_download(ep):
        async with semaphore:
            ep_num = str(ep.get('episode', 'unk')).zfill(3)
            filename = f"episode_{ep_num}.mp4"
            filepath = os.path.join(download_dir, filename)

            # Prefer h264 for wider compatibility, fallback to h265
            url = ep.get('h264') or ep.get('h265')

            if not url:
                logger.error(f"No URL found for episode {ep_num}")
                return False

            success = await download_hls_episode(url, filepath)
            return success

    results = await asyncio.gather(*(limited_download(ep) for ep in episodes))
    return all(results)
