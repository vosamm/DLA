# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# 프로젝트 개요

로컬 환경에서 동작하는 **URL 기반 웹 크롤링 및 RAG 챗봇 서비스**입니다.
사용자가 URL을 등록하면 해당 사이트를 자동으로 크롤링하고, 수집된 정보를 대시보드에서 한눈에 확인할 수 있습니다.
새로운 콘텐츠가 감지되면 알림을 제공하며, 챗봇을 통해 크롤링된 데이터를 자연어로 질의할 수 있습니다.

---

## 핵심 기능

### 1. URL 크롤링
- 사용자가 URL을 입력하면 해당 사이트를 자동으로 크롤링합니다.
- 크롤링 엔진으로 **crawl4ai**를 사용합니다.
- 로컬 웹 브라우저 기반으로 동작하므로 별도 서버 배포가 필요하지 않습니다.

### 2. 정보 대시보드
- 크롤링된 정보를 정렬·분류하여 한눈에 볼 수 있게 시각화합니다.
- 등록된 URL 목록과 각 사이트의 수집 상태를 표시합니다.

### 3. 새 소식 알림
- 이미 크롤링한 사이트에서 새로운 콘텐츠가 감지되면 사용자에게 알립니다.
- 변경 감지는 주기적 재크롤링을 통해 이루어집니다.

### 4. RAG 챗봇
- 크롤링된 데이터를 벡터화하여 RAG(Retrieval-Augmented Generation) 파이프라인을 구성합니다.
- 사용자가 자연어로 질문하면 관련 정보를 크롤링 데이터에서 찾아 답변합니다.
- LLM은 **Ollama** (로컬 LLM)를 사용합니다.

---

## 기술 스택

| 역할 | 기술 |
|---|---|
| 프론트엔드 | Next.js |
| 백엔드 API | FastAPI (Python) |
| 크롤링 | [crawl4ai](https://github.com/unclecode/crawl4ai) |
| 로컬 LLM / 임베딩 | [Ollama](https://ollama.com) |
| 브라우징 | 로컬 웹 브라우저 (Playwright 기반) |
| 벡터 DB | 미정 |

---

## 실행 방법

### 프론트엔드 (Next.js)
```bash
cd frontend
npm install
npm run dev
```

### 백엔드 (FastAPI)
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

---

## 아키텍처

```
사용자 입력 (URL)
      ↓
  crawl4ai 크롤링 (로컬 브라우저)
      ↓
  텍스트 파싱 및 청크 분할
      ↓
  벡터 임베딩 저장 (로컬 벡터 DB)
      ↓
  대시보드 표시 / 변경 감지 알림
      ↓
  챗봇 질의 → RAG 검색 → Ollama LLM 응답
```

---

## 제약 및 범위

- 이 서비스는 **로컬 전용**으로 동작하며 외부 클라우드 API를 사용하지 않습니다.
- 제공하는 기능은 위 4가지(크롤링, 대시보드, 알림, 챗봇)에 한정됩니다.
- 로그인, 사용자 관리, 외부 공유 등의 기능은 범위에 포함되지 않습니다.

---

## 개발 시 주의사항

- crawl4ai는 Playwright를 내부적으로 사용하므로 첫 실행 전 `playwright install` 이 필요합니다.
- Ollama는 로컬에 설치되어 있어야 하며, 사용할 모델은 사전에 `ollama pull <model>` 로 다운로드해야 합니다.
- 크롤링 대상 사이트의 `robots.txt` 및 이용약관을 반드시 확인하세요.
- 임베딩 모델도 Ollama를 통해 로컬에서 실행합니다 (예: `nomic-embed-text`).
