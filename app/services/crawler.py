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


_DOM_ITEMS_JS = r"""
(selector) => {
    const container = document.querySelector(selector);
    if (!container) return {titles: [], links: []};

    function isNav(t) {
        return /^(다음|이전|next|prev|[><\u00BB\u00AB\u25B6\u25C0]|\d{1,3})$/i.test(t.trim());
    }

    const TITLE_SEL = 'h1,h2,h3,h4,h5,h6,[class*="title"],[class*="subject"],[class*="tit"],[class*="heading"]';

    function bestTitle(row) {
        const candidates = Array.from(row.querySelectorAll(TITLE_SEL));
        const leaves = candidates.filter(el => !el.querySelector(TITLE_SEL));
        for (const el of (leaves.length ? leaves : candidates)) {
            const t = (el.innerText || '').trim().replace(/\s+/g, ' ');
            if (t.length > 5 && t.length < 300 && !isNav(t)) return t;
        }
        for (const a of row.querySelectorAll('a')) {
            const t = (a.innerText || a.textContent || '').trim().replace(/\s+/g, ' ');
            if (t.length > 10 && t.length < 300 && !isNav(t)) return t;
        }
        return null;
    }

    function isDownload(href) {
        return /[?&]fSeq=|\/(?:download|attach|file|filedown)[/.]|\.(pdf|hwp|doc|xls|ppt|zip|csv)(x?)(\?|$)/i.test(href);
    }

    function bestHref(row) {
        if (row.tagName === 'A' && row.href && !row.href.startsWith('javascript') && !isDownload(row.href)) return row.href;
        for (const a of row.querySelectorAll('a[href]')) {
            const t = (a.innerText || '').trim().replace(/\s+/g, ' ');
            if (!a.href.startsWith('javascript') && !isNav(t) && !isDownload(a.href)) return a.href;
        }
        return null;
    }

    function jsHint(row) {
        // onclick 우선 (fn_view('123') 같은 패턴을 AI가 파싱하기 쉬움)
        for (const el of [row, ...Array.from(row.querySelectorAll('[onclick]'))]) {
            const oc = el.getAttribute && el.getAttribute('onclick');
            if (oc && oc.trim().length > 3) return oc.trim();
        }
        // onclick 없으면 javascript: href
        for (const a of row.querySelectorAll('a[href^="javascript:"]')) {
            const t = (a.innerText || '').trim();
            if (!isNav(t)) return a.href;
        }
        return null;
    }

    const ROW_SEL = 'tr, li, [role="listitem"], [role="row"], article';
    const CARD_SEL = '[class*="item"], [class*="card"], [class*="post"], [class*="list-el"]';

    function findRows(el) {
        let rows = Array.from(el.querySelectorAll(ROW_SEL));
        if (rows.length < 2) rows = Array.from(el.querySelectorAll(CARD_SEL));
        if (rows.length >= 2) return rows;
        const children = Array.from(el.children);
        if (children.length === 1) {
            const deeper = findRows(children[0]);
            if (deeper.length >= 2) return deeper;
        }
        return children;
    }

    const items = findRows(container);

    const titles = [];
    const links = [];
    const js_hints = [];
    const seen = new Set();

    for (const item of items) {
        const t = bestTitle(item);
        if (!t || seen.has(t)) continue;
        seen.add(t);
        titles.push(t);
        const href = bestHref(item);
        if (href) {
            links.push({title: t, href});
        } else {
            const js = jsHint(item);
            if (js) js_hints.push({title: t, js_attr: js});
        }
    }

    return {titles, links, js_hints};
}
"""


