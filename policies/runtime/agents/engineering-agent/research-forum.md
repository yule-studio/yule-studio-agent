# Agent Research Forum (`#운영-리서치`) — v0

이 문서는 **Discord Forum 채널 `#운영-리서치`** 를 부서 에이전트의 연구·심의(deliberation) inbox로 운영하기 위한 정책 기준선이다. 본 마일스톤은 **운영 규약과 데이터 구조만** 정의하며, 실제 게시/댓글 자동화와 Obsidian export 구현은 후속 이슈에서 다룬다.

## 1. 포럼이 하는 일

운영-리서치 포럼은 단순 채팅 채널이 아니라 **에이전트 간 자료가 흐르고, 검토받고, 합의되는 inbox**다. 단계별 책임:

1. **자료 수집** — 어느 멤버 봇이든(또는 사람 운영자가) 새 자료(레퍼런스 / 도구 후보 / 리서치 노트)를 발견하면 새 forum thread 게시.
2. **역할별 검토** — 같은 thread에 멤버 봇이 자기 책임 범위로 댓글: backend-engineer는 보안/스키마 영향, product-designer는 시각 가치, qa-engineer는 회귀 위험 등.
3. **tech-lead 종합** — 댓글이 어느 정도 모이면 tech-lead가 thread 안에 `[Decision]` 댓글을 남겨 합의안과 후속 작업 배정을 명문화.
4. **Obsidian 후보 선정** — 이후 외부 노트(개인 Obsidian)에 보존할 가치가 있는 thread는 `[Obsidian]` prefix로 closing 댓글을 추가해 export 후보로 표시.

원칙
- 모든 단계가 한 thread 안에서 보관된다 (Discord Forum이 자연스럽게 thread 단위 인덱싱을 제공하므로).
- engineering-agent가 1차 운영 책임을 가지지만 **다른 부서 에이전트도 같은 포럼을 공유**한다. 그래서 env 키는 `DISCORD_ENGINEERING_*`이 아니라 `DISCORD_AGENT_RESEARCH_*`로 쓴다.

## 2. 환경변수

| 키 | 런타임 | 용도 |
|---|---|---|
| `DISCORD_AGENT_RESEARCH_FORUM_CHANNEL_ID` | 예약 (본 단계 미연결) | Forum 채널 ID. 런타임 일치 우선. |
| `DISCORD_AGENT_RESEARCH_FORUM_CHANNEL_NAME` | 예약 (본 단계 미연결) | 채널 이름 fallback (기본 `운영-리서치`). |

규약
- ID/NAME 중 하나만 매치되어도 라우팅이 동작하도록 후속 코드는 매트릭스(`discord-workflow.md` §1.1)와 동일한 패턴을 따른다.
- 본 마일스톤에서 어떤 코드 경로도 위 키를 읽지 않는다. forum publisher가 들어올 때 본 키를 진실 소스로 사용한다.

## 3. Thread 제목 prefix

새 forum post의 제목은 항상 다음 prefix 하나로 시작한다.

| Prefix | 의미 | 누가 게시 |
|---|---|---|
| `[Research]` | 사용자 흐름·시장·기술 동향 노트 | 어느 멤버 봇 / 사람 모두 |
| `[Tool]` | 도입 후보 도구·라이브러리·서비스 (장단점 정리) | tech-lead / backend-engineer / platform 멤버 |
| `[Reference]` | UI/UX/마케팅/이메일/온보딩 레퍼런스 (출처·차용·회피·재구성) | product-designer / frontend-engineer 위주 |
| `[Decision]` | 위 thread 안 합의안 + 후속 작업 배정 | **tech-lead만** thread 본문이 아닌 댓글로 게시 |
| `[Obsidian]` | 외부 노트(Obsidian)로 export 후보 마킹 | tech-lead가 thread 종료 시 댓글로 게시 |

예
- `[Research] 신규 사용자 첫 30초 이탈 원인 가설 정리`
- `[Tool] resend.com — 트랜잭션 메일 도입 후보 비교`
- `[Reference] Stripe Pricing hero 섹션 패턴 5선`
- `[Decision] 회원가입 onboarding step 2 분리안 채택` (앞 두 thread를 종합)
- `[Obsidian] Stripe Pricing 패턴 노트 export 후보`

`[Decision]`/`[Obsidian]`은 thread 본문 제목이 아니라 **기존 thread의 댓글 prefix**로 사용한다. 같은 thread 안에서 단계 추적이 가능하도록.

## 4. 댓글 형식

### 4.1 역할별 검토 댓글

각 멤버 봇이 자기 역할로 검토할 때 쓰는 표준 4줄 양식:

```
[role:<role-id>]
- 요점: <한 줄 요약>
- 영향: <시스템·사용자·일정 영향 한 줄>
- 다음 행동(권고): <옵션 1~2개>
- 신뢰도: high|medium|low (이유 한 줄)
```

