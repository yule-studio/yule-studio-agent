"""Autonomous first-pass research collector for engineering-agent.

When a user posts a free-form request and the gateway needs reference
material to drive deliberation, this module runs a metadata-only
collection step **before** asking the user for links/screenshots:

1. Build a role-aware search query from the prompt + task_type.
2. Hand it to a :class:`ResearchCollector` (Mock by default; Tavily/Brave
   when their API keys are present and the operator opted in).
3. Wrap the results into typed :class:`ResearchSource` instances and
   compose a :class:`ResearchPack` together with the original user
   message and any user-supplied links/attachments.
4. Return a :class:`CollectionOutcome` that tells the conversation
   layer whether to:
   - run deliberation immediately (``AUTO_COLLECTED`` / ``USER_PROVIDED``), or
   - ask the user for more input (``NEEDS_USER_INPUT``).

Operating principles (matches policy / design rules):

- **Metadata-only.** We never download an image, copy body text, or
  bypass auth. Each :class:`ResearchSource` keeps title/url/domain/
  thumbnail_url/description/snippet — and that's it.
- **Mock fallback.** When auto-collect is disabled or the chosen
  provider has no API key, the factory returns a deterministic mock
  collector so tests run without a network and operators can preview
  the contract before paying for a search API.
- **Role-aware.** Each role's research profile (already centralised in
  ``deliberation.ROLE_RESEARCH_PROFILES``) drives query boosters and
  result ranking. The mock collector returns canned domains per role
  so different roles see different first-pass material.

The collector itself never touches Discord, never writes files, and
never persists. Storage and forum posting belong to upstream wiring.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

from .deliberation import KNOWN_SOURCE_TYPES, ROLE_RESEARCH_PROFILES
from .research_pack import (
    ResearchAttachment,
    ResearchFinding,
    ResearchPack,
    ResearchRequest,
    ResearchSource,
    SourceType,
    make_research_request,
    pack_from_request,
    source_from_user_message,
)


# ---------------------------------------------------------------------------
# Env config
# ---------------------------------------------------------------------------


ENV_AUTO_COLLECT_ENABLED = "ENGINEERING_RESEARCH_AUTO_COLLECT_ENABLED"
ENV_PROVIDER = "ENGINEERING_RESEARCH_PROVIDER"
ENV_MAX_RESULTS = "ENGINEERING_RESEARCH_MAX_RESULTS"

ENV_TAVILY_API_KEY = "TAVILY_API_KEY"
ENV_BRAVE_API_KEY = "BRAVE_SEARCH_API_KEY"


PROVIDER_MOCK = "mock"
PROVIDER_TAVILY = "tavily"
PROVIDER_BRAVE = "brave"
KNOWN_PROVIDERS: Tuple[str, ...] = (PROVIDER_MOCK, PROVIDER_TAVILY, PROVIDER_BRAVE)

DEFAULT_MAX_RESULTS = 5


@dataclass(frozen=True)
class CollectorConfig:
    """Resolved env config for the auto-collector.

    ``enabled=False`` means "skip collection entirely; jump straight to
    the user-input fallback". ``provider`` and ``max_results`` are still
    resolved so observability commands can show the operator what would
    happen if they flipped the flag.
    """

    enabled: bool
    provider: str
    max_results: int
    api_key: Optional[str] = None

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "CollectorConfig":
        env_map: Mapping[str, str] = env if env is not None else os.environ

        enabled = _truthy(env_map.get(ENV_AUTO_COLLECT_ENABLED))
        provider_raw = (env_map.get(ENV_PROVIDER) or "").strip().lower() or PROVIDER_MOCK
        if provider_raw not in KNOWN_PROVIDERS:
            provider_raw = PROVIDER_MOCK
        max_results = _positive_int(
            env_map.get(ENV_MAX_RESULTS), default=DEFAULT_MAX_RESULTS
        )

        api_key: Optional[str] = None
        if provider_raw == PROVIDER_TAVILY:
            api_key = _strip_or_none(env_map.get(ENV_TAVILY_API_KEY))
        elif provider_raw == PROVIDER_BRAVE:
            api_key = _strip_or_none(env_map.get(ENV_BRAVE_API_KEY))

        return cls(
            enabled=enabled,
            provider=provider_raw,
            max_results=max_results,
            api_key=api_key,
        )


def _truthy(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def _positive_int(value: Optional[str], *, default: int) -> int:
    if value is None or not str(value).strip():
        return default
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _strip_or_none(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


# ---------------------------------------------------------------------------
# Collector interface
# ---------------------------------------------------------------------------


class CollectorError(RuntimeError):
    """Raised when the chosen provider failed (network, auth, parse)."""


class ProviderUnavailable(CollectorError):
    """Raised when the provider can't run (missing API key / wrong shape)."""