_NEXT_SEQ_JS = r"""
() => {
    function getSelector(el) {
        if (el.id && /^[a-zA-Z_]/.test(el.id)) return '#' + el.id;
        const parts = [];
        let cur = el;
        for (let d = 0; d < 6 && cur && cur.tagName; d++) {
            if (cur === document.body) break;
            if (cur.id && /^[a-zA-Z_]/.test(cur.id)) { parts.unshift('#' + cur.id); break; }
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
                    const sibs = Array.from(parent.children).filter(s => s.tagName === cur.tagName);
                    if (sibs.length > 1) part += ':nth-of-type(' + (sibs.indexOf(cur) + 1) + ')';
                }
            }
            parts.unshift(part);
            cur = cur.parentElement;
        }
        return parts.join(' > ');
    }

    // 페이지네이션 후보를 모두 수집 후, 가장 작은 페이지 번호(1~5)를 포함한 컨테이너 우선 선택
    const candidates = Array.from(document.querySelectorAll(
        '[class*="pag"], [class*="page-nav"], [class*="paginate"], ' +
        '.pagination, nav[aria-label], [role="navigation"]'
    ));

    function scorePagination(el) {
        const nums = Array.from(el.querySelectorAll('a, button, strong, b, em'))
            .map(e => parseInt(e.textContent.trim()))
            .filter(n => !isNaN(n) && n > 0);
        if (nums.length === 0) return -1;
        // 최솟값이 작을수록 (1~5 근처), 개수가 많을수록 높은 점수
        return 100 - Math.min(...nums) + nums.length;
    }

    candidates.sort((a, b) => scorePagination(b) - scorePagination(a));
    const paginationArea = candidates[0] || null;
    if (paginationArea && scorePagination(paginationArea) >= 0) {
        const activeEl = paginationArea.querySelector(
            '.active, .current, .on, .selected, [aria-current], strong, b, em'
        );
        if (activeEl) {
            const currentNum = parseInt(activeEl.textContent.trim());
            if (!isNaN(currentNum)) {
                const areaSel = getSelector(paginationArea);
                for (const el of paginationArea.querySelectorAll('a, button')) {
                    if (parseInt(el.textContent.trim()) === currentNum + 1 && !el.disabled) {
                        return { nextSel: getSelector(el), areaSel };
                    }
                }
            }
        }
    }

    const NEXT_RE = /^(다음|next|[›»]|>{1,2})$/i;
    for (const el of document.querySelectorAll('a[href], button')) {
        const t = (el.innerText || el.textContent || '').trim();
        if (NEXT_RE.test(t) && !el.disabled) return { nextSel: getSelector(el), areaSel: getSelector(el) };
    }

    const curPage = parseInt(new URLSearchParams(window.location.search).get('page') || '1');
    for (const el of document.querySelectorAll('a[href*="page="]')) {
        const m = el.href.match(/[?&]page=(\d+)/);
        if (m && parseInt(m[1]) === curPage + 1) return { nextSel: getSelector(el), areaSel: getSelector(el) };
    }
    return null;
}
"""



_DETAIL_SELECTORS = [
    "article", ".view-content", ".view_content", ".board-view",
    ".board_view", ".post-content", ".detail-content",
    ".bbs-view", '[class*="view"]', "main", "#content",
]


