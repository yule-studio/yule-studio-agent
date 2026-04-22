# Planning Agent Workflow

## Purpose
The Planning Agent creates a daily plan from multiple personal and project data sources.  
(Planning Agent는 여러 개인/프로젝트 데이터 소스에서 daily plan을 생성한다)

## Default Flow
1. Load the target date.  
   (대상 날짜를 정한다)

2. Read available planning inputs.  
   (사용 가능한 planning 입력을 읽는다)
   - calendar events
   - calendar todos
   - GitHub open issues
   - reminder or review items

3. Normalize all inputs into shared planning records.  
   (모든 입력을 공통 planning 레코드로 정규화한다)

4. Rank candidate tasks with explainable rules.  
   (설명 가능한 규칙으로 작업 후보의 우선순위를 매긴다)

5. Parse optional sub-blocks from timed event descriptions.  
   (시간이 있는 이벤트 설명에서 선택적 세부 블록을 파싱한다)

6. Build suggested focus blocks around fixed calendar events.  
   (고정 일정 사이에 추천 집중 시간 블록을 만든다)

7. Generate reminder checkpoints before execution blocks end.  
   (세부 실행 블록 종료 전에 reminder checkpoint를 생성한다)

8. Produce outputs for:  
   (다음 용도의 출력을 만든다)
   - daily-plan
   - Discord briefing
   - Coding Agent handoff

## Prioritization Rules
- Overdue work is ranked above non-overdue work.  
  (기한이 지난 작업은 그렇지 않은 작업보다 우선한다)

- Today-bound work is ranked above future work.  
  (오늘 처리해야 하는 작업은 미래 작업보다 우선한다)

- Fixed schedule items are not reordered; they only constrain planning windows.  
  (고정 일정은 재정렬하지 않고 planning 가능한 시간 범위를 제한하는 데만 사용한다)

- Completed todos are excluded from candidate work lists.  
  (완료된 todo는 작업 후보 목록에서 제외한다)

- GitHub issues can become Coding Agent handoff targets even when they are not scheduled into today's focus blocks.  
  (GitHub issue는 오늘 시간 블록에 배치되지 않더라도 Coding Agent handoff 대상이 될 수 있다)

- Description-based execution blocks refine a fixed event instead of replacing it.  
  (description 기반 세부 실행 블록은 고정 일정을 대체하지 않고 보강한다)

## Failure Handling
- If one source fails, continue with the remaining sources.  
  (하나의 소스가 실패해도 나머지 소스로 계속 진행한다)

- Record source-level warnings in the plan output.  
  (소스 단위 warning을 plan 출력에 기록한다)

- Do not fabricate missing records.  
  (없는 레코드를 임의로 생성하지 않는다)
