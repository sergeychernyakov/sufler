# План разработки — sufler

Документ переводит **[`SUFLER_SPEC.md`](../SUFLER_SPEC.md)** в конкретные фазы, модули,
критерии приёмки и тесты. Спека — это «что» и «зачем»; этот план — «как» и «в каком порядке».

## Статус (2026-06-03)
- ✅ **Фазы 1–6** реализованы: overlay, screenshot, Claude-клиент, ручной ввод, rolling context,
  **STT** (MLX Whisper + микрофон + пайплайн) — плюс контроллер `on_capture`, живая речь в
  оверлей/контекст и `main.py`. `python main.py` запускает оверлей; STT включается при
  установленном `mlx-whisper` и выданном праве на микрофон.
- Покрытие ~98 %, `bin/ci` зелёный. Ветка `feat/app-mvp`.
- ⏳ Осталось: **Фаза 7 (loopback)** — захват звука собеседника (BlackHole).

## Принципы

- **MVP сначала, аудио-ад потом.** Порядок намеренно переставлен (см. спеку): сначала
  польза без STT/loopback. Каждая фаза — самостоятельно работающий инкремент.
- **Одна фаза = одна фича-ветка = один PR.** Имя ветки и scope коммитов — по
  [`COMMIT_CONVENTION.md`](./COMMIT_CONVENTION.md).
- **Definition of Done у каждой фазы:** `bin/ci` зелёный, тесты добавлены (покрытие по
  целям ниже), README/доки обновлены, ответ на русском / термины на English.
- **Приватность:** ключи только в `.env`; локальный STT (whisper.cpp/MLX) — звук наружу не уходит.
- **Стелс — не «потом», а часть каждой UI-фазы.** Суфлёр не должен палиться.

## Целевая архитектура

Корень пакета — существующий `src/` (skeleton уже задаёт `src/config`, `src/helpers`,
`src/models`). Модули из спеки добавляются под `src/`:

```
src/
├── config/
│   ├── settings.py        # есть — расширить: API key, model, mode, lang, hotkeys
│   └── __init__.py        # есть — get_config()/config
├── helpers/
│   └── logger.py          # есть — logging с ротацией
├── models/
│   ├── base.py            # есть — Pydantic Base
│   └── enums.py           # есть — добавить Mode(ANSWER/COACH), AnswerLang, SttEngine
├── audio/                 # НОВОЕ (фаза 5+)
│   ├── capture.py         #   sounddevice: буферы, partial/finalize
│   └── stt.py             #   STTEngine (ABC) + MLX/whisper.cpp + Deepgram(stub)
├── vision/                # НОВОЕ (фаза 2)
│   └── screenshot.py      #   screencapture -x + mss fallback → base64 PNG
├── llm/                   # НОВОЕ (фаза 2)
│   └── claude.py          #   мультимодальный запрос + стрим + режимы answer/coach
├── ui/                    # НОВОЕ (фаза 1)
│   └── overlay.py         #   PyQt6 оверлей: вопрос/ответ, кнопка, ручной ввод, stealth
└── core/                  # НОВОЕ (фазы 3/6)
    ├── context.py         #   rolling-контекст 30–60 сек
    └── controller.py      #   склейка: вход → (скрин) → context → Claude → оверлей
main.py                    # есть — точка входа: собрать controller + overlay
```

**Единая точка `on_capture` (ядро дизайна).** Три входа сходятся в один метод контроллера:
хоткей, кнопка «📸 Скрин», ручной ввод. `on_capture`: спрятать оверлей → скрин → показать →
(скрин + rolling context) в Claude → стрим в оверлей.

**Целевые пороги покрытия** (форсит `bin/check_coverage`): `src/llm` и `src/core` — **95 %**,
`src/audio` и `src/vision` — **90 %**, глобально — **90 %**.

## Конфигурация (`.env`)

Поверхность настроек (см. `.env.example`): `ANTHROPIC_API_KEY`, `SUFLER_MODEL`,
`SUFLER_MODE` (coach|answer), `SUFLER_ANSWER_LANG`, `SUFLER_STT_ENGINE`
(mlx|whispercpp|deepgram), хоткеи `SUFLER_HOTKEY_*`. Никаких ключей в коде.

---

## Фазы

### Фаза 0 — Quality tooling ✅ (сделано)
pre-commit, ruff/black/isort/pylint/mypy/bandit/pip-audit, `bin/ci`, `bin/check_coverage`,
строгий git-workflow. `bin/ci` зелёный на скелете.

### Фаза 1 — Overlay (мок) ✅  · ветка `feat/overlay-mvp`
**Цель:** полезного ответа ещё нет, но есть незаметное окно со стелс-контролами и
замоканным «стримом».

| | |
|---|---|
| **Файлы** | `src/ui/overlay.py`, `src/models/enums.py` (+`Mode`), `main.py` (wiring), `tests/ui/test_overlay.py` |
| **Задачи** | frameless + `WindowStaysOnTopHint` + `WA_TranslucentBackground`; поле вопроса (сверху, мелко) + поле ответа (снизу); кнопка «📸 Скрин»; постоянное поле ручного ввода; стелс: opacity 20/40/70 %, click-through (`WA_TransparentForMouseEvents`), compact mode (только ответ), auto-hide 10–15 с, **panic-hide**; мок-ответ выводится «по токенам» (таймер) |
| **Приёмка** | окно поверх всех приложений, полупрозрачное; стелс-тогглы работают; panic прячет мгновенно; ответ обновляется инкрементально |
| **Тесты** | логика состояний оверлея (уровни opacity, compact, panic, auto-hide) через `pytest-qt` (добавить в dev-deps); сигнал «append token» дописывает текст |
| **Риски** | прозрачность/ click-through на macOS капризны — проверить флаги рано |

