# Coding Agent Team Structure

## Overview
Coding Agent는 단일 에이전트가 아니라 **엔지니어링 부서(Department)** 형태로 구성된다.
부서 폴더(`agents/coding-agent/`)가 게이트웨이 역할을 하고, 그 아래 폴더들이 부서 안의 개별 역할(Role) 멤버다.

```
agents/
└── coding-agent/                 ← Department gateway (게이트웨이)
    ├── agent.json                  type=department, members=[...]
    ├── CLAUDE.md
    ├── frontend-engineer/        ← Role member
    ├── backend-engineer/
    ├── designer/
    ├── qa-engineer/
    └── tech-lead/
```

## Why a Department, Not a Flat List of Agents
1. **요청 라우팅이 자연스럽다.** planning-agent나 사용자가 "코딩 작업 필요"라고 하면 부서장(coding-agent)에게만 보내면 된다. 부서장이 어떤 멤버가 받을지 결정한다.
2. **크로스팀 작업이 한 곳에서 조율된다.** 회원가입 같은 기능은 backend + frontend + designer + qa가 다 같이 움직이는데, 부서장이 한 번에 분배·합의·회신을 책임진다.
3. **외부 인터페이스가 단순하다.** 다른 시스템(Discord, planning-agent, orchestrator)은 부서장과만 대화한다. 내부 멤버 구성을 알 필요가 없다.
4. **확장이 쉽다.** 나중에 product-agent, marketing-agent 같은 새 부서를 같은 패턴으로 추가하면 된다.

## How Members Share LLM Backends
멤버 폴더의 `agent.json`은 **개별 LLM 백엔드를 직접 소유하지 않는다**. 모든 멤버는 부서 단위 `agent.json`의 `participants`/`integrations` 풀을 공유한다.

- 부서장이 작업 성격을 보고 어떤 executor(Claude / Codex / Gemini / Ollama / GitHub Copilot)를 쓸지 결정
- 멤버는 자기 책임 범위(responsibilities)와 입력/출력 계약만 정의
- 멤버 폴더의 `runner: null`은 "현재 골격 단계라 실행 백엔드는 비어 있음"을 뜻함

## Role Members (현재 골격)

| Member | 책임 요약 |
|---|---|
| `tech-lead` | 작업 분해, 의존 순서, 멤버 간 합의 조율, 외부 회신 |
| `designer` | 화면 흐름·구조·시각 가이드 결정 |
| `backend-engineer` | 도메인 모델, 서비스, API, 데이터 계층 구현 |
| `frontend-engineer` | UI 컴포넌트, 사용자 흐름 코드, 데이터 연결 |
| `qa-engineer` | 수용 기준, 회귀 시나리오, 테스트 우선순위 |

## Typical Collaboration Flow (참조용 — 아직 자동화 X)
1. 게이트웨이가 요청 수신 → `tech-lead`에게 작업 분해 요청
2. `tech-lead`가 의존 순서 결정 → 필요한 멤버 호출 순서 결정 (예: designer → backend → frontend → qa)
3. `designer`가 화면/흐름 결정 산출
4. `backend-engineer`가 도메인/API 작업
5. `frontend-engineer`가 UI 옮김
6. `qa-engineer`가 수용 기준과 회귀 시나리오로 검증
7. `tech-lead`가 종합 → 게이트웨이가 외부에 회신

## Phase
현재 단계는 **골격(skeleton)** 이다. 실제 LLM 호출, 멤버 간 메시지 전달, 자동 워크플로우는 아직 구현되지 않았다.

다음 단계 후보:
- 멤버 호출용 Python 러너 추상화 (Claude Code subprocess, Codex subprocess 등)
- 멤버 간 메시지 프로토콜과 디스패처
- 게이트웨이 자동 분배 로직
- Discord 통합(작업 시작/회신 메시지)
- 추가 부서(`product-agent`, `marketing-agent` 등) 골격

## Boundaries
- 모든 코드 변경은 부서 단위 `write_policy`를 따른다(사용자 승인 필수, executor 1명).
- 멤버는 부서 외부와 직접 대화하지 않는다. 모든 외부 회신은 게이트웨이를 거친다.
- Coding Agent 외 다른 부서가 만들어지면, 부서 간 협업은 `orchestrator-agent` 같은 상위 조율자를 통해 이루어진다(아직 미구현).
