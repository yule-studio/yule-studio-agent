# Autonomous Research Collector — v0 (MVP)

이 문서는 engineering-agent가 사용자에게 링크/이미지를 묻기 **전에** 1차 자료를 자동 수집하는 collector MVP의 정책 기준선이다. 코드 진실 소스는 `src/yule_orchestrator/agents/research_collector.py`.

## 1. 흐름

```
user message
   │
   ▼
auto_collect_or_request_more_input(role, prompt, task_type, user_links, user_attachments)
   │
   ├── enabled=False  → NoOpCollector → user_links/attachments 있으면 USER_PROVIDED, 없으면 NEEDS_USER_INPUT
   ├── enabled=True   → MockSearchCollector / TavilySearchCollector / BraveSearchCollector
   │                    └── 결과 ≥ 1 → AUTO_COLLECTED
   │                    └── 결과 0 + user 자료 있음 → USER_PROVIDED
   │                    └── 결과 0 + user 자료 없음 → NEEDS_USER_INPUT
   ▼
CollectionOutcome
   ├── pack: ResearchPack | None  (None은 needs_user_input 한정)
   ├── user_prompt: str | None    (needs_user_input일 때 사용자에게 보낼 안내)
   ├── collector_name: str        ("mock" / "tavily" / "brave" / "noop")
   ├── query: str                 (실제 사용한 검색 쿼리)
   └── auto_collected_count: int  (자동 수집 source 수, USER_MESSAGE 제외)
```

원칙: **사용자에게 자료를 묻기 전에 자동 수집을 먼저 시도한다.** 자동 수집이 비어 있을 때만 사용자에게 자료를 요청한다.

## 2. 환경변수

| 키 | 기본값 | 의미 |
|---|---|---|
| `ENGINEERING_RESEARCH_AUTO_COLLECT_ENABLED` | `false` | 자동 수집 on/off. opt-in이라 명시적으로 켜야 동작. |
| `ENGINEERING_RESEARCH_PROVIDER` | `mock` | `mock` / `tavily` / `brave`. 알 수 없는 값은 `mock`으로 fallback. |
| `ENGINEERING_RESEARCH_MAX_RESULTS` | `5` | provider에 요청할 최대 결과 수. 음수/비숫자는 기본값 사용. |
| `TAVILY_API_KEY` | (없음) | provider=tavily일 때 필요. 없으면 mock으로 silent fallback. |
| `BRAVE_SEARCH_API_KEY` | (없음) | provider=brave일 때 필요. 없으면 mock으로 silent fallback. |

규약
- truthy 값: `1` / `true` / `yes` / `on` (대소문자 무시).
- API key는 `.env.local`에만 두고, 절대 출력/로깅하지 않는다.
- `enabled=False`일 때는 어떤 provider 호출도 일어나지 않는다 — `NoOpCollector`가 즉시 빈 튜플을 반환.

## 3. 메타데이터-only 수집 원칙

수집은 **외부 사이트의 본문/이미지를 다운로드하거나 복제하지 않는다**. 각 source에는 다음만 저장한다.

- `title` — 제목
- `url` 또는 `attachment_id` — 식별자
- `domain` — `extra["domain"]` (URL 호스트만)
- `source_type` — `SourceType` enum 값
- `collected_by_role` — 수집한 역할
- `query` — `extra["query"]` (실제 사용한 검색 쿼리)
- `summary` / `snippet` — 본문은 안 내려받고 검색결과의 snippet만
- `thumbnail_url` — `extra["thumbnail_url"]` (이미지 메타데이터 URL만; 본 모듈은 fetch하지 않음)
- `why_relevant` — 역할 관점에서 왜 관련 있는지 한 줄
- `risk_or_limit` — 약관/한계 (Notefolio·Mobbin 등 자동 수집 민감 사이트는 명시)
- `collected_at` — 시점
- `confidence` — high|medium|low
- `provider` — `extra["provider"]` ("mock"/"tavily"/"brave")

이미지 첨부는 `ResearchAttachment(kind="image", description="thumbnail (metadata only ...)" )` 형태로 메타데이터만 저장. **원본 이미지 파일은 다운로드하지 않는다.**

## 4. 역할별 수집 전략

`build_query_for_role`이 prompt + task_type에 역할별 booster를 붙여 검색 쿼리를 만든다.

| 역할 | booster terms |
|---|---|
| tech-lead | architecture, decision, RFC |
| product-designer | UI reference, UX pattern, design |
| backend-engineer | official docs, API, schema |
| frontend-engineer | MDN, framework docs, accessibility |
| qa-engineer | regression, test plan, e2e |

수집 결과는 `deliberation.ROLE_RESEARCH_PROFILES`의 우선순위로 정렬되어 ResearchPack에 들어간다. 즉:
- product-designer: image_reference / design_reference / file_attachment 우선
- backend-engineer: official_docs / code_context / github_pr 우선
- frontend-engineer: official_docs / design_reference / code_context 우선
- qa-engineer: github_issue / community_signal / official_docs 우선
- tech-lead: user_message / url / official_docs 우선

## 5. Mock collector

외부 네트워크 없이 결정적으로 동작하는 fallback. 각 역할별로 canned bucket을 가지고 있고, 같은 query는 항상 같은 결과 순서를 반환한다 (다른 query는 다른 첫 hit). 테스트와 운영자 dry-run에 동일하게 사용 가능.

