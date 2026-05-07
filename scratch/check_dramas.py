
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import asyncio
from api import get_latest_dramas

async def main():
    dramas = await get_latest_dramas(pages=1)
    if dramas:
        print(f"Total dramas found: {len(dramas)}")
        first_drama = dramas[0]
        print(f"Judul 1 (First Drama):")
        print(f"  Title: {first_drama.get('title')}")
        print(f"  Slug: {first_drama.get('slug')}")
        print(f"  ID: {first_drama.get('id')}")
    else:
        print("No dramas found.")

if __name__ == '__main__':
    asyncio.run(main())