@dataclass(frozen=True)
class CollectorQuery:
    """Input shape consumed by :meth:`ResearchCollector.search`."""

    query: str
    role: str
    max_results: int
    task_type: Optional[str] = None
    extra: Mapping[str, Any] = field(default_factory=dict)


class ResearchCollector(ABC):
    """Provider-agnostic search interface.

    Implementations must return a sequence of :class:`ResearchSource`
    instances tagged with the right :class:`SourceType` and metadata
    (title / url / domain / snippet / thumbnail / why_relevant). They
    must never raise on empty results — return an empty tuple instead.
    """

    name: str = "abstract"

    @abstractmethod
    def search(self, query: CollectorQuery) -> Sequence[ResearchSource]:
        ...


class NoOpCollector(ResearchCollector):
    """Used when auto-collect is disabled. Always returns ``()``."""

    name = "noop"

    def search(self, query: CollectorQuery) -> Sequence[ResearchSource]:
        return ()


# ---------------------------------------------------------------------------
# Role-aware query construction
# ---------------------------------------------------------------------------


# Boost terms appended to the user prompt for each role to nudge the search
# engine (or mock) toward role-relevant material. Kept short so providers
# like Tavily/Brave that respect natural-language queries still rank
# user keywords highly.
ROLE_QUERY_BOOSTS: Mapping[str, Tuple[str, ...]] = {
    "tech-lead": ("architecture", "decision", "RFC"),
    "product-designer": ("UI reference", "UX pattern", "design"),
    "backend-engineer": ("official docs", "API", "schema"),
    "frontend-engineer": ("MDN", "framework docs", "accessibility"),
    "qa-engineer": ("regression", "test plan", "e2e"),
}


def short_role(role: str) -> str:
    """Strip ``<agent>/`` prefix so we can reuse role-keyed mappings."""

    return role.split("/", 1)[1] if "/" in role else role


def build_query_for_role(
    *,
    role: str,
    prompt: str,
    task_type: Optional[str] = None,
    extra_keywords: Sequence[str] = (),
) -> str:
    """Build a search query string from the user prompt + role + task_type.

    Strategy:
    - Take the first line of the prompt (avoid runaway sentences).
    - Append task_type as a keyword (e.g. ``landing-page``).
    - Append role-specific booster terms (`UI reference`, `official docs`).
    - Dedup tokens to keep the query short.
    """

    short = short_role(role)
    base = (prompt or "").strip().splitlines()[0:1]
    base_text = base[0].strip() if base else ""
    parts: list[str] = []
    if base_text:
        parts.append(base_text)
    if task_type:
        parts.append(task_type.strip())
    parts.extend(s for s in (extra_keywords or ()) if s and s.strip())
    parts.extend(ROLE_QUERY_BOOSTS.get(short, ()))

    seen: dict[str, None] = {}
    for token in parts:
        cleaned = (token or "").strip()
        if cleaned and cleaned.lower() not in seen:
            seen[cleaned.lower()] = None

    return " ".join(seen.keys()).strip()


# ---------------------------------------------------------------------------
# Mock collector — deterministic role-aware canned results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _MockHit:
    title: str
    url: str
    domain: str
    snippet: str
    source_type: SourceType
    why_relevant: str
    risk_or_limit: Optional[str] = None
    thumbnail_url: Optional[str] = None


