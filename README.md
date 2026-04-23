# Yule Studio Agent

Yule Studio Agent는 개인 홈서버에서 여러 AI 에이전트와 개발 도구를 조율하기 위한 오케스트레이터입니다.

GitHub 이슈, 일정 데이터, 에이전트 정책, 실행 흐름을 하나의 작업 체계로 연결해 개인 비서이자 개인 개발팀처럼 운영하는 것을 목표로 합니다.

## 현재 포함된 기능

- 에이전트 컨텍스트 로드
- 로컬 실행 환경 점검(`doctor`)
- GitHub의 열린 이슈 읽기
- Naver CalDAV 일정/할 일 읽기 및 구조화된 데이터(JSON) 변환
- Planning Agent 기반 daily plan 생성
- 시간 블록 브리핑과 체크포인트 생성
- Discord 슬래시 명령 기반 최소 봇 실행

## 디렉토리 구조

```text
.
├── AGENTS.md
├── CLAUDE.md
├── GEMINI.md
├── README.md
├── agents/
│   ├── coding-agent/
│   │   ├── CLAUDE.md
│   │   └── agent.json
│   └── planning-agent/
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
        ├── discord/
        ├── integrations/
        └── planning/
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
- 기존 `.env.local`이 있으면 덮어쓰지 않고, `.env.example` 대비 빠진 키만 안내

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
# NAVER_CALDAV_CACHE_SECONDS=300
# NAVER_CALDAV_INCLUDE_ALL_TODOS=false
YULE_NAVER_CATEGORY_POLICY_FILE=policies/runtime/agents/planning-agent/naver-category-policy.json
# YULE_WAKE_TIME=06:00
# YULE_WORK_START_TIME=09:00
# YULE_COMMUTE_MINUTES=45
# YULE_DEPARTURE_BUFFER_MINUTES=10
# YULE_HOME_AREA=신정동
# YULE_WORK_AREA=마곡

DISCORD_BOT_TOKEN=
# DISCORD_APPLICATION_ID=
DISCORD_GUILD_ID=
# DISCORD_DAILY_CHANNEL_ID=
# DISCORD_CHECKPOINT_CHANNEL_ID=
# DISCORD_NOTIFY_USER_ID=
# DISCORD_DAILY_BRIEFING_TIME=06:00
# DISCORD_CHECKPOINT_PREFETCH_MINUTES=5

# GITHUB_ISSUES_CACHE_SECONDS=300
```

- 실제 값은 `.env.local`에 넣습니다.
- 예시는 `.env.example`에 둡니다.
- `.env.local`은 Git에 올리지 않습니다.
- `./scripts/bootstrap`은 기존 `.env.local`을 덮어쓰지 않습니다. 새 설정 키가 추가되면 빠진 키만 알려줍니다.
- 응답이 오래 걸리면 `NAVER_CALDAV_TIMEOUT_SECONDS`로 요청 타임아웃을 조절할 수 있습니다.
- `NAVER_CALDAV_CACHE_SECONDS`를 지정하면 해당 TTL을 우선 사용합니다.
- 값을 지정하지 않으면 오늘이 포함된 범위는 5분, 미래 범위는 30분, 과거 범위는 24시간 동안 SQLite 로컬 캐시를 재사용합니다.
- 캐시 저장소 기본 위치는 `.cache/yule/cache.sqlite3`입니다.
- 원격 fetch가 `network`, `query`, `unknown` 성격의 오류로 실패하면 오래된 stale cache를 임시 fallback 으로 사용할 수 있습니다.
- 같은 SQLite 안에 캘린더 항목 상태(`calendar_item_states`)도 함께 동기화합니다.
- `YULE_NAVER_CATEGORY_POLICY_FILE`로 네이버 범주 색상별 Planning 우선순위 정책을 지정할 수 있습니다.
- `YULE_WAKE_TIME`, `YULE_WORK_START_TIME`, `YULE_COMMUTE_MINUTES`, `YULE_DEPARTURE_BUFFER_MINUTES`로 아침 브리핑의 기상/출발/업무 시작 기준을 조정할 수 있습니다.
- `YULE_HOME_AREA`, `YULE_WORK_AREA`는 아침 브리핑 문구에 사용하는 출발/도착 지역 이름입니다.
- 기본 동작은 요청한 날짜 범위 안의 일정과 할 일만 읽습니다.
- 할 일 캘린더는 전체 캘린더 목록에서 `할 일`, `todo`, `task`가 들어간 이름을 자동 탐지합니다.
- 자동 탐지된 할 일 캘린더가 여러 개일 때는 `NAVER_CALDAV_TODO_CALENDAR` 설정을 우선합니다.
- 자동 탐지 결과가 없으면 일반 일정 조회 대상 캘린더를 기준으로 fallback 합니다.
- `NAVER_CALDAV_INCLUDE_ALL_TODOS=true`는 서버가 날짜 범위 검색으로 할 일을 제대로 주지 않을 때만 사용하는 느린 마지막 보강 옵션입니다.
- `NAVER_CALDAV_INCLUDE_ALL_TODOS=true`를 써도 같은 범위 재실행은 캐시 덕분에 더 빠르게 응답할 수 있습니다.
- 캐시를 무시하고 새로 가져오려면 `--force-refresh`를 사용합니다.
- Discord Bot 실행에는 `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`가 필요합니다.
- `DISCORD_APPLICATION_ID`는 선택값입니다. 비워두면 토큰 기준으로 실제 Discord 애플리케이션 ID를 자동 사용합니다.
- `DISCORD_DAILY_CHANNEL_ID`와 `DISCORD_DAILY_BRIEFING_TIME`을 함께 넣으면 봇이 살아 있는 동안 매일 해당 시각에 자동 브리핑을 보냅니다.
- `DISCORD_NOTIFY_USER_ID`를 넣으면 브리핑과 체크포인트 메시지 앞에 해당 사용자 멘션을 붙입니다.
- 슬래시 명령 동기화를 빠르게 하기 위해 현재 최소 봇은 guild 단위 명령 등록을 사용합니다.
- `GITHUB_ISSUES_CACHE_SECONDS`를 지정하면 GitHub open issue 조회 결과를 해당 TTL 동안 재사용합니다. 기본값은 300초입니다.

