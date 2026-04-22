# Branching Strategy (Main-Based)

## 1. 기본 브랜치

| 브랜치 | 역할 |
| ------ | ------ |
| `main` | 기본 통합 브랜치. 모든 작업 브랜치의 시작점이자 머지 대상 |

## 2. 브랜치 타입

모든 작업 브랜치는 `main`에서 시작한다.

형식:

```text
<prefix>/<short-description>
```

예시:

```text
feature/calendar-sqlite-cache
refactor/calendar-cache-layer
fix/calendar-timeout-message
chore/update-bootstrap-docs
docs/refresh-readme
```

### Prefix 종류

| Prefix | 용도 |
| ------ | ------ |
| `feature` | 신규 기능 개발 |
| `refactor` | 리팩토링, 구조 개선 |
| `fix` | 일반 버그 수정 |
| `chore` | 설정, 스크립트, 의존성, 운영 보조 작업 |
| `test` | 테스트 코드 추가 또는 수정 |
| `docs` | 문서 수정 |
| `hotfix` | 빠른 운영 대응이 필요한 긴급 수정 |

## 3. 기본 작업 흐름

1. `main` 브랜치로 이동하고 최신 상태를 맞춘다

```bash
git checkout main
git pull origin main
```

2. 작업 브랜치를 생성한다

```bash
git checkout -b feature/calendar-sqlite-cache
```

3. 개발 및 커밋을 진행한다
4. `main` 대상으로 Pull Request를 생성한다
5. 리뷰와 확인이 끝나면 `main`으로 머지한다

## 4. hotfix 브랜치

긴급 수정도 동일하게 `main`에서 시작한다.

형식:

```text
hotfix/<short-description>
```

예시:

```text
hotfix/calendar-auth-failure
```

흐름:

1. `main` 브랜치에서 `hotfix` 브랜치를 만든다
2. 수정 및 검증을 진행한다
3. `main` 대상으로 Pull Request를 생성한다
4. 검토 후 `main`으로 머지한다

## 5. Pull Request 규칙

- PR 제목은 작업 내용을 짧고 명확하게 적는다
- 가능하면 하나의 PR에는 하나의 목적만 담는다
- 확인 가능한 테스트 또는 검증 결과를 함께 남긴다
- 리뷰 전에는 범위를 넓히지 않는다

## 6. 머지 전략

- 기본적으로 `main`으로 Squash Merge를 사용한다
- 히스토리를 보존해야 하는 특별한 경우만 Merge Commit을 사용한다

## 7. 금지 사항

- `main` 브랜치에 직접 커밋하지 않는다
- 관련 없는 변경을 한 브랜치에 섞지 않는다
- 오래된 작업 브랜치를 기준으로 새 작업을 시작하지 않는다
