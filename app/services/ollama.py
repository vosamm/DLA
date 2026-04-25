import base64
import json
import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

CONTENT_PROMPT = """\
페이지 제목: {title}

변경된 내용:
{diff}

JSON으로만 응답하세요:
{{
  "summary": "핵심 변경 내용을 2~3문장으로 요약. 공지라면 공지가 올라온 시간, 신청 방법·기간·대상 등 중요 정보를 포함. 이미지에 추가 정보가 있다면 함께 설명."
}}"""


class OllamaClient:
    def __init__(self):
        self.base_url = settings.ollama_url.rstrip("/")
        self.model = settings.ollama_model

    async def analyze(self, url: str, title: str, diff: str, image_bytes: bytes | None = None) -> dict:
        prompt = CONTENT_PROMPT.format(
            title=title or url,
            diff=diff[:800],
        )

        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }

        if image_bytes:
            payload["images"] = [base64.b64encode(image_bytes).decode()]
            logger.info("Sending screenshot to Ollama for multimodal analysis")

        try:
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

            raw = data.get("response", "{}")
            return json.loads(raw)

        except json.JSONDecodeError:
            logger.warning("Ollama returned non-JSON response")
            return {"summary": data.get("response", "분석 실패"), "raw": True}
        except httpx.TimeoutException:
            logger.error("Ollama timeout: 모델 응답 시간 초과")
            return {"summary": "분석 오류: 응답 시간 초과", "error": True}
        except Exception as e:
            logger.error(f"Ollama error: {type(e).__name__}: {e}")
            return {"summary": f"분석 오류: {type(e).__name__}", "error": True}


ollama = OllamaClient()
