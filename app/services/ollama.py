import base64
import json
import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

ANALYZE_PROMPT = """\
당신은 웹 페이지 변경 감지 시스템의 분류기입니다.
아래는 웹 페이지에서 방금 새로 감지된 텍스트 줄 목록입니다:

{new_lines}

이 목록에서 실제로 새로 등록된 공지·게시글·뉴스 항목의 제목을 찾아내세요.

판단 기준:
- 선택해야 할 것: 독자에게 전달할 내용이 있는 실질적인 게시글 제목
- 제외해야 할 것:
  - 숫자·조회수·순위·날짜·시간만 바뀐 줄 (예: "3분 전", "조회 142")
  - 추천수·점수 변경 (예: "1 point by helio", "3 points by user123")
  - 댓글 수 변경 (예: "댓글 5개", "12 comments")
  - 배너·팝업·광고·이벤트 홍보 문구
  - 네비게이션·메뉴·버튼·UI 레이블 텍스트
  - 의미 없는 짧은 단어, 기호, 빈 문자열

각 항목의 필드:
1. "title": 목록에서 그대로 복사한 제목 텍스트 (절대 수정하지 마세요)
2. "summary": 위 텍스트 목록에 있는 정보만 사용해 2~3문장 요약.
   날짜, 마감일, 대상, 신청 방법 등이 보이면 반드시 포함하세요.
   목록에 없는 정보는 절대 추가하지 마세요.

실질적인 새 게시글이 없으면 반드시 빈 배열 []을 반환하세요.
JSON 배열 외에 다른 텍스트는 출력하지 마세요."""


MARKET_ANALYZE_PROMPT = """\
당신은 중고거래·부동산 등 거래 플랫폼의 신규 매물 감지기입니다.
아래는 웹 페이지에서 방금 새로 감지된 텍스트 줄 목록입니다:

{new_lines}
{screenshot_hint}
새로 등록된 매물·상품·거래 게시글 제목을 모두 찾아내세요.

판단 기준:
- 선택해야 할 것: 실제 판매/구매/임대 목적의 게시글 제목
- 제외해야 할 것:
  - 숫자·조회수·순위·가격·시간 정보만 바뀐 줄
  - 광고 배너, 이벤트 홍보 문구, 공지 팝업
  - 네비게이션·메뉴·버튼·UI 레이블 텍스트
  - 실제 거래 게시글이 아닌 경우

각 항목의 필드:
1. "title": 목록에서 그대로 복사한 제목 텍스트 (절대 수정하지 마세요)
2. "summary": 위 텍스트 목록과 스크린샷에서 확인된 정보만 사용해 2~3문장 요약.
   가격, 상태(새상품/중고), 거래 방식(직거래/택배), 위치가 보이면 반드시 포함하세요.
   확인되지 않은 정보는 절대 추가하지 말것. 스크린샷을 언급하지 말것.

실제 거래 게시글이 없으면 반드시 빈 배열 []을 반환하세요.
JSON 배열 외에 다른 텍스트는 출력하지 마세요."""


# Ollama structured output schema — 배열 형태 강제
_ITEMS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "title":   {"type": "string"},
            "summary": {"type": "string"},
        },
        "required": ["title", "summary"],
    },
}


def _parse_items(result) -> list[dict]:
    """LLM 응답에서 유효한 항목만 추출."""
    if isinstance(result, dict):
        result = [result]
    items = []
    for item in result:
        title = item.get("title", "").strip()
        summary = item.get("summary", "").strip()
        if title:
            items.append({"title": title, "summary": summary})
    return items


class OllamaClient:
    def __init__(self):
        self.base_url = settings.ollama_url.rstrip("/")
        self.model = settings.ollama_model

    async def analyze(self, new_lines: list[str]) -> list[dict]:
        """새로 추가된 줄에서 제목과 요약을 모두 추출한다 (복수 반환)."""
        formatted_lines = "\n".join(f"- {line}" for line in new_lines)
        prompt = ANALYZE_PROMPT.format(new_lines=formatted_lines)

        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": _ITEMS_SCHEMA,
        }

        try:
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(f"{self.base_url}/api/generate", json=payload)
                resp.raise_for_status()
                data = resp.json()

            raw = data.get("response", "").strip()
            logger.debug(f"Ollama analyze raw response: {raw[:500]}")
            result = json.loads(raw)
            return _parse_items(result)

        except json.JSONDecodeError:
            logger.warning(f"Ollama returned non-JSON response for analyze: {raw[:200]}")
            return []
        except httpx.TimeoutException:
            logger.error("Ollama timeout during analyze")
            return []
        except Exception as e:
            logger.error(f"Ollama analyze error: {type(e).__name__}: {e}")
            return []


    async def analyze_market(self, new_lines: list[str], screenshot: bytes | None) -> list[dict]:
        """거래 사이트: 스크린샷 + 텍스트 diff를 Vision LLM으로 분석 (복수 반환)."""
        formatted_lines = "\n".join(f"- {line}" for line in new_lines)
        screenshot_hint = (
            "첨부된 스크린샷도 함께 참고하여 텍스트에서 보이지 않는 가격·이미지 정보를 보완하세요.\n"
            if screenshot else ""
        )
        prompt = MARKET_ANALYZE_PROMPT.format(new_lines=formatted_lines, screenshot_hint=screenshot_hint)

        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": _ITEMS_SCHEMA,
        }
        if screenshot:
            payload["images"] = [base64.b64encode(screenshot).decode()]

        try:
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(f"{self.base_url}/api/generate", json=payload)
                resp.raise_for_status()
                data = resp.json()

            raw = data.get("response", "").strip()
            logger.debug(f"Ollama analyze_market raw response: {raw[:500]}")
            result = json.loads(raw)
            return _parse_items(result)

        except json.JSONDecodeError:
            logger.warning(f"Ollama returned non-JSON response for analyze_market: {raw[:200]}")
            return []
        except httpx.TimeoutException:
            logger.error("Ollama timeout during analyze_market")
            return []
        except Exception as e:
            logger.error(f"Ollama analyze_market error: {type(e).__name__}: {e}")
            return []


ollama = OllamaClient()
