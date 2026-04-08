import asyncio
import json
import logging
import os
import re
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
import httpx
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

UOS_API_KEY = os.getenv("UOS_API_KEY", "")
UOS_API_URL = os.getenv("UOS_API_URL", "https://factchat-cloud.mindlogic.ai/v1/api/anthropic/messages")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

executor = ThreadPoolExecutor(max_workers=4)

browser_config = BrowserConfig(
    headless=True,
    verbose=False,
    user_agent=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
)

EXCLUDED_TAGS = ["nav", "header", "footer", "aside", "script", "style", "noscript"]

# 페이지네이션에 사용되는 쿼리 파라미터 이름 후보
PAGE_PARAMS = ["pageIndex", "page", "pageNo", "pg", "p", "currentPage", "pageNum"]

EXTRACT_PROMPT = """\
아래는 웹 페이지에서 크롤링한 텍스트입니다.
이 내용을 읽고, 공지사항·안내·모집·지원·행사·정책 등 사용자에게 유용한 정보 항목들을 찾아 정리해주세요.

각 항목에 대해 다음을 추출하세요:
- 제목 (title)
- 날짜 (date, 없으면 null)
- 한 줄 요약 (summary)
- 링크 URL (url, 있으면 포함)

반드시 아래 JSON 형식으로만 반환하세요. 다른 설명이나 코드블록 없이 JSON만 출력하세요.

{{"items": [{{"title": "...", "date": "...", "summary": "...", "url": "..."}}]}}

항목이 없으면 {{"items": []}} 를 반환하세요.

크롤링된 내용:
{markdown}
"""


# ---------------------------------------------------------------------------
# URL / 마크다운 유틸
# ---------------------------------------------------------------------------

def normalize_url(url: str) -> str:
    return url.replace("identified=success", "identified=anonymous")


def get_page_param(url: str) -> str | None:
    """URL에서 페이지네이션 파라미터 이름 반환. 없으면 None."""
    params = parse_qs(urlparse(url).query, keep_blank_values=True)
    return next((p for p in PAGE_PARAMS if p in params), None)


def build_page_url(url: str, page_param: str, page: int) -> str:
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params[page_param] = [str(page)]
    return urlunparse(parsed._replace(query=urlencode(params, doseq=True)))


