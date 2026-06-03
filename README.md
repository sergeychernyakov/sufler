# sufler

AI-суфлёр для технических собеседований (macOS / Apple Silicon). See **[`SUFLER_SPEC.md`](./SUFLER_SPEC.md)** for the product spec and build order.

## Overview

A Python desktop app (PyQt6 overlay + Claude + screenshots, later microphone STT) with a strict, automated quality toolchain: pre-commit hooks, linters, formatters, type checking, security scans, tests/coverage, and a one-command local quality gate (`bin/ci`).

## Features

**Product** — see **[`docs/DEVELOPMENT_PLAN.md`](./docs/DEVELOPMENT_PLAN.md)** for the build order:

- **Stealth overlay** (PyQt6): translucent, always-on-top, with click-through, opacity & compact modes and a panic-hide hotkey
- **Screenshot → Claude**: multimodal request (text + screen image) with streamed answers; `coach` / `answer` modes
- **Manual question input** + **global hotkeys** (incl. panic)
- **Live STT** (MLX Whisper): microphone → partial/final transcription → 30–60 s rolling context
- **Loopback capture** (Phase 7): point STT at a virtual input device (BlackHole) to transcribe the interviewer

**Engineering:**

- **Quality Gates**: pre-commit hooks + `bin/ci` running isort, black, ruff, pylint (≥9.5), mypy, bandit, pip-audit, secret scan, and pytest + coverage (90 %+)
- **Strict Git Workflow**: protected `main`, Conventional Commits, feature-branch naming (see `docs/COMMIT_CONVENTION.md`)
- **Type hints everywhere** + Google-style docstrings; logging with rotation (10 MB × 5)
- **Claude Code Agents**: pre-configured AI agents for SDLC workflows (planner, architect, coder, reviewer, QA)

## macOS prerequisites

Target: **macOS on Apple Silicon**, Python 3.11+.

Grant these to the app/terminal you launch from (System Settings → Privacy & Security):

- **Screen Recording** — otherwise screenshots come out black
- **Accessibility** — required for global hotkeys (`pynput`)
- **Microphone** — for STT (Phase 5+)

Apple Silicon STT uses whisper.cpp (Metal) or `mlx-whisper` (native) — **not**
faster-whisper (its CTranslate2 backend is CPU-only on Mac).

