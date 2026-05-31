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
형식: {"selector": "CSS selector"} 또는 {"selector": null}

주의:
- "다음", ">", "▶", "next", ">>" 같은 다음 페이지 이동 버튼을 찾으세요
- 숫자 페이지 버튼(1,2,3...)은 제외
- elements 목록에 있는 selector만 사용
- 없으면 {"selector": null}"""

ROI_EXTRACT_PROMPT = """\
이 이미지는 웹페이지 공지사항/게시글 목록 영역의 스크린샷입니다.

각 게시글의 제목만 추출하여 다음 JSON 형식으로 반환하세요:
{"items": [{"title": "제목 원문", "summary": "날짜·마감·대상 등 핵심 정보 (없으면 빈 문자열)"}]}

규칙:
- items 배열 길이 = 화면에 보이는 게시글 수 (게시글 1개 → 항목 1개, 초과 금지)
- 제목 아래 미리보기·설명·요약문은 별도 항목으로 추가하지 말 것 (제목과 같은 게시글의 일부)
- 작성자명·닉네임·날짜·조회수·포인트·댓글 수 제외
- title은 클릭 가능한 링크 텍스트 (가장 크고 굵게 표시된 줄)
- 항목이 없으면 {"items": []} 반환
- JSON 외 텍스트 출력 금지"""


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

    async def extract_titles(self, image_b64: str) -> list[dict]:
        """ROI 이미지에서 공지 제목 목록 추출."""
        try:
            parsed = await self._call_vision(ROI_EXTRACT_PROMPT, image_b64, timeout=60)
            items = parsed.get("items", [])
            return [
                {"title": i["title"].strip(), "summary": i.get("summary", "").strip()}
                for i in items if i.get("title", "").strip()
            ]
        except Exception as e:
            logger.error(f"extract_titles failed: {type(e).__name__}: {e}")
            return []

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
            '형식: {"matches": [{"title": "원본제목", "href": "url 또는 null"}]}'
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


ai_client = AIClient()
