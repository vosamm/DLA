"""Playwright 기반 직접 크롤러.

app-browser 컨테이너(ws://app-browser:3000/?stealth=1)에 연결해
스크린샷 · CSS 셀렉터 추출 · 텍스트 수집을 담당한다.
"""

import base64
import logging
from typing import Optional

from playwright.async_api import (
    Browser,
    Page,
    Playwright,
    async_playwright,
)

logger = logging.getLogger(__name__)

_VIEWPORT_W = 1280
_VIEWPORT_H = 900

_ELEMENT_MAP_JS = r"""() => {
                function getSelector(el) {
                    if (el.id && /^[a-zA-Z_]/.test(el.id)) return '#' + el.id;
                    const parts = [];
                    let cur = el;
                    for (let d = 0; d < 6 && cur && cur.tagName; d++) {
                        if (cur === document.body) break;
                        if (cur.id && /^[a-zA-Z_]/.test(cur.id)) {
                            parts.unshift('#' + cur.id);
                            break;
                        }
                        const tag = cur.tagName.toLowerCase();
                        const cls = Array.from(cur.classList)
                            .filter(c => /^[a-zA-Z][a-zA-Z0-9_-]*$/.test(c) && c.length < 30)
                            .slice(0, 2);
                        let part = tag;
                        if (cls.length) {
                            part += '.' + cls.join('.');
                        } else {
                            const parent = cur.parentElement;
                            if (parent) {
                                const sibs = Array.from(parent.children)
                                    .filter(s => s.tagName === cur.tagName);
                                if (sibs.length > 1)
                                    part += ':nth-of-type(' + (sibs.indexOf(cur) + 1) + ')';
                            }
                        }
                        parts.unshift(part);
                        cur = cur.parentElement;
                    }
                    return parts.join(' > ');
                }

                const scrollY = window.scrollY || 0;
                const seen = new Set();
                const result = [];

                const targets = document.querySelectorAll(
                    'table, tbody, ul, ol, ' +
                    '[class*="list"], [class*="board"], [class*="notice"], ' +
                    '[class*="bbs"], [class*="table"], [class*="grid"], ' +
                    '[class*="content"], [class*="wrap"], article, section, main'
                );

                for (const el of targets) {
                    const rect = el.getBoundingClientRect();
                    const x = Math.round(rect.left);
                    const y = Math.round(rect.top + scrollY);
                    const w = Math.round(rect.width);
                    const h = Math.round(rect.height);

                    if (w < 80 || h < 40) continue;
                    if (w * h < 5000) continue;

                    const style = getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') continue;

                    const selector = getSelector(el);
                    if (seen.has(selector)) continue;
                    seen.add(selector);

                    const text = (el.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
                    result.push({ selector, bbox: { x, y, w, h }, text });
                    if (result.length >= 60) break;
                }

                // 인터랙티브 요소(버튼·링크) 추가 – 다음 페이지 버튼 선택에 사용
                const interactive = document.querySelectorAll('button, a[href], [role="button"]');
                for (const el of interactive) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width < 10 || rect.height < 5) continue;
                    if (rect.width * rect.height > 30000) continue;
                    const style = getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') continue;
                    const selector = getSelector(el);
                    if (seen.has(selector)) continue;
                    seen.add(selector);
                    const txt = (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 30);
                    const x = Math.round(rect.left);
                    const y = Math.round(rect.top + scrollY);
                    const w = Math.round(rect.width);
                    const h = Math.round(rect.height);
                    result.push({ selector, bbox: { x, y, w, h }, text: txt });
                }
                return result;
            }"""