For **loopback** (transcribing the interviewer rather than your own mic), install
[BlackHole](https://github.com/ExistentialAudio/BlackHole), route the call's audio to it,
and set `SUFLER_LOOPBACK_DEVICE=BlackHole`.

## Setup

### 1. Clone the Repository

Begin by cloning the repository to your local machine:

```bash
git clone https://github.com/sergeychernyakov/sufler.git
cd sufler
```

### 2. Create a Virtual Environment

It's recommended to use a virtual environment to manage dependencies:

```bash
python3 -m venv .venv
```

### 3. Activate the Virtual Environment

Activate the virtual environment before installing dependencies.

- **Linux/MacOS:**

    ```bash
    source .venv/bin/activate
    ```

- **Windows:**

    ```bash
    .venv\Scripts\activate
    ```

### 4. Install Dependencies & Hooks

Recommended — one command bootstraps the venv, installs all deps, and installs the git hooks:

```bash
bin/setup
```

Or manually:

```bash
pip install -r requirements.txt       # runtime (the app)
pip install -r requirements-dev.txt   # quality toolchain
pre-commit install --install-hooks \
  --hook-type pre-commit --hook-type commit-msg \
  --hook-type pre-push --hook-type post-checkout
```

### 5. Configure Environment Variables

The application relies on environment variables for configuration. Create a `.env` file in the root directory with the following content:

```env
APP_ENV=development
```

- Ensure that the `.env` file is **not** committed to version control to protect sensitive information.

### 6. Managing Dependencies

Add new dependencies **by hand** to the right file — never `pip freeze` (it pollutes
the list with transitive packages):

- runtime deps → `requirements.txt`
- dev/quality tools → `requirements-dev.txt`

## Quality Gates

All quality automation is wired into **pre-commit hooks** and a local runner, **`bin/ci`**.

### Run everything locally

```bash
bin/ci            # all gates (scaffold-aware: skips checks with no code/tests yet)
bin/ci --fast     # skip network/slow checks (pip-audit)
```

### Checks

| Stage        | Tools |
|--------------|-------|
| Format       | `black`, `isort` (profile black, line length 120) |
| Lint         | `ruff` (fast), `pylint` (deep, score ≥ 9.5) |
| Types        | `mypy` (`disallow_untyped_defs`) |
| Security     | `bandit`, `pip-audit`, secret scan, `detect-private-key` |
| Tests        | `pytest` + `coverage` (global ≥ 90 %; `llm`/`core` ≥ 95 %, `audio`/`vision` ≥ 90 %) |
| Git policy   | protected `main`, Conventional Commits, branch-name warning |

Configuration lives in `pyproject.toml` (black/isort/ruff/mypy/pytest/coverage/bandit)
and `.pylintrc`. Hooks are defined in `.pre-commit-config.yaml`.

### Hook stages

- **pre-commit**: format, lint, types, security, secret scan, block commits to `main`
- **commit-msg**: Conventional Commit format
- **pre-push**: tests + coverage, `pip-audit`, block pushes to `main`
- **post-checkout**: branch-name convention warning

Run hooks manually against everything:

```bash
pre-commit run --all-files
```

### Git workflow

`main` is protected. Work on feature branches with Conventional Commit messages —
see **[`docs/COMMIT_CONVENTION.md`](./docs/COMMIT_CONVENTION.md)**.


## Usage

### Running the Application

To run the main application:

```bash
python main.py
```

`python main.py` launches the stealth overlay. Phases 1–6 are built (incl. live STT via
MLX Whisper); loopback (Phase 7) is planned (see [`docs/DEVELOPMENT_PLAN.md`](./docs/DEVELOPMENT_PLAN.md)).
Requires `ANTHROPIC_API_KEY` in `.env` and macOS **Screen Recording** + **Accessibility**
(+ **Microphone** for STT) permissions (see above). It will:
1. Show a translucent, always-on-top overlay with a question field, a streamed answer
   area, a "📸 Скрин" button and a manual input field
2. On capture (button or hotkey): hide the overlay, screenshot the screen, and stream
   Claude's answer back into the overlay (`coach` / `answer` modes)
3. Honor stealth controls (opacity, click-through, compact, panic-hide) and global hotkeys

> Logs go to `tmp/logs/`. Without an API key the overlay still launches, but captures error.

### Using the Logger

Import and use the logger in your modules:

```python
from src.helpers.logger import get_logger

logger = get_logger(__name__)
logger.info("Starting process")
logger.error("An error occurred", exc_info=True)
```

## Project Structure

```
.
├── README.md
├── SUFLER_SPEC.md         # Product spec & build order
├── AGENTS.md / CLAUDE.md  # AI assistant instructions (CLAUDE.md -> AGENTS.md)
├── PYTHON_STYLE_GUIDE.md  # Python coding standards
├── pyproject.toml         # black/isort/ruff/mypy/pytest/coverage/bandit config
├── .pylintrc              # pylint config (score >= 9.5)
├── .editorconfig          # editor defaults
├── .pre-commit-config.yaml
├── requirements.txt       # runtime dependencies
├── requirements-dev.txt   # dev/quality toolchain
├── main.py                # Application entry point
├── bin/                   # dev scripts
│   ├── setup              # bootstrap venv + deps + hooks
│   ├── ci                 # run all quality gates locally
│   ├── check_coverage     # per-package coverage thresholds
│   └── hooks/             # git-hook helper scripts
├── docs/
│   ├── COMMIT_CONVENTION.md
│   └── DEVELOPMENT_PLAN.md # phases, architecture, acceptance criteria
├── media/                 # Media assets
├── .claude/              # Claude Code configuration
│   └── agents/           # AI agent definitions
│       ├── SHARED_CONFIG.md      # Common agent configuration
│       ├── planner.md            # Orchestrator agent
│       ├── code-architect.md     # Architecture design agent
│       ├── senior-coder.md       # Implementation agent
│       ├── code-reviewer.md      # Code review agent
│       └── qa-engineer.md        # Quality assurance agent
├── src/
│   ├── config/           # settings (env-based: API key, model, mode, hotkeys)
│   ├── helpers/          # logger (rotation)
│   ├── models/           # Pydantic base + enums
│   ├── ui/               # overlay.py (PyQt6, stealth) ✅
│   ├── vision/           # screenshot.py (screencapture/mss) ✅
│   ├── llm/              # claude.py (multimodal + streaming) ✅
│   ├── audio/            # capture + stt + pipeline + devices (MLX Whisper, loopback) ✅
│   └── core/             # context.py + controller.py + hotkeys.py ✅
├── tests/                # Unit tests
│   └── __init__.py
├── artifacts/            # Agent outputs (created during workflows)
│   ├── archive/          # Previous task results
│   └── handoff/          # Agent communication files
└── tmp/
    └── logs/             # Application logs with rotation
```

### Directory Breakdown

- **`main.py`**: Main application entry point with error handling and logging
- **`media/`**: Contains input and output files, and other media assets
- **`.claude/agents/`**: Claude Code AI agent definitions for automated workflows
- **`src/`**: Source code organized into subdirectories:
  - **`config/`**: Configuration management with environment-based settings
  - **`helpers/`**: Utility modules including the logger with rotation
  - **`models/`**: Data models with Pydantic base model and enumerations
  - **`ui/`, `vision/`, `llm/`, `audio/`, `core/`**: application modules, added per [`docs/DEVELOPMENT_PLAN.md`](./docs/DEVELOPMENT_PLAN.md)
- **`tests/`**: Unit tests for various components
- **`artifacts/`**: Agent-generated outputs during development workflows (created automatically)
- **`tmp/logs/`**: Log files with automatic rotation (10MB limit, 5 backups)

## Logging

Logs are stored in the `tmp/logs/` directory with automatic rotation:
- Each module logs to its own file (e.g., `__main__.log`, `module_name.log`)
- Log files rotate when they reach 10MB in size
- Up to 5 backup files are kept (`.log.1` through `.log.5`)
- Logging level is DEBUG in development, INFO in production
- Logs output to both console and file simultaneously

## Testing

Unit tests are located in the `tests/` directory. To run the tests, execute:

```bash
pytest
```

## Claude Code Agents

This project includes pre-configured AI agents for automated software development lifecycle (SDLC) workflows:

### Available Agents

1. **Planner Agent** (`planner.md`)
   - Orchestrates the entire development pipeline
   - Manages workflow between specialized agents
   - Creates branches, PRs, and coordinates quality gates
   - Workflow modes: BUGFIX, FEATURE, HOTFIX

2. **Code Architect Agent** (`code-architect.md`)
   - Designs system architecture before implementation
   - Creates component specifications and file maps
   - Defines interfaces, data flows, and patterns
   - Produces actionable design documents

3. **Senior Coder Agent** (`senior-coder.md`)
   - Implements features based on architect designs
   - Fixes bugs with minimal changes
   - Adds comprehensive tests
   - Ensures code quality with type hints and documentation

4. **Code Reviewer Agent** (`code-reviewer.md`)
   - Reviews code for correctness and security
   - Enforces project standards and best practices
   - Provides actionable feedback with severity levels
   - Posts review comments to PRs

5. **QA Engineer Agent** (`qa-engineer.md`)
   - Runs automated tests and quality gates
   - Executes static analysis (ruff, mypy, pylint)
   - Validates test coverage (≥90%)
   - Generates comprehensive quality reports

### Workflow Example

For implementing a new feature:
1. Planner creates branch and launches architect
2. Architect designs the solution
3. Senior Coder implements the design
4. Planner creates PR
5. Code Reviewer checks the implementation
6. QA Engineer runs tests and quality gates
7. Planner posts summary to PR

### Configuration

- **Shared Config**: `.claude/agents/SHARED_CONFIG.md` - Common settings for all agents
- **Project Rules**: `CLAUDE.md` - Project-specific coding conventions
- **Style Guide**: `PYTHON_STYLE_GUIDE.md` - Python coding standards

### Key Features

- **Continuous Execution**: Agents run until all tasks are complete
- **Quality Gates**: Automated checks at each stage
- **PR Integration**: Automatic GitHub PR creation and updates
- **Scope Management**: Strict limits on change size (BUGFIX: <50 lines, FEATURE: <200 lines)
- **Test Coverage**: Minimum 90% code coverage requirement

## Author

**Sergey Chernyakov**

📬 Telegram: [@AIBotsTech](https://t.me/AIBotsTech)

