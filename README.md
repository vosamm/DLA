# NoticeFeed

웹페이지의 목록형 콘텐츠를 주기적으로 크롤링해 새 항목을 감지하는 셀프 호스팅 서비스.

브라우저 스크린샷에서 감시할 영역을 드래그하면 AI가 CSS 셀렉터를 자동으로 찾아주고, 이후 스케줄러가 주기적으로 크롤링해 새 항목을 알림 목록에 저장한다.

## 주요 기능

- **드래그 셀렉터 설정** — 페이지 스크린샷에서 감시할 영역을 드래그하면 AI가 목록 컨테이너의 CSS 셀렉터를 자동 지정
- **자동 페이지네이션** — DOM 분석으로 다음 페이지 버튼을 자동 감지 (최대 5페이지), 이미 알고 있는 항목을 만나면 즉시 중단
- **클릭 기반 상세 수집** — 목록에서 각 항목을 실제로 클릭해 본문을 수집 (AJAX·팝업·새 탭 대응)
- **AI 요약** — 상세 본문을 2~3문장으로 요약해 알림에 함께 저장
- **중복 방지** — 워치별로 최근 200개 항목 제목을 기억해 신규 항목만 감지
- **개별 크롤 주기** — 워치마다 크롤 간격(시간 단위)을 독립 설정 가능

## 기술 스택

| 영역 | 사용 기술 |
|------|-----------|
| 프론트엔드 | React 18 · TypeScript · Vite |
| 백엔드 | FastAPI · Python 3.12 · APScheduler |
| 크롤링 | Playwright (Chromium headless) |
| AI | OpenAI-compatible API (vision + text) |
| 저장소 | SQLite |
| 배포 | Docker (멀티스테이지 빌드, 단일 컨테이너) |

## 시작하기

### 1. 환경 변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 열어 API 키를 입력한다:

```env
AI_API_KEY=발급받은_키
AI_API_BASE=https://factchat-cloud.mindlogic.ai/v1/gateway
AI_MODEL=gpt-5.4-mini
POLL_INTERVAL=60
```

OpenAI 호환 API라면 `AI_API_BASE`와 `AI_MODEL`을 해당 서비스에 맞게 변경한다.

### 2. 실행

```bash
docker compose up -d --build
```

### 3. 접속

브라우저에서 `http://localhost:8000` 열기

## 사용법

1. **워치 추가** — URL과 이름을 입력해 감시 대상 등록
2. **영역 선택** — 👁 버튼 클릭 → 페이지 스크린샷에서 감시할 목록 영역을 드래그 → AI가 CSS 셀렉터 자동 설정
3. **즉시 크롤** — 설정 후 바로 크롤 버튼으로 동작 확인
4. **알림 확인** — 새 항목이 감지되면 알림 탭에 제목·요약·링크가 자동 저장

## 환경 변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `AI_API_KEY` | **(필수)** | OpenAI-compatible API 키 |
| `AI_API_BASE` | `https://factchat-cloud.mindlogic.ai/v1/gateway` | API 엔드포인트 |
| `AI_MODEL` | `gpt-5.4-mini` | 사용할 모델 ID |
| `POLL_INTERVAL` | `60` | 스케줄러 체크 주기 (초) |

크롤 간격은 워치별로 UI에서 설정한다 (기본 12시간).

## 아키텍처

```
┌─────────────────────────────────────────────────────┐
│                  Docker Container                   │
│                                                     │
│  React SPA (정적 파일)                               │
│       ↕ REST API                                    │
│  FastAPI                                            │
│   ├── /api/watches  워치 CRUD + 셀렉터 설정          │
│   └── /api/alerts   알림 조회·삭제                   │
│                                                     │
│  APScheduler (poll_interval 초마다)                  │
│   └── 크롤 대상 조회 → process_watch()              │
│        ├── Playwright  페이지 수집 + 페이지네이션     │
│        ├── AI Client   셀렉터 식별 / 제목 추출 / 요약│
│        └── SQLite      알림·known_titles 저장        │
└─────────────────────────────────────────────────────┘
```

데이터는 `./data` 볼륨에 SQLite 파일로 저장된다.

## API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/api/watches/` | 워치 목록 |
| `POST` | `/api/watches/` | 워치 추가 |
| `PUT` | `/api/watches/{uuid}` | 워치 수정 (이름·간격·셀렉터) |
| `DELETE` | `/api/watches/{uuid}` | 워치 삭제 |
| `GET` | `/api/watches/{uuid}/element-map` | 페이지 요소 맵 조회 (셀렉터 설정 UI용) |
| `POST` | `/api/watches/{uuid}/analyze-region` | 드래그 영역 AI 분석 → 셀렉터 자동 저장 |
| `POST` | `/api/watches/{uuid}/crawl` | 즉시 크롤 트리거 |
| `GET` | `/api/alerts/` | 알림 목록 (watch_uuid 필터 가능) |
| `DELETE` | `/api/alerts/` | 알림 삭제 |

## 크롤링 동작 방식

1. 스케줄러가 `poll_interval`마다 크롤 기한이 된 워치를 DB에서 조회
2. Playwright로 페이지 로드 → DOM JS로 항목 제목·링크 추출 (AI 폴백 포함)
3. `known_titles`와 비교해 신규 항목만 선별
4. 신규 항목이 있으면 다음 페이지로 이동, 없거나 기존 항목을 만나면 중단 (최대 5페이지)
5. 신규 항목을 클릭해 상세 본문 수집 → AI 2~3문장 요약
6. 알림을 DB에 저장하고 `known_titles` 업데이트

### 페이지네이션 감지 순서

1. `[class*="pag"]` 등 페이지네이션 영역 후보 수집 → 숫자 분포로 점수화해 최적 컨테이너 선택
2. `.active / .current / strong` 등으로 현재 페이지 번호 파악 → `N+1` 버튼 셀렉터 반환
3. 폴백: "다음 / next / ›" 텍스트 버튼 탐색
4. 폴백: `?page=N` URL 파라미터 파싱
5. 위 모두 실패 시 AI vision으로 다음 버튼 셀렉터 식별

## 로컬 개발

```bash
# 백엔드
cd app
pip install -r requirements.txt
playwright install chromium
uvicorn main:app --reload

# 프론트엔드 (별도 터미널)
cd frontend
npm install
npm run dev
```

프론트는 `localhost:5173`, 백엔드는 `localhost:8000`에서 각각 실행된다.
Vite가 `/api` 요청을 백엔드로 자동 프록시한다.
