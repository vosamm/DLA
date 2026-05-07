import json
import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

ANALYZE_PROMPT = """\
웹 페이지에서 새로 감지된 텍스트 줄 목록입니다:

{new_lines}

실제 공지·게시글 제목만 추출하세요.

제외:
- 수치·날짜·조회수·추천수·댓글 수만 바뀐 줄
- 부서명·날짜·번호 조합처럼 실제 제목이 없는 메타데이터
- 광고·홍보·상업성 문구
- UI 텍스트 (메뉴·버튼·배너 등)

예시:
입력: ["교무과 2026-05-04 141", "조회 142", "2026 수시 일정 변경 안내"]
출력: [{{"title": "2026 수시 일정 변경 안내", "summary": "2026 수시 일정이 변경되었습니다."}}]

입력: ["교무과 2026-429", "추천 3", "공지사항"]
출력: []

각 항목:
- "title": 목록에서 그대로 복사 (수정 금지)
- "summary": 목록 내 정보만으로 2~3문장. 날짜·마감일·대상·신청 방법 포함. 없는 정보 추가 금지.

새 게시글이 없으면 [] 반환. JSON 외 출력 금지."""


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

    async def _call_llm(self, prompt: str) -> list[dict]:
        """공통 LLM 호출: payload 빌드 → httpx POST → JSON 파싱 → 항목 반환."""
        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": _ITEMS_SCHEMA,
            "options": {"temperature": 0.1},
        }

        raw = ""
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(f"{self.base_url}/api/generate", json=payload)
                resp.raise_for_status()
                data = resp.json()

            raw = data.get("response", "").strip()
            logger.debug(f"Ollama raw response: {raw[:500]}")
            result = json.loads(raw)
            return _parse_items(result)

        except json.JSONDecodeError:
            logger.warning(f"Ollama returned non-JSON response: {raw[:200]}")
            return []
        except httpx.TimeoutException:
            logger.error("Ollama timeout")
            return []
        except Exception as e:
            logger.error(f"Ollama error: {type(e).__name__}: {e}")
            return []

    async def analyze(self, new_lines: list[str]) -> list[dict]:
        """새로 추가된 줄에서 제목과 요약을 모두 추출한다 (복수 반환)."""
        formatted_lines = "\n".join(f"- {line}" for line in new_lines)
        prompt = ANALYZE_PROMPT.format(new_lines=formatted_lines)
        return await self._call_llm(prompt)


ollama = OllamaClient()
