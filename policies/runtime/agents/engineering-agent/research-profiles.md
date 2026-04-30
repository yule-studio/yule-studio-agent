# Engineering-Agent — Role Research Profiles

각 역할이 자료를 수집할 때 어떤 source type을 우선시하고, 어떤 검색 쿼리 템플릿을 쓰며, 어떤 reference 카테고리를 참고해야 하는지 정의한다. 자료 수집은 `research_pack.ResearchPack`이 그릇이고, 본 문서는 "그릇을 누가 무엇으로 채우는가"의 정책표다.

## 모듈 위치

- 코드: `src/yule_orchestrator/agents/research_profiles.py`
- 테스트: `tests/test_research_profiles.py`
- 입력 task_type: `dispatcher.TaskType` 값 문자열 (예: `backend-feature`, `landing-page`).

## 지원 자료 유형 (source_type)

| source_type | 의미 |
| --- | --- |
| `user_message` | 사용자가 직접 쓴 요구사항/메시지 |
| `url` | 사용자가 붙인 임의 링크 |
| `web_result` | 검색으로 발견한 웹 자료 |
| `image_reference` | 이미지/스크린샷/디자인 레퍼런스 |
| `file_attachment` | Discord 첨부 파일 (PDF/Figma export 등) |
| `github_issue` | GitHub issue |
| `github_pr` | GitHub PR |
| `code_context` | 현재 레포의 코드/문서에서 찾은 맥락 |
| `official_docs` | 공식 문서 (API, framework, DB, infra) |
| `community_signal` | Reddit, Hacker News, Stack Overflow 등 커뮤니티 신호 |
| `design_reference` | Pinterest, Notefolio, Behance, Awwwards, Canva, Wix Templates, Mobbin, Page Flows 등 디자인 참고 |

상수는 `research_profiles.SOURCE_TYPE_*`에 박혀 있으며, `ALL_SOURCE_TYPES` 튜플로 순서가 고정된다. 새 유형이 필요하면 본 표와 모듈의 상수를 함께 갱신한다.

## 역할별 기본 프로필

각 역할에는 `RoleResearchProfile(role, preferred_source_types, suggested_queries, reference_categories, weight_hints)`이 정의돼 있다. `weight_hints`는 0~10 정수이며 0/미지정은 "특별히 우선하지 않음"을 의미한다.

### tech-lead

- 우선 source_type (상위): `user_message`, `github_issue`, `github_pr`, `official_docs`, `code_context`, `url`
- 쿼리 템플릿: `{topic} architecture overview`, `{topic} dependency map`, `{topic} risk and tradeoffs`, `{topic} rollout plan`
- reference: 내부 docs, ADR/RFC, GitHub history
- 핵심: 결정/순서/리스크/승인 여부 종합

### product-designer

- 우선 source_type (상위): `image_reference`, `design_reference`, `file_attachment`, `url`, `user_message`, `web_result`
- 쿼리 템플릿: `{topic} UI examples`, `{topic} moodboard`, `{topic} accessibility checklist`, `{topic} onboarding flow patterns`
- reference: Pinterest Trends, Notefolio, Behance, Awwwards, Canva Design School, Wix Templates, Mobbin, Page Flows
- 핵심: 무드보드/플로우/UI 레퍼런스/접근성 체크리스트

### backend-engineer

- 우선 source_type (상위): `official_docs`, `code_context`, `github_issue`, `github_pr`, `url`, `user_message`
- 쿼리 템플릿: `{topic} API reference`, `{topic} data model`, `{topic} authentication flow`, `{topic} migration plan`, `{topic} infra/deployment notes`
- reference: 공식 API docs, DB engine docs, auth provider docs, 내부 repo 코드
- 핵심: 데이터 모델, 인증/권한, infra/migration

### frontend-engineer

- 우선 source_type (상위): `official_docs`, `code_context`, `design_reference`, `url`, `user_message`, `web_result`
- 쿼리 템플릿: `{topic} component example`, `{topic} accessibility WCAG`, `{topic} browser compatibility`, `{topic} framework guide`, `{topic} design system mapping`
- reference: MDN, framework 공식 docs, design system docs, Awwwards, Mobbin, Page Flows
- 핵심: 컴포넌트 구조, 접근성, 브라우저 호환성, 디자인 시스템 매핑

