# Planning Agent Architecture

## Purpose
Describe how the Planning Agent coordinates data sources, planning logic, and AI roles.  
(Planning Agent가 데이터 소스, planning 로직, AI 역할을 어떻게 조율하는지 설명한다)

## Current MVP Shape
The current MVP uses:
- structured input contracts
- deterministic prioritization rules
- reusable daily-plan output

This means the Planning Agent can already:
- read today's schedule
- read today's todos
- read open GitHub issues
- read reminder items from JSON
- build a prioritized daily plan
- parse timed sub-blocks from event descriptions
- generate pre-end checkpoints for those sub-blocks
- produce a Discord-ready summary
- choose Coding Agent handoff candidates

## Data Flow
1. **Input collection**
   - calendar events
   - calendar todos
   - GitHub open issues
   - reminder items

2. **Normalization**
   - all sources are mapped into shared planning structures
   - warnings and source status are preserved

3. **Rule-based planning**
   - overdue work first
   - today-bound work next
   - fixed events constrain focus windows
   - coding-related tasks are marked for handoff

4. **Output generation**
   - daily-plan JSON
   - text rendering
   - Discord briefing text
   - execution checkpoints
   - Coding Agent handoff candidates

## AI Role Coordination

### Ollama
- default executor for Planning Agent
- privacy-first summarizer
- future role:
  - rewrite daily plan into more natural guidance
  - generate softer, more human daily briefings
  - propose alternative task orderings

### Claude
- planning advisor
- useful for:
  - refining contracts
  - checking whether planning output is actionable
  - clarifying ambiguous requirements

### Gemini
- long-context planning advisor
- useful for:
  - reading larger history or notes
  - comparing more sources at once
  - planning across longer time horizons

### Codex
- reviewer and workflow advisor
- useful for:
  - validating planning logic structure
  - checking schema consistency
  - reviewing Coding Agent handoff shape

## Recommended Orchestration

### Phase 1: Rule-first
- Python builds the first daily-plan
- no heavy model dependency required
- output stays stable and testable

### Phase 2: Ollama enhancement
- Ollama receives structured plan JSON
- Ollama returns:
  - recommended_order_reason
  - top_risks
  - discord_tone_briefing
  - suggested_first_step
  - more human checkpoint-aware briefing

### Phase 3: Multi-agent review
- Claude or Gemini may review the generated plan
- Codex may review handoff formatting for Coding Agent

### Phase 4: Operational channel delivery
- Discord receives the final briefing
- user approves one or more coding tasks
- approved tasks are transformed into Coding Agent input

## Boundaries
- Planning Agent recommends work; it does not execute code changes.
- Planning Agent may mark Coding Agent candidates, but it does not modify repositories.
- Reminder scheduling logic is intentionally outside this MVP.