## 실행

```bash
yule doctor
yule context coding-agent
yule context planning-agent
yule github issues --limit 30
yule calendar events --json
yule calendar sync --force-refresh --json
yule calendar categories --json
yule calendar cache inspect --json
yule calendar cache cleanup --json
yule planning daily --json
yule planning checkpoints --at 2026-04-22T09:50:00+09:00 --json
yule discord bot
```

로컬 환경에 따라 엔트리포인트 설치가 덜 맞물려 있을 때는 아래처럼 모듈 실행 방식으로 동일하게 사용할 수 있습니다.

```bash
PYTHONPATH=src python3 -m yule_orchestrator doctor
PYTHONPATH=src python3 -m yule_orchestrator context planning-agent
PYTHONPATH=src python3 -m yule_orchestrator calendar events --json
PYTHONPATH=src python3 -m yule_orchestrator calendar sync --json
PYTHONPATH=src python3 -m yule_orchestrator calendar cache cleanup --json
PYTHONPATH=src python3 -m yule_orchestrator planning daily --json
PYTHONPATH=src python3 -m yule_orchestrator discord bot
```

기간을 지정해서 일정 데이터를 읽을 수도 있습니다.

```bash
yule calendar events --start-date 2026-04-21 --end-date 2026-04-25 --json
```

## 캘린더 연동 메모

- 현재는 Naver CalDAV를 통해 일정 이벤트(`VEVENT`)와 CalDAV로 노출되는 할 일(`VTODO`)을 함께 읽습니다.
- 네이버 웹 화면의 할 일이 항상 CalDAV `VTODO`로 제공되는지는 계정 상태와 클라이언트 설정에 따라 달라질 수 있습니다.
- `todo_count`가 0이면 현재 CalDAV 응답에 할 일이 포함되지 않았을 가능성이 큽니다.
- `VTODO`는 기본적으로 지정한 기간 안에 해당하는 항목만 출력합니다.
- `yule calendar events --json` 실행 중 실패가 발생하면 `error.code`, `error.category`, `retryable`, `manual_action_required`, `alert_recommended`를 포함한 구조화된 에러 JSON을 반환합니다.
- 현재 에러 분류는 `configuration`, `validation`, `authentication`, `network`, `query`, `parsing`, `dependency`, `unknown` 범주를 사용합니다.
- `retry_strategy`는 `none` 또는 `backoff`를 사용하며, 이후 Planning Agent / Discord 알림 흐름에서 그대로 재사용할 수 있습니다.
- 세부 운영 기준은 [policies/runtime/common/calendar-error-handling.md](policies/runtime/common/calendar-error-handling.md)에 정리합니다.
- 같은 날짜 범위와 같은 캘린더 설정 요청은 SQLite 캐시를 재사용합니다.
- stale cache는 기본적으로 만료 후 7일 동안 남겨두고, `yule calendar cache cleanup`에서 정리합니다.
- 이 캐시 구조는 이후 daily-plan, Planning Agent, Discord 브리핑이 같은 저장소를 재사용할 수 있도록 설계되었습니다.
- 조회 결과를 동기화할 때 일정/할 일 항목 단위 상태를 upsert 하므로, 이후 완료 여부 변화와 최근 본 항목을 기준으로 다음 작업 추천 로직을 붙일 수 있습니다.
- `yule calendar sync`는 원격 캘린더를 읽어 캐시와 상태 DB를 채우는 운영용 명령입니다.
- `yule calendar categories`는 상태 DB에 저장된 `category_color` 숫자 코드와 항목을 보여줍니다.
- 범주 색상 정책은 [policies/runtime/agents/planning-agent/naver-category-policy.md](policies/runtime/agents/planning-agent/naver-category-policy.md)에 정리합니다.
- Discord 봇을 오래 켜둘 때는 먼저 `yule calendar sync`로 상태 DB를 채워두면, Planning Agent가 원격 조회보다 로컬 상태를 우선 사용합니다.

