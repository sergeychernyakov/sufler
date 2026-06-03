# AGENTS.md  <!-- Human-to-Agent instructions -->

## 🧠 General Agent Instructions
- You are an AI coding assistant working inside this container/repository.
- Follow every instruction in this file **unless** a direct user prompt overrides it.
- If something is unclear, ask clarifying questions rather than guessing.

---

## 📖 Project Description
See **[`README.md`](./README.md)** for an overview of the project’s purpose, requirements and architecture.

---

## 📐 Coding Conventions
- Follow the style guide in **[`PYTHON_STYLE_GUIDE.md`](./PYTHON_STYLE_GUIDE.md)**.
- File names: **snake_case** (`email_service.py`), class names: **CamelCase** (`EmailService`).
- First line of each code file must be a comment with the file path, e.g.  
  `# src/services/email_service.py`
- Use type hints everywhere and Google-style docstrings for all public APIs.
- Do **not** use `print()` for output—use the standard `logging` module.

---

## 🧪 Testing & Quality
- Use **pytest**; follow Arrange → Act → Assert.
- Place tests in a mirroring structure under `tests/`.
- Target **90 %+** code coverage (critical packages — `llm`, `core`, `audio`, `vision` — aim for **95 %**).
- Line length is **120**.
- Run the full local quality gate before finishing: **`bin/ci`**. It mirrors the
  pre-commit/pre-push hooks: `black`, `isort`, `ruff`, `pylint (≥9.5)`, `mypy`,
  `bandit`, `pip-audit`, secret scan, and `pytest` + coverage.
- One-time setup installs the venv, deps and git hooks: **`bin/setup`**.

---

## 🔐 Security & Secrets
- Never hardcode secrets—use environment variables or a secret manager.
- Sanitize user inputs and escape web outputs.
- Run dependency audit tools (`pip-audit`, `safety`, etc.) if relevant.

---

## 🌿 Git Workflow (enforced by hooks)
- `main` is **protected**: direct commits and pushes are blocked. Use feature branches + PRs.
- Branch names: `<type>/<short-description>` (e.g. `feat/overlay-stealth`).
- Commit messages follow **Conventional Commits**: `<type>(<scope>): <subject>` (subject ≤ 72 chars).
- Full rules and examples: **[`docs/COMMIT_CONVENTION.md`](./docs/COMMIT_CONVENTION.md)**.

---

## 🤖 Agent Limitations
- Do **not** execute system commands unless explicitly told to.
- Do **not** commit or push to git; source-control steps are handled outside this agent.
- Never overwrite user data without confirmation.
- If a required decision is ambiguous—ask.

---

## ✅ Final Deliverables Checklist
- [ ] Code adheres to `PYTHON_STYLE_GUIDE.md`.
- [ ] `bin/ci` passes (or all checks PASS/SKIP).
- [ ] All tests pass (`pytest -q`) with ≥ 90 % coverage.
- [ ] Linting/formatting/types pass (`black`, `isort`, `ruff`, `pylint ≥ 9.5`, `mypy`).
- [ ] No hard-coded secrets; environment variables used where necessary.
- [ ] Commit messages follow Conventional Commits (see `docs/COMMIT_CONVENTION.md`).
- [ ] Any setup or run instructions updated in `README.md` if required.
