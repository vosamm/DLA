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

화면에 보이는 게시글 제목을 모두 추출하여 다음 JSON 형식으로 반환하세요:
{"items": [{"title": "제목 원문", "summary": "날짜·마감·대상 등 핵심 정보 (없으면 빈 문자열)"}]}

주의:
- title은 제목 원문 그대로 (번호·날짜·조회수·부서명 등 메타데이터 제외)
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


ai_client = AIClient()
