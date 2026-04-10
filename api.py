import httpx
import logging

logger = logging.getLogger(__name__)

BASE_URL = "https://stardusttv.dramabos.my.id/v1"
AUTH_CODE = "A8D6AB170F7B89F2182561D3B32F390D"


async def get_latest_dramas(pages=1):
    """Fetches latest dramas from StardustTV list endpoint."""
    all_dramas = []

    async with httpx.AsyncClient(timeout=60) as client:
        for page in range(1, pages + 1):
            url = f"{BASE_URL}/list"
            params = {
                "lang": "id",
                "page": page,
            }

            try:
                response = await client.get(url, params=params)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") and "data" in data:
                        items = data["data"]
                        if not items:
                            break
                        all_dramas.extend(items)
                    else:
                        break
                else:
                    break
            except Exception as e:
                logger.error(f"Error fetching list page {page}: {e}")
                break

    return all_dramas


async def search_dramas(query: str):
    """Searches dramas using StardustTV find endpoint."""
    url = f"{BASE_URL}/find"
    params = {
        "q": query,
        "lang": "id",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") and "data" in data:
                    return data["data"]
            return []
        except Exception as e:
            logger.error(f"Error searching dramas for '{query}': {e}")
            return []


async def get_drama_detail(slug: str, drama_id: str):
    """Fetches drama detail + episodes from StardustTV.
    
    Returns dict with keys: id, slug, title, poster, totalEpisodes, episodes
    episodes is a dict like {"1": {"h264": url, "h265": url}, "2": {...}, ...}
    """
    url = f"{BASE_URL}/detail/{slug}/{drama_id}"
    params = {
        "lang": "id",
        "code": AUTH_CODE,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            if data and isinstance(data, dict):
                if data.get("success") and "data" in data:
                    return data["data"]
                return data
            return None
        except Exception as e:
            logger.error(f"Error fetching drama detail for {slug}/{drama_id}: {e}")
            return None


async def get_all_episodes(slug: str, drama_id: str):
    """Fetches all episodes from StardustTV detail endpoint.
    
    Returns a list of dicts: [{"episode": 1, "h264": url, "h265": url}, ...]
    sorted by episode number.
    """
    detail = await get_drama_detail(slug, drama_id)
    if not detail or "episodes" not in detail:
        return []

    episodes_dict = detail["episodes"]
    if not isinstance(episodes_dict, dict):
        return []

    # Convert dict to sorted list
    episodes_list = []
    for ep_num_str, urls in episodes_dict.items():
        try:
            ep_num = int(ep_num_str)
        except ValueError:
            continue
        episodes_list.append({
            "episode": ep_num,
            "h264": urls.get("h264", ""),
            "h265": urls.get("h265", ""),
        })

    episodes_list.sort(key=lambda x: x["episode"])
    return episodes_list


async def get_episode_stream(slug: str, drama_id: str, ep_num: int):
    """Fetches a single episode stream URL from StardustTV.
    
    Returns dict with keys: episode, h264, h265
    """
    url = f"{BASE_URL}/detail/{slug}/{drama_id}/episode/{ep_num}"
    params = {
        "lang": "id",
        "code": AUTH_CODE,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            if data and data.get("success") and "data" in data:
                return data["data"]
            return None
        except Exception as e:
            logger.error(f"Error fetching episode {ep_num} for {slug}/{drama_id}: {e}")
            return None
