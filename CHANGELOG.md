# Changelog

All notable changes to **sufler** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Entries are
derived from [Conventional Commits](./docs/COMMIT_CONVENTION.md); **every change adds a
line under `[Unreleased]`**.

## [Unreleased]

### Added
- **Quality toolchain & strict git workflow** — pre-commit hooks (format / lint / type /
  security / secret-scan / tests), `bin/setup`, `bin/ci`, `bin/check_coverage`,
  `pyproject.toml`, `.editorconfig`; Conventional Commits + protected `main`
  (`docs/COMMIT_CONVENTION.md`). _chore(tooling)_
- **App config & scaffolding** — env-based settings (API key, model, mode, language,
  hotkeys), `Mode` / `SttEngine` enums, `src/` package layout. _feat(config)_
- **Overlay (Phase 1)** — frameless PyQt6 stealth overlay: opacity 20/40/70 %,
  click-through, compact mode, auto-hide, panic-hide, question/answer areas, capture
  button, manual input. _feat(overlay)_
- **Screenshot (Phase 2)** — `grab_screen()` via `screencapture -x` with `mss` fallback
  → base64 PNG. _feat(vision)_
- **Claude client (Phase 2)** — streaming multimodal requests with `answer` / `coach`
  system prompts. _feat(llm)_
- **Rolling context (Phase 6)** — 30–60 s sliding window of recent speech + last question.
  _feat(context)_
- **Controller** — single `on_capture` flow (hotkey / button / manual), threaded Claude
  streaming into the overlay, `on_answer_last`, panic, mode switch. _feat(controller)_
- **Global hotkeys (Phase 3)** — pynput hotkeys bridged to Qt signals (capture / panic /
  answer-last). _feat(hotkey)_
- **Manual input (Phase 4)** and `main.py` wiring (`build_app` / `main`). _feat(controller)_
- **STT (Phase 5)** — `STTEngine` abstraction with MLX Whisper engine + Deepgram stub +
  `create_engine` factory; microphone capture with partial (~1.2 s) / pause-finalized
  (~0.7 s) segmentation; speech pipeline; live partial/final speech routed into the
  overlay and rolling context; started from `main` when the backend is available.
  _feat(stt)_ / _feat(audio)_
- **Configurable STT model** via `SUFLER_STT_MODEL` (empty = default `whisper-large-v3-turbo`;
  set e.g. `mlx-community/whisper-small` for lower latency). _feat(config)_
- **Loopback capture (Phase 7)** — `src/audio/devices.py` resolves input devices by index or
  name; capture/pipeline accept a `device`; `SUFLER_LOOPBACK_DEVICE` (e.g. `BlackHole`) points
  STT at the interviewer's audio, falling back to the default input when absent. _feat(audio)_
- **Tests** across every module — ~98 % coverage (critical packages ≥ 95 %).
- This **`CHANGELOG.md`** and the practice of tracking every change here. _docs(changelog)_

### Changed
- `README.md`, `PYTHON_STYLE_GUIDE.md`, `AGENTS.md` aligned to the project; line length
  standardized to **120**; `docs/DEVELOPMENT_PLAN.md` phase statuses (Phases 1–6 done).
  _docs_

### Fixed
- `secret-scan` scoped to skip `tests/` fixtures and `.claude/` worktrees. _fix(tooling)_
- Template correctness: `main.py` return type `NoReturn` → `None`; `base.py` validator
  return types and dict-key typing.
- STT-start unit test no longer opens a real microphone (nor loads pyobjc), which
  segfaulted the test suite once `mlx-whisper` was installed. _fix(test)_

### Security
- `bandit`, `pip-audit`, private-key detection and a hardcoded-credential scan wired into
  the quality gate.

---

> No releases yet. When the MVP ships, move the relevant entries under a version heading
> (e.g. `## [0.1.0] - YYYY-MM-DD`) and start a fresh `[Unreleased]`.
> Deferred: **Phase 7 — loopback audio (BlackHole)**.
