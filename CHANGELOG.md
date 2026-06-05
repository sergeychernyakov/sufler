# Changelog

All notable changes to **sufler** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Entries are
derived from [Conventional Commits](./docs/COMMIT_CONVENTION.md); **every change adds a
line under `[Unreleased]`**.

## [Unreleased]

### Added
- **Microphone toggle button** in the overlay — listening is **on by default**. The button
  shows a filled green mic while listening and a dimmed, slashed mic when muted; muting closes
  the input stream (so the macOS microphone indicator turns off too). It is disabled when no STT
  backend is available. _feat(ui)_
- **Configurable STT language** via `SUFLER_STT_LANGUAGE` (empty = auto-detect, best for mixed
  ru+en speech; set `ru` / `en` to pin a single language and drop auto-detection garbage). The
  code default already targets `whisper-large-v3-turbo`. _feat(config)_
- **Brand shown as "Sufler"** in the macOS Dock / ⌘-Tab (bundle display name); the window itself
  has no title text (macOS centers native titles, with no Qt way to left-align them). _feat(ui)_
- **Microphone input-volume slider** + a **live input-level meter** in the overlay — adjust the
  system mic gain without opening System Settings, and see the mic working at a glance (the meter
  bars turn amber/red to warn of clipping). Muting the mic dims these controls and drops the meter
  to zero. System volume is read/set via `osascript`. _feat(ui)_
- **Font zoom** — `Cmd +` / `Cmd =` enlarge and `Cmd -` shrink the overlay text, `Cmd 0` resets
  (all fonts scale 0.7×–2.5×). _feat(ui)_
- **Free answer backends (Gemini & Groq)** — `SUFLER_LLM_PROVIDER=claude|gemini|groq` selects the
  answer LLM via a provider-agnostic factory. Gemini (`langchain-google-genai`) and Groq
  (`langchain-groq`, default Llama 4 Scout) stream answers and **read screenshots**, mirroring the
  Claude client; configured via `SUFLER_GEMINI_API_KEY` / `SUFLER_GROQ_API_KEY` and the matching
  `*_MODEL`. _feat(llm)_
- **"Thinking" spinner** — an animated indicator in the answer area while the LLM generates,
  replaced by the first streamed token (and showing "(пустой ответ)" if nothing comes back). _feat(ui)_
- **Auto-answer recognized speech** — speak a question → it answers. Controlled by the **microphone
  toggle** (mic off = no answers); disable via `SUFLER_AUTO_ANSWER=false`. _feat(controller)_
- **Answer questions only + cooldown** — auto-answer now fires only on utterances that look like a
  question/request (interrogative or `?`), not on every monologue chunk, and is rate-limited by a
  cooldown (`SUFLER_ANSWER_COOLDOWN`, default 6 s). This stops the free-tier rate-limit spam and the
  "answering mid-sentence fragments" problem. Toggle with `SUFLER_ANSWER_QUESTIONS_ONLY`. _feat(controller)_
- **Drill-down on terms** — the bold `**terms**` and `` `code` `` spans (the English terms) in an
  answer are clickable: tapping one asks the LLM about that term and navigates into a fresh answer
  (unlimited depth). Browser-style **back (←)** / **forward (→)** buttons at the top move through
  the history. _feat(ui)_