# Canned per-role hit sets. The mock cycles through these (modulated by the
# query) so different prompts get a different first hit, but the same prompt
# always returns the same ordering — handy for tests and debugging.
_MOCK_BUCKETS: Mapping[str, Tuple[_MockHit, ...]] = {
    "tech-lead": (
        _MockHit(
            title="ADR template — architecture decision record",
            url="https://github.com/joelparkerhenderson/architecture-decision-record",
            domain="github.com",
            snippet="Record context, decision, consequence — base ADR template.",
            source_type=SourceType.OFFICIAL_DOCS,
            why_relevant="작업 분해와 결정 기록 양식을 그대로 차용 가능",
        ),
        _MockHit(
            title="A Philosophy of Software Design — talk notes",
            url="https://blog.acolyer.org/2018/09/04/a-philosophy-of-software-design/",
            domain="blog.acolyer.org",
            snippet="Module 분해와 의존 순서 결정에 대한 정리 노트.",
            source_type=SourceType.COMMUNITY_SIGNAL,
            why_relevant="작업 순서 결정 시 가독성/모듈성 trade-off 참고",
            risk_or_limit="블로그 요약본 — 원문 검증 필요",
        ),
        _MockHit(
            title="GitHub Issue: 기존 hero 회귀 추적",
            url="https://github.com/example/example/issues/42",
            domain="github.com",
            snippet="Issue body — hero 카피 변경 후 모바일 그리드 깨짐 보고.",
            source_type=SourceType.GITHUB_ISSUE,
            why_relevant="과거 회귀 패턴 — 같은 영역 변경 시 재현 위험",
        ),
    ),
    "product-designer": (
        _MockHit(
            title="Mobbin — landing hero patterns",
            url="https://mobbin.com/discover/landing-page",
            domain="mobbin.com",
            snippet="실제 출시된 모바일 앱의 랜딩 hero 섹션 캡처 모음.",
            source_type=SourceType.DESIGN_REFERENCE,
            why_relevant="hero 카피·CTA 배치 패턴 차용 후보 — Mobbin 스크린숏 가이드",
            risk_or_limit="Mobbin 약관: 직접 scraping 금지, OG/검색 결과 metadata만 사용",
            thumbnail_url="https://mobbin.com/static/preview/landing.png",
        ),
        _MockHit(
            title="Behance — 브랜딩 hero 컬렉션",
            url="https://www.behance.net/search/projects/landing%20hero",
            domain="behance.net",
            snippet="Behance에서 큐레이션된 hero 시안 큐레이션.",
            source_type=SourceType.DESIGN_REFERENCE,
            why_relevant="다양한 브랜드 톤 비교 — 단순 복제 금지, 차용 패턴만 정리",
            thumbnail_url="https://www.behance.net/preview/hero.jpg",
        ),
        _MockHit(
            title="Awwwards — Site of the Day (landing 카테고리)",
            url="https://www.awwwards.com/websites/landing-page/",
            domain="awwwards.com",
            snippet="Awwwards 큐레이션 — 인터랙션·애니메이션 레퍼런스.",
            source_type=SourceType.DESIGN_REFERENCE,
            why_relevant="모바일/데스크톱 전환 인터랙션 검토 후보",
            thumbnail_url="https://www.awwwards.com/preview/landing.jpg",
        ),
        _MockHit(
            title="Notefolio — 한국 디자이너 hero 시안",
            url="https://notefolio.net/categories/branding",
            domain="notefolio.net",
            snippet="Notefolio — 지역 감성 톤 참고용 포트폴리오 큐레이션.",
            source_type=SourceType.DESIGN_REFERENCE,
            why_relevant="한국 사용자 톤 검토에 적합 — 직접 scraping 대신 사용자 제공 링크 권장",
            risk_or_limit="Notefolio 약관: 자동 수집 민감 — 메타데이터만 보존",
        ),
    ),
    "backend-engineer": (
        _MockHit(
            title="FastAPI — Security 가이드",
            url="https://fastapi.tiangolo.com/tutorial/security/",
            domain="fastapi.tiangolo.com",
            snippet="OAuth2 / API key 인증 권장 패턴 공식 문서.",
            source_type=SourceType.OFFICIAL_DOCS,
            why_relevant="인증/권한 변경 시 공식 권장 패턴 따라 위험 최소화",
        ),
        _MockHit(
            title="PostgreSQL — Concurrency Control",
            url="https://www.postgresql.org/docs/current/mvcc.html",
            domain="postgresql.org",
            snippet="PostgreSQL MVCC 락 정책 — 마이그레이션 잠금 위험 점검용.",
            source_type=SourceType.OFFICIAL_DOCS,
            why_relevant="schema 변경 시 동시 작업 충돌 점검 근거",
        ),
        _MockHit(
            title="OWASP — Authentication Cheat Sheet",
            url="https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html",
            domain="cheatsheetseries.owasp.org",
            snippet="OWASP 인증 보안 권장 항목.",
            source_type=SourceType.OFFICIAL_DOCS,
            why_relevant="email 인증 / 토큰 저장 정책의 보안 기준",
        ),
    ),
    "frontend-engineer": (
        _MockHit(
            title="MDN — Accessibility · ARIA roles",
            url="https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA",
            domain="developer.mozilla.org",
            snippet="ARIA role / state / property 표준 정의.",
            source_type=SourceType.OFFICIAL_DOCS,
            why_relevant="hero CTA 접근성 점검 — role/aria-label 적용 기준",
        ),
        _MockHit(
            title="web.dev — Performance & Accessibility",
            url="https://web.dev/learn/accessibility/",
            domain="web.dev",
            snippet="web.dev 학습 트랙 — 접근성 / 성능 best practice.",
            source_type=SourceType.OFFICIAL_DOCS,
            why_relevant="모바일 hero 렌더링 성능 점검 가이드",
        ),
        _MockHit(
            title="React — Components & Composition",
            url="https://react.dev/learn",
            domain="react.dev",
            snippet="React 공식 문서 — 컴포넌트 분해 권장 패턴.",
            source_type=SourceType.OFFICIAL_DOCS,
            why_relevant="hero 컴포넌트 props/상태 분리 기준",
        ),
    ),
    "qa-engineer": (
        _MockHit(
            title="Playwright — Best Practices",
            url="https://playwright.dev/docs/best-practices",
            domain="playwright.dev",
            snippet="Playwright e2e 작성 권장 패턴 (locator/wait/visual).",
            source_type=SourceType.OFFICIAL_DOCS,
            why_relevant="hero 회귀 e2e 시나리오 작성 기준",
        ),
        _MockHit(
            title="Testing Library — Guiding Principles",
            url="https://testing-library.com/docs/guiding-principles",
            domain="testing-library.com",
            snippet="사용자 관점 테스트 작성 원칙.",
            source_type=SourceType.OFFICIAL_DOCS,
            why_relevant="hero CTA 접근성 단위 테스트 작성 근거",
        ),
        _MockHit(
            title="GitHub Issue: 기존 hero 회귀 누적",
            url="https://github.com/example/example/issues/42",
            domain="github.com",
            snippet="과거 hero 회귀 사례 누적 — 회귀 시나리오 입력으로 활용.",
            source_type=SourceType.GITHUB_ISSUE,
            why_relevant="회귀 케이스 우선순위 결정",
        ),
    ),
}


