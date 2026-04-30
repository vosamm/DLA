import base64
import json
import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

ANALYZE_PROMPT = """\
아래는 웹 페이지에서 새로 추가된 텍스트 줄 목록입니다:

{new_lines}

위 목록을 보고 다음 두 가지를 JSON으로만 응답하세요:

1. title: 새로 등록된 공지·게시글·뉴스 항목의 제목 텍스트를 목록에서 그대로 골라주세요.
   다음에 해당하면 반드시 빈 문자열로 반환하세요:
   - 숫자·조회수·순위만 바뀐 경우
   - 배너·팝업·광고·이벤트 홍보 문구
   - 네비게이션·메뉴·버튼 텍스트
   - 의미 없는 짧은 단어나 기호
   - 실질적인 새 게시물이 아닌 경우

2. summary: 해당 제목의 게시글 내용을 위 텍스트만으로 2~3문장 요약하세요.
   날짜, 마감일, 대상, 신청 방법 등 중요한 정보가 있으면 반드시 포함하세요.
   title이 빈 문자열이면 summary도 빈 문자열로 반환하세요.

{{"title": "제목 텍스트 또는 빈 문자열", "summary": "2~3문장 요약 또는 빈 문자열"}}"""


MARKET_ANALYZE_PROMPT = """\
아래는 웹 페이지에서 새로 추가된 텍스트 줄 목록입니다:

{new_lines}

첨부된 스크린샷을 함께 참고하여 다음 두 가지를 JSON으로만 응답하세요:

1. title: 새로 등록된 매물·상품·거래 게시글의 제목을 목록에서 그대로 골라주세요.
   다음에 해당하면 반드시 빈 문자열로 반환하세요:
   - 숫자·조회수·순위·가격만 바뀐 경우
   - 광고 배너, 이벤트 홍보 문구, 공지 팝업
   - 네비게이션·메뉴·버튼 텍스트
   - 실제 거래/매물 게시글이 아닌 경우

2. summary: 해당 게시글의 내용을 2~3문장으로 요약하세요.
   가격, 상태(새상품/중고), 거래 방식(직거래/택배), 위치 등 중요한 정보가 있으면 반드시 포함하세요.
   title이 빈 문자열이면 summary도 빈 문자열로 반환하세요.

{{"title": "제목 텍스트 또는 빈 문자열", "summary": "2~3문장 요약 또는 빈 문자열"}}"""


class OllamaClient:
    def __init__(self):
        self.base_url = settings.ollama_url.rstrip("/")
        self.model = settings.ollama_model

    async def analyze(self, new_lines: list[str]) -> dict:
        """새로 추가된 줄에서 제목과 요약을 한 번에 추출한다."""
        formatted_lines = "\n".join(f"- {line}" for line in new_lines)
        prompt = ANALYZE_PROMPT.format(new_lines=formatted_lines)

        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }

        try:
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(f"{self.base_url}/api/generate", json=payload)
                resp.raise_for_status()
                data = resp.json()

            result = json.loads(data.get("response", "{}"))
            title = result.get("title", "").strip()
            summary = result.get("summary", "").strip()
            return {"title": title, "summary": summary}

        except json.JSONDecodeError:
            logger.warning("Ollama returned non-JSON response for analyze")
            return {"title": "", "summary": ""}
        except httpx.TimeoutException:
            logger.error("Ollama timeout during analyze")
            return {"title": "", "summary": ""}
        except Exception as e:
            logger.error(f"Ollama analyze error: {type(e).__name__}: {e}")
            return {"title": "", "summary": ""}


    async def analyze_market(self, new_lines: list[str], screenshot: bytes | None) -> dict:
        """거래 사이트: 스크린샷 + 텍스트 diff를 Vision LLM으로 분석."""
        formatted_lines = "\n".join(f"- {line}" for line in new_lines)
        prompt = MARKET_ANALYZE_PROMPT.format(new_lines=formatted_lines)

        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }
        if screenshot:
            payload["images"] = [base64.b64encode(screenshot).decode()]

        try:
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(f"{self.base_url}/api/generate", json=payload)
                resp.raise_for_status()
                data = resp.json()

            result = json.loads(data.get("response", "{}"))
            title = result.get("title", "").strip()
            summary = result.get("summary", "").strip()
            return {"title": title, "summary": summary}

        except json.JSONDecodeError:
            logger.warning("Ollama returned non-JSON response for analyze_market")
            return {"title": "", "summary": ""}
        except httpx.TimeoutException:
            logger.error("Ollama timeout during analyze_market")
            return {"title": "", "summary": ""}
        except Exception as e:
            logger.error(f"Ollama analyze_market error: {type(e).__name__}: {e}")
            return {"title": "", "summary": ""}


ollama = OllamaClient()