| 역할 | mock domain |
|---|---|
| product-designer | mobbin.com / behance.net / awwwards.com / notefolio.net |
| backend-engineer | fastapi.tiangolo.com / postgresql.org / cheatsheetseries.owasp.org |
| frontend-engineer | developer.mozilla.org / web.dev / react.dev |
| qa-engineer | playwright.dev / testing-library.com / github.com |
| tech-lead | github.com / blog.acolyer.org / github.com (issue) |

**왜 mock이 기본값인가**: API key가 없거나 enabled=false 상태에서도 conversation 흐름은 멈추지 않아야 하므로. 운영자는 prod에서 Tavily/Brave key를 채우고 `ENGINEERING_RESEARCH_AUTO_COLLECT_ENABLED=true` + `ENGINEERING_RESEARCH_PROVIDER=tavily` 같은 식으로 활성화한다.

## 6. 외부 provider skeleton

`TavilySearchCollector`와 `BraveSearchCollector`는 MVP 단계에서 **호출만 가능한 형태로 정의**되어 있다. 실제 호출 본문은 `urllib.request` 기반으로 구현됐지만 테스트에서는 build_collector가 key 부재로 mock에 fallback하기 때문에 한 번도 실행되지 않는다.

API 응답을 ResearchSource로 변환하는 `_result_dict_to_source`는 다음 키를 인식한다:
- `title` / `name`
- `url` / `link`
- `snippet` / `description`
- `thumbnail` / `image` / `favicon` (객체면 `src` / `url` 값을 사용)

도메인 → SourceType 매핑은 `_classify_remote_source_type`이 담당한다 (behance/awwwards/mobbin/notefolio → DESIGN_REFERENCE, mdn/web.dev/react/fastapi → OFFICIAL_DOCS 등).

## 7. 자동 수집을 끄지 않는 장면 vs 끄는 장면

**기본 켜기 권장** (`ENGINEERING_RESEARCH_AUTO_COLLECT_ENABLED=true`):
- 일반 운영. 사용자가 한 줄로 요청해도 collector가 첫 단계 자료를 채워 deliberation으로 바로 넘어간다.

**끄기 권장** (`ENGINEERING_RESEARCH_AUTO_COLLECT_ENABLED=false`):
- API key 비용 이슈 / outage.
- Tavily/Brave 서비스 장애 시 mock으로도 안정적이지 않은 경우.
- conversation 디버깅 — 사용자 입력만으로 흐름이 동작하는지 검증할 때.

## 8. Discord 통합 가이드 (호출자 영역)

`auto_collect_or_request_more_input`은 conversation/router 코드가 사용자 메시지를 받은 직후에 호출하도록 설계되었다. 응답 envelope의 분기 처리:

| outcome.mode | conversation 응답 |
|---|---|
| `AUTO_COLLECTED` | 1차 자료 수집 완료 메시지 + `format_collection_summary` 결과를 운영-리서치 forum 게시. deliberation으로 바로 진행. |
| `USER_PROVIDED` | 사용자 자료를 그대로 사용해 deliberation 진행. forum에는 사용자 제공 source 출처를 함께 게시. |
| `NEEDS_USER_INPUT` | `outcome.user_prompt` 그대로 사용자에게 답변. deliberation은 보류. |

운영-리서치 forum 게시는 `format_collection_summary(pack, collector_name, query, role)`이 출처 / 요약 / 활용 가능성 / 한계를 한 블록으로 만들어 주므로, 호출자는 이걸 forum thread post body나 댓글에 그대로 끼워 넣으면 된다.

## 9. 외부 사이트 정책 (재확인)

- **Notefolio / Pinterest / Canva / Wix / Mobbin** 은 직접 scraping 금지. Mock canned data + 사용자 제공 링크 + 검색 결과 metadata + 공식 API만 사용.
- **로그인/권한이 필요한 사이트**는 자동 수집 대상에서 제외.
- **이미지 본문**은 다운로드하지 않는다. thumbnail URL만 ResearchAttachment metadata에 보존.
- **GitHub**는 공식 REST API (gh CLI 또는 토큰)를 통한 read-only만 허용. issue/PR fetch는 별도 마일스톤.

## 10. 변경 절차

- 새 provider 추가 시 `KNOWN_PROVIDERS` 튜플과 `build_collector` factory 분기, env 키 명시까지 같은 PR로.
- canned mock bucket을 바꿀 때는 본 정책 §5 표도 같이 갱신.
- `_classify_remote_source_type` 도메인 매핑이 늘어나면 `research-pack.md` §3의 SourceType 표와 일치 검증.
- max_results 기본값을 바꾸면 본 §2 표와 `.env.example` 둘 다 갱신.

## 11. 후속 작업

1. discord conversation/router 통합 — `outcome.mode`에 따른 응답 분기 wire-up (다른 Claude 영역).
2. forum publisher가 `format_collection_summary`를 thread body에 끼워 넣어 자동 게시.
3. Tavily/Brave 실 호출 검증 — 실제 API key 환경에서 응답 shape이 `_result_dict_to_source`와 일치하는지 확인.
4. provider별 rate limit / 비용 관리 정책.
5. 자동 수집 결과의 `confidence` 보강 — provider score / domain trust / role profile 일치도를 합쳐 high/medium/low 결정.
