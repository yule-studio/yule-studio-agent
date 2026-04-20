# Coding Workflow Policy

## Purpose
This policy defines the default workflow for Coding Agent implementation tasks.  
(이 정책은 Coding Agent 구현 작업의 기본 흐름을 정의한다)

## Workflow
- Clarify the task, target repository, and expected outcome before implementation.  
  (구현 전에 작업, 대상 레포지토리, 기대 결과를 명확히 한다)

- Inspect the existing codebase and follow local patterns before proposing changes.  
  (변경을 제안하기 전에 기존 코드베이스를 확인하고 로컬 패턴을 따른다)

- Produce an implementation plan before modifying files.  
  (파일을 수정하기 전에 구현 계획을 작성한다)

- Use one write executor per run unless the user explicitly approves a multi-executor workflow.  
  (사용자가 명시적으로 multi-executor workflow를 승인하지 않는 한 하나의 실행에는 하나의 write executor만 사용한다)

- Keep changes focused on the approved task.  
  (승인된 작업 범위에 맞게 변경을 집중한다)

- Summarize what changed, what was verified, and what still needs attention.  
  (변경 사항, 검증한 내용, 아직 주의가 필요한 내용을 요약한다)