def reconstruct_js_links(markdown: str, source_url: str) -> str:
    """javascript:fnView('index', 'seq') → 실제 view URL로 변환."""
    parsed = urlparse(source_url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    list_id = params.get("list_id", [""])[0]
    base = f"{parsed.scheme}://{parsed.netloc}"
    view_path = parsed.path.replace("list.do", "view.do")

    def replace_fn_view(match):
        seq = match.group(2)
        qs = f"list_id={list_id}&seq={seq}" if list_id else f"seq={seq}"
        return f"{base}{view_path}?{qs}"

    # javascript:fnView\('index', 'seq'\) 패턴 변환
    return re.sub(
        r"javascript:fnView\\\('(\d+)',\s*'(\d+)'\\\)",
        replace_fn_view,
        markdown,
    )


def clean_markdown(markdown: str, source_url: str = "") -> str:
    """불필요한 링크 제거 및 JS 링크 복원."""
    if source_url:
        markdown = reconstruct_js_links(markdown, source_url)

    lines = []
    for line in markdown.splitlines():
        stripped = line.strip()
        # 앵커(#) 링크만 있는 스킵 내비게이션 제거
        if re.match(r'^\[.+?\]\([^)]*#[^)]*\)\s*$', stripped):
            continue
        # javascript:void / javascript:; 링크만 있는 라인 제거
        if re.match(r'^\[.*?\]\(javascript:(void.*?|;)\)\s*$', stripped):
            continue
        lines.append(line)

    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()


# ---------------------------------------------------------------------------
# 크롤링
# ---------------------------------------------------------------------------

async def _do_crawl(url: str, crawl_config: CrawlerRunConfig):
    async with AsyncWebCrawler(config=browser_config) as crawler:
        return await crawler.arun(url, config=crawl_config)


def _crawl_in_thread(url: str, crawl_config: CrawlerRunConfig):
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    return asyncio.run(_do_crawl(url, crawl_config))


async def crawl_url(url: str, crawl_config: CrawlerRunConfig) -> str:
    """단일 URL 크롤링 후 정제된 마크다운 반환."""
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(executor, _crawl_in_thread, url, crawl_config)
    if not result.success:
        raise RuntimeError(result.error_message)
    return clean_markdown(result.markdown.raw_markdown or "", source_url=url)


async def crawl_all_pages(
    start_url: str, crawl_config: CrawlerRunConfig, max_pages: int
) -> tuple[str, int]:
    """
    페이지네이션이 있으면 전 페이지를 순회하며 크롤링.
    내용이 비어 있거나 이전 페이지와 동일하면 조기 종료.
    반환값: (합친 마크다운, 실제 크롤링한 페이지 수)
    """
    page_param = get_page_param(start_url)

    if not page_param:
        md = await crawl_url(start_url, crawl_config)
        return md, 1

    pages_markdown: list[str] = []
    prev_md = None

    for page in range(1, max_pages + 1):
        url = build_page_url(start_url, page_param, page)
        try:
            md = await crawl_url(url, crawl_config)
        except Exception:
            # 타임아웃 또는 접근 불가 → 마지막 페이지 이후로 판단하고 종료
            break

        # 내용이 없거나 이전 페이지와 동일하면 마지막 페이지로 판단
        if not md.strip() or md == prev_md:
            break

        pages_markdown.append(f"<!-- 페이지 {page} -->\n{md}")
        prev_md = md

    return "\n\n".join(pages_markdown), len(pages_markdown)


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

def _compress_markdown(markdown: str, max_chars: int = 8000) -> str:
    """이미지만 제거하고 링크는 유지한 채 LLM 입력 크기를 줄임."""
    # 이미지 제거 ![alt](url)
    text = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', markdown)
    # 연속 공백/빈줄 정리
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text[:max_chars]


async def extract_notices(markdown: str) -> list[dict]:
    compressed = _compress_markdown(markdown)
    logger.info("LLM에 전달하는 텍스트 (앞 1000자):\n%s", compressed[:1000])
    prompt = EXTRACT_PROMPT.format(markdown=compressed)
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                UOS_API_URL,
                headers={
                    "Authorization": f"Bearer {UOS_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-5-20250929",
                    "max_tokens": 2048,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
        raw = resp.json()
        logger.info("UOS API 응답: %s", raw)
        # Anthropic 형식: content[0]["text"]
        text = raw["content"][0]["text"]
        # 코드블록(```json ... ```) 제거
        text = re.sub(r'^```[a-z]*\s*', '', text.strip())
        text = re.sub(r'\s*```$', '', text.strip())
        return json.loads(text).get("items", [])
    except Exception as e:
        logger.error("extract_notices 실패: %s", e)
        return []


# ---------------------------------------------------------------------------
# 모델
# ---------------------------------------------------------------------------

class NoticeItem(BaseModel):
    title: str
    date: str | None = None
    summary: str
    url: str | None = None


class CrawlRequest(BaseModel):
    url: HttpUrl
    wait_for: str | None = None
    delay: float = 3.0
    max_pages: int = 5


class CrawlResponse(BaseModel):
    url: str
    title: str
    markdown: str
    pages_crawled: int
    notices: list[NoticeItem]


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------

@app.post("/api/crawl", response_model=CrawlResponse)
async def crawl(request: CrawlRequest):
    target_url = normalize_url(str(request.url))

    crawl_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        delay_before_return_html=request.delay,
        page_timeout=60000,
        wait_for=request.wait_for,
        excluded_tags=EXCLUDED_TAGS,
        markdown_generator=DefaultMarkdownGenerator(),
    )

    try:
        markdown, pages_crawled = await crawl_all_pages(
            target_url, crawl_config, request.max_pages
        )
        notices = await extract_notices(markdown)

        return CrawlResponse(
            url=target_url,
            title="",
            markdown=markdown,
            pages_crawled=pages_crawled,
            notices=notices,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