_DOM_TITLES_JS = r"""
(selector) => {
    const container = document.querySelector(selector);
    if (!container) return [];
    // 공지 제목은 보통 <a> 링크로 표시됨
    const links = Array.from(container.querySelectorAll('a')).filter(a => {
        const t = (a.innerText || a.textContent || '').trim();
        return t.length > 10 && t.length < 300
            && !/^\d+$/.test(t)
            && !/^(다음|이전|next|prev|[><»«▶◀])$/i.test(t);
    });
    if (links.length >= 2) {
        return links.map(a => (a.innerText || a.textContent || '').trim().replace(/\s+/g, ' '));
    }
    // 링크가 없으면 tr/li 단위로 텍스트 추출
    const rows = Array.from(container.querySelectorAll('tr, li'));
    const items = rows.length > 0 ? rows : Array.from(container.children);
    return items
        .map(el => (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 300))
        .filter(t => t.length > 5);
}
"""


async def _extract_dom_titles(page: Page, selector: str) -> list[str]:
    """CSS 셀렉터 컨테이너에서 공지 제목 목록을 DOM에서 직접 추출."""
    try:
        return await page.evaluate(_DOM_TITLES_JS, selector)
    except Exception as e:
        logger.warning(f"_extract_dom_titles failed [{selector}]: {e}")
        return []


async def _crop_roi(page: Page, roi: dict) -> bytes:
    """ROI 영역(정규화 좌표 0~1)만 크롭한 스크린샷 반환."""
    page_height: float = await page.evaluate("document.documentElement.scrollHeight")
    x1 = roi["x1"] * _VIEWPORT_W
    y1 = roi["y1"] * page_height
    x2 = roi["x2"] * _VIEWPORT_W
    y2 = roi["y2"] * page_height
    scroll_y = max(0.0, y1)
    await page.evaluate("(y) => window.scrollTo(0, y)", scroll_y)
    return await page.screenshot(
        type="png",
        clip={"x": x1, "y": y1 - scroll_y, "width": max(x2 - x1, 1), "height": max(y2 - y1, 1)},
    )


