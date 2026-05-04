# Notice Ping

웹사이트 변경을 감지하고 로컬 AI로 요약해주는 셀프 호스팅 모니터링 서비스입니다.  
공지사항·뉴스부터 거래 사이트까지, 원하는 페이지를 등록하면 변경이 감지될 때마다 AI가 핵심 내용을 요약합니다.

## 구조

```
changedetection.io  →  웹사이트 변경 감지 (5분 주기)
        ↓
noticeping-app   →  타입별 분석 파이프라인 → AI 요약 → 알림 저장
        ↑
ollama (gemma4:e2b) →  로컬 멀티모달 AI 분석 엔진
```

| 서비스 | 주소 |
|--------|------|
| Notice Ping | http://localhost:8000 |
| changedetection.io | http://localhost:5000 |
| Ollama API | http://localhost:11434 |

---

## 사전 요구사항

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Docker Compose 포함)

---

## 시작하기

### 1. 실행

```bash
docker compose up -d --build
```

- 프론트엔드 빌드(Node.js)가 Docker 내부에서 자동으로 처리됩니다.
- 최초 실행 시 `ollama-init` 컨테이너가 `gemma4:e2b` 모델을 자동 다운로드합니다 (약 5GB, 네트워크 속도에 따라 10~30분 소요).
- 모델 다운로드 중에는 AI 분석이 동작하지 않으나, 다운로드 완료 후 자동으로 정상 동작합니다.

### 2. 접속

```
http://localhost:8000
```

별도 설정 없이 바로 사용 가능합니다. API 키는 기본값(`localkey123`)으로 자동 연동됩니다.

> **선택 사항**: API 키나 폴링 주기를 변경하려면 프로젝트 루트에 `.env` 파일을 생성하세요.
> ```env
> CHANGEDETECTION_API_KEY=원하는키
> POLL_INTERVAL=30
> ```
> 변경 후 `docker compose up -d --build`로 재시작하면 적용됩니다.

### 3. 중지 / 재시작

```bash
# 중지 (데이터 유지)
docker compose down

# 재시작
docker compose up -d
```

---

## 사용 방법

### 모니터 등록

http://localhost:8000 → 우측 상단 설정 아이콘 또는 사이드바 **모니터 관리**

- **추가**: URL·이름·타입 입력 후 추가 (자동으로 5분 주기 감지 등록)
- **설정**: 각 항목의 수정 아이콘으로 이름·타입·상단 무시 줄 수 변경
- **시각적 필터**: 눈 아이콘 클릭 → changedetection.io 비주얼 셀렉터에서 감시할 영역을 직접 선택
- **삭제**: 휴지통 아이콘

### 알림 확인

- 사이드바에서 **전체 받은 알림** 또는 사이트별 항목 클릭
- 알림 클릭 시 우측 드로어에서 제목·요약 확인, 원문 링크 제공
- 읽음 처리·닫기는 각 알림 행 우측 버튼 또는 드로어 하단 버튼

---

## 모니터 타입

| 타입 | 대상 | AI 분석 방식 |
|------|------|-------------|
| `content` | 공지사항, 뉴스, 커뮤니티 | 텍스트 diff → LLM |
| `market` | 중고거래, 쇼핑몰, 매물 | 텍스트 diff + 스크린샷 → Vision LLM |

---

## AI 분석 동작 방식

1. changedetection이 페이지 변경 감지 (5분 주기)
2. 앱이 폴링 주기마다 신규 변경 확인
3. 다음 변경은 자동으로 무시:
   - 숫자·조회수·건수만 바뀐 경우
   - 커뮤니티 포인트/점수 변경 (`N points by username` 패턴)
   - **content 타입**: 상업성 키워드가 다수 포함된 광고·스팸 게시글
4. 타입별 LLM 분석:
   - **content**: 텍스트 diff → 공지·뉴스 여부 판단 → 한국어 요약
   - **market**: 텍스트 diff + 스크린샷 → 신규 매물·상품 여부 판단 → 한국어 요약
5. 동일 제목의 알림은 중복 저장하지 않음

---

## 환경 변수

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `CHANGEDETECTION_API_KEY` | changedetection.io API 토큰 | `localkey123` |
| `POLL_INTERVAL` | changedetection 폴링 주기 (초) | `30` |
| `IGNORE_TOP_LINES` | 텍스트 diff 상위 N줄 무시 (헤더·배너 노이즈 방지) | `10` |

---

## 데이터 저장 위치

```
data/
├── app/noticeping.db     ← 알림 및 watch 이력 (SQLite)
├── changedetection/      ← 페이지 스냅샷, 설정
└── ollama/               ← AI 모델 파일 (수 GB)
```

전체 백업은 `data/` 폴더를 복사하면 됩니다.

---

## 기술 스택

- **Frontend**: React, TypeScript, Vite
- **Backend**: FastAPI, APScheduler, httpx
- **AI**: Ollama (gemma4:e2b, 멀티모달 Vision)
- **변경 감지**: changedetection.io + Playwright
- **인프라**: Docker Compose (멀티스테이지 빌드)
- **DB**: SQLite
