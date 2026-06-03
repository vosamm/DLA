import json
import logging

from openai import AsyncOpenAI

from config import settings

logger = logging.getLogger(__name__)

IDENTIFY_SELECTORS_PROMPT = """\
이 이미지는 사용자가 드래그로 선택한 웹페이지 영역입니다.
아래 elements 목록에서:
1. 공지/게시물 목록 컨테이너의 selector (content_selector)
2. 다음 페이지로 이동하는 버튼/링크의 selector (next_page_selector, 없으면 null)

JSON으로만 반환: {"content_selector": "...", "next_page_selector": "..." or null}

주의:
- elements 목록에 있는 selector만 사용
- 다음 페이지 버튼이 없으면 next_page_selector를 null로"""

FIND_NEXT_PROMPT = """\
이 이미지는 웹페이지 스크린샷이고, elements는 페이지 요소 목록입니다.

"다음 페이지"로 이동하는 버튼이나 링크를 찾아 JSON으로 반환하세요.
JSON 형식으로만 반환: {"selector": "CSS selector"} 또는 {"selector": null}

주의:
- "다음", ">", "▶", "next", ">>" 같은 다음 페이지 이동 버튼을 찾으세요
- 숫자 페이지 버튼(1,2,3...)은 제외
- elements 목록에 있는 selector만 사용
- 없으면 {"selector": null}"""


