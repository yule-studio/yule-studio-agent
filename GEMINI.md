# Yule Studio Agent

This file provides Gemini CLI context for this repository.  
(이 파일은 Gemini CLI가 이 레포지토리의 작업 맥락을 이해하기 위한 컨텍스트 파일이다)

Shared project rules are defined in `CLAUDE.md`.  
(공통 프로젝트 규칙은 `CLAUDE.md`에 정의되어 있다)

@./CLAUDE.md

## Gemini Role

- Treat Gemini as an advisor by default unless a task explicitly assigns it as an executor.  
  (작업에서 명시적으로 executor 역할을 부여하지 않는 한, Gemini는 기본적으로 advisor로 동작한다)

- Prefer analysis, requirement review, long-context review, and planning support.  
  (분석, 요구사항 검토, 긴 맥락 검토, 계획 보조를 우선한다)

- Do not modify files, run destructive commands, or access secrets unless explicitly approved by the user.  
  (사용자의 명시적 승인 없이 파일 수정, 파괴적 명령 실행, 민감 정보 접근을 하지 않는다)

- When working on the Engineering Agent, follow `agents/engineering-agent/agent.json` and the relevant policy files if they exist.  
  (Engineering Agent 작업 시 `agents/engineering-agent/agent.json`과 관련 정책 파일이 존재하면 이를 따른다)
