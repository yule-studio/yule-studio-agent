# GitHub Label Policy

Planning Agent uses GitHub issue labels to adjust open-issue priority so that the recommended development order matches actual layering (foundation → feature → surface).

## How To Identify Labels

Run a sync first.

```bash
yule github issues --limit 30 --force-refresh --json
```

Each issue payload now includes a `labels` field. Add confirmed label names to `github-label-policy.json` with a `priority_boost` and a short `reason`.

## Policy Fields

- `priority_boost`: Score added to matching open issues. Positive boosts move the issue toward the top of the daily plan. Negative values push it down.
- `reason`: Briefing reason shown in Planning output.

When an issue has multiple matching labels, every matching boost is applied (sum) and every reason is appended.

## Default Mapping (이모지 컨벤션 기반)

사용자 GitHub 저장소에 등록된 이모지+한국어 라벨에 맞춰 정책이 정의되어 있습니다. 정책 키는 라벨명 소문자 그대로 사용합니다.

### 기존 사용자 라벨 (실제 GitHub에 등록되어 있음)

| 라벨 | 우선순위 | 설명 |
|---|---|---|
| `⚙ Setting` | +25 | 개발 환경 세팅 |
| `🌏 Deploy` | +20 | 배포 |
| `🐞 BugFix` | +25 | 버그 수정 |
| `📬 API` | +15 | API 통신 |
| `✨ Feature` | +10 | 기능 개발 |
| `🥰 Accessibility` | +5 | 웹접근성 |
| `✅ Test` | +5 | 테스트 |
| `🔨 Refactor` | 0 | 리팩토링 |
| `🙋‍♂️ Question` | 0 | 질문/정보 요청 |
| `💻 CrossBrowsing` | -5 | 브라우저 호환성 |
| `📃 Docs` | -5 | 문서 |
| `🎨 Html&css` | -10 | 마크업/스타일링 |

### 신규 추천 라벨 (GitHub에 추가하면 자동 적용)

기반 작업 카테고리가 부족해 다음 5개 라벨을 정책에 미리 등록해 두었습니다. GitHub 저장소 Issues → Labels → New label로 직접 추가해 사용하세요. 추가하지 않으면 무시됩니다.

| 라벨 이름 | 색상 코드 | 설명 | priority_boost |
|---|---|---|---|
| `🏗 Infrastructure` | `#5319E7` | 기반 인프라 (DB, 배포 환경, CI 등) | +30 |
| `📦 Domain` | `#7057FF` | 도메인 모델/엔티티 정의 | +25 |
| `🗄 Schema` | `#0E8A16` | DB 스키마/마이그레이션 | +25 |
| `🎯 Core` | `#FBCA04` | 코어 비즈니스 로직 | +25 |
| `🔐 Auth` | `#B60205` | 인증/인가 흐름 | +20 |

## How a Boost Is Applied

이슈에 두 라벨이 동시에 붙으면 `priority_boost`가 더해지고 `reason`이 한 줄씩 누적됩니다.

예: `🐞 BugFix` + `🔐 Auth` → `+25 + +20 = +45`, reasons 두 개 함께 노출.

## Override

다른 저장소나 다른 컨벤션에 맞춰 다른 정책을 쓰려면:

- `YULE_GITHUB_LABEL_POLICY_FILE` 환경변수로 다른 JSON 파일 경로 지정
- `YULE_GITHUB_LABEL_POLICY_JSON` 환경변수에 inline JSON 직접 넣기 (CI 등에서 사용)
