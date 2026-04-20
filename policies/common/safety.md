# Common Safety Policy

## Purpose
This policy defines safety rules shared by all agents.  
(이 정책은 모든 에이전트가 공유하는 안전 규칙을 정의한다)

## Rules
- Never commit secrets, credentials, private keys, local runtime state, or temporary execution logs.  
  (secret, 인증 정보, 개인 키, 로컬 실행 상태, 임시 실행 로그를 커밋하지 않는다)

- Do not expose `.env` files, local configuration, agent memory, or private user data.  
  (`.env` 파일, 로컬 설정, 에이전트 메모리, 개인 사용자 데이터를 외부에 노출하지 않는다)

- Ask for human approval before destructive commands, production deployments, secret access, or broad repository changes.  
  (파괴적 명령, 프로덕션 배포, secret 접근, 광범위한 레포지토리 변경 전에는 사람의 승인을 받는다)

- Prefer branch and pull request workflows over direct changes to protected branches.  
  (보호된 브랜치에 직접 변경하기보다 브랜치와 Pull Request 기반 흐름을 우선한다)

- Keep outputs auditable with plans, summaries, diffs, test results, or review notes.  
  (계획, 요약, diff, 테스트 결과, 리뷰 노트처럼 추적 가능한 결과물을 남긴다)
