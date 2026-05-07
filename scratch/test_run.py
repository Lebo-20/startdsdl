
import os
import sys
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient

# Add root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from api import get_latest_dramas
from main import process_drama_full, BotState

async def main():
    load_dotenv()
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    AUTO_CHANNEL = int(os.environ.get("AUTO_CHANNEL", "0"))
    
    print("Starting Telegram Client...")
    client = TelegramClient('dramabox_bot', API_ID, API_HASH)
    await client.start(bot_token=BOT_TOKEN)
    
    # We need to set the client in main.py's global scope if we use their process_drama_full
    # But wait, main.py already has a 'client' global. 
    # Let's check how main.py's process_drama_full uses it.
    # It uses the global 'client' variable.
    
    import main
    main.client = client # Inject our started client
    
    print("Fetching latest dramas...")
    dramas = await get_latest_dramas(pages=1)
    if not dramas:
        print("No dramas found.")
        return
        
    target = dramas[0]
    title = target.get('title')
    slug = target.get('slug')
    drama_id = target.get('id')
    
    print(f"Targeting Judul 1: {title} ({slug}/{drama_id})")
    
    # Check if already processed (optional for test, but good to know)
    if str(drama_id) in main.processed_ids:
        print(f"Note: {title} is already in processed.json. Proceeding anyway for test.")
    
    print("Starting process...")
    success = await process_drama_full(slug, drama_id, AUTO_CHANNEL)
    
    if success:
        print(f"SUCCESS: Processed {title}")
    else:
        print(f"FAILED: Could not process {title}")
    
    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
