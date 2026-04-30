# Obsidian Memory Export — v0 contract (string-only)

이 문서는 engineering-agent의 ResearchPack/deliberation 결과를 **개인 Obsidian vault**로 내보낼 때 사용할 Markdown 구조와 path 규칙을 정의한다. 본 단계는 **문자열 생성**까지만 다루며 실제 파일 쓰기는 호출자(또는 후속 `yule obsidian sync`)가 결정한다.

코드 진실 소스: `src/yule_orchestrator/agents/obsidian_export.py`. contract 식별자: `research-forum-export/v0`.

## 1. 진입점

```python
from yule_orchestrator.agents.obsidian_export import (
    render_research_note, recommend_path,
)

note = render_research_note(
    pack,                       # ResearchPack
    session=session,            # Optional[WorkflowSession]
    synthesis=synth,            # Optional[TechLeadSynthesis]
    kind="reference",           # "research" / "decision" / "reference"
    exported_at=datetime.utcnow(),
)
# note.path.full   → "Agents/Engineering/References/2026-04-30_stripe-pricing.md"
# note.content     → frontmatter + body Markdown 문자열
# note.frontmatter → 파싱된 dict (외부 인덱서 재사용용)
```

본 모듈은 어떤 IO도 일으키지 않는다 — Discord, 네트워크, 파일시스템 모두 호출 안 함.

## 2. Vault path 규칙

| kind | folder |
|---|---|
| `research` (기본) / 미지정 | `Agents/Engineering/Research/` |
| `decision` / `decisions` | `Agents/Engineering/Decisions/` |
| `reference` / `references` | `Agents/Engineering/References/` |
| 그 외 | `Agents/Engineering/Research/` (fallback) |

- 파일명: `<YYYY-MM-DD>_<slug>.md`. 날짜는 `pack.created_at`(없으면 UTC 오늘)을 사용.
- slug는 NFC 정규화 후 `0-9A-Za-z가-힣` 외 문자를 `-`로 치환, 양 끝 `-` 제거, 소문자, 80자 컷. 한국어 제목은 그대로 보존된다.
- title이 비어 있으면 slug는 `untitled`.
- `synthesis`가 주어지고 `kind` 미지정이면 자동으로 `decision`으로 분류된다.

## 3. Frontmatter 스키마 (v0)

```yaml
---
title: <pack.title>
source: <primary_url 또는 첫 source.url 또는 null>
roles: [<pack에 등장한 author_roles>]
status: captured | decided | approval-pending | <session.state.value>
session_id: <세션 id 또는 null>
created_at: <pack.created_at ISO 또는 null>
kind: research | decision | reference
tags: [<kind 단수형 + pack.tags>]
contract: research-forum-export/v0
approval_required: true | false       # synthesis가 있을 때만
exported_at: <ISO 시각>                # 호출자가 넘기면 표시
---
```

규약
- `status` 결정 우선순위: `synthesis.approval_required=True` → `approval-pending`. synthesis가 있으면 → `decided`. session 없음 → `captured`. `session.state == intake` → `captured`. 그 외 → `session.state.value`.
- `tags`는 항상 `[<kind>]`로 시작하고 `pack.tags`를 dedup해 합친다. 예: `[research, ux]`, `[decision, ux]`.
- YAML quoting은 진짜 필요할 때만 적용된다 — `: `(콜론+공백) / 양 끝 공백 / `[`/`#`/`-`/`,`/줄바꿈 같은 제어 문자가 들어간 경우. URL이나 ISO 시각은 보통 unquoted로 출력된다.

## 4. Body 구조

순서대로 나타난다 (각 섹션은 비면 자동 생략):

```
# <pack.title>

## 합의안                  (synthesis가 있을 때)
<synthesis.consensus>

## 해야 할 일               (synthesis.todos)
- ...

## 더 조사할 것              (synthesis.open_research)
- ...

## 사용자 결정 필요          (synthesis.user_decisions_needed)
- ...

## 승인 필요 여부            (synthesis가 있을 때)
yes | no   (yes일 때 — 사유)

## 요약                     (pack.summary)

## 자료 링크                 (pack.urls)
- https://...

## 첨부                     (pack.attachments)
- `<kind>` <filename> <url>

## 출처                     (pack.sources)
- **<author_role>** · <posted_at> · <url> · <title>

## 메타                     (session 있을 때)
- session_id: `...`
- task_type: `...`
- executor_role: `...`
```

## 5. 호출 패턴

| 시나리오 | 호출 |
|---|---|
| forum thread `[Research]` 한 thread를 외부 노트로 보존 | `render_research_note(pack)` |
| forum thread 안 `[Decision]` 댓글이 달린 합의안을 보존 | `render_research_note(pack, synthesis=...)` (자동 `decision` kind) |
| 외부 reference 묶음 노트 | `render_research_note(pack, kind="reference")` |
| 작업 세션 컨텍스트 함께 보존 | `session=session` 추가 — frontmatter `session_id` + 본문 메타 블록 활성화 |

## 6. 멱등성 / 충돌 처리

- 본 contract는 **멱등 export**를 가정한다 — 같은 pack을 다시 export하면 같은 path/content가 생성되어야 한다(타임스탬프 차이 외).
- 같은 path가 이미 존재할 때 덮어쓸지 보존할지의 결정은 **호출자 영역**이다. 본 모듈은 항상 path 제안만 한다.
- 같은 thread를 여러 번 export하면서 본문이 바뀌면 git diff로 추적하는 운영을 권장한다(vault를 git으로 관리할 경우).

## 7. 변경 절차

- frontmatter key 추가/변경 시 `contract` 버전을 올린다 (`v0` → `v1`). 같은 vault에 v0/v1이 섞여도 인덱서가 분기할 수 있게 한다.
- vault path 변경(`Agents/Engineering/...` 트리)은 호환성 영향이 크므로 별도 PR로 처리하고 마이그레이션 스크립트를 함께 제시한다.
- `_yaml_scalar` quoting 규칙을 바꾸면 frontmatter 파싱이 영향받으므로 본 문서 §3 마지막 항목과 함께 갱신한다.

## 8. 후속 작업

1. 실제 파일 writer (`yule obsidian sync`) — 본 contract의 `note.path.full`에 `note.content`를 쓰는 얇은 CLI.
2. vault git 통합 — 변경 분 자동 commit.
3. `[Obsidian]` 댓글이 달린 forum thread 자동 export pipeline (research-forum.md §4.3와 결합).
4. 파일명 충돌 정책 — 같은 날짜·같은 slug일 때 suffix 처리 (`_2.md`).
