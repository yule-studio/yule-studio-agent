from __future__ import annotations

import json
from datetime import datetime
from typing import Sequence
from urllib import error, request

from .models import PlanningBlockBriefing, PlanningCheckpoint, PlanningTaskCandidate, PlanningTimeBlock


def generate_human_briefing(
    plan_date: str,
    summary_line: str,
    fixed_schedule: Sequence[PlanningTimeBlock],
    prioritized_tasks: Sequence[PlanningTaskCandidate],
    time_block_briefings: Sequence[PlanningBlockBriefing],
    checkpoints: Sequence[PlanningCheckpoint],
    model: str = "gemma3:latest",
    endpoint: str = "http://localhost:11434",
    timeout_seconds: int = 20,
) -> str:
    prompt = _build_prompt(
        plan_date=plan_date,
        summary_line=summary_line,
        fixed_schedule=fixed_schedule,
        prioritized_tasks=prioritized_tasks,
        time_block_briefings=time_block_briefings,
        checkpoints=checkpoints,
    )
    return generate_ollama_text(
        prompt,
        model=model,
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
        temperature=0.4,
        empty_error_message="Ollama briefing response was empty.",
        request_label="briefing",
    )


def generate_ollama_text(
    prompt: str,
    *,
    model: str = "gemma3:latest",
    endpoint: str = "http://localhost:11434",
    timeout_seconds: int = 20,
    temperature: float = 0.4,
    empty_error_message: str = "Ollama response was empty.",
    request_label: str = "request",
) -> str:
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req = request.Request(
        endpoint.rstrip("/") + "/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ValueError(f"Ollama {request_label} request failed: {exc}") from exc

    result = data.get("response")
    if not isinstance(result, str) or not result.strip():
        raise ValueError(empty_error_message)
    return result.strip()


def _build_prompt(
    plan_date: str,
    summary_line: str,
    fixed_schedule: Sequence[PlanningTimeBlock],
    prioritized_tasks: Sequence[PlanningTaskCandidate],
    time_block_briefings: Sequence[PlanningBlockBriefing],
    checkpoints: Sequence[PlanningCheckpoint],
) -> str:
    schedule_lines = [
        f"- {_format_time_range(block.start, block.end)} | {block.title}"
        for block in fixed_schedule[:5]
    ] or ["- 고정 일정 없음"]
    task_lines = [
        f"- {task.title} | 우선순위={_priority_label(task.priority_level)} | 이유={_summarize_reasons(task.reasons)}"
        for task in prioritized_tasks[:5]
    ] or ["- 우선 작업 없음"]
    block_lines = [
        f"- {_format_time_range(briefing.start, briefing.end)} | {briefing.title} | {briefing.briefing}"
        for briefing in time_block_briefings[:5]
    ] or ["- 시간대별 브리핑 없음"]
    checkpoint_lines = [
        f"- {datetime.fromisoformat(checkpoint.remind_at).strftime('%H:%M')} | {checkpoint.block_title} | {checkpoint.prompt}"
        for checkpoint in checkpoints[:5]
    ] or ["- 체크포인트 없음"]

    return f"""당신은 개인 Planning Agent의 브리핑 작성자입니다.
다음 daily-plan 입력을 보고 한국어로 자연스럽고 실용적인 아침 브리핑을 작성하세요.

조건:
- 2~4개의 짧은 문단으로 쓸 것
- 각 문단은 1~2문장으로 짧게 유지할 것
- 너무 딱딱하거나 과장하지 말 것
- 가장 먼저 할 일 1개를 분명하게 추천할 것
- 가능하면 2순위, 3순위는 별도 문장이나 bullet로 숨이 쉬게 이어서 설명할 것
- 시간 블록이 있으면 어느 시간대에 무엇을 하면 좋을지 짚을 것
- 체크포인트가 있으면 마지막 문단에서 짧게 한 줄로 언급할 것
- 내부 점수, 우선순위 계산 숫자, ISO datetime 원문은 절대 노출하지 말 것
- 사용자가 입력하지 않은 수치 평가(예: 95점, 87점)를 만들어내지 말 것
- 문단 사이에는 반드시 빈 줄 하나를 넣을 것

날짜:
{plan_date}

헤드라인 요약:
{summary_line}

고정 일정:
{chr(10).join(schedule_lines)}

우선 작업:
{chr(10).join(task_lines)}

시간대별 브리핑 초안:
{chr(10).join(block_lines)}

체크포인트:
{chr(10).join(checkpoint_lines)}
"""


def _format_time_range(start_value: str, end_value: str) -> str:
    start_label = datetime.fromisoformat(start_value).strftime("%H:%M")
    end_label = datetime.fromisoformat(end_value).strftime("%H:%M")
    return f"{start_label}~{end_label}"


def _priority_label(value: str) -> str:
    return {
        "high": "높음",
        "medium": "중간",
        "low": "낮음",
    }.get(value, value)


def _summarize_reasons(reasons: Sequence[str]) -> str:
    filtered = [reason.strip() for reason in reasons if reason.strip()]
    if not filtered:
        return "특별한 사유 없음"
    return ", ".join(filtered[:3])
