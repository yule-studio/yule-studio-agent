# ResearchPack — neutral data model (v0)

이 문서는 engineering-agent(및 향후 cto-agent / design-agent / marketing-agent)가 **연구·심의 자료를 한 덩어리로 다루기 위한 데이터 모델**을 정의한다. 코드 진실 소스는 `src/yule_orchestrator/agents/research_pack.py`.

본 모듈은 transport 비종속이며 **순수 dataclass + 작은 URL/dedup helper**로만 구성된다. Discord API, 웹 자동 수집, 파일 쓰기는 모두 본 모듈 밖이다.

## 1. 누가 이 데이터를 쓰나

| 소비자 | 입력으로 사용하는 시점 | 산출 |
|---|---|---|
| forum publisher (`discord/research_forum.py`) | thread 본문/댓글 포맷 | thread post + 역할 댓글 |
| dispatcher / workflow | reference 추천 보강 (URL 리스트) | DispatchPlan.reference_sources에 사용자 1순위로 합성 |
| Obsidian export (`agents/obsidian_export.py`) | thread → 마크다운 변환 | YAML frontmatter + 본문 |

세 소비자 모두 **같은 ResearchPack 인스턴스**를 입력으로 받을 수 있어야 하므로 transport 정보(channel_id/thread_id/message_id)는 옵션이고, Discord 외 origin도 같은 모델로 표현된다.

## 2. 자료 구조

```
ResearchPack
├── title: str               # 필수, 빈 입력은 "(untitled)"
├── summary: str             # 한두 문단
├── primary_url: str?        # 가장 중요한 URL (보통 첫 source의 URL)
├── sources: tuple[ResearchSource, ...]
├── tags: tuple[str, ...]
├── created_at: datetime?    # merge 시 가장 이른 timestamp
└── extra: Mapping[str, Any]
```

```
ResearchSource
├── source_url: str?
├── title / summary: str?
├── author_role: str?        # "engineering-agent/backend-engineer" 형식 권장
├── channel_id / thread_id / message_id: int?
├── posted_at: datetime?
├── attachments: tuple[ResearchAttachment, ...]
└── extra: Mapping[str, Any]
```

```
ResearchAttachment
├── kind: str                # "image" / "file" / "embed" / 자유 형식
├── url: str
├── filename / content_type: str?
├── size_bytes: int?
└── description: str?
```

## 3. 파생 속성

- `ResearchPack.urls` — `primary_url + 모든 source.source_url`을 dedup해 반환. 호출 비용은 낮은 편.
- `ResearchPack.attachments` — 모든 source의 attachment를 dedup. dedup 키는 `(kind, cleaned_url)`.
- `ResearchPack.author_roles` — 등장한 역할 주소를 first-seen 순서로 dedup.
- `ResearchSource.discord_origin` — channel_id/thread_id/message_id 중 하나라도 있으면 True.

## 4. Helper 함수

### 4.1 URL helpers
- `extract_urls(text) -> tuple[str, ...]` — 자유 텍스트에서 URL을 정규식으로 추출, 끝 punctuation(`.,);`) 제거, dedup.
- `dedup_urls(iterable) -> tuple[str, ...]` — None/빈 입력 drop, first-seen 순서 보존.

### 4.2 Pack 생성
- `pack_from_discord_message(title, content, ...)` — 한 Discord 메시지 → 단일-source pack. content의 첫 URL을 `primary_url`로.
- `merge_packs([p1, p2, ...])` — N개 pack을 합쳐 source/tag/url을 union+dedup. 빈 입력은 ValueError.
- `pack_with_extra_source(pack, source)` — 기존 pack에 source 1개 추가. 같은 message_id+channel+thread+url이면 무시.

### 4.3 Source dedup 키

**`(message_id, thread_id, channel_id, cleaned_url)`** 4-튜플. title/summary는 dedup 키에 들어가지 않는다 — 같은 메시지를 다시 본 경우 title이 다르더라도 한 source로 취급한다. 후속 enrichment(예: title 보강)는 `pack_with_extra_source` 대신 `dataclasses.replace`로 직접 수행한다.

## 5. 사용 예

```python
from yule_orchestrator.agents.research_pack import (
    pack_from_discord_message, merge_packs,
)

# 한 메시지에서
p1 = pack_from_discord_message(
    title="Stripe Pricing 패턴",
    content="hero step copy 강조 — https://stripe.com/pricing 참고",
    author_role="engineering-agent/product-designer",
    channel_id=1499287359483805879,
    thread_id=1500000000000000001,
    message_id=1500000000000000002,
)

# 두 번째 메시지(같은 thread)에서 추가 자료
p2 = pack_from_discord_message(
    title="Wix 랜딩 grid",
    content="https://wix.com/templates 참고",
    channel_id=1499287359483805879,
    thread_id=1500000000000000001,
    message_id=1500000000000000003,
)

bundle = merge_packs([p1, p2])
print(bundle.urls)
# → ('https://stripe.com/pricing', 'https://wix.com/templates')
```

## 6. 변경 절차

- 새 필드를 추가할 때는 본 문서 §2 트리를 먼저 갱신하고 코드 dataclass와 함께 푼다.
- dedup 키를 바꾸면 forum publisher / Obsidian export 모두 동작이 흔들리므로 별도 PR로 처리하고 영향 범위를 PR 본문에 명시한다.
- transport 정보(channel_id 등)를 필수로 올리지 않는다 — Discord 외 origin도 같은 모델로 흘려야 한다.

## 7. 후속 작업

1. `discord/research_forum.py` adapter — ResearchPack을 thread post/댓글로 포맷.
2. dispatcher에서 사용자 제공 reference 1순위로 ResearchPack URL 흡수.
3. `agents/obsidian_export.py` — ResearchPack + deliberation 결과를 Markdown으로 변환.
4. URL 정규화 강화 — 트래킹 파라미터 제거, 동일 host의 prefix 통합 등.
