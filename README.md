# Notice Ping

웹페이지 변경을 감지해 알림을 보내는 셀프 호스팅 서비스.

## 시작하기

`.env` 생성:
```env
AI_API_KEY=발급받은_키
AI_API_BASE=https://api.openai.com/v1
AI_MODEL=gpt-4o-mini
```

실행:
```bash
docker compose up -d --build
```

접속: `http://localhost:8000`

## 사용법

1. **모니터 관리** → URL·이름 입력 후 추가
2. 👁 (영역 선택) → 스크린샷에서 감시할 요소 클릭 → AI가 selector 자동 지정
3. 새 공지 감지 시 알림 목록에 자동 추가

## 환경 변수

| 변수 | 기본값 |
|------|--------|
| `AI_API_KEY` | (필수) |
| `AI_API_BASE` | `https://factchat-cloud.mindlogic.ai/v1/gateway` |
| `AI_MODEL` | `gpt-5.4-nano` |
| `POLL_INTERVAL` | `60` (초) |

## 기술 스택

React · FastAPI · Playwright · SQLite · Docker
