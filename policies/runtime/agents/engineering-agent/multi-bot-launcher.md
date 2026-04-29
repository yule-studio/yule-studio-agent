# Engineering Agent Multi-bot Launcher (v0)

이 문서는 engineering-agent의 gateway 봇과 역할(member) 봇을 Discord에서 실행하는 **operator 가이드**다. 토큰 발급·길드 초대는 사용자가 수행하고, 코드 경로(env 파싱, 런처, persona 라우팅)는 본 정책 위에서 동작한다.

## 1. 실행 모델

- **Gateway 봇** (`role=gateway`) — 외부와 대화하는 부서 대표. 채널 라우팅과 사용자 응답을 담당한다.
- **Member 봇** (`role=tech-lead`, `backend-engineer`, `frontend-engineer`, `product-designer`, `qa-engineer`) — 내부 발화 전용. 외부에 직접 답하지 않고, 게이트웨이가 분배한 작업만 수행한다.
- 각 봇은 자기 토큰으로 별도 프로세스로 기동한다 (`yule discord member`).
- 토큰이 비어 있는 멤버는 자동 비활성. 게이트웨이가 단일봇 fallback으로 그 멤버 메시지를 처리한다 (env-strategy.md §2).

## 2. 환경변수

| 키 | 역할 |
|---|---|
| `ENGINEERING_AGENT_BOT_GATEWAY_TOKEN` | 게이트웨이 봇 토큰 (외부 회신 전용 봇) |
| `ENGINEERING_AGENT_BOT_TECH_LEAD_TOKEN` | tech-lead 멤버 봇 |
| `ENGINEERING_AGENT_BOT_BACKEND_ENGINEER_TOKEN` | backend-engineer 멤버 봇 |
| `ENGINEERING_AGENT_BOT_FRONTEND_ENGINEER_TOKEN` | frontend-engineer 멤버 봇 |
| `ENGINEERING_AGENT_BOT_PRODUCT_DESIGNER_TOKEN` | product-designer 멤버 봇 |
| `ENGINEERING_AGENT_BOT_QA_ENGINEER_TOKEN` | qa-engineer 멤버 봇 |

채워진 키만 활성화된다. Phase 1 단일봇 운영 시에는 모두 비워두고 기존 `DISCORD_BOT_TOKEN`만 사용한다.

키 네이밍은 `env-strategy.md` §1 prefix 규칙을 따른다. design-agent로 분리될 때는 `DESIGN_AGENT_BOT_PRODUCT_DESIGNER_TOKEN`로 키만 옮긴다.

## 3. CLI

```bash
# Dry-run: 토큰 없이도 활성/비활성 상태와 env 키 매핑을 출력
yule discord member --agent engineering-agent --role gateway --dry-run

# 실제 기동 (해당 토큰이 채워져 있어야 함)
yule discord member --agent engineering-agent --role backend-engineer
```

옵션
- `--agent` (기본값 `engineering-agent`) — 부서 id.
- `--role` (필수) — `gateway` 또는 멤버 id.
- `--dry-run` — Discord에 접속하지 않고 활성화 요약만 출력.

## 4. 시작 로그 규약

런처는 시작 시 **한 번**, 다음 형식의 stderr 로그를 출력한다.

```
engineering-agent multi-bot summary for 'engineering-agent':
  - engineering-agent (gateway): active [ENGINEERING_AGENT_BOT_GATEWAY_TOKEN]
  - engineering-agent/tech-lead: skipped (token missing) [ENGINEERING_AGENT_BOT_TECH_LEAD_TOKEN]
  ...
```

운영자는 이 한 블록만 보고도 어떤 봇이 살아 있고 어떤 봇이 토큰 누락으로 빠졌는지 즉시 알 수 있어야 한다. 추가 로그는 디버깅 외에는 늘리지 않는다.

## 5. 에러 정책

- `--role`에 미등록 이름을 주면: `role '<name>' is not registered for engineering-agent. Available roles: gateway, tech-lead, ...`로 즉시 종료 (exit 1).
- `--role`에 등록은 됐지만 토큰이 없으면 (실기동 시): `<ENV_KEY> is required to start <agent>/<role>. Add it to .env.local before running this role bot.` (exit 1).
- `--dry-run`은 토큰이 없어도 종료하지 않는다 (검증용).

위 메시지 형식은 `env-strategy.md` §6.2와 동일하게 유지한다.

## 6. 메시지 포맷 확장 (references 슬롯)

`format_references_block(references, *, title="참고 레퍼런스", limit=5)`가 추가됐다 (`discord/formatter.py`). references 항목 키는 `title`, `source`, `url`, `takeaway`. 본 슬롯은 product-designer / 마케팅 작업이 추가될 때 임베드/메시지에 끼워 넣기 위한 자리다.

- 자동 수집기는 후속 마일스톤에서 추가한다 (env-strategy.md §7 슬롯이 채워졌을 때만 동작).
- 자동 수집이 약관상 민감한 소스(Notefolio·Behance 등)는 사용자 제공 링크로만 사용한다.
- references 인자가 비어 있으면 `format_references_block`은 빈 문자열을 반환하므로, 모든 호출자에서 안전하게 splice할 수 있다.

## 7. 사용자 개입 절차 (Phase 2 활성화)

1. Discord Developer Portal에서 멤버별 application 생성 → bot 추가 → 토큰 발급.
2. OAuth2 URL Generator로 봇을 guild에 초대. Intents: `MESSAGE CONTENT INTENT` 켜기. 권한은 최소 (`Send Messages`, `Read Message History`, `Use Slash Commands`).
3. 발급받은 토큰을 `.env.local`의 해당 `ENGINEERING_AGENT_BOT_*_TOKEN`에 붙여넣기.
4. `yule discord member --agent engineering-agent --role <name> --dry-run`으로 활성화 표시 확인.
5. `--dry-run` 빼고 실제 기동, 길드에서 봇 onlnie 상태 확인.
6. 게이트웨이도 동일 절차로 활성화하면 단일봇 fallback이 자동으로 해제된다.

## 8. 후속 작업

- 멤버 간 IPC (in-process queue → 분리 프로세스 시 socket).
- doctor 명령에 멤버 토큰별 SKIP/OK/FAIL 보고.
- references 자동 수집기 (Pinterest Trends / Meta Ad Library / TikTok Creative Center / Google Trends).
- product-designer가 design-agent로 분리될 때의 키 이전 자동화.
