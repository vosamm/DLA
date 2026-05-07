# Notice Ping

웹사이트 변경을 감지하고 로컬 AI로 요약해주는 셀프 호스팅 모니터링 서비스입니다.  
원하는 페이지를 등록하면 변경이 감지될 때마다 AI가 알림으로 보내줍니다.

## 구조

```
changedetection.io  →  웹사이트 변경 감지 (Playwright)
        ↓
noticeping-app   →  diff 분석 → LLM 요약 → 알림 저장
        ↑
ollama (gemma4:e2b) →  로컬 AI 분석 엔진
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
- 모델 다운로드 중에는 AI 분석이 동작하지 않으나, 완료 후 자동으로 정상 동작합니다.

### 2. 접속

```
http://localhost:8000
```

별도 설정 없이 바로 사용 가능합니다.

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

- **추가**: URL·이름 입력 후 추가 (자동으로 30초 주기 감지 등록)
- **설정**: 수정 아이콘 → 이름·상단 무시 줄 수 변경
- **시각적 필터**: 눈 아이콘 → changedetection.io 비주얼 셀렉터에서 감시할 영역 직접 선택
- **삭제**: 휴지통 아이콘

### 알림 확인

- 사이드바에서 **전체 받은 알림** 또는 사이트별 항목 클릭
- 알림 클릭 시 우측 드로어에서 제목·요약 확인 및 원문 링크 이동
- 읽음 처리·닫기는 각 알림 행 우측 버튼 또는 드로어 하단 버튼

---

## AI 분석 동작 방식

1. changedetection.io가 Playwright로 페이지 변경 감지
2. 앱이 30초 주기로 신규 변경 확인
3. 다음 변경은 자동으로 무시:
   - 숫자·조회수만 바뀐 경우
   - 제목 없는 메타데이터 (부서명·날짜 조합 등)
   - UI 텍스트 (메뉴·버튼·배너 등)
4. LLM(gemma4:e2b)이 새 줄 목록에서 실제 게시글 제목·요약 추출
5. 동일 제목 알림은 중복 저장하지 않음

---

## 환경 변수

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `CHANGEDETECTION_API_KEY` | changedetection.io API 토큰 | `localkey123` |
| `POLL_INTERVAL` | 폴링 주기 (초) | `30` |
| `IGNORE_TOP_LINES` | diff 상위 N줄 무시 (헤더·배너 노이즈 방지) | `10` |
| `MAX_DIFF_LINES` | diff 최대 줄 수 (초과분 무시) | `30` |

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
- **AI**: Ollama (gemma4:e2b)
- **변경 감지**: changedetection.io + Playwright
- **인프라**: Docker Compose (멀티스테이지 빌드)
- **DB**: SQLite
