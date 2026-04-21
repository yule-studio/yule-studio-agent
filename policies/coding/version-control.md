# Coding Version Control Policy

## Purpose
This policy defines how Coding Agent should handle branches, commits, pull requests, and repository naming rules.
(이 정책은 Coding Agent가 브랜치, 커밋, Pull Request, 저장소 네이밍 규칙을 어떻게 다뤄야 하는지 정의한다)

## Rules
- Follow the repository branch strategy documented in `docs/common/v1/policy/BRANCH_STRATEGY.md` when that document exists.
  (`docs/common/v1/policy/BRANCH_STRATEGY.md`가 존재하면 해당 브랜치 전략을 따른다)

- Follow the repository commit convention documented in `docs/common/v1/policy/COMMIT_CONVENTION.md` when that document exists.
  (`docs/common/v1/policy/COMMIT_CONVENTION.md`가 존재하면 해당 커밋 규칙을 따른다)

- Follow the repository naming convention documented in `docs/common/v1/policy/NAMING_CONVENTION.md` when that document exists.
  (`docs/common/v1/policy/NAMING_CONVENTION.md`가 존재하면 해당 네이밍 규칙을 따른다)

- Prefer branch-based work. Do not commit directly to protected branches such as `main` or `dev`.
  (브랜치 기반 작업을 우선하고 `main`, `dev` 같은 보호 브랜치에 직접 커밋하지 않는다)

- Use one clear purpose per commit.
  (하나의 커밋에는 하나의 명확한 목적만 담는다)

- Use Gitmoji-based commit messages when the repository defines that convention.
  (레포지토리가 해당 규칙을 정의하면 Gitmoji 기반 커밋 메시지를 사용한다)

- If the branch strategy requires a Jira ticket key and no ticket key is available, pause before creating a new branch and ask the user for the intended key.
  (브랜치 전략이 Jira 티켓 키를 요구하는데 티켓 키가 없으면 새 브랜치 생성 전에 멈추고 사용자에게 키를 확인한다)

- Treat large rename or move operations as separate commits when practical.
  (가능하면 대규모 리네임이나 이동 작업은 별도 커밋으로 분리한다)