class MockSearchCollector(ResearchCollector):
    """Deterministic role-aware canned collector.

    Returns ``min(max_results, len(_MOCK_BUCKETS[role]))`` hits drawn from
    the role's bucket. The first hit is rotated based on a stable hash of
    the query so the same prompt always sees the same first hit, but
    different prompts see different first hits — useful for showing
    operators that the collector is "alive" without ever leaving the
    process.
    """

    name = "mock"

    def search(self, query: CollectorQuery) -> Sequence[ResearchSource]:
        bucket = _MOCK_BUCKETS.get(short_role(query.role), ())
        if not bucket:
            return ()
        offset = (abs(hash(query.query)) if query.query else 0) % len(bucket)
        ordered = bucket[offset:] + bucket[:offset]
        capped = ordered[: max(1, query.max_results)]
        collected_at = datetime.utcnow()
        return tuple(
            self._hit_to_source(hit, query=query, collected_at=collected_at)
            for hit in capped
        )

    @staticmethod
    def _hit_to_source(
        hit: _MockHit,
        *,
        query: CollectorQuery,
        collected_at: datetime,
    ) -> ResearchSource:
        attachments: Tuple[ResearchAttachment, ...] = ()
        if hit.thumbnail_url:
            attachments = (
                ResearchAttachment(
                    kind="image",
                    url=hit.thumbnail_url,
                    description="thumbnail (metadata only — 이미지 원본 저장 안 함)",
                ),
            )
        extra = {
            "domain": hit.domain,
            "snippet": hit.snippet,
            "thumbnail_url": hit.thumbnail_url,
            "query": query.query,
            "provider": "mock",
        }
        return ResearchSource(
            source_type=hit.source_type,
            source_url=hit.url,
            title=hit.title,
            summary=hit.snippet,
            collected_by_role=query.role,
            why_relevant=hit.why_relevant,
            risk_or_limit=hit.risk_or_limit,
            collected_at=collected_at,
            confidence="medium",
            attachments=attachments,
            extra=extra,
        )


