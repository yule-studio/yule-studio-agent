# Yule Studio Agent

Yule Studio Agent는 개인 홈서버에서 여러 AI 에이전트와 개발 도구를 조율하기 위한 오케스트레이터입니다.

GitHub 이슈, 일정 데이터, 에이전트 정책, 실행 흐름을 하나의 작업 체계로 연결해 개인 비서이자 개인 개발팀처럼 운영하는 것을 목표로 합니다.

## 현재 포함된 기능

- 에이전트 컨텍스트 로드
- 로컬 실행 환경 점검(`doctor`)
- GitHub의 열린 이슈 읽기
- Naver CalDAV 일정/할 일 읽기 및 구조화된 데이터(JSON) 변환

## 디렉토리 구조

```text
.
├── AGENTS.md
├── CLAUDE.md
├── GEMINI.md
├── README.md
├── agents/
│   └── coding-agent/
│       ├── CLAUDE.md
│       └── agent.json
├── policies/
│   ├── reference/
│   └── runtime/
├── scripts/
│   └── bootstrap
└── src/
    └── yule_orchestrator/
        ├── cli/
        ├── core/
        ├── diagnostics/
        └── integrations/
```

## 설치

### 빠른 설치

macOS + Homebrew 기준:

```bash
./scripts/bootstrap
```

이 스크립트는 아래 작업을 수행합니다.

- Homebrew 확인
- `gh`와 Python 확인
- `.venv` 생성
- `pip`, `setuptools`, `wheel` 업그레이드
- 프로젝트 editable install
- `.env.example`이 있으면 `.env.local` 템플릿 생성

선택 AI CLI까지 함께 설치하려면:

```bash
./scripts/bootstrap --all
```

### 수동 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
```

## 수동 인증

아래 로그인은 자동화하지 않습니다.

```bash
gh auth login
claude
codex
gemini
copilot
```

Ollama는 필요할 때 실행합니다.

```bash
open -a Ollama
# 또는
ollama serve
```

## 환경 변수

캘린더 연동은 루트의 `.env.local`에 값을 넣어 사용합니다.

```bash
NAVER_CALDAV_URL=https://caldav.calendar.naver.com
NAVER_ID=
NAVER_APP_PASSWORD=
# NAVER_CALDAV_CALENDAR=
# NAVER_CALDAV_TODO_CALENDAR=내 할 일
# NAVER_CALDAV_TIMEOUT_SECONDS=15
# NAVER_CALDAV_INCLUDE_ALL_TODOS=false
```

- 실제 값은 `.env.local`에 넣습니다.
- 예시는 `.env.example`에 둡니다.
- `.env.local`은 Git에 올리지 않습니다.
- 응답이 오래 걸리면 `NAVER_CALDAV_TIMEOUT_SECONDS`로 요청 타임아웃을 조절할 수 있습니다.
- 기본 동작은 요청한 날짜 범위 안의 일정과 할 일만 읽습니다.
- 할 일 캘린더는 전체 캘린더 목록에서 `할 일`, `todo`, `task`가 들어간 이름을 자동 탐지합니다.
- 자동 탐지된 할 일 캘린더가 여러 개일 때는 `NAVER_CALDAV_TODO_CALENDAR` 설정을 우선합니다.
- 자동 탐지 결과가 없으면 일반 일정 조회 대상 캘린더를 기준으로 fallback 합니다.
- `NAVER_CALDAV_INCLUDE_ALL_TODOS=true`는 서버가 날짜 범위 검색으로 할 일을 제대로 주지 않을 때만 사용하는 느린 마지막 보강 옵션입니다.

## 실행

```bash
yule doctor
yule context coding-agent
yule github issues --limit 30
yule calendar events --json
```

기간을 지정해서 일정 데이터를 읽을 수도 있습니다.

```bash
yule calendar events --start-date 2026-04-21 --end-date 2026-04-25 --json
```

설치 전에 바로 실행해야 하면:

```bash
PYTHONPATH=src python3 -m yule_orchestrator doctor
```

## 캘린더 연동 메모

- 현재는 Naver CalDAV를 통해 일정 이벤트(`VEVENT`)와 CalDAV로 노출되는 할 일(`VTODO`)을 함께 읽습니다.
- 네이버 웹 화면의 할 일이 항상 CalDAV `VTODO`로 제공되는지는 계정 상태와 클라이언트 설정에 따라 달라질 수 있습니다.
- `todo_count`가 0이면 현재 CalDAV 응답에 할 일이 포함되지 않았을 가능성이 큽니다.
- `VTODO`는 기본적으로 지정한 기간 안에 해당하는 항목만 출력합니다.

## 로컬 전용 파일

아래 파일과 폴더는 로컬 실행 상태이거나 민감 정보가 포함될 수 있으므로 Git에 올리지 않습니다.

```text
.claude/
.codex/
.gemini/
.env
.env.local
.venv/
runs/*
*.egg-info/
```

`src/yule_studio_agent.egg-info/`는 로그인 정보가 아니라 Python 패키지 설치 과정에서 생성되는 메타데이터입니다.
