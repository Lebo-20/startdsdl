
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import asyncio
import json
from api import get_drama_detail

async def main():
    slug = "bukan-menantu-tapi-selir-mertua"
    drama_id = "18182"
    detail = await get_drama_detail(slug, drama_id)
    print(json.dumps(detail, indent=2))

if __name__ == '__main__':
    asyncio.run(main())
