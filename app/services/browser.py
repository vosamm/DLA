import logging

from playwright.async_api import async_playwright

from config import settings

logger = logging.getLogger(__name__)


class BrowserService:
    async def get_detail_content(self, page_url: str, title: str) -> tuple[str, str | None] | None:
        """상세 페이지 본문과 URL을 가져온다. 실패하면 None 반환."""
        try:
            async with async_playwright() as p:
                browser = await p.chromium.connect(settings.app_browser_ws_url)
                context = await browser.new_context()
                page = await context.new_page()
                try:
                    await page.goto(page_url, wait_until="networkidle", timeout=30_000)

                    # 1. href 방식: 제목 텍스트로 <a> 탐색 후 이동
                    href = await self._find_href(page, title)
                    if href:
                        detail = await context.new_page()
                        try:
                            await detail.goto(href, wait_until="networkidle", timeout=30_000)
                            return await self._extract_text(detail), detail.url
                        finally:
                            await detail.close()

                    # 2. 클릭 방식: 요소 클릭 후 열리는 페이지에서 추출
                    return await self._try_click_and_extract(page, context, title)

                finally:
                    await context.close()

        except Exception as e:
            logger.warning(f"Browser detail fetch failed [{title}] {page_url}: {e}")
            return None

    async def _find_href(self, page, title: str) -> str | None:
        """제목 텍스트와 연결된 href를 DOM에서 탐색한다."""
        try:
            href = await page.evaluate(
                """(title) => {
                    const needle = title.trim().slice(0, 20);
                    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                    while (walker.nextNode()) {
                        const node = walker.currentNode;
                        if (!node.textContent.trim().includes(needle)) continue;
                        const el = node.parentElement;
                        const a = el.closest('a') || el.querySelector('a');
                        if (a && a.href && a.href.startsWith('http')) return a.href;
                    }
                    return null;
                }""",
                title,
            )
            return href or None
        except Exception as e:
            logger.debug(f"href find failed: {e}")
            return None

    async def _try_click_and_extract(self, page, context, title: str) -> tuple[str, str | None] | None:
        """요소 클릭 후 열리는 페이지에서 본문과 URL을 추출한다."""
        try:
            locator = page.get_by_text(title[:30], exact=False).first

            # 새 탭으로 열리는 경우
            try:
                async with context.expect_page(timeout=4_000) as new_page_info:
                    await locator.click(timeout=5_000)
                new_page = await new_page_info.value
                try:
                    await new_page.wait_for_load_state("networkidle", timeout=15_000)
                    return await self._extract_text(new_page), new_page.url
                finally:
                    await new_page.close()
            except Exception:
                pass

            # 같은 탭 내 페이지 이동
            try:
                await page.wait_for_load_state("networkidle", timeout=8_000)
                return await self._extract_text(page), page.url
            except Exception:
                pass

        except Exception as e:
            logger.debug(f"Click extract failed: {e}")
        return None

    async def _extract_text(self, page) -> str:
        """메인 본문 텍스트만 추출한다 (nav/header/footer 제거)."""
        try:
            text = await page.evaluate(
                """() => {
                    ['script','style','nav','header','footer','aside'].forEach(tag =>
                        document.querySelectorAll(tag).forEach(el => el.remove())
                    );
                    const main = document.querySelector(
                        'main, article, [role="main"], .content, #content, .post-body, .view-content'
                    );
                    return (main || document.body).innerText.replace(/\\s+/g, ' ').trim();
                }"""
            )
            return text[:4_000] if text else ""
        except Exception as e:
            logger.debug(f"Text extraction failed: {e}")
            return ""


browser_service = BrowserService()
