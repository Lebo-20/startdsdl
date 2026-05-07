
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import asyncio
from api import get_latest_dramas, get_all_episodes

async def main():
    dramas = await get_latest_dramas(pages=1)
    if dramas:
        first_drama = dramas[0]
        title = first_drama.get('title')
        slug = first_drama.get('slug')
        drama_id = first_drama.get('id')
        print(f"Checking episodes for: {title} ({slug}/{drama_id})")
        
        episodes = await get_all_episodes(slug, drama_id)
        print(f"Total episodes: {len(episodes)}")
        if episodes:
            print(f"Example episode 1 URL: {episodes[0].get('h264')}")
    else:
        print("No dramas found.")

if __name__ == '__main__':
    asyncio.run(main())