class Crawler:
    def __init__(self) -> None:
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None

    async def _ensure_browser(self) -> Browser:
        """브라우저 연결이 없거나 끊겼으면 재연결."""
        if self._browser and self._browser.is_connected():
            return self._browser

        if self._pw is None:
            self._pw = await async_playwright().start()

        try:
            self._browser = await self._pw.chromium.launch(headless=True)
            logger.info("Browser launched")
        except Exception as e:
            logger.error(f"Browser connection failed: {e}")
            raise

        return self._browser

    async def screenshot_roi(self, url: str, roi: dict) -> bytes:
        """ROI 영역(정규화 좌표 0~1)만 크롭한 스크린샷 반환."""
        browser = await self._ensure_browser()
        ctx = await browser.new_context(viewport={"width": _VIEWPORT_W, "height": _VIEWPORT_H})
        try:
            page = await ctx.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            return await _crop_roi(page, roi)
        except Exception as e:
            logger.error(f"screenshot_roi failed for {url}: {e}")
            raise
        finally:
            await ctx.close()

    async def get_element_map(self, url: str) -> dict:
        """페이지 전체 스크린샷 + 주요 요소 목록(셀렉터·bbox·텍스트)을 반환."""
        browser = await self._ensure_browser()
        ctx = await browser.new_context(viewport={"width": _VIEWPORT_W, "height": _VIEWPORT_H})
        try:
            page = await ctx.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            page_height: float = await page.evaluate("document.documentElement.scrollHeight")
            png = await page.screenshot(type="png", full_page=True)
            elements = await page.evaluate(_ELEMENT_MAP_JS)
            return {
                "image": base64.b64encode(png).decode(),
                "page_height": int(page_height),
                "viewport_width": _VIEWPORT_W,
                "elements": elements,
            }
        except Exception as e:
            logger.error(f"get_element_map failed for {url}: {e}")
            raise
        finally:
            await ctx.close()

    async def screenshot_element(self, url: str, selector: str) -> bytes:
        """CSS 셀렉터로 특정 요소만 스크린샷해 반환."""
        browser = await self._ensure_browser()
        ctx = await browser.new_context(viewport={"width": _VIEWPORT_W, "height": _VIEWPORT_H})
        try:
            page = await ctx.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            el = await page.query_selector(selector)
            if not el:
                raise ValueError(f"Selector not found: {selector}")
            return await el.screenshot(type="png")
        except Exception as e:
            logger.error(f"screenshot_element failed for {url} [{selector}]: {e}")
            raise
        finally:
            await ctx.close()

    async def get_page_content(
        self, url: str, *, selector: str
    ) -> dict:
        """단일 브라우저 세션: 요소 스크린샷 + 전체 페이지 element map."""
        browser = await self._ensure_browser()
        ctx = await browser.new_context(viewport={"width": _VIEWPORT_W, "height": _VIEWPORT_H})
        try:
            page = await ctx.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)

            dom_titles = await _extract_dom_titles(page, selector)
            el = await page.query_selector(selector)
            if not el:
                raise ValueError(f"Selector not found: {selector}")
            element_png = await el.screenshot(type="png")

            full_png = await page.screenshot(type="png", full_page=True)
            elements = await page.evaluate(_ELEMENT_MAP_JS)
            return {
                "element_image": base64.b64encode(element_png).decode(),
                "image": base64.b64encode(full_png).decode(),
                "elements": elements,
                "dom_titles": dom_titles,
            }
        except Exception as e:
            logger.error(f"get_page_content failed for {url}: {e}")
            raise
        finally:
            await ctx.close()

    async def navigate_and_get_content(
        self,
        url: str,
        next_selector: str,
        *,
        element_selector: str,
    ) -> dict:
        """next_selector 클릭 후 새 페이지의 element_image + element map을 단일 세션으로 반환."""
        browser = await self._ensure_browser()
        ctx = await browser.new_context(viewport={"width": _VIEWPORT_W, "height": _VIEWPORT_H})
        try:
            page = await ctx.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            btn = await page.query_selector(next_selector)
            if not btn:
                raise ValueError(f"Next selector not found: {next_selector}")
            await btn.click()
            await page.wait_for_load_state("networkidle", timeout=15000)
            current_url = page.url

            dom_titles = await _extract_dom_titles(page, element_selector)
            el = await page.query_selector(element_selector)
            if not el:
                raise ValueError(f"Element selector not found after navigation: {element_selector}")
            element_png = await el.screenshot(type="png")

            full_png = await page.screenshot(type="png", full_page=True)
            elements = await page.evaluate(_ELEMENT_MAP_JS)
            return {
                "element_image": base64.b64encode(element_png).decode(),
                "image": base64.b64encode(full_png).decode(),
                "elements": elements,
                "current_url": current_url,
                "dom_titles": dom_titles,
            }
        except Exception as e:
            logger.error(f"navigate_and_get_content failed for {url}: {e}")
            raise
        finally:
            await ctx.close()

    async def navigate_and_get_element_map(self, url: str, next_selector: str) -> dict:
        """next_selector 클릭 후 새 페이지의 element map만 반환."""
        browser = await self._ensure_browser()
        ctx = await browser.new_context(viewport={"width": _VIEWPORT_W, "height": _VIEWPORT_H})
        try:
            page = await ctx.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            btn = await page.query_selector(next_selector)
            if not btn:
                raise ValueError(f"Next selector not found: {next_selector}")
            await btn.click()
            await page.wait_for_load_state("networkidle", timeout=15000)
            current_url = page.url
            page_height = await page.evaluate("document.documentElement.scrollHeight")
            full_png = await page.screenshot(type="png", full_page=True)
            elements = await page.evaluate(_ELEMENT_MAP_JS)
            return {
                "image": base64.b64encode(full_png).decode(),
                "page_height": int(page_height),
                "viewport_width": _VIEWPORT_W,
                "elements": elements,
                "current_url": current_url,
            }
        except Exception as e:
            logger.error(f"navigate_and_get_element_map failed for {url}: {e}")
            raise
        finally:
            await ctx.close()

    async def close(self) -> None:
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None


crawler = Crawler()