class AIClient:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.ai_api_key,
            base_url=settings.ai_api_base,
        )
        self.model = settings.ai_model

    async def _call_vision(
        self,
        prompt: str,
        image_b64: str,
        *,
        timeout: int = 30,
    ) -> dict:
        """단일 이미지 + 텍스트 프롬프트로 JSON 응답을 반환하는 공통 vision 호출."""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                ],
            }],
            response_format={"type": "json_object"},
            temperature=0,
            timeout=timeout,
        )
        text = response.choices[0].message.content or ""
        return json.loads(text)

    async def filter_titles(self, titles: list[str], image_b64: str | None = None) -> list[str]:
        """DOM에서 추출한 제목 후보 목록에서 태그·카테고리·레이블 등 비제목을 제거한다.
        image_b64가 주어지면 스크린샷을 함께 보고 시각적으로 판단한다."""
        if not titles:
            return []
        titles_json = json.dumps(titles, ensure_ascii=False)
        prompt = (
            "이 스크린샷은 웹페이지 목록 영역입니다.\n"
            "아래 텍스트 목록은 DOM에서 추출한 후보들입니다. "
            "스크린샷을 보고 실제로 게시글·토픽의 제목으로 표시된 항목만 남기세요.\n"
            "태그·카테고리 라벨·날짜·작성자명·조회수·버튼 텍스트는 제거하세요.\n\n"
            f"후보 목록:\n{titles_json}\n\n"
            'JSON 형식으로만 반환: {"titles": ["제목1", "제목2", ...]}'
        )
        try:
            if image_b64:
                parsed = await self._call_vision(prompt, image_b64, timeout=30)
            else:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=0,
                    timeout=20,
                )
                parsed = json.loads(response.choices[0].message.content or "{}")
            return [t for t in parsed.get("titles", []) if isinstance(t, str) and t.strip()]
        except Exception as e:
            logger.error(f"filter_titles failed: {e}")
            return titles  # 실패 시 원본 그대로

    async def extract_titles_from_text(self, text: str) -> list[dict]:
        """요소 텍스트에서 공지 제목 목록 추출 (이미지 없이 텍스트만 사용)."""
        prompt = (
            "아래는 웹페이지 공지사항/게시글 목록 영역의 텍스트입니다.\n"
            "각 게시글의 제목만 추출하여 JSON으로 반환하세요:\n"
            '{"items": [{"title": "제목 원문", "summary": "날짜·마감·대상 등 핵심 정보 (없으면 빈 문자열)"}]}\n\n'
            "규칙:\n"
            "- 제목은 반드시 아래 텍스트에 그대로 등장하는 문장만 사용. 없는 말 추가·변형·조합 절대 금지\n"
            "- 게시글 1개당 항목 1개 (제목 아래 설명문은 별도 항목 금지)\n"
            "- 번호·날짜·조회수·작성자·부서명 제외, 제목 원문만\n"
            "- 항목 없으면 {\"items\": []} 반환, JSON 외 출력 금지\n\n"
            "텍스트:\n"
        ) + text[:4000]
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0,
                timeout=30,
            )
            parsed = json.loads(response.choices[0].message.content or "")
            items = parsed.get("items", [])
            return [
                {"title": i["title"].strip(), "summary": i.get("summary", "").strip()}
                for i in items if i.get("title", "").strip()
            ]
        except Exception as e:
            logger.error(f"extract_titles_from_text failed: {type(e).__name__}: {e}")
            return []

    async def identify_selectors(self, image_b64: str, elements: list[dict]) -> dict:
        """드래그 영역 스크린샷과 요소 목록으로 content_selector, next_page_selector 식별."""
        elements_text = json.dumps(
            [{"selector": e["selector"], "text": e.get("text", "")} for e in elements[:60]],
            ensure_ascii=False,
        )
        try:
            parsed = await self._call_vision(
                IDENTIFY_SELECTORS_PROMPT + f"\n\nelements:\n{elements_text}",
                image_b64,
            )
            return {
                "content_selector": parsed.get("content_selector") or None,
                "next_page_selector": parsed.get("next_page_selector") or None,
            }
        except Exception as e:
            logger.error(f"identify_selectors failed: {e}")
            raise

    async def find_next_selector(self, image_b64: str, elements: list[dict]) -> str | None:
        """스크린샷과 요소 목록에서 '다음 페이지' 버튼의 selector를 반환."""
        elements_text = json.dumps(
            [{"selector": e["selector"], "text": e.get("text", "")} for e in elements],
            ensure_ascii=False,
        )
        try:
            parsed = await self._call_vision(
                FIND_NEXT_PROMPT + f"\n\nelements:\n{elements_text}",
                image_b64,
            )
            return parsed.get("selector") or None
        except Exception as e:
            logger.error(f"find_next_selector failed: {e}")
            return None

    async def summarize_detail(self, text: str) -> str:
        """상세 페이지 본문을 2~3문장으로 요약."""
        prompt = (
            "아래는 공지사항·게시글의 상세 페이지 내용입니다.\n"
            "핵심 내용만 2~3문장으로 간결하게 요약하세요.\n"
            "날짜·작성자·조회수 등 메타정보는 제외하고 실제 내용 위주로 요약하세요.\n\n"
            f"본문:\n{text[:4000]}\n\n"
            '다음 JSON 형식으로만 답하세요:\n{"summary": "요약 내용"}'
        )
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0,
                timeout=30,
            )
            result = json.loads(response.choices[0].message.content or "{}")
            return result.get("summary", "")
        except Exception as e:
            logger.error(f"summarize_detail failed: {e}")
            return ""

    async def find_href_for_titles(
        self,
        unmatched_titles: list[str],
        title_links: list[dict],
    ) -> dict[str, str]:
        """DOM 매칭 실패 제목들을 title_links와 fuzzy 매칭해 {title: href} 반환."""
        if not unmatched_titles or not title_links:
            return {}
        titles_json = json.dumps(unmatched_titles, ensure_ascii=False)
        links_json = json.dumps(
            [{"title": l["title"], "href": l["href"]} for l in title_links[:50]],
            ensure_ascii=False,
        )
        prompt = (
            "두 목록을 보고 의미상 같은 항목끼리 매칭하세요.\n\n"
            f"제목 목록:\n{titles_json}\n\n"
            f"링크 목록 (텍스트가 약간 다를 수 있음):\n{links_json}\n\n"
            "각 제목과 가장 의미상 같은 링크의 href를 찾아 반환하세요. "
            "확실하지 않으면 null.\n"
            'JSON 형식으로만 반환: {"matches": [{"title": "원본제목", "href": "url 또는 null"}]}'
        )
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0,
                timeout=20,
            )
            parsed = json.loads(response.choices[0].message.content or "{}")
            return {
                m["title"]: m["href"]
                for m in parsed.get("matches", [])
                if m.get("title") and m.get("href")
            }
        except Exception as e:
            logger.error(f"find_href_for_titles failed: {e}")
            return {}


    async def extract_detail_from_screenshot(self, image_b64: str, title: str) -> str:
        """클릭 후 URL이 바뀌지 않는 AJAX/SPA 페이지에서 상세 내용을 스크린샷으로 추출한다."""
        prompt = (
            f"이 스크린샷은 공지 목록에서 '{title}' 항목을 클릭한 직후 화면입니다.\n"
            "화면에 해당 공지의 상세 본문이 로드되어 있으면 그 내용을 텍스트로 추출하세요.\n"
            "여전히 목록만 보이거나 상세 내용이 없으면 content를 빈 문자열로 반환하세요.\n\n"
            'JSON 형식으로만 반환: {"content": "추출된 본문 텍스트 (없으면 빈 문자열)"}'
        )
        try:
            parsed = await self._call_vision(prompt, image_b64, timeout=30)
            return (parsed.get("content") or "").strip()
        except Exception as e:
            logger.error(f"extract_detail_from_screenshot failed: {e}")
            return ""

    async def infer_hrefs_from_js(
        self,
        page_url: str,
        js_hints: list[dict],
    ) -> dict[str, str]:
        """javascript: 표현식과 목록 페이지 URL로 실제 detail URL을 추론한다.

        Args:
            page_url: 현재 목록 페이지 URL (URL 패턴 추론 힌트로 사용)
            js_hints: [{"title": "...", "js_attr": "fn_view('123')"}]

        Returns:
            {title: inferred_href} — 추론 실패 항목은 포함하지 않음
        """
        if not js_hints:
            return {}
        prompt = (
            f"목록 페이지 URL: {page_url}\n\n"
            "아래 항목들은 공지 목록의 링크가 javascript: 표현식이라 실제 URL을 모릅니다.\n"
            "각 항목의 js_attr(onclick 또는 javascript: href)과 목록 URL 패턴을 보고 "
            "실제 상세 페이지 URL을 추론하세요.\n\n"
            "추론 방법:\n"
            "- list.do → view.do, /list → /view, /board/list → /board/view 같은 경로 패턴\n"
            "- fn_view·goView·viewDetail 등의 함수 인자는 보통 seq/nttId/id에 해당\n"
            "- 목록 URL의 쿼리 파라미터(bbsId 등)는 상세 URL에도 공통으로 사용되는 경우 多\n"
            "- 확신할 수 없으면 null\n\n"
            f"항목:\n{json.dumps(js_hints, ensure_ascii=False)}\n\n"
            'JSON 형식으로만 반환: {"matches": [{"title": "...", "href": "추론된 절대 URL 또는 null"}]}'
        )
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0,
                timeout=20,
            )
            parsed = json.loads(response.choices[0].message.content or "{}")
            return {
                m["title"]: m["href"]
                for m in parsed.get("matches", [])
                if m.get("title") and m.get("href")
            }
        except Exception as e:
            logger.error(f"infer_hrefs_from_js failed: {e}")
            return {}


ai_client = AIClient()