# ---------------------------------------------------------------------------
# Provider skeletons (Tavily / Brave) — never invoked in tests
# ---------------------------------------------------------------------------


class TavilySearchCollector(ResearchCollector):
    """Skeleton Tavily collector — used when api_key is set.

    Calls ``https://api.tavily.com/search``. Tests don't exercise this
    path because :func:`build_collector` falls back to mock when keys
    are missing.
    """

    name = "tavily"
    endpoint = "https://api.tavily.com/search"

    def __init__(self, *, api_key: str, timeout_seconds: int = 10) -> None:
        if not api_key:
            raise ProviderUnavailable("tavily provider requires an api_key")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def search(self, query: CollectorQuery) -> Sequence[ResearchSource]:
        payload = {
            "api_key": self.api_key,
            "query": query.query,
            "max_results": max(1, query.max_results),
        }
        try:
            data = _http_post_json(
                self.endpoint, payload=payload, timeout_seconds=self.timeout_seconds
            )
        except Exception as exc:  # noqa: BLE001 - surface as collector error
            raise CollectorError(f"tavily search failed: {exc}") from exc
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            return ()
        collected_at = datetime.utcnow()
        return tuple(
            _result_dict_to_source(
                item, query=query, collected_at=collected_at, provider="tavily"
            )
            for item in results
            if isinstance(item, dict)
        )


class BraveSearchCollector(ResearchCollector):
    """Skeleton Brave Search collector. Auth via ``X-Subscription-Token`` header."""

    name = "brave"
    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, *, api_key: str, timeout_seconds: int = 10) -> None:
        if not api_key:
            raise ProviderUnavailable("brave provider requires an api_key")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def search(self, query: CollectorQuery) -> Sequence[ResearchSource]:
        url = self.endpoint + "?" + urllib.parse.urlencode(
            {"q": query.query, "count": max(1, query.max_results)}
        )
        try:
            data = _http_get_json(
                url,
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self.api_key,
                },
                timeout_seconds=self.timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            raise CollectorError(f"brave search failed: {exc}") from exc
        web = data.get("web") if isinstance(data, dict) else None
        results = web.get("results") if isinstance(web, dict) else None
        if not isinstance(results, list):
            return ()
        collected_at = datetime.utcnow()
        return tuple(
            _result_dict_to_source(
                item, query=query, collected_at=collected_at, provider="brave"
            )
            for item in results
            if isinstance(item, dict)
        )


def _result_dict_to_source(
    item: Mapping[str, Any],
    *,
    query: CollectorQuery,
    collected_at: datetime,
    provider: str = "live",
) -> ResearchSource:
    """Coerce a generic provider result into our :class:`ResearchSource` shape."""

    title = str(item.get("title") or item.get("name") or "(untitled)")
    url = str(item.get("url") or item.get("link") or "")
    snippet = str(item.get("snippet") or item.get("description") or "")
    thumbnail = item.get("thumbnail") or item.get("image") or item.get("favicon")
    if isinstance(thumbnail, dict):
        thumbnail = thumbnail.get("src") or thumbnail.get("url")
    domain = extract_domain(url)
    attachments: Tuple[ResearchAttachment, ...] = ()
    if isinstance(thumbnail, str) and thumbnail.strip():
        attachments = (
            ResearchAttachment(
                kind="image",
                url=thumbnail.strip(),
                description="thumbnail (metadata only)",
            ),
        )
    extra = {
        "domain": domain,
        "snippet": snippet,
        "thumbnail_url": thumbnail if isinstance(thumbnail, str) else None,
        "query": query.query,
        "provider": provider,
    }
    return ResearchSource(
        source_type=_classify_remote_source_type(domain, query.role),
        source_url=url or None,
        title=title,
        summary=snippet or None,
        collected_by_role=query.role,
        why_relevant=None,
        collected_at=collected_at,
        confidence="medium",
        attachments=attachments,
        extra=extra,
    )


