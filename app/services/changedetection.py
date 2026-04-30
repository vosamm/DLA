import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)


class ChangeDetectionClient:
    def __init__(self):
        self.base_url = settings.changedetection_url.rstrip("/")
        self.api_key = settings.changedetection_api_key

    @property
    def headers(self):
        return {"x-api-key": self.api_key}

    async def list_watches(self) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.base_url}/api/v1/watch",
                headers=self.headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_history(self, uuid: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.base_url}/api/v1/watch/{uuid}/history",
                headers=self.headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_snapshot(self, uuid: str, timestamp: str) -> str:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.base_url}/api/v1/watch/{uuid}/history/{timestamp}",
                headers=self.headers,
            )
            resp.raise_for_status()
            return resp.text

    async def update_watch(self, uuid: str, title: str) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.put(
                f"{self.base_url}/api/v1/watch/{uuid}",
                headers=self.headers,
                json={"title": title},
            )
            resp.raise_for_status()

    async def migrate_to_playwright(self) -> int:
        """기존 watch 전체를 Playwright 페처로 업데이트. 업데이트된 수 반환."""
        watches = await self.list_watches()
        count = 0
        async with httpx.AsyncClient(timeout=30) as client:
            for uuid, data in watches.items():
                if data.get("fetch_backend") == "html_webdriver":
                    continue
                resp = await client.put(
                    f"{self.base_url}/api/v1/watch/{uuid}",
                    headers=self.headers,
                    json={"fetch_backend": "html_webdriver"},
                )
                if resp.status_code == 200:
                    count += 1
        return count

    async def create_watch(self, url: str, title: str = "") -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/api/v1/watch",
                headers=self.headers,
                json={
                    "url": url,
                    "title": title,
                    "time_between_check": {
                        "weeks": None, "days": None, "hours": None,
                        "minutes": 5, "seconds": None,
                    },
                    "fetch_backend": "html_webdriver",
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def get_html_snapshot(self, uuid: str, timestamp: str) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{self.base_url}/api/v1/watch/{uuid}/history/{timestamp}",
                    headers=self.headers,
                    params={"html": "1"},
                )
                if resp.status_code == 200:
                    return resp.text
        except Exception as e:
            logger.debug(f"HTML snapshot fetch failed for {uuid}: {e}")
        return None

    async def get_screenshot(self, uuid: str) -> bytes | None:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{self.base_url}/api/v1/watch/{uuid}/screenshot",
                    headers=self.headers,
                )
                if resp.status_code == 200:
                    return resp.content
        except Exception as e:
            logger.debug(f"Screenshot fetch failed for {uuid}: {e}")
        return None

    async def delete_watch(self, uuid: str) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.delete(
                f"{self.base_url}/api/v1/watch/{uuid}",
                headers=self.headers,
            )
            resp.raise_for_status()


changedetection = ChangeDetectionClient()