## Planning Agent

- `agents/planning-agent/agent.json`과 `agents/planning-agent/CLAUDE.md`를 추가했습니다.
- Planning Agent는 캘린더 일정, 캘린더 할 일, GitHub open issue, reminder JSON을 받아 daily plan을 만듭니다.
- 현재 버전은 설명 가능한 규칙 기반 우선순위, 추천 시간 블록, 이벤트 설명 기반 세부 실행 블록, 5분 전 체크포인트 생성에 집중합니다.
- 기본 출력은 짧은 `discord_briefing`과 상세한 `morning_briefing`, `time_block_briefings`, `checkpoints`를 함께 제공합니다.
- 아침 브리핑은 기상, 출근 준비, 권장 출발 시간, 업무 시작 시간을 구분해서 안내합니다.
- 추천 집중 작업은 기본적으로 `YULE_WORK_START_TIME` 이후 시간대에 배치합니다.
- 일정 이벤트가 없으면 전체 일정 작성 안내를 포함합니다.
- 설명이 있는 일정 이벤트는 시작 10분 전에 다음 일정으로 전환하는 재브리핑 체크포인트를 생성합니다.
- 설명이 비어 있는 일정 이벤트는 시작 10분 전에 세부 계획 작성 체크포인트를 생성합니다.

```bash
yule planning daily --json
yule planning daily --date 2026-04-22 --github-limit 10
yule planning daily --reminders-file reminders.json --json
yule planning daily --use-ollama --json
yule planning checkpoints --at 2026-04-22T09:50:00+09:00 --json
```

이벤트 설명에 아래처럼 세부 시간표를 적으면 Planning Agent가 실행 블록과 체크포인트를 생성합니다.

```text
- 9시 ~ 10시 : 할일 목록 정리
- 10 ~ 1시 : 업무 수행 (회의 없음)
```

기본적으로 각 세부 블록이 끝나기 5분 전에 체크포인트를 만들며, `--reminder-lead-minutes`로 조절할 수 있습니다.

실제 알림 전송 전에, 지금 시각 기준으로 곧 울려야 하는 체크포인트만 뽑아내는 명령도 사용할 수 있습니다.

```bash
yule planning checkpoints --at 2026-04-22T09:50:00+09:00 --window-minutes 10 --json
```

## Discord Bot

- 최소 Discord Bot은 `yule discord bot`으로 실행합니다.
- 현재 MVP 명령은 `/ping`, `/plan_today`, `/checkpoints_now` 입니다.
- `/plan_today`는 Planning Agent 결과를 Discord 메시지로 정리해 보여줍니다.
- `/checkpoints_now`는 지금 시각 기준으로 다가오는 체크포인트를 빠르게 확인할 때 사용합니다.
- `--use-ollama`와 같은 세부 옵션은 아직 slash command 전체에 다 노출하지 않았고, 먼저 안정적인 최소 흐름에 집중한 상태입니다.

```bash
yule discord bot
```

아침 브리핑 운영 흐름은 아래 순서를 권장합니다.

```bash
yule calendar sync --json
yule planning daily --json
yule discord bot
```

## 테스트

기본 자동 테스트는 표준 라이브러리 `unittest`로 실행합니다.

```bash
python3 -m unittest discover -s tests -t .
```

## 로컬 전용 파일

아래 파일과 폴더는 로컬 실행 상태이거나 민감 정보가 포함될 수 있으므로 Git에 올리지 않습니다.

```text
.claude/
.codex/
.gemini/
.env
.env.local
.venv/
.cache/
runs/*
*.egg-info/
```

`src/yule_studio_agent.egg-info/`는 로그인 정보가 아니라 Python 패키지 설치 과정에서 생성되는 메타데이터입니다.
