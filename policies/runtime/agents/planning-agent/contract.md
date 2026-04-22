# Planning Agent Contract

## Goal
Define the shared input/output contract used by the Planning Agent.  
(Planning Agent가 사용하는 공통 입력/출력 계약을 정의한다)

This contract is the basis for:
- calendar events
- calendar todos (VTODO)
- GitHub open issues
- review/reminder items
- daily-plan
- Discord briefing
- Coding Agent handoff

## Input Contract

### Shared Envelope
- `plan_date`: target date in `YYYY-MM-DD`
- `timezone`: local timezone string
- `source_statuses`: source-level status list
- `warnings`: non-fatal warnings

### Input Sources

#### `calendar_events`
- fixed schedule blocks
- important fields:
  - `item_uid`
  - `title`
  - `start`
  - `end`
  - `all_day`
  - `calendar_name`
  - `description`
  - `last_modified`

#### `calendar_todos`
- todo work candidates
- important fields:
  - `item_uid`
  - `title`
  - `start`
  - `due`
  - `status`
  - `completed`
  - `priority`
  - `percent_complete`
  - `description`

#### `github_issues`
- coding / project work candidates
- important fields:
  - `number`
  - `repository`
  - `title`
  - `url`
  - `owner`
  - `scope`

#### `reminders`
- review or habit-oriented reminder items
- important fields:
  - `item_id`
  - `title`
  - `description`
  - `due_date`
  - `priority_hint`
  - `estimated_minutes`
  - `tags`

## Output Contract

### `summary`
- fixed event count
- all-day event count
- todo count
- GitHub issue count
- reminder count
- recommended task count
- available focus minutes

### `prioritized_tasks`
- ordered candidate task list
- important fields:
  - `task_id`
  - `source_type`
  - `title`
  - `due_date`
  - `priority_score`
  - `priority_level`
  - `estimated_minutes`
  - `reasons`
  - `coding_candidate`

### `suggested_time_blocks`
- focus blocks inserted around fixed events
- important fields:
  - `start`
  - `end`
  - `block_type`
  - `title`
  - `task_id`
  - `locked`

### `execution_blocks`
- optional sub-blocks parsed from timed event descriptions
- important fields:
  - `block_id`
  - `source_event_uid`
  - `source_event_title`
  - `start`
  - `end`
  - `title`
  - `description`

### `checkpoints`
- reminder points generated before execution blocks end
- important fields:
  - `checkpoint_id`
  - `remind_at`
  - `source_event_uid`
  - `block_id`
  - `block_title`
  - `prompt`

### `coding_agent_handoff`
- top coding-related tasks to pass to Coding Agent

### `discord_briefing`
- short text payload for Discord reporting
- may be generated either by rules or by Ollama

## Example JSON

```json
{
  "inputs": {
    "plan_date": "2026-04-22",
    "timezone": "KST",
    "source_statuses": [
      {
        "source_id": "calendar",
        "source_type": "calendar",
        "ok": true,
        "item_count": 7,
        "warning": null
      }
    ],
    "warnings": [],
    "calendar_events": [
      {
        "item_uid": "event-1",
        "title": "업무 수행",
        "start": "2026-04-22T09:00:00+09:00",
        "end": "2026-04-22T12:00:00+09:00",
        "all_day": false,
        "calendar_name": "내 캘린더",
        "source": "naver-caldav",
        "description": "",
        "last_modified": "2026-04-22T08:00:00+09:00"
      }
    ],
    "calendar_todos": [
      {
        "item_uid": "todo-1",
        "title": "오늘 해야 할 업무",
        "start": null,
        "due": "2026-04-22",
        "start_all_day": false,
        "due_all_day": true,
        "status": "NEEDS-ACTION",
        "completed": false,
        "completed_at": null,
        "priority": 0,
        "percent_complete": null,
        "calendar_name": "내 할 일",
        "source": "naver-caldav",
        "description": "",
        "last_modified": "2026-04-22T07:30:00+09:00"
      }
    ],
    "github_issues": [
      {
        "number": 12,
        "repository": "yule-studio/yule-studio-agent",
        "title": "Planning Agent 입력/출력 포맷 정의",
        "url": "https://github.com/yule-studio/yule-studio-agent/issues/12",
        "owner": "yule-studio",
        "scope": "org:yule-studio"
      }
    ],
    "reminders": [
      {
        "item_id": "review-java-record",
        "title": "Record 정리 복습",
        "description": "DTO 관련 복습",
        "due_date": "2026-04-22",
        "priority_hint": "medium",
        "estimated_minutes": 30,
        "tags": ["review", "java"]
      }
    ]
  },
  "daily_plan": {
    "plan_date": "2026-04-22",
    "timezone": "KST",
    "summary": {
      "fixed_event_count": 1,
      "all_day_event_count": 0,
      "todo_count": 1,
      "github_issue_count": 1,
      "reminder_count": 1,
      "recommended_task_count": 3,
      "available_focus_minutes": 480
    },
    "prioritized_tasks": [
      {
        "task_id": "todo:todo-1",
        "source_type": "calendar_todo",
        "title": "오늘 해야 할 업무",
        "due_date": "2026-04-22",
        "priority_score": 88,
        "priority_level": "high",
        "estimated_minutes": 60,
        "reasons": ["due today", "calendar todo"],
        "coding_candidate": false
      }
    ],
    "suggested_time_blocks": [
      {
        "start": "2026-04-22T13:00:00+09:00",
        "end": "2026-04-22T14:00:00+09:00",
        "block_type": "focus",
        "title": "오늘 해야 할 업무",
        "task_id": "todo:todo-1",
        "locked": false
      }
    ],
    "execution_blocks": [
      {
        "block_id": "block-1",
        "source_event_uid": "event-1",
        "source_event_title": "업무 수행",
        "start": "2026-04-22T09:00:00+09:00",
        "end": "2026-04-22T10:00:00+09:00",
        "title": "할일 목록 정리",
        "description": "- 9시 ~ 10시 : 할일 목록 정리"
      }
    ],
    "checkpoints": [
      {
        "checkpoint_id": "checkpoint-1",
        "remind_at": "2026-04-22T09:55:00+09:00",
        "source_event_uid": "event-1",
        "source_event_title": "업무 수행",
        "block_id": "block-1",
        "block_title": "할일 목록 정리",
        "block_start": "2026-04-22T09:00:00+09:00",
        "block_end": "2026-04-22T10:00:00+09:00",
        "prompt": "09:55 체크: '할일 목록 정리' 마무리됐는지 확인해 주세요. 10:00부터 '업무 수행 (회의 없음)'가 이어집니다.",
        "kind": "wrap_up"
      }
    ],
    "coding_agent_handoff": [
      {
        "task_id": "issue:yule-studio/yule-studio-agent#12",
        "source_type": "github_issue",
        "title": "Planning Agent 입력/출력 포맷 정의",
        "due_date": null,
        "priority_score": 45,
        "priority_level": "medium",
        "estimated_minutes": 90,
        "reasons": ["open GitHub issue", "coding candidate"],
        "coding_candidate": true
      }
    ],
    "discord_briefing": "오늘은 고정 일정 1건, 우선 작업 3건이 있습니다. 먼저 오늘 해야 할 업무를 처리하고, 이후 Planning Agent 포맷 정의 이슈를 Coding Agent 후보로 넘기는 흐름을 추천합니다.",
    "briefing_source": "rules"
  }
}
```
