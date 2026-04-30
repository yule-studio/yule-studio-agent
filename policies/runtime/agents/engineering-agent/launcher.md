# Discord Launcher (`yule discord up`)

planning-bot, engineering-agent gateway, engineering-agent member 봇을 한 번에 띄우는 supervisor 진입점. 운영자가 봇을 하나씩 수동으로 켜지 않아도 되게 만드는 MVP.

## 사용

```bash
# 활성/비활성 봇 목록만 확인 (Discord 연결 없음)
yule discord up --dry-run

# 실제 실행
yule discord up

# 다른 부서 에이전트도 한 번에 (예: 추후 marketing-agent 등이 추가될 때)
yule discord up --agents engineering-agent,marketing-agent
```

`--agents` 미지정 시 기본은 `engineering-agent` 하나입니다. planning-bot은 부서 에이전트와 무관하게 항상 inventory에 포함됩니다.

## Inventory 산출 규칙

`build_inventory(repo_root, agent_ids=...)`가 다음 순서로 봇 목록을 만듭니다.

1. **planning-bot** — `DISCORD_BOT_TOKEN` 환경변수 사용. `discord/bot.py:run_discord_bot`로 실행.
2. **부서 에이전트별로 (입력 순서대로):**
   - **gateway** 봇 — `<AGENT>_BOT_GATEWAY_TOKEN`
   - **각 멤버** 봇 — `<AGENT>_BOT_<ROLE>_TOKEN` (`agent.json`의 `members` 순서 그대로)

각 봇은 토큰 유무에 따라 다음 상태:

- 토큰 있음 → `active`
- 토큰 없음/공백 → `skipped (token missing)`

## 출력 양식

```
discord launcher inventory:
  - planning-bot: active [DISCORD_BOT_TOKEN]
  - engineering-agent (gateway): active [ENGINEERING_AGENT_BOT_GATEWAY_TOKEN]
  - engineering-agent/tech-lead: skipped (token missing) [ENGINEERING_AGENT_BOT_TECH_LEAD_TOKEN]
  - engineering-agent/backend-engineer: skipped (token missing) [ENGINEERING_AGENT_BOT_BACKEND_ENGINEER_TOKEN]
  ...
summary: 2 active / 5 skipped
```

`--dry-run`일 때는 위 inventory만 출력하고 즉시 0으로 종료합니다.

실제 실행 시에는 inventory 출력 후 active 봇별로 `started: <bot_id>` / 실패 시 `failed: <bot_id> — <error>` / skip된 봇은 `skipped: <bot_id> (...)`를 stderr로 추가 출력합니다.

## 종료 코드

| 코드 | 의미 |
| --- | --- |
| `0` | dry-run 성공, 또는 실 실행에서 최소 한 봇이 시작됨 |
| `2` | 모든 봇이 토큰 부재로 `skipped` |
| `3` | 시작한 봇이 하나도 없고 spawn 단계에서 예외가 발생함 |

## 프로세스 관리 방식 (MVP)

- 봇 한 개당 별도 `multiprocessing.Process` 한 개를 띄웁니다.
- 자식 프로세스는 `fork`/`spawn` 시점의 부모 환경변수를 그대로 상속받습니다 — 토큰을 부모가 갖고 있어야 합니다.
- 자식 프로세스가 죽어도 supervisor 부모 프로세스는 그대로 살아 있습니다 (자동 재기동은 후속 마일스톤).
- 부모 종료 시 자식 종료 보장은 추후 보강 — 현재는 자식이 데몬이 아니므로 명시적 `kill`이 필요할 수 있습니다.

운영 권고: tmux/launchd/systemd 같은 외부 supervisor 아래에서 본 명령을 돌리는 것을 가정합니다.

## 건드리지 않은 것

- `discord/bot.py`, `discord/member_bot.py`, `discord/commands.py`, `agents/workflow.py`는 그대로 유지합니다.
- supervisor는 위 모듈의 공개 진입점만 호출합니다.
- planning-bot 단독 실행 경로(`yule discord bot`)와 단일 멤버 실행 경로(`yule discord member --role`)도 그대로 유지됩니다 — 이 launcher는 추가 진입점이지 대체가 아닙니다.

## 후속 마일스톤

- 자식 프로세스 재기동 정책 (백오프 포함).
- 부모 종료 시 SIGTERM 전파 보장.
- 봇별 stdout/stderr 분리 로그 라우팅.
- 헬스체크 엔드포인트 (`#봇-상태` 채널 자동 갱신).
- planning과 engineering-agent를 동일 토큰으로 띄울 때의 충돌 가드 (현재 토큰 단위로 1 프로세스 가정).

## Discord 채널 운영 원칙

`yule discord up`이 띄우는 봇들은 다음 채널 분담을 따릅니다 (운영자/사용자 모두 같은 약속을 사용).

| 채널 | 역할 | 사용 키 |
|---|---|---|
| `#일정-관리` (기존 CONVERSATION) | planning-bot 자유 대화 | `DISCORD_CONVERSATION_CHANNEL_*` |
| `#업무-접수` | engineering-agent 자유 대화 + 작업 접수 | `DISCORD_ENGINEERING_INTAKE_CHANNEL_*` (런타임 활성) |
| `#승인-대기` | write 승인 UX | `DISCORD_ENGINEERING_APPROVAL_CHANNEL_*` (예약) |
| `#봇-상태` | 상태/오류/헬스체크 | `DISCORD_ENGINEERING_STATUS_CHANNEL_*` (예약) |
| `#실험실` | 워크플로·프롬프트 테스트 | `DISCORD_ENGINEERING_LAB_CHANNEL_*` (예약) |
| `#운영-리서치` (Forum) | 부서 공통 research/deliberation inbox (자료 수집·역할별 검토·tech-lead 종합·Obsidian 후보 선정) | `DISCORD_AGENT_RESEARCH_FORUM_CHANNEL_*` (예약) |

규약
- planning-bot과 engineering-agent gateway는 **다른 채널을 본다**. 같은 채널을 보면 두 봇이 동일 메시지에 응답하므로 분리 운영을 강제한다.
- intake 채널 외 4종은 본 마일스톤에서 키 슬롯만 예약했다. 후속 운영 자동화가 들어올 때 본 표를 진실 소스로 사용한다.
- 운영-리서치 forum은 engineering 전용이 아니라 부서 공통 inbox이므로 키 prefix가 `DISCORD_AGENT_RESEARCH_*`다. 게시 규약과 댓글 양식, Obsidian export contract는 `research-forum.md` 참조.
- 채널 정의의 자세한 매트릭스는 `discord-workflow.md` §1.1을 참고한다.
