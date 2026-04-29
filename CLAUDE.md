# Yule Studio Agent

## Purpose
This repository is a personal agent platform for managing the user's GitHub projects, issues, documents, and workflows across multiple repositories.  
(이 레포지토리는 여러 GitHub 프로젝트의 이슈, 문서, 작업 흐름을 관리하기 위한 개인 에이전트 플랫폼이다)

Current priority:
- Build the `engineering-agent` MVP.  
  (현재는 `engineering-agent` MVP 개발에만 집중한다)

## Platform Direction
- This repository will host multiple specialized agents.  
  (이 레포는 여러 개의 역할별 전문 에이전트를 포함하는 플랫폼으로 구성한다)

- Each agent must have a clear and focused responsibility.  
  (각 에이전트는 명확하고 좁은 책임 범위를 가져야 한다)

- Do not mix responsibilities across agents unless explicitly required.  
  (명시적인 필요가 없으면 에이전트 간 책임을 섞지 않는다)

- Shared principles are defined in this root `CLAUDE.md`.  
  (공통 원칙은 루트 `CLAUDE.md`에서 정의한다)

- Agent-specific rules must be defined in each agent directory's `CLAUDE.md`.  
  (에이전트별 세부 규칙은 각 에이전트 디렉터리의 `CLAUDE.md`에서 정의한다)

## Core Safety Rules
- Never commit secrets, credentials, private keys, or local runtime state.  
  (비밀 정보, 인증 정보, 개인 키, 로컬 실행 상태는 절대 커밋하지 않는다)

- Human approval is required before destructive commands, production deployments, or secret access.  
  (파괴적 명령, 프로덕션 배포, 민감한 인증 정보 접근 전에는 반드시 사람의 승인이 필요하다)
