# Engineering Agent Team Conversation (v0, sequential MVP)

이 문서는 engineering-agent member 봇들이 같은 Discord thread 안에서 **순차 발화**하도록 하는 MVP의 정책 기준선이다. 코드 진실 소스는 `src/yule_orchestrator/discord/engineering_team_runtime.py` 와 `member_bot.py`. 자유 토론 / 다회 ping-pong 은 본 마일스톤 범위 밖이다.

## 1. 범위

- **포함**: thread 안에서 `tech-lead → product-designer → backend-engineer / frontend-engineer → qa-engineer` 처럼 dispatcher가 정한 `role_sequence`를 한 번씩 발화한다.
- **포함**: 각 발화는 세션 메타데이터(분류, 실행자, 승인 상태, reference)를 반영한 1차 요약이다. 실제 runner(claude/gemini/codex/ollama)를 깊게 호출하지 않는다.
- **제외**: 자유 토론, 역할 간 자율 reply, 사용자와의 직접 대화. 이 단계의 member 봇은 dispatch 마커가 본인을 지목할 때만 발화한다.

## 2. 사전 조건

- `WorkflowSession` 이 다음을 채워야 한다:
  - `thread_id` (게이트웨이가 thread를 만든 뒤 세션에 기입; D 마일스톤에서 wiring).
  - `role_sequence` (dispatcher가 채움).
  - `executor_role` (단일 실행자, dispatcher 결정).
- 각 역할의 토큰(`ENGINEERING_AGENT_BOT_<ROLE>_TOKEN`)이 활성화되어 member 봇이 기동되어 있어야 한다 (`multi-bot-launcher.md` §2 참조). 비활성 토큰은 해당 역할의 발화를 건너뛰고 chain이 끊긴다 — 운영자가 다음 directive 를 수동으로 다시 발사해 복구한다.

## 3. Dispatch 프로토콜

발화 chain 은 thread 안 메시지 본문에 다음 마커를 포함하는 방식으로 흘러간다:

```
[team-turn:<session_id> <role>]
```

- `<session_id>` 는 `WorkflowSession.session_id` 12자 hex.
- `<role>` 는 `tech-lead` / `product-designer` / `frontend-engineer` / `backend-engineer` / `qa-engineer` 중 하나. 없으면 plan 의 첫 역할(보통 `tech-lead`)이 응답한다 — kickoff 1회용.
- 정규식: `\[team-turn:(?P<sid>[A-Za-z0-9_\-]+)(?:\s+(?P<role>[A-Za-z0-9_\-]+))?\]` (`engineering_team_runtime.DISPATCH_MARKER_RE`).

흐름:

1. 게이트웨이가 thread 를 만들고 `kickoff_directive(session)` 결과를 thread 에 게시한다 (예: `[team-turn:abc123 tech-lead]`).
2. tech-lead 봇의 `on_message` 가 마커를 감지 → `engineering_team_runtime.handle_team_turn_message` 호출 → 본인의 발화 + 다음 role 의 directive 를 한 메시지로 thread 에 게시.
3. 다음 봇이 동일하게 동작. 마지막 role 은 directive 를 붙이지 않고 `closing_message(session)` 을 덧붙여 chain 을 닫는다.
4. 게이트웨이는 각 발화 직후 `mark_turn_played(session, role)` 으로 세션 상태를 갱신한다 — 봇이 같은 thread 에 두 번 발화하지 못하도록 막는 단일 진실 소스.

## 4. 메시지 포맷

각 turn 메시지 본문:

```
**[<role>]** <header>
<body>
[team-turn:<session_id> <next-role>]   ← 마지막 turn 이면 생략
```

- `header` 는 역할별 한 줄 인사 (`engineering_team_runtime._ROLE_HEADERS`).
- `body` 는 task_type / executor / write_blocked / reference 4가지를 짧게 요약한 1차 의견. 영문 약어와 한국어를 섞어도 좋지만 한 turn 당 4줄을 넘지 않는다.
- 사용자 멘션은 사용하지 않는다. role 식별은 `**[role]**` 헤더로만 한다.

기본 템플릿이 다루는 역할: `tech-lead`, `product-designer`, `frontend-engineer`, `backend-engineer`, `qa-engineer`. 그 외는 generic 템플릿으로 fallback (역할 이름이 본문에 그대로 노출).

## 5. 실패 모드 / 운영 가이드

| 증상 | 원인 후보 | 대응 |
|---|---|---|
| chain 이 도중에 멈춤 | 다음 role 봇이 비활성(토큰 미발급) | 운영자가 thread 에 `[team-turn:<sid> <next-role>]` 를 직접 게시하거나, `--dry-run` 으로 활성 상태 확인 |
| 동일 role 이 두 번 발화 | `mark_turn_played` 가 호출되지 않음 (게이트웨이 wiring 누락) | 게이트웨이 hook 점검; 재현되면 `extra.team_conversation.played_roles` 수동 보정 |
| kickoff 마커에 role 미지정 시 여러 봇이 동시 답변 | role-less 마커는 plan 에 든 모든 활성 봇이 응답 가능 | 운영 규약: 게이트웨이는 항상 role 지정 directive 를 게시한다 (`kickoff_directive` 가 자동으로 해줌) |
| thread 가 없는 세션에 chain 시도 | dispatcher 만 끝나고 thread 가 아직 생성되지 않은 상태 | `build_turn_plan` 이 `ValueError` 로 차단; 게이트웨이가 thread 생성 → `session.thread_id` 기입 후 재시도 |

## 6. 다음 마일스톤

1. **자유 회신** — 각 role 이 다른 role 의 발화에 멘션 응답. 본 MVP 완료 후 도입.
2. **runner 통합** — turn 본문을 templated 문자열 대신 실제 runner 출력(요약 1단락)으로 교체. role × runner 매트릭스는 `role-weights-v0.md`.
3. **재진입** — 같은 thread 에 review 피드백이 들어오면 `played_roles` 를 reset 하고 chain 재시작 (review-loop.md 와 합치기).
4. **IPC** — 현재는 Discord 본문에 마커를 박아 흐르지만, 같은 호스트 안에서 zmq/queue 로 직접 dispatch 하는 채널을 추가해 latency 개선.

## 7. 참고

- 코드 진실 소스: `src/yule_orchestrator/discord/engineering_team_runtime.py` (TeamTurn / TeamTurnOutcome / handle_team_turn_message).
- 테스트: `tests/test_engineering_team_runtime.py`.
- 관련 정책: `discord-workflow.md` §7, `multi-bot-launcher.md` §1, `dispatcher.md` (role_sequence/executor_role 결정).
