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

## 6. Deliberation 확장 (`agents/deliberation.py`)

§4의 한 줄 템플릿이 thread 시작용이라면, **deliberation loop**는 같은 thread 안에서 ResearchPack과 이전 turn을 입력받아 **구조화된 역할별 take + tech-lead 종합**을 생산하는 상위 계층이다. 진실 소스: `src/yule_orchestrator/agents/deliberation.py`. 진입점은 `discord/engineering_team_runtime.deliberation_role_turn` / `synthesize_thread`.

### 6.1 역할별 take 데이터클래스

모든 role take는 공통 4-section 계약을 따른다:

- `perspective: str?` — **관점**. 이 역할이 작업을 어떻게 보는지 한 줄.
- `evidence: tuple[str, ...]` — **근거**. ResearchPack에서 본인 역할 우선 source 를 인용. 형식: `[<source_type>] <title> — <url|attachment_id> · <why_relevant>`.
- `risks: tuple[str, ...]` — **리스크**. 역할 관점에서 보이는 위험.
- `next_actions: tuple[str, ...]` — **다음 행동**. 본인 또는 실행자가 즉시 해야 할 일. previous_turns 에 따라 동적으로 추가됨 (예: backend-engineer 가 designer 의 ux_direction 을 받아 정합성 점검 항목 추가).

위 4-section 외에 역할별 구조화 필드는 다음과 같다:

| 역할 | dataclass | 역할 고유 필드 |
|---|---|---|
| tech-lead (opening) | `TechLeadOpening` | `task_breakdown`, `dependencies`, `decisions_needed`, `notes` |
| product-designer | `ProductDesignerTake` | `reference_summary`, `ux_direction`, `visual_direction` |
| backend-engineer | `BackendEngineerTake` | `data_impact`, `api_impact`, `storage_impact` |
| frontend-engineer | `FrontendEngineerTake` | `ui_components`, `state_strategy`, `user_flow` |
| qa-engineer | `QaEngineerTake` | `acceptance_criteria`, `regression_targets` |

알 수 없는 role은 generic `TechLeadOpening`-shaped take로 fallback해 호출자가 항상 무언가 렌더링할 수 있게 한다.

### 6.1.1 ResearchPack source 메타데이터

ResearchPack 안 각 `ResearchSource` 는 (`research_pack.py`) 다음 메타데이터를 표현해야 한다. 표현은 dataclass 표준 필드 + `source.extra` 자유 필드 조합으로 한다 (research_pack 모듈은 본 정책의 소유 영역이 아니므로 deliberation 측 helper `source_meta()` 가 통일된 dict 로 노출한다):

| 키 | 입력 | 비고 |
|---|---|---|
| `title` | `ResearchSource.title` | 표시명 |
| `url` 또는 `attachment_id` | `ResearchSource.source_url` 또는 첫 번째 attachment URL | URL 이 없을 때 첨부 ID 로 대체 |
| `source_type` | `ResearchSource.extra["source_type"]` (없으면 attachment kind / URL host 로 추정) | §6.1.2 카탈로그 |
| `collected_by_role` | `ResearchSource.extra["collected_by_role"]` (없으면 `author_role`) | 어떤 역할이 수집했는가 |
| `summary` | `ResearchSource.summary` | 본문 요약 |
| `why_relevant` | `ResearchSource.extra["why_relevant"]` | 왜 이 작업과 관련 있는가 |
| `risk_or_limit` | `ResearchSource.extra["risk_or_limit"]` | 자료 자체의 한계 (예: 공식 문서 v18 한정) |
| `collected_at` | `ResearchSource.posted_at` | 시점 |
| `confidence` | `ResearchSource.extra["confidence"]` | 0.0–1.0 (자동으로 clamp) |

### 6.1.2 source_type 카탈로그 (`KNOWN_SOURCE_TYPES`)

`user_message`, `url`, `web_result`, `image_reference`, `file_attachment`, `github_issue`, `github_pr`, `code_context`, `official_docs`, `community_signal`, `design_reference`.

### 6.1.3 역할별 Research Profile (`ROLE_RESEARCH_PROFILES`)