### qa-engineer

- 우선 source_type (상위): `user_message`, `github_issue`, `code_context`, `official_docs`, `github_pr`, `community_signal`
- 쿼리 템플릿: `{topic} acceptance criteria`, `{topic} regression scenarios`, `{topic} edge cases`, `{topic} bug reports`, `{topic} test strategy`
- reference: 내부 test plan, bug 라벨 GitHub issues, postmortems, regression suites
- 핵심: 수용 기준, 회귀 시나리오, 엣지 케이스

## task_type 보정 규칙

`build_role_query_hints(role, task_type, topic=...)`가 기본 프로필에 task_type 신호를 더해 가중치를 미세 조정한다. 매칭 없으면 보정 없이 기본 프로필 가중치 그대로 반환한다.

| task_type 그룹 | 매칭 task_type | 영향받는 역할 | 가중치 상향 |
| --- | --- | --- | --- |
| design-heavy | `landing-page`, `visual-polish`, `onboarding-flow`, `email-campaign` | product-designer | `image_reference`, `design_reference` |
| backend-heavy | `backend-feature`, `platform-infra` | backend-engineer | `official_docs`, `code_context` |
| frontend-heavy | `frontend-feature`, `landing-page`, `onboarding-flow`, `visual-polish`, `email-campaign` | frontend-engineer | `code_context`, `official_docs`, `design_reference` (소폭) |
| qa-heavy | `qa-test` | qa-engineer | `github_issue`, `code_context` |

규칙:

- 디자인 task일 때 product-designer의 `image_reference`/`design_reference`가 1위/2위로 올라간다.
- 백엔드 task일 때 backend-engineer의 `official_docs`/`code_context`가 상위로 올라간다.
- 프론트 task일 때 frontend-engineer의 `code_context`(컴포넌트 예시)와 `official_docs`(framework·MDN·접근성)가 상위로 올라간다.
- QA task일 때 qa-engineer의 `github_issue`(과거 사례)와 `code_context`(테스트 대상 코드)가 상위로 올라간다.
- 매칭되지 않은 역할/task 조합은 기본 프로필이 그대로 적용된다 (`notes`도 빈 튜플).

## 출력 — `RoleQueryHints`

```
RoleQueryHints(
    role="product-designer",
    task_type="landing-page",
    weighted_source_types=(
        ("image_reference", 11),
        ("design_reference", 10),
        ("file_attachment", 7),
        ...
    ),
    suggested_queries=("hero UI examples", "hero moodboard", ...),
    reference_categories=("Pinterest Trends", "Notefolio", ...),
    notes=("design-heavy task (landing-page) → image_reference / design_reference 가중치 상향",),
)
```

호출자는 `weighted_source_types`를 그대로 자료 수집기 우선순위 큐로, `suggested_queries`를 검색 쿼리로, `reference_categories`를 reference 추천 카드로, `notes`를 Discord 인테이크 메시지에 그대로 노출할 수 있다.

## 운영 가드

- 본 모듈은 I/O를 하지 않는다. 검색/페치/Discord 호출은 호출자의 책임이다.
- `_DEFAULT_PROFILES`는 모듈 전역 상수다. 런타임에 직접 mutate하지 말 것 — 테스트 시 override가 필요하면 `replace_role_profile_for_tests`를 쓰면 된다.
- task_type은 `dispatcher.TaskType.value`와 동일한 문자열 키를 가정한다. 새 task_type을 추가했다면 위 표와 모듈의 frozenset 4종을 함께 갱신한다.

## 후속 마일스톤

- ResearchPack과 본 프로필의 연결: 자료가 들어올 때 `collected_by_role`과 `source_type`을 보고 본 프로필 가중치로 자동 정렬.
- 사용자 task 신호(예: prompt에 "moodboard", "API reference" 같은 단어)가 있을 때 task_type 분류 외에 추가 가중치를 주는 보정.
- 가중치를 외부 정책 JSON으로 빼서 운영자가 코드 수정 없이 조정 가능하게.