# ---------------------------------------------------------------------------
# Domain → SourceType classification (for live providers)
# ---------------------------------------------------------------------------


_DESIGN_DOMAINS = (
    "behance.net",
    "awwwards.com",
    "mobbin.com",
    "notefolio.net",
    "dribbble.com",
    "pinterest.com",
    "canva.com",
    "wix.com",
)
_OFFICIAL_HINTS = (
    "developer.mozilla.org",
    "web.dev",
    "react.dev",
    "vuejs.org",
    "angular.io",
    "nextjs.org",
    "fastapi.tiangolo.com",
    "django",
    "postgresql.org",
    "playwright.dev",
    "testing-library.com",
    "owasp.org",
    "rfc-editor.org",
)


def _classify_remote_source_type(domain: str, role: str) -> SourceType:
    """Best-effort source_type based on domain only (no fetch)."""

    short = (domain or "").lower()
    if any(d in short for d in _DESIGN_DOMAINS):
        return SourceType.DESIGN_REFERENCE
    if any(d in short for d in _OFFICIAL_HINTS):
        return SourceType.OFFICIAL_DOCS
    if "github.com" in short:
        # We can't tell issue vs PR vs repo from the URL alone; default
        # to OFFICIAL_DOCS so the role profile rankings still surface it.
        return SourceType.OFFICIAL_DOCS
    if "reddit.com" in short or "forum" in short or "stackoverflow.com" in short:
        return SourceType.COMMUNITY_SIGNAL
    return SourceType.WEB_RESULT


def extract_domain(url: Optional[str]) -> str:
    """Return ``host[:port]`` (lower-cased) for *url*, or ``""``."""

    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(str(url))
    except Exception:  # noqa: BLE001
        return ""
    return (parsed.netloc or "").lower()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_collector(
    config: Optional[CollectorConfig] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
) -> ResearchCollector:
    """Resolve env config and return a usable collector.

    Fallback chain:
    - ``enabled=False`` → :class:`NoOpCollector` (always returns ``()``).
    - ``provider=mock`` (default) → :class:`MockSearchCollector`.
    - ``provider=tavily`` + ``TAVILY_API_KEY`` set → :class:`TavilySearchCollector`.
    - ``provider=brave`` + ``BRAVE_SEARCH_API_KEY`` set → :class:`BraveSearchCollector`.
    - Provider key missing → silent fallback to :class:`MockSearchCollector`.
    """

    cfg = config if config is not None else CollectorConfig.from_env(env)
    if not cfg.enabled:
        return NoOpCollector()
    if cfg.provider == PROVIDER_TAVILY and cfg.api_key:
        try:
            return TavilySearchCollector(api_key=cfg.api_key)
        except ProviderUnavailable:
            return MockSearchCollector()
    if cfg.provider == PROVIDER_BRAVE and cfg.api_key:
        try:
            return BraveSearchCollector(api_key=cfg.api_key)
        except ProviderUnavailable:
            return MockSearchCollector()
    return MockSearchCollector()


# ---------------------------------------------------------------------------
# Pack assembly
# ---------------------------------------------------------------------------


