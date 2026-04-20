# Yule Studio Agent

Yule Studio Agent는 개인 홈서버에서 여러 AI 에이전트와 개발 도구를 조율하기 위한 개인 에이전트 운영 플랫폼입니다.

이 프로젝트는 GitHub 프로젝트, 이슈, 문서, 작업 흐름, 코드 변경, 리뷰, 운영 알림을 하나의 흐름으로 관리하는 개인 비서이자 개발팀 운영 시스템을 목표로 합니다.

## Concept

Yule Studio Agent는 단일 챗봇이 아니라 여러 역할의 에이전트를 조율하는 오케스트레이터입니다.

예상되는 에이전트 역할:

- Coding Agent: 구현, 테스트, PR 초안
- Review Agent: 구조, 예외 처리, 성능, 위험 포인트 점검
- Troubleshooting Agent: 로그, 예외, 원인 후보 분석
- Ops Agent: 장애 탐지, 메트릭, 배포 이력, 알림
- Docs Agent: ADR, 트러블슈팅 문서, 회고, README 정리

## Repository Structure

```text
.
├── AGENTS.md
├── CLAUDE.md
├── GEMINI.md
├── agents/
│   └── coding-agent/
│       ├── CLAUDE.md
│       └── agent.json
├── policies/
│   ├── common/
│   └── coding/
├── runs/
└── src/
    └── yule_orchestrator/
```

## Setup

현재 Python 코드는 표준 라이브러리만 사용합니다. 별도의 Python 패키지 의존성은 아직 없습니다.

macOS 기준 빠른 세팅:

```bash
./scripts/bootstrap
```

선택 AI CLI까지 함께 설치하려면:

```bash
./scripts/bootstrap --all
```

자동화하지 않는 수동 인증 단계:

```bash
gh auth login
claude
codex
gemini
copilot
```

Ollama는 필요할 때 서버를 실행합니다.

```bash
open -a Ollama
# or
ollama serve
```

## Commands

에이전트 컨텍스트 로드:

```bash
PYTHONPATH=src python3 -m yule_orchestrator context coding-agent
```

로컬 환경 진단:

```bash
PYTHONPATH=src python3 -m yule_orchestrator doctor
```

editable install 이후에는 다음처럼 실행할 수 있습니다.

```bash
yule context coding-agent
yule doctor
```

## Optional Local Tools

아래 도구들은 에이전트 운영에 연결할 수 있는 외부 CLI입니다. 모든 기능이 항상 필요한 것은 아니며, 사용하는 역할에 따라 선택적으로 설치합니다.

```bash
brew install gh
brew install codex
brew install gemini-cli
brew install ollama
brew install copilot-cli
```

Claude Code는 npm 설치를 사용합니다.

```bash
npm install -g @anthropic-ai/claude-code
```

Ollama 모델 예시:

```bash
ollama run gemma3
```

## Local Files

아래 파일과 폴더는 로컬 설정, 실행 기록, 인증 정보가 포함될 수 있으므로 Git에 올리지 않습니다.

```text
.claude/
.codex/
.gemini/
.env
runs/*
```

`runs/.gitkeep`만 폴더 유지를 위해 커밋합니다.
