
import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api import get_all_episodes

async def main():
    slug = "hina-mertua-bayar-mahal"
    drama_id = "18379"
    episodes = await get_all_episodes(slug, drama_id)
    print(f"Total episodes for {slug}: {len(episodes)}")

if __name__ == "__main__":
    asyncio.run(main())