역할별로 우선 검토할 source_type 의 순서를 명시한다. `filter_pack_for_role(pack, role)` 가 이 순서대로 source 를 정렬하고, `evidence_lines_for_role` 가 이를 사용해 근거 라인을 생성한다.

| 역할 | 우선순위 (앞 3개) |
|---|---|
| tech-lead | user_message → url → official_docs |
| product-designer | image_reference → design_reference → file_attachment |
| backend-engineer | official_docs → code_context → github_pr |
| frontend-engineer | official_docs → design_reference → code_context |
| qa-engineer | github_issue → community_signal → official_docs |

profile 에 없는 source_type 도 뒤로 밀려나 표시될 뿐 숨기지는 않는다.

### 6.2 tech-lead 종합 (`TechLeadSynthesis`)

thread 마지막에 tech-lead가 게시하는 dataclass. 필드:

- `consensus: str` — 합의안 한 줄.
- `todos: tuple[str, ...]` — 각 역할 take에서 추출한 후속 작업.
- `open_research: tuple[str, ...]` — 더 조사할 것 (reference 부족·갭 자동 인지).
- `user_decisions_needed: tuple[str, ...]` — tech-lead가 명시한 결정 항목.
- `approval_required: bool` + `approval_reason: str?` — `WorkflowSession.write_requested` && 승인 전이면 yes.

### 6.3 LLM runner 주입

`run_role_deliberation(context, runner_fn=...)`가 핵심 API. *runner_fn*이 `RoleTake` 데이터클래스를 반환하면 그대로 사용하고, None을 반환하거나 예외가 발생하면 **deterministic fallback**을 사용한다. fallback 은 (a) 역할 프로필 순서로 `evidence_lines_for_role` 을 채우고 (b) `previous_turns` 의 핵심 필드 (`ux_direction`, `api_impact`, `data_impact`, `user_flow` 등) 를 인용해 next_actions 를 만든다 — 같은 thread 에서 역할들이 서로의 말을 이어받아 토의하는 모양이 외부 호출 없이도 나온다. 그래서 백엔드가 죽어도 thread는 멈추지 않는다.

```python
from yule_orchestrator.discord.engineering_team_runtime import (
    deliberation_role_turn, synthesize_thread,
)

# 한 역할의 turn (Discord member 봇이 자기 마커를 받았을 때 사용)
take, text = deliberation_role_turn(
    session,
    "engineering-agent/qa-engineer",
    research_pack=pack,
    previous_turns=collected_takes,
    runner_fn=optional_llm_callable,
)

# 모든 turn이 끝난 뒤 합의
synth, synth_text = synthesize_thread(session, all_takes, research_pack=pack)
```

### 6.3.1 표준 토의 순서와 round-trip 헬퍼

deliberation 의 표준 순서는 다음과 같으며, 비-Discord round-trip 시뮬레이션 (테스트 / replay / 디버깅) 은 `run_deliberation_loop` 한 번 호출로 끝난다:

1. **tech-lead** — 문제 정의 / 작업 분해 / 역할별 조사 지시.
2. **product-designer** — UX 흐름 / UI 시각 톤 / 이미지·디자인 reference.
3. **backend-engineer** — 데이터 / API / 저장소 / 인증·권한 / 확장성.
4. **frontend-engineer** — UI 구현 / 상태 / 접근성 / 반응형.
5. **qa-engineer** — 수용 기준 / 회귀 영향 / 위험 시나리오.
6. **tech-lead 종합** — `synthesize()` → `TechLeadSynthesis` (합의안 / 작업 배정 / 승인 필요 여부).

```python
from yule_orchestrator.discord.engineering_team_runtime import run_deliberation_loop

result = run_deliberation_loop(
    session,
    research_pack=pack,
    runner_fn=optional_llm_callable,  # None 이면 deterministic fallback
)
for record in result.turns:
    post_to_thread(record.role, record.rendered)
post_to_thread("engineering-agent/tech-lead", result.synthesis_text)
```