async def _extract_detail_text(page: Page) -> str:
    """페이지에서 상세 본문 텍스트를 추출한다."""
    for sel in _DETAIL_SELECTORS:
        try:
            el = await page.query_selector(sel)
            if el:
                t = (await el.inner_text()).strip()
                if len(t) > 100:
                    return t[:4000]
        except Exception:
            continue
    return (await page.inner_text("body"))[:4000]


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

    async def screenshot_roi_with_next_seq(
        self, url: str, roi: dict
    ) -> tuple[bytes, str | None, str | None, bytes | None]:
        """ROI 크롭 스크린샷, 다음 버튼 selector, 페이지네이션 컨테이너 selector,
        페이지네이션 영역 스크린샷(있을 경우)을 단일 세션으로 반환."""
        browser = await self._ensure_browser()
        ctx = await browser.new_context(viewport={"width": _VIEWPORT_W, "height": _VIEWPORT_H})
        try:
            page = await ctx.new_page()
            await page.goto(url, wait_until="load", timeout=30000)
            image = await _crop_roi(page, roi)
            _next_seq = await page.evaluate(_NEXT_SEQ_JS)
            next_sel = _next_seq["nextSel"] if _next_seq else None
            area_sel = _next_seq["areaSel"] if _next_seq else None

            pag_image: bytes | None = None
            if area_sel:
                try:
                    pag_el = await page.query_selector(area_sel)
                    if pag_el:
                        pag_image = await pag_el.screenshot(type="png")
                except Exception as e:
                    logger.warning(f"pagination screenshot failed [{area_sel}]: {e}")

            return image, next_sel, area_sel, pag_image
        except Exception as e:
            logger.error(f"screenshot_roi_with_next_seq failed for {url}: {e}")
            raise
        finally:
            await ctx.close()

    async def get_element_map(self, url: str) -> dict:
        """페이지 전체 스크린샷 + 주요 요소 목록(셀렉터·bbox·텍스트)을 반환."""
        browser = await self._ensure_browser()
        ctx = await browser.new_context(viewport={"width": _VIEWPORT_W, "height": _VIEWPORT_H})
        try:
            page = await ctx.new_page()
            await page.goto(url, wait_until="load", timeout=30000)
            await page.wait_for_timeout(1500)
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

    async def get_page_content(
        self, url: str, *, selector: str
    ) -> dict:
        """단일 브라우저 세션: 요소 텍스트 + 전체 페이지 element map."""
        browser = await self._ensure_browser()
        ctx = await browser.new_context(viewport={"width": _VIEWPORT_W, "height": _VIEWPORT_H})
        try:
            page = await ctx.new_page()
            await page.goto(url, wait_until="load", timeout=30000)

            try:
                dom_items = await page.evaluate(_DOM_ITEMS_JS, selector)
            except Exception as e:
                logger.warning(f"_dom_items failed [{selector}]: {e}")
                dom_items = {"titles": [], "links": [], "js_hints": []}
            dom_titles = dom_items.get("titles", [])
            title_links = dom_items.get("links", [])
            js_hints = dom_items.get("js_hints", [])
            el = await page.query_selector(selector)
            if not el:
                raise ValueError(f"Selector not found: {selector}")
            element_text = await el.inner_text()

            full_png = await page.screenshot(type="png", full_page=True)
            elements = await page.evaluate(_ELEMENT_MAP_JS)
            _next_seq = await page.evaluate(_NEXT_SEQ_JS)
            return {
                "element_text": element_text,
                "image": base64.b64encode(full_png).decode(),
                "elements": elements,
                "dom_titles": dom_titles,
                "title_links": title_links,
                "js_hints": js_hints,
                "next_seq_selector": _next_seq["nextSel"] if _next_seq else None,
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
        """next_selector 클릭 후 새 페이지의 element 텍스트 + element map을 단일 세션으로 반환."""
        browser = await self._ensure_browser()
        ctx = await browser.new_context(viewport={"width": _VIEWPORT_W, "height": _VIEWPORT_H})
        try:
            page = await ctx.new_page()
            await page.goto(url, wait_until="load", timeout=30000)
            btn = await page.query_selector(next_selector)
            if not btn:
                raise ValueError(f"Next selector not found: {next_selector}")
            await btn.click()
            await page.wait_for_load_state("networkidle", timeout=15000)
            current_url = page.url

            try:
                dom_items = await page.evaluate(_DOM_ITEMS_JS, element_selector)
            except Exception as e:
                logger.warning(f"_dom_items failed [{element_selector}]: {e}")
                dom_items = {"titles": [], "links": [], "js_hints": []}
            dom_titles = dom_items.get("titles", [])
            title_links = dom_items.get("links", [])
            js_hints = dom_items.get("js_hints", [])
            el = await page.query_selector(element_selector)
            if not el:
                raise ValueError(f"Element selector not found after navigation: {element_selector}")
            element_text = await el.inner_text()

            full_png = await page.screenshot(type="png", full_page=True)
            elements = await page.evaluate(_ELEMENT_MAP_JS)
            _next_seq = await page.evaluate(_NEXT_SEQ_JS)
            return {
                "element_text": element_text,
                "image": base64.b64encode(full_png).decode(),
                "elements": elements,
                "current_url": current_url,
                "dom_titles": dom_titles,
                "title_links": title_links,
                "js_hints": js_hints,
                "next_seq_selector": _next_seq["nextSel"] if _next_seq else None,
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
            await page.goto(url, wait_until="load", timeout=30000)
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

    async def get_detail_texts_by_click(
        self,
        url: str,
        selector: str,
        titles: list[str],
    ) -> dict[str, dict]:
        """javascript: 링크 등 href 추출 불가 시, 실제 클릭으로 상세 본문을 수집한다.
        Returns: {title: {"text": str, "url": str | None}}
        """
        if not titles:
            return {}
        browser = await self._ensure_browser()
        ctx = await browser.new_context(viewport={"width": _VIEWPORT_W, "height": _VIEWPORT_H})
        results: dict[str, str] = {}
        try:
            page = await ctx.new_page()
            page.on("dialog", lambda d: d.accept())  # alert/confirm 자동 닫기
            await page.goto(url, wait_until="load", timeout=30000)
            list_url = page.url

            for title in titles:
                new_pages: list = []  # finally 블록에서 항상 참조되므로 루프 시작 시 초기화
                try:
                    a_handle = await page.evaluate_handle(
                        r"""([sel, t]) => {
                            const c = document.querySelector(sel);
                            if (!c) return null;
                            const norm = s => s.normalize('NFC').trim().replace(/\s+/g, ' ');
                            const clean = s => norm(s).replace(/[\[\]<>()\{\}「」【】『』·,\.…]/g, '').replace(/\s+/g, ' ').trim();
                            const nt = norm(t);
                            const ntc = clean(t);
                            for (const a of c.querySelectorAll('a')) {
                                const txt = norm(a.innerText || a.textContent || '');
                                const txtc = clean(txt);
                                if (txt === nt
                                    || txt.includes(nt)
                                    || txtc.includes(ntc)
                                    || (nt.includes(txt) && txt.length >= nt.length * 0.7)) return a;
                            }
                            return null;
                        }""",
                        [selector, title],
                    )
                    el = a_handle.as_element()
                    if not el:
                        logger.warning(f"link not found for [{title[:40]}]")
                        continue

                    # 새 탭/팝업 감지 (javascript:window.open() 등 대응)

                    def _on_page(p):
                        new_pages.append(p)

                    ctx.on("page", _on_page)
                    try:
                        try:
                            async with page.expect_navigation(wait_until="networkidle", timeout=15000):
                                await el.click()
                        except Exception:
                            # ERR_ABORTED / frame detached 등 — URL이 바뀌었으면 이동 성공으로 처리
                            await page.wait_for_load_state("domcontentloaded", timeout=10000)
                    finally:
                        ctx.remove_listener("page", _on_page)

                    # 새 탭이 열렸으면 그 탭에서 추출
                    if new_pages:
                        new_page = new_pages[0]
                        try:
                            await new_page.wait_for_load_state("networkidle", timeout=10000)
                        except Exception:
                            pass
                        text = await _extract_detail_text(new_page)
                        detail_url = new_page.url
                        await new_page.close()
                        if text:
                            results[title] = {"text": text, "url": detail_url}
                            logger.info(f"popup-detail fetched [{title[:40]}] ({len(text)} chars) url={detail_url}")
                        continue

                    if page.url == list_url:
                        # AJAX/SPA — 콘텐츠 로드 대기 후 스크린샷을 AI에 넘긴다
                        try:
                            try:
                                await page.wait_for_load_state("networkidle", timeout=5000)
                            except Exception:
                                await page.wait_for_timeout(3000)
                            screenshot = await page.screenshot(type="png", full_page=True)
                            results[title] = {
                                "screenshot_b64": base64.b64encode(screenshot).decode(),
                                "url": list_url,
                            }
                            logger.info(f"ajax-screenshot captured [{title[:40]}]")
                        except Exception as e:
                            logger.warning(f"ajax screenshot failed [{title[:40]}]: {e}")
                        # AJAX가 DOM을 변경했으므로 다음 반복을 위해 목록 페이지 복원
                        try:
                            await page.goto(list_url, wait_until="networkidle", timeout=20000)
                        except Exception:
                            pass
                        continue

                    text = await _extract_detail_text(page)
                    results[title] = {"text": text, "url": page.url}
                    logger.info(f"click-detail fetched [{title[:40]}] ({len(text)} chars) url={page.url}")

                except Exception as e:
                    logger.warning(f"click-nav failed [{title[:40]}]: {e}")
                finally:
                    # 새로 열린 탭 정리
                    for p in new_pages:
                        try:
                            if not p.is_closed():
                                await p.close()
                        except Exception:
                            pass
                    if page.url != list_url:
                        try:
                            await page.goto(list_url, wait_until="networkidle", timeout=20000)
                        except Exception:
                            pass
        except Exception as e:
            logger.error(f"get_detail_texts_by_click failed for {url}: {e}")
        finally:
            await ctx.close()
        return results

    async def get_detail_text(self, url: str) -> str:
        """상세 페이지 본문 텍스트 추출."""
        browser = await self._ensure_browser()
        ctx = await browser.new_context(viewport={"width": _VIEWPORT_W, "height": _VIEWPORT_H})
        try:
            page = await ctx.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            return await _extract_detail_text(page)
        except Exception as e:
            logger.error(f"get_detail_text failed for {url}: {e}")
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