규약
- `<role-id>`는 `engineering-agent/backend-engineer` 식의 정식 주소(`message-protocol.md` §2와 동일)를 쓴다.
- 4줄 모두 채운다. 정보 부족이면 `다음 행동`에 "추가 자료 요청 — <무엇>"으로 써서 thread를 멈추지 않고 다음 단계로 보낸다.

### 4.2 `[Decision]` 댓글 (tech-lead)

```
[Decision] <합의안 한 줄>
- 채택 근거: <thread 안 어느 댓글들을 종합했는지 짧게>
- 후속 작업:
  1. <역할/주소> — <action> — <due 또는 트리거>
  2. ...
- 보류 항목: <지금 결정하지 않고 다음 thread로 미루는 것>
- write_required: yes|no  (yes면 workflow.intake와 승인 게이트가 필요)
```

`[Decision]`이 게시된 시점 이후 thread는 read-mostly로 본다. 추가 검토가 필요하면 새 thread를 연다.

### 4.3 `[Obsidian]` 댓글

```
[Obsidian] <export 제목>
- 출처 thread: <Discord thread URL 또는 thread_id>
- 보존 이유: <왜 외부 노트로 옮길 가치가 있는지>
- 태그(권장): #research / #tool / #reference / #decision 중 하나 이상
- export contract 버전: v0
```

본 댓글이 달린 thread만 향후 Obsidian export 후보로 잡는다. export 자동화는 후속 이슈에서 본 contract를 그대로 입력으로 사용한다.

## 5. Obsidian Export Contract (v0, 예약)

본 단계에서는 export 코드를 작성하지 않는다. 다만 후속 코드가 입력으로 사용할 thread→note 변환 규약을 미리 고정한다.

### 5.1 입력 (한 thread당)
- thread 제목 (`[Research]/[Tool]/[Reference]` 중 하나로 시작)
- thread 본문 (게시자, 본문, 첨부 링크)
- 댓글 시퀀스 (역할별 검토 4줄 양식 + `[Decision]` + `[Obsidian]`)

### 5.2 출력 (Obsidian markdown 1개)
```
---
title: <[Obsidian] 댓글의 제목>
source: <discord thread URL>
created: <thread 게시 시각 (ISO)>
decided: <[Decision] 댓글 시각 (ISO)>
exported: <export 시각 (ISO)>
tags: [research|tool|reference, decision?]
roles: [list of role-ids that commented]
contract: research-forum-export/v0
---

## 요약
<[Decision] 댓글의 합의안 한 줄>

## 검토 요약
- backend-engineer: <요점>
- product-designer: <요점>
- ...

## 후속 작업
1. <역할> — <action> — <due/트리거>

## 원본 자료
- <thread 본문 본문 링크/요약>
- <첨부 링크들>
```

규약
- 파일명은 `YYYY-MM-DD_<제목 slug>.md` 권장.
- `contract` 필드는 export 포맷 버전. 본 문서가 v0를 정의한다.
- export는 항상 멱등이어야 한다 — 같은 thread를 다시 export해도 같은 파일을 덮어쓰는 형태.

## 6. 다른 채널과의 관계

| 채널 | 본 forum과의 관계 |
|---|---|
| `#업무-접수` | thread의 `[Decision]`이 `write_required=yes`면 운영자가 그 합의안을 그대로 `/engineer_intake`에 넘긴다. forum이 작업 origin, 업무-접수가 작업 입구. |
| `#승인-대기` | forum thread에서 결정된 write 작업이 workflow의 승인 단계로 갈 때 미러링 대상 (예약). |
| `#봇-상태` | forum publisher 자체의 게시 실패/지연을 broadcast (예약). |
| `#실험실` | forum 게시 자동화 dry-run/실험 (예약). |

## 7. 변경 절차

- prefix 5종(`[Research]`/`[Tool]`/`[Reference]`/`[Decision]`/`[Obsidian]`) 추가/축소는 본 문서를 먼저 갱신한다.
- 댓글 양식(4줄/Decision/Obsidian)을 바꾸면 export contract v0가 영향을 받는다 — contract 버전을 같이 올리고 후속 export 코드의 호환 처리를 메모로 남긴다.
- env 키 이름은 부서 비종속(`DISCORD_AGENT_RESEARCH_*`)을 유지한다. engineering 전용 prefix로 좁히면 다른 부서가 같은 forum을 공유할 수 없다.

## 8. 후속 작업

1. forum publisher 코드 — env 키 활성화 후 멤버 봇이 thread를 만들고 댓글을 다는 진입점.
2. `[Decision]` 댓글 → `workflow.intake` 자동 연결 (Forum-driven intake).
3. Obsidian export — 본 §5의 contract를 그대로 입력으로 사용.
4. forum thread 검색 인덱서 — 본 thread의 자료가 dispatcher의 reference 추천에 다시 흘러 들어가도록.