def collect_research_pack(
    *,
    collector: ResearchCollector,
    role: str,
    prompt: str,
    task_type: Optional[str] = None,
    user_links: Sequence[str] = (),
    user_attachments: Sequence[ResearchAttachment] = (),
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
    max_results: int = DEFAULT_MAX_RESULTS,
    extra_keywords: Sequence[str] = (),
) -> ResearchPack:
    """Run one collection pass and assemble a :class:`ResearchPack`.

    The pack always contains a USER_MESSAGE source mirroring *prompt*.
    User-supplied links become URL sources, user-supplied attachments
    become FILE_ATTACHMENT (or IMAGE_REFERENCE if the metadata says so)
    sources, and collector hits are appended on top with role-aware
    typing.
    """

    request = make_research_request(
        topic=prompt,
        role=role,
        session_id=session_id,
        request_id=request_id,
        context={"task_type": task_type or "unknown"},
    )

    sources: list[ResearchSource] = [
        source_from_user_message(
            content=prompt,
            collected_by_role=role,
        )
    ]

    for url in user_links:
        cleaned = (url or "").strip()
        if not cleaned:
            continue
        sources.append(
            ResearchSource(
                source_type=SourceType.URL,
                source_url=cleaned,
                title=cleaned,
                summary=None,
                collected_by_role=role,
                why_relevant="사용자 제공 링크 — 1순위 reference",
                confidence="high",
                collected_at=datetime.utcnow(),
                extra={
                    "domain": extract_domain(cleaned),
                    "query": "<user-provided>",
                },
            )
        )

    for att in user_attachments:
        # Honour the user's actual attachment shape; we only surface metadata.
        sources.append(
            ResearchSource(
                source_type=(
                    SourceType.IMAGE_REFERENCE
                    if (att.kind or "").lower() == "image"
                    else SourceType.FILE_ATTACHMENT
                ),
                source_url=att.url or None,
                title=att.filename or att.kind or "(attachment)",
                summary=att.description,
                collected_by_role=role,
                why_relevant="사용자 첨부 — 1순위 reference",
                confidence="high",
                collected_at=datetime.utcnow(),
                attachments=(att,),
                attachment_id=att.attachment_id,
                extra={"query": "<user-provided>"},
            )
        )

    query = build_query_for_role(
        role=role,
        prompt=prompt,
        task_type=task_type,
        extra_keywords=extra_keywords,
    )
    if query:
        try:
            web_hits = collector.search(
                CollectorQuery(
                    query=query,
                    role=role,
                    max_results=max_results,
                    task_type=task_type,
                )
            )
        except CollectorError:
            web_hits = ()
        # Order role-preferred source_type buckets first, then the rest.
        ranked = _rank_sources_for_role(web_hits, role=role)
        sources.extend(ranked)

    return pack_from_request(
        request=request,
        sources=tuple(sources),
        tags=("auto-collected",) if any(s.extra.get("provider") for s in sources if s.extra) else (),
    )


def _rank_sources_for_role(
    sources: Sequence[ResearchSource],
    *,
    role: str,
) -> Tuple[ResearchSource, ...]:
    """Order *sources* using ``deliberation.ROLE_RESEARCH_PROFILES``."""

    profile = ROLE_RESEARCH_PROFILES.get(short_role(role), ())
    if not profile:
        return tuple(sources)
    rank_index: dict[str, int] = {value: idx for idx, value in enumerate(profile)}
    fallback = len(profile) + len(KNOWN_SOURCE_TYPES)

    def key(source: ResearchSource) -> int:
        type_value = (
            source.source_type.value
            if isinstance(source.source_type, SourceType)
            else str(source.source_type)
        )
        return rank_index.get(type_value, fallback)

    return tuple(sorted(sources, key=key))


# ---------------------------------------------------------------------------
# Outcome flow — collect first, ask user only when nothing
# ---------------------------------------------------------------------------


class CollectionMode(str, Enum):
    AUTO_COLLECTED = "auto_collected"
    USER_PROVIDED = "user_provided"
    NEEDS_USER_INPUT = "needs_user_input"


@dataclass(frozen=True)
class CollectionOutcome:
    """What the conversation layer should do next.

    - ``AUTO_COLLECTED`` — collector produced ≥1 web result. Run deliberation.
    - ``USER_PROVIDED`` — user already supplied links/attachments. Run deliberation.
    - ``NEEDS_USER_INPUT`` — nothing usable. Reply with *user_prompt*.
    """

    mode: CollectionMode
    pack: Optional[ResearchPack]
    user_prompt: Optional[str]
    collector_name: str
    query: str
    auto_collected_count: int