### Фаза 2 — Screenshot → Claude ✅  · ветка `feat/screenshot-claude`
**Цель:** первый реально полезный инструмент — скрин экрана уходит в Claude, ответ стримится.

| | |
|---|---|
| **Файлы** | `src/vision/screenshot.py`, `src/llm/claude.py`, `src/config/settings.py` (API key, model, mode), `src/core/controller.py` (минимальный `on_capture`), тесты |
| **Задачи** | `grab_screen(region=None) -> base64` через `screencapture -x` (+ `-R x,y,w,h`), fallback `mss`; **прятать оверлей до захвата** (`hide()`+`processEvents()`+~0.15 с)→`show()`; `claude.py`: мультимодальный `{text}+{image base64 PNG}` + rolling-context-плейсхолдер + **стриминг токенами**; системный промпт уровня senior; режимы **answer** (2–4 пункта) / **coach** (3 тезиса-опоры); модель из конфига |
| **Приёмка** | по кнопке: оверлей прячется → скрин (без суфлёра в кадре) → Claude → стрим ответа; переключение coach/answer меняет стиль |
| **Тесты** | base64 из `screencapture` (mock subprocess) + fallback mss; сборка мультимодального запроса и выбор системного промпта по режиму (mock `anthropic` client/stream) |
| **Покрытие** | `src/llm` ≥ 95 %, `src/vision` ≥ 90 % |

### Фаза 3 — Hotkeys (+ panic) ✅  · ветка `feat/hotkeys`
| | |
|---|---|
| **Файлы** | `src/core/controller.py` (общий `on_capture`), менеджер хоткеев на `pynput`, конфиг биндингов |
| **Задачи** | глобальный хоткей → `on_capture`; **panic-хоткей** → мгновенно скрыть всё; хоткей «ответь по последним N сек» (стаб до STT); opacity-хоткеи |
| **Приёмка** | хоткеи срабатывают глобально (нужен Accessibility); panic мгновенный |
| **Тесты** | маппинг хоткей→callback; оркестрация `on_capture` (mock screenshot+claude+overlay) |

### Фаза 4 — Ручной ввод текста ✅  · ветка `feat/manual-input`
**Цель:** напечатать вопрос быстрее, чем ждать STT. Постоянная фича.

| | |
|---|---|
| **Файлы** | связка поля ввода оверлея с `controller` (отправка **без скрина**) |
| **Задачи** | ручной ввод → Claude без скриншота, с rolling-контекстом |
| **Приёмка** | ввод + Enter → стрим ответа |
| **Тесты** | путь контроллера для ручного ввода (скриншот не вызывается) |

> **— здесь уже рабочий полезный инструмент на собесе —**

### Фаза 5 — STT ✅  · ветка `feat/stt`
**Решение до старта:** движок по умолчанию — **`mlx-whisper`** (pip, нативно Apple Silicon)
либо **whisper.cpp** (Metal, внешний бинарь/server). Архитектура — сменой одного модуля.

| | |
|---|---|
| **Файлы** | `src/audio/capture.py`, `src/audio/stt.py` (ABC `STTEngine` + реализация + `DeepgramEngine` stub), конфиг `SUFLER_STT_ENGINE` |
| **Задачи** | захват микрофона (`sounddevice`); **быстрый partial buffer 1–1.5 с**; **финализация по паузе 600–900 мс**; автоопределение языка (ru/en, код-свитчинг); хоткей «по последним 15–25 с речи» |
| **Приёмка** | живой черновой текст в поле вопроса; финализация по паузе; задержки в целевых рамках (буфер 2–4 с — НЕ годится) |
| **Тесты** | контракт `STTEngine`; буферизация capture (mock `sounddevice`); логика финализации по таймауту (без реального звука) |
| **Покрытие** | `src/audio` ≥ 90 % |

### Фаза 6 — Rolling context ✅  · ветка `feat/rolling-context`
| | |
|---|---|
| **Файлы** | `src/core/context.py`, интеграция в `controller` |
| **Задачи** | скользящее окно: последние 30–60 с речи + последний уверенный вопрос + последний скрин; контекст уходит в Claude вместе с запросом |
| **Приёмка** | отвечает на «а чем отличается от предыдущего варианта?» с учётом истории |
| **Тесты** | вытеснение по времени; сериализация контекста в запрос Claude |
| **Покрытие** | `src/core` ≥ 95 % |

### Фаза 7 — Loopback audio  · ветка `feat/loopback-audio`
| | |
|---|---|
| **Файлы** | `src/audio/capture.py` (выбор устройства **BlackHole**), доки по установке |
| **Задачи** | захват звука собеседника через BlackHole (проще, чем ScreenCaptureKit) |
| **Приёмка** | речь собеседника распознаётся без эха/шумов голого микро |
| **Тесты** | логика выбора аудио-устройства |
| **Позже** | ScreenCaptureKit / CoreAudio Taps — официально, но больнее |

---

## Вне scope первой версии
- Реализация Deepgram streaming (интерфейс заложить, реализацию — позже).
- Автотриггер по детекту вопроса.
- ScreenCaptureKit loopback.

## Definition of Done (каждая фаза)
- [ ] `bin/ci` зелёный (формат/линт/типы/секреты/тесты).
- [ ] Тесты добавлены; целевое покрытие пакета достигнуто.
- [ ] Нет хардкода секретов; новые настройки — в `.env.example`.
- [ ] README/доки и `.env.example` отражают изменения.
- [ ] Коммиты по Conventional Commits; PR из фича-ветки в `main`.
