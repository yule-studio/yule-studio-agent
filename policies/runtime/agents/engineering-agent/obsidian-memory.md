# Obsidian Memory Export — v0 contract (string + local file writer)

이 문서는 engineering-agent의 ResearchPack/deliberation 결과를 **개인 Obsidian vault**로 내보낼 때 사용할 Markdown 구조와 path 규칙을 정의한다. 문자열 생성은 `obsidian_export`가, 실제 파일 쓰기는 `obsidian_writer` + `yule obsidian sync` CLI가 담당한다.

코드 진실 소스:
- 문자열 생성: `src/yule_orchestrator/agents/obsidian_export.py` (contract 식별자: `research-forum-export/v0`).
- 파일 쓰기: `src/yule_orchestrator/agents/obsidian_writer.py` (얇은 IO 레이어 — exporter contract는 그대로 유지).
- CLI: `src/yule_orchestrator/cli/obsidian.py` (`yule obsidian sync`).

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
topic: <pack.title — 인덱서/요약기가 title 변경에 영향받지 않게 별도 키>
task_type: <session.task_type 또는 null — 작업 분류용>
sources: [<pack.urls + 첨부 식별자 합본 — 인덱서가 한 줄로 읽는 평면 리스트>]
contract: research-forum-export/v0
approval_required: true | false       # synthesis가 있을 때만
exported_at: <ISO 시각>                # 호출자가 넘기면 표시
---
```

규약
- `status` 결정 우선순위: `synthesis.approval_required=True` → `approval-pending`. synthesis가 있으면 → `decided`. session 없음 → `captured`. `session.state == intake` → `captured`. 그 외 → `session.state.value`.
- `tags`는 항상 `[<kind>]`로 시작하고 `pack.tags`를 dedup해 합친다. 예: `[research, ux]`, `[decision, ux]`.
- `topic`은 현재 `pack.title`과 동일하지만 별도 키로 노출한다 — title rewriting을 해도 인덱서가 동일 토픽을 추적할 수 있도록 분리.
- `task_type`은 session에서만 채워진다(없으면 `null`). 작업 배정/리포팅 인덱서가 분류 키로 쓰는 값.
- `sources`는 `pack.urls` (primary + 각 source.url, dedup) 뒤에 `pack.attachments`의 url(또는 filename)을 dedup해 붙인 평면 리스트다. 본문 ## 출처 블록이 사람용이라면 frontmatter `sources`는 인덱서/스크립트용이다.
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

## 8. 로컬 파일 동기화 (`yule obsidian sync`)

`obsidian_export`가 만든 `note.content`를 vault 안 `note.path.full` 위치에 실제 Markdown 파일로 쓰는 얇은 IO 레이어다. exporter contract는 건드리지 않는다.

### 8.1 환경변수

- `OBSIDIAN_VAULT_PATH`: Obsidian vault의 **절대경로**. 이 값이 없으면 sync는 즉시 실패한다.
- 실제 사용자 절대경로는 반드시 `.env.local`에 둔다. `.env.example`은 git에 커밋되는 파일이므로 placeholder만 두고, 실제 경로는 git 추적에서 빠진 `.env.local`(또는 `.env`)에서만 읽도록 강제한다 — `.gitignore`가 `.env`/`.env.*`는 제외하고 `.env.example`만 화이트리스트로 남기는 구조와 일관된다.

### 8.2 사용

```bash
# 1) session_id로 저장된 ResearchPack을 vault에 쓴다 (가장 흔한 경우)
yule obsidian sync --session abc12345

# 2) 미리 결과만 보고 싶을 때
yule obsidian sync --session abc12345 --dry-run

# 3) 같은 path가 이미 있을 때 명시적으로 덮어쓰기
yule obsidian sync --session abc12345 --overwrite

# 4) reference 노트로 분류해 저장 (kind 강제)
yule obsidian sync --session abc12345 --kind reference

# 5) env가 아닌 임시 vault로 보내기
yule obsidian sync --session abc12345 --vault-path /tmp/sandbox-vault
```

CLI는 다음 순서로 동작한다.

1. `load_session(session_id)` — workflow cache에서 세션을 읽는다. 없으면 사람 가독 에러.
2. `session.extra["research_pack"]`를 `pack_from_dict`로 복원. 없으면 "research_pack이 없다" 안내 후 종료.
3. `OBSIDIAN_VAULT_PATH`(또는 `--vault-path`) 검증 — 절대경로/존재/디렉터리 여부.
4. `render_research_note(pack, session=session, kind=...)`로 `ObsidianNote` 생성 (exporter contract 그대로).
5. `write_note(note, vault_root, overwrite=..., dry_run=...)` 호출.

### 8.3 안전 정책

- vault root는 절대경로여야 하고 디렉터리로 존재해야 한다.
- 최종 target path는 `vault_root.resolve() / note.path.full`을 다시 resolve한 뒤 `relative_to(vault_root)`로 검증 — 즉 symlink 등으로 vault 밖으로 나가는 path traversal은 거부된다.
- parent 디렉터리는 `mkdir(parents=True, exist_ok=True)`로 자동 생성한다.
- 기본은 **overwrite 금지**: 같은 path가 이미 있으면 `skipped` 결과를 반환하고 사유를 출력한다. 덮어쓰려면 `--overwrite`를 명시해야 한다.
- `--dry-run`은 모든 검증을 수행하지만 파일은 만들지 않는다.
- 실패 시 `error: ...` 형식으로 stderr에 사람이 이해 가능한 메시지를 남긴다.

### 8.4 출력 경로 예시

`render_research_note`가 만든 vault-relative path가 그대로 vault 안에 떨어진다.

```text
$OBSIDIAN_VAULT_PATH/Agents/Engineering/Research/2026-04-30_stripe-pricing.md
$OBSIDIAN_VAULT_PATH/Agents/Engineering/Decisions/2026-04-30_hero-합의.md
$OBSIDIAN_VAULT_PATH/Agents/Engineering/References/2026-04-30_landing-references.md
```

### 8.5 doctor 연동

`yule doctor`는 `obsidian vault` 체크를 포함한다.

- 미설정: `SKIP` (sync 사용 안 하면 정상).
- 절대경로 아님 / 디렉터리 없음: `FAIL` + hint.
- 정상: `OK` + 해석된 절대경로.

### 8.6 남은 후속 작업

1. vault git 통합 — vault를 git으로 관리하고 sync 직후 자동 commit.
2. `[Obsidian]` 댓글이 달린 forum thread 자동 export pipeline (research-forum.md §4.3와 결합).
3. 파일명 충돌 정책 확장 — 같은 날짜·같은 slug일 때 `_2.md` 같은 suffix 자동 부여 (현재는 `--overwrite` 명시 또는 skip).
4. synthesis 영속화 — 현재 `WorkflowSession`에는 `TechLeadSynthesis`가 저장되지 않으므로 sync도 synthesis 본문 없이 진행된다. 필요해지면 session.extra에 함께 round-trip.
