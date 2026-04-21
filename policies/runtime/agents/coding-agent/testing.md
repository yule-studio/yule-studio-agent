# Coding Testing Policy

## Purpose
This policy defines how Coding Agent should handle tests and validation.  
(이 정책은 Coding Agent가 테스트와 검증을 다루는 방식을 정의한다)

## Rules
- Discover existing test, lint, typecheck, and build commands before inventing new ones.  
  (새 명령을 만들기 전에 기존 테스트, lint, typecheck, build 명령을 찾는다)

- Run the most relevant checks for the changed area when practical.  
  (가능하면 변경된 영역과 가장 관련 있는 검사를 실행한다)

- Do not hide failed checks. Report failures with the command, result, and likely next step.  
  (실패한 검사를 숨기지 말고 명령, 결과, 다음 조치 후보를 보고한다)

- If checks cannot be run, explain why and describe the remaining risk.  
  (검사를 실행할 수 없으면 이유와 남은 위험을 설명한다)

- Avoid broad or expensive validation unless the task risk justifies it.  
  (작업 위험도가 정당화하지 않는 한 광범위하거나 비용이 큰 검증은 피한다)
