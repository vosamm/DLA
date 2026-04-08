# 웹 크롤링 & LLM 공지 추출 서비스

로컬 환경에서 동작하는 URL 기반 웹 크롤링 및 LLM 공지 추출 서비스입니다.
URL을 입력하면 해당 페이지를 자동으로 크롤링하고, LLM이 공지/안내 항목을 구조화된 형태로 추출합니다.

---

## 주요 기능

- **URL 크롤링**: crawl4ai + Playwright 기반, JavaScript 렌더링 지원
- **페이지네이션 자동 탐색**: `pageIndex`, `page`, `pageNo` 등 쿼리 파라미터 감지 후 전 페이지 순회
- **LLM 공지 추출**: UOS MindLogic API(claude-sonnet)를 통해 공지 제목, 날짜, 요약, URL 구조화
- **대시보드**: (예정)
- **RAG 챗봇**: (예정)

---

## 기술 스택

| 역할 | 기술 |
|---|---|
| 프론트엔드 | Next.js |
| 백엔드 API | FastAPI (Python) |
| 크롤링 | [crawl4ai](https://github.com/unclecode/crawl4ai) (Playwright 기반) |
| LLM | UOS MindLogic API (claude-sonnet-4-5) |
| 임베딩 / 벡터 DB | 미정 |

---

## 시작하기

### 사전 요구사항

- Node.js 18+
- Python 3.10+
- UOS MindLogic API 키

### 1. 저장소 클론

```bash
git clone <repository-url>
cd DLA
```

### 2. 환경 변수 설정

```bash
cd backend
cp .env.example .env
```

`.env` 파일을 열어 API 키를 입력합니다:

```
UOS_API_KEY=여기에_발급받은_키_입력
UOS_API_URL=https://factchat-cloud.mindlogic.ai/v1/api/anthropic/messages
```

### 3. Playwright 브라우저 설치

```bash
playwright install
```

### 4. 백엔드 실행

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

백엔드는 `http://localhost:8000` 에서 실행됩니다.

### 5. 프론트엔드 실행

```bash
cd frontend
npm install
npm run dev
```

프론트엔드는 `http://localhost:3000` 에서 실행됩니다.

---

## API 명세

### `POST /api/crawl`

URL을 크롤링하고 LLM이 공지 항목을 추출합니다.

**Request Body**

```json
{
  "url": "https://example.com/notice/list.do",
  "wait_for": null,
  "delay": 3.0,
  "max_pages": 5
}
```

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `url` | string | 필수 | 크롤링할 URL |
| `wait_for` | string | null | 대기할 CSS 셀렉터 |
| `delay` | float | 3.0 | HTML 반환 전 대기 시간(초) |
| `max_pages` | int | 5 | 최대 페이지 수 |

**Response**

```json
{
  "url": "https://example.com/notice/list.do",
  "title": "",
  "markdown": "...",
  "pages_crawled": 3,
  "notices": [
    {
      "title": "2025년 1학기 수강신청 안내",
      "date": "2025-01-15",
      "summary": "수강신청 일정 및 방법 안내",
      "url": "https://example.com/notice/view.do?seq=12345"
    }
  ]
}
```

---

## 프로젝트 구조

```
DLA/
├── README.md
├── CLAUDE.md               # AI 개발 가이드
├── .gitignore
├── backend/
│   ├── main.py             # FastAPI 앱 (크롤링 + LLM 추출)
│   ├── requirements.txt    # Python 의존성
│   ├── .env.example        # 환경 변수 템플릿
│   └── .env                # 실제 환경 변수 (Git 제외)
└── frontend/
    ├── package.json
    ├── next.config.mjs
    └── app/
        ├── layout.tsx
        └── page.tsx        # URL 입력 및 결과 표시
```

---

## 주의사항

- 크롤링 전 대상 사이트의 `robots.txt` 및 이용약관을 반드시 확인하세요.
- Windows 환경에서는 asyncio ProactorEventLoop이 자동으로 설정됩니다.
