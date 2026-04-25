# VisualMonitor

웹사이트 변경을 감지하고 로컬 AI로 요약해주는 셀프 호스팅 모니터링 서비스입니다.  
공지사항, 뉴스 등 원하는 페이지를 등록하면 변경이 감지될 때마다 AI가 핵심 내용을 요약합니다.

## 구조

```
changedetection.io  →  웹사이트 변경 감지 (5분 주기)
        ↓
visualmonitor-app   →  변경 분석 → 스크린샷 + diff → AI 요약 → 알림 저장
        ↑
ollama (gemma4:e2b) →  로컬 멀티모달 AI 분석 엔진
```

| 서비스 | 주소 |
|--------|------|
| VisualMonitor 대시보드 | http://localhost:8000 |
| Ollama API | http://localhost:11434 |

---

## 시작하기

### 1. 실행

```bash
docker compose up -d
```

처음 실행 시 `ollama-init` 컨테이너가 `gemma4:e2b` 모델을 자동 다운로드합니다.

### 2. API 토큰 설정

최초 실행 후 changedetection이 API 토큰을 자동 생성합니다. `.env`에 등록해야 앱이 연동됩니다.

```bash
# 토큰 확인
cat data/changedetection/changedetection.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['settings']['application']['api_access_token'])"
```

`.env` 파일:

```env
CHANGEDETECTION_API_KEY=<위에서 확인한 토큰>
POLL_INTERVAL=30
```

설정 후 재시작:

```bash
docker compose up -d
```

### 3. 중지 / 재시작

```bash
# 재시작 (데이터 유지)
docker compose down && docker compose up -d

# 코드 변경 후 재빌드
docker compose down && docker compose up -d --build
```

---

## 사용 방법

### URL 등록 / 수정 / 삭제

http://localhost:8000 → **모니터 관리** 탭

- **추가**: URL과 이름 입력 후 추가 버튼 (자동으로 5분 주기 감지 등록)
- **이름 수정**: 목록에서 **수정** 버튼 클릭 → 인라인 편집
- **삭제**: **삭제** 버튼 클릭

### 알림 확인

http://localhost:8000 메인 화면

- **전체** 탭: 모든 사이트의 알림을 최신순으로 표시, 카드 내 사이트명 레이블 포함
- **사이트별 탭**: 등록한 모니터 이름으로 탭이 자동 생성, 해당 사이트 알림만 표시
- 알림 카드의 사이트명 또는 URL을 클릭하면 해당 페이지로 이동

### AI 분석 동작 방식

1. changedetection이 페이지 변경 감지 (5분 주기)
2. 앱이 30초마다 폴링해서 신규 변경 확인
3. **단순 숫자 변화(조회수, 건수 등)는 자동 무시**
4. 실제 변경이면 페이지 스크린샷 + 텍스트 diff를 Ollama에 전달
5. gemma4:e2b가 텍스트와 이미지를 함께 분석해 한국어 요약 생성

---

## 환경 변수

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `CHANGEDETECTION_API_KEY` | changedetection.io API 토큰 | `localkey123` |
| `POLL_INTERVAL` | 앱의 changedetection 폴링 주기 (초) | `30` |

changedetection의 실제 웹사이트 체크 주기는 기본 **5분**이며, URL 등록 시 자동 설정됩니다.

---

## 데이터 저장 위치

```
data/
├── app/visualmonitor.db     ← 알림 및 watch 이력 (SQLite)
├── changedetection/         ← 페이지 스냅샷, 설정
└── ollama/                  ← AI 모델 파일 (수 GB)
```

전체 백업은 `data/` 폴더를 복사하면 됩니다.

---

## 기술 스택

- **Backend**: FastAPI, APScheduler, httpx
- **AI**: Ollama (gemma4:e2b, 멀티모달)
- **변경 감지**: changedetection.io
- **인프라**: Docker Compose
- **DB**: SQLite
