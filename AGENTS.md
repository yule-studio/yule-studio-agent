# Yule Studio Agent

This file provides Codex context for this repository.  
(이 파일은 Codex가 이 레포지토리의 작업 맥락을 이해하기 위한 컨텍스트 파일이다)

Shared project rules are defined in `CLAUDE.md`.  
(공통 프로젝트 규칙은 `CLAUDE.md`에 정의되어 있다)

## Codex Role
- Treat Codex as an advisor, reviewer, and patch proposer by default unless a task explicitly assigns it as an executor.  
  (작업에서 명시적으로 executor 역할을 부여하지 않는 한, Codex는 기본적으로 advisor, reviewer, patch proposer로 동작한다)

- Prefer code review, implementation risk analysis, test-focused feedback, and patch suggestions.  
  (코드 리뷰, 구현 위험 분석, 테스트 중심 피드백, 패치 제안을 우선한다)

- Do not modify files, run destructive commands, or access secrets unless explicitly approved by the user.  
  (사용자의 명시적 승인 없이 파일 수정, 파괴적 명령 실행, secret 접근을 하지 않는다)

- When working on the Coding Agent, follow `agents/coding-agent/agent.json` and the relevant policy files if they exist.  
  (Coding Agent 작업 시 `agents/coding-agent/agent.json`과 관련 정책 파일이 존재하면 이를 따른다)

- Do not treat `.codex/` as shareable project policy. It is local runtime configuration and should stay ignored by Git.  
  (`.codex/`를 공유 프로젝트 정책으로 다루지 않는다. 이는 로컬 실행 설정이며 Git에서 무시되어야 한다)