def auto_collect_or_request_more_input(
    *,
    role: str,
    prompt: str,
    task_type: Optional[str] = None,
    user_links: Sequence[str] = (),
    user_attachments: Sequence[ResearchAttachment] = (),
    session_id: Optional[str] = None,
    request_id: Optional[str] = None,
    config: Optional[CollectorConfig] = None,
    collector: Optional[ResearchCollector] = None,
) -> CollectionOutcome:
    """Top-level entry point for the conversation layer.

    *collector* is an injection seam for tests; production callers can
    pass ``None`` and let the env-driven factory decide.
    """

    cfg = config if config is not None else CollectorConfig.from_env()
    chosen = collector or build_collector(cfg)
    user_supplied = bool(user_links) or bool(user_attachments)

    pack = collect_research_pack(
        collector=chosen,
        role=role,
        prompt=prompt,
        task_type=task_type,
        user_links=user_links,
        user_attachments=user_attachments,
        session_id=session_id,
        request_id=request_id,
        max_results=cfg.max_results,
    )

    # Count sources stamped by *some* provider (mock/tavily/brave/live).
    # User-supplied URLs/attachments use ``provider`` ∉ extra, so they don't
    # count even though they're valid reference material.
    auto_collected_count = sum(
        1 for source in pack.sources if (source.extra or {}).get("provider")
    )

    query = build_query_for_role(role=role, prompt=prompt, task_type=task_type)

    if auto_collected_count > 0:
        return CollectionOutcome(
            mode=CollectionMode.AUTO_COLLECTED,
            pack=pack,
            user_prompt=None,
            collector_name=chosen.name,
            query=query,
            auto_collected_count=auto_collected_count,
        )
    if user_supplied:
        return CollectionOutcome(
            mode=CollectionMode.USER_PROVIDED,
            pack=pack,
            user_prompt=None,
            collector_name=chosen.name,
            query=query,
            auto_collected_count=0,
        )
    return CollectionOutcome(
        mode=CollectionMode.NEEDS_USER_INPUT,
        pack=None,
        user_prompt=_format_user_input_request(role=role, task_type=task_type),
        collector_name=chosen.name,
        query=query,
        auto_collected_count=0,
    )


def _format_user_input_request(
    *,
    role: str,
    task_type: Optional[str],
) -> str:
    short = short_role(role)
    role_hint = {
        "product-designer": "참고할 화면 / 무드보드 / Mobbin·Behance 링크",
        "frontend-engineer": "참고할 컴포넌트 사례 / MDN·web.dev 문서 / 디자인 시스템 캡처",
        "backend-engineer": "관련 공식 문서 / API 스펙 / 보안 정책 링크",
        "qa-engineer": "기존 회귀 사례 / 테스트 시나리오 / GitHub issue 링크",
        "tech-lead": "관련 ADR / RFC / 의사결정 기록 또는 GitHub PR",
    }.get(short, "관련 자료")
    task_hint = f" ({task_type})" if task_type else ""
    return (
        "아직 자동으로 수집된 자료가 없습니다."
        f" {role_hint}을(를) 한두 개 붙여 주시면 1차 reference로 사용할게요{task_hint}."
    )


# ---------------------------------------------------------------------------
# Forum-friendly summary (for #운영-리서치 게시 시 호출자가 사용)
# ---------------------------------------------------------------------------


def format_collection_summary(
    pack: ResearchPack,
    *,
    collector_name: str,
    query: str,
    role: str,
) -> str:
    """Produce a Markdown summary block surfacing why_relevant per source.

    Designed to be appended inside ``format_research_post_body`` so the
    forum thread carries 수집 출처 / 요약 / 역할별 활용 가능성 in one block.
    """

    lines: list[str] = [
        f"**1차 자료 수집 — {short_role(role)}**",
        f"- collector: `{collector_name}` · query: `{query or '(empty)'}` · 자료 {len(pack.sources)}건",
    ]
    for source in pack.sources:
        if source.source_type == SourceType.USER_MESSAGE:
            continue
        domain = (source.extra or {}).get("domain") or extract_domain(source.source_url)
        title = source.title or "(no title)"
        bits = [f"- **{title}** [{(source.source_type.value if isinstance(source.source_type, SourceType) else str(source.source_type))}]"]
        if domain:
            bits.append(f" · `{domain}`")
        if source.source_url:
            bits.append(f" — {source.source_url}")
        lines.append("".join(bits))
        if source.why_relevant:
            lines.append(f"  ↪ 활용 가능성: {source.why_relevant}")
        if source.risk_or_limit:
            lines.append(f"  ⚠ 한계/리스크: {source.risk_or_limit}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTTP helpers (used by Tavily/Brave skeletons; not exercised in tests)
# ---------------------------------------------------------------------------


def _http_get_json(
    url: str,
    *,
    headers: Mapping[str, str],
    timeout_seconds: int,
) -> Any:  # pragma: no cover - real network only
    request = urllib.request.Request(url, headers=dict(headers))
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def _http_post_json(
    url: str,
    *,
    payload: Mapping[str, Any],
    timeout_seconds: int,
) -> Any:  # pragma: no cover - real network only
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)