`deliberation_role_sequence(session)` 가 `WorkflowSession.role_sequence` 를 정규화한다 — 비어 있으면 위 1–5 default 를 사용하고, prefix 가 없는 역할에는 `engineering-agent/` 를 붙이고, tech-lead 가 빠져 있으면 맨 앞에 끼워넣는다. Discord member 봇 모드에서는 여전히 `handle_team_turn_message` 가 turn 단위로 dispatch 하지만, `run_deliberation_loop` 는 같은 입력으로 재현 가능한 진실 소스를 제공한다.

### 6.4 호환성

- 기존 `format_role_turn_text` / `build_turn_plan` / `handle_team_turn_message` 시그니처는 그대로 유지된다. deliberation 진입점은 추가 함수일 뿐 기존 sequential MVP를 깨지 않는다.
- 기존 turn 메시지를 deliberation 출력으로 교체할지 결정은 게이트웨이가 한다 — ResearchPack이 있는 세션은 deliberation, 없는 세션은 기존 templated turn.
- 4-section 필드는 모두 default 가 비어 있는 형태로 추가되었기 때문에, deliberation 데이터클래스를 직접 인스턴스화하던 기존 호출자(테스트 포함)는 그대로 동작한다.

### 6.5 Synthesis 가 자동으로 잡는 후속 항목

`synthesize(session, role_takes, research_pack=...)` 는 단순 종합이 아니라 후속 작업을 자동으로 추가한다:

- 각 role take 의 `next_actions` 항목을 `[<role>] <action>` 형태로 `todos` 에 누적.
- ResearchPack 이 비어 있거나 url 이 3건 미만이면 `open_research` 에 보강 권고 추가.
- ResearchPack 이 있더라도 *어느 역할의 profile 최우선 source_type 이 비어 있으면* `<role> 우선 자료 유형(<type>)이 비어 있음 — 보강 권장` 을 `open_research` 에 추가. 이 규칙 덕분에 디자이너 자료(이미지) 만 모인 세션이라도 백엔드 관점의 공식 문서 결손이 자동 노출된다.
- `WorkflowSession.write_requested` 가 True 이고 아직 승인 전이면 `approval_required=True`. 이유는 `write_blocked_reason` 을 그대로 사용한다 (없으면 기본 문구).

## 7. 다음 마일스톤

1. **자유 회신** — 각 role 이 다른 role 의 발화에 멘션 응답. 본 MVP 완료 후 도입.
2. **runner 통합** — turn 본문을 templated 문자열 대신 실제 runner 출력(요약 1단락)으로 교체. role × runner 매트릭스는 `role-weights-v0.md`. deliberation의 runner_fn 주입 슬롯이 통합 진입점.
3. **재진입** — 같은 thread 에 review 피드백이 들어오면 `played_roles` 를 reset 하고 chain 재시작 (review-loop.md 와 합치기).
4. **IPC** — 현재는 Discord 본문에 마커를 박아 흐르지만, 같은 호스트 안에서 zmq/queue 로 직접 dispatch 하는 채널을 추가해 latency 개선.
5. **자동 자료 수집** — 현재는 운영-리서치 forum 또는 사용자 입력으로 ResearchPack 을 채우지만, 추후 fetcher 가 source_type 별로 자동 수집하도록 확장. 자동 수집 금지 소스(Notefolio / Mobbin 등) 는 `discord-workflow.md` §4.3 참조.

## 8. 참고

- 코드 진실 소스: `src/yule_orchestrator/discord/engineering_team_runtime.py` (TeamTurn / TeamTurnOutcome / handle_team_turn_message / `run_deliberation_loop` / `deliberation_role_sequence`), `src/yule_orchestrator/agents/deliberation.py` (RoleTake / TechLeadSynthesis / source_type / filter_pack_for_role / evidence_lines_for_role / `KNOWN_SOURCE_TYPES` / `ROLE_RESEARCH_PROFILES`).
- 테스트: `tests/test_engineering_team_runtime.py`, `tests/test_engineering_deliberation.py`.
- 관련 정책: `discord-workflow.md` §7, `multi-bot-launcher.md` §1, `dispatcher.md` (role_sequence/executor_role 결정), `research-forum.md` (forum publisher).
