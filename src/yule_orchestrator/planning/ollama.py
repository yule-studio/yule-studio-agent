from __future__ import annotations

import json
from typing import Sequence
from urllib import error, request

from .models import PlanningCheckpoint, PlanningTaskCandidate, PlanningTimeBlock


def generate_human_briefing(
    plan_date: str,
    fixed_schedule: Sequence[PlanningTimeBlock],
    prioritized_tasks: Sequence[PlanningTaskCandidate],
    checkpoints: Sequence[PlanningCheckpoint],
    model: str = "gemma3:latest",
    endpoint: str = "http://localhost:11434",
    timeout_seconds: int = 20,
) -> str:
    prompt = _build_prompt(
        plan_date=plan_date,
        fixed_schedule=fixed_schedule,
        prioritized_tasks=prioritized_tasks,
        checkpoints=checkpoints,
    )
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.4
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
        raise ValueError(f"Ollama briefing request failed: {exc}") from exc

    result = data.get("response")
    if not isinstance(result, str) or not result.strip():
        raise ValueError("Ollama briefing response was empty.")
    return result.strip()


def _build_prompt(
    plan_date: str,
    fixed_schedule: Sequence[PlanningTimeBlock],
    prioritized_tasks: Sequence[PlanningTaskCandidate],
    checkpoints: Sequence[PlanningCheckpoint],
) -> str:
    schedule_lines = [
        f"- {block.start} -> {block.end} | {block.title}"
        for block in fixed_schedule[:5]
    ] or ["- 고정 일정 없음"]
    task_lines = [
        f"- {task.title} | {task.priority_level} | score={task.priority_score} | 이유={', '.join(task.reasons)}"
        for task in prioritized_tasks[:5]
    ] or ["- 우선 작업 없음"]
    checkpoint_lines = [
        f"- {checkpoint.remind_at} | {checkpoint.block_title} | {checkpoint.prompt}"
        for checkpoint in checkpoints[:5]
    ] or ["- 체크포인트 없음"]

    return f"""당신은 개인 Planning Agent의 브리핑 작성자입니다.
다음 daily-plan 입력을 보고 한국어로 짧고 자연스러운 아침 브리핑을 작성하세요.

조건:
- 4문장 이하
- 너무 딱딱하지 않게
- 가장 먼저 할 일 1개를 분명하게 추천
- 고정 일정이 있으면 시간 압박을 짚기
- 체크포인트가 있으면 자연스럽게 한 줄 언급

날짜:
{plan_date}

고정 일정:
{chr(10).join(schedule_lines)}

우선 작업:
{chr(10).join(task_lines)}

체크포인트:
{chr(10).join(checkpoint_lines)}
"""