- **Single-word lookup** — typing a bare word + Enter is treated as a definition query ("Что такое
  <word>?" / "What is <word>?" by language). _feat(controller)_
- **Session-wide back/forward** — a new question no longer clears history; back (←) / forward (→)
  now move through every previous hint and drill-down (browser-style). _feat(controller)_
- **Tag cloud** — clickable pill chips of terms collected from answers, shown **above the
  recognition area**, **sorted alphabetically** and fully visible (wrap, no scroll), up to 20
  unique; clicking one drills down like an inline term link. When the recognition feed is hidden,
  the tags drop to the bottom (above the controls) instead of floating in the middle. _feat(ui)_
- **Pin (📌)** — freeze the current answer: sufler keeps recognizing and answering in the
  background, and the new answers queue into forward history (reachable with →). _feat(ui)_
- **In-window model selector** — a dropdown switches the answer model on the fly (the active
  provider's free models). _feat(ui)_
- **Output-language selector** — a dropdown (right of the model selector) sets the answer language
  (`ru` / `en`, default `ru`), wired into the system prompt via `SUFLER_ANSWER_LANG`. _feat(ui)_
- **Copy button** (📋, in the button row right of Enter) — copies the current question + answer
  (markdown markers stripped) to the clipboard, with a brief ✓ confirmation. _feat(ui)_
- **Resizable recognition area** — answer and transcript share a draggable splitter; drag its handle
  (the transcript's top border) to enlarge the recognition feed. _feat(ui)_
- **Longer answers** — up to **7** points/theses by default (was ~3); configurable via
  `SUFLER_ANSWER_POINTS`. _feat(controller)_

### Added
- **Smartest Groq model by default** — `openai/gpt-oss-120b` (free, strongest reasoning) is now the
  default answer model; screenshots automatically fall back to the vision model
  (`llama-4-scout`) for that request. _feat(llm)_
- **Lookup dots in the recognition feed** — a `·` between two words looks up that pair, a `•` at a
  sentence end looks up the whole sentence, and hovering any word/dot highlights it (colour change).
  Selecting any text drops it into the manual-input field (edit/Enter); the selection is shown
  highlighted. _feat(ui)_
- **Two parallel passes over recognized speech** — (1) technical terms are extracted heuristically
  from every utterance (no LLM, Latin-script tokens like `REST`/`deadlock`) and added to the tag
  cloud; (2) questions are detected and answered as before. _feat(controller)_
- **Clickable words in the recognition feed** — every word in the live transcript is now a link;
  clicking it asks the LLM for a definition, exactly like a tag chip. _feat(ui)_

### Fixed
- **Crash (SIGSEGV) under heavy speech** — overlapping utterances spawned concurrent MLX Whisper
  transcriptions, and MLX/Metal is not thread-safe, so two simultaneous `eval` calls segfaulted the
  app shortly after launch. Transcription is now serialized (one at a time); an utterance arriving
  while the engine is busy is dropped instead of run concurrently. _fix(audio)_
- **Weak-microphone recognition** — the speech-detection RMS gate is now configurable
  (`SUFLER_MIN_SPEECH_RMS`, default lowered `0.008` → `0.004`), so quiet mic input is no longer
  silently skipped. _fix(audio)_
- **Scrollable answer area** — long answers were clipped; the answer now scrolls inside its pane. _fix(ui)_
- **Hide model reasoning** — `<think>…</think>` blocks (emitted by some models) are stripped from
  the answer. _fix(ui)_
- **Language selector width** — the `ru`/`en` dropdown was too narrow (clipped, worse when text was
  enlarged); it now has a minimum width and sizes to its content. _fix(ui)_
- **Question/answer text is selectable** (copyable) in the window — the question label was not
  selectable before. _fix(ui)_
- **App icon transparency** — the source icon was flattened to RGB, so its corners rendered as
  opaque white in the Dock / app switcher; restored an alpha channel (transparent squircle corners),
  which the bundle and `app.setWindowIcon` now carry through. _fix(ui)_
- **Capture button icon** now reads as a camera (it looked like a suitcase) — redrawn with a
  lens-housing hump, concentric lens rings, and a flash dot. _fix(ui)_
- **STT silently produced no text when the model cache was incomplete** — `_model_path` accepted
  a metadata-only Hugging Face cache (weights missing) and never fetched them, so every
  transcription raised and was swallowed. The full snapshot is now fetched first (completing a
  partial cache); `local_files_only` is only an offline fallback. _fix(stt)_
- **Filter Whisper silence hallucinations** — discard the YouTube-subtitle artefacts Whisper emits
  on non-speech (e.g. "Субтитры сделал DimaTorzok", "Продолжение следует", "Thank you.", a bare
  "You") so they no longer appear in the window. Now also: **discard transcripts in a non-allowed
  language** (`SUFLER_STT_ALLOWED_LANGS`, default `ru,en` — kills random foreign garbage like Dutch
  "welk een driet"), and **catch looped short phrases** ("Thank you. Thank you. Thank you."). _fix(stt)_

## [0.2.0] - 2026-06-03

### Added
- **Normal-window UI** (default): native title bar (drag + close-to-quit), always-on-top;
  the frameless stealth overlay is now opt-in via `SUFLER_STEALTH=true`. _feat(ui)_
- **Live transcript** panel with a show/hide toggle; a **Send** button (⏎) beside the manual
  input; the capture button is a vector **camera icon**; the window is draggable by its body. _feat(ui)_
- **`bin/make_app`** — builds a double-clickable macOS `sufler.app` launcher. _chore(tooling)_
- **App icon** — `assets/icon.png` is rendered into a multi-resolution `sufler.icns` (16–1024 px,
  1x + 2x) by `bin/make_app` and referenced from `Info.plist` (`CFBundleIconFile`); it is also set
  on the running window / Dock tile via `app.setWindowIcon`. _feat(ui)_

### Fixed
- **Real-time STT now works reliably** (it previously produced empty/garbled output, stalled,
  or hallucinated repeated phrases on silence):
  - Copy audio out of the `sounddevice` callback buffer — it is reused, so stored views were
    overwritten before transcription (**the core bug**). _fix(audio)_
  - Resolve the Whisper model to a local path once — avoids a slow per-call Hugging Face fetch
    that stalled transcription. _fix(stt)_
  - Transcribe only finalized utterances (not the growing buffer on every partial) and cap
    utterance length at 8 s — removes the engine backlog. _fix(audio)_
  - Peak-normalize quiet audio; gate on RMS and drop degenerate/repetitive output
    (`condition_on_previous_text=False`) — quiet speech is recognized, silence stays empty. _fix(stt)_
- **Overlay visibility on macOS** — `WA_MacAlwaysShowToolWindow`, explicit top-right placement,
  and no auto-hide at launch (the window stayed hidden/blank before). _fix(ui)_

## [0.1.0] - 2026-06-03

First MVP: stealth overlay + screenshot → Claude (streaming) + global hotkeys + manual
input + live STT (MLX Whisper) + loopback capture + rolling context, on a strict,
automated quality toolchain.

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

> Beyond v1 (deferred): Deepgram streaming STT, auto-trigger on question detection,
> and ScreenCaptureKit / CoreAudio Taps loopback instead of BlackHole.
