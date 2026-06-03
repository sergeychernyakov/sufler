# Commit & Branch Convention

This project enforces a strict, automated git workflow (via pre-commit hooks).
The rules below are checked locally — `bin/ci` and the hooks are the source of truth.

## Branches

`main` is **protected**: direct commits and pushes are blocked. All work happens
on feature branches merged via PR.

```
<type>/<short-description>
```

- **type**: `feat` `fix` `refactor` `perf` `test` `docs` `chore` `security` `hotfix` `build` `ci`
- **description**: lowercase, `-` separated. e.g. `feat/overlay-stealth`, `fix/screenshot-region`

Branch names that break the convention produce a **warning** (post-checkout), not a block.

## Commit messages — Conventional Commits

```
<type>(<scope>): <subject>
```

- **type** (required): `feat` `fix` `refactor` `perf` `test` `docs` `chore` `security` `build` `ci` `style` `revert`
- **scope** (required): the area touched — e.g.
  `overlay` `llm` `stt` `audio` `vision` `context` `controller` `config` `hotkey` `ui` `deps` `tooling` `ci` `docs`
- **subject** (required): imperative mood, ≤ 72 chars, no trailing period.

Merge/revert/fixup/squash commits are exempt from the format check.

### Examples

```
feat(overlay): add click-through stealth mode
fix(vision): hide overlay before screencapture so it stays out of frame
refactor(llm): extract streaming into a reusable helper
chore(tooling): pin ruff to match the pre-commit rev
docs(readme): document the quality gates
```

## First commit on a fresh clone

Because `main` is protected, the very first commit (including the quality tooling
itself) must go on a feature branch:

```bash
git checkout -b chore/quality-tooling
bin/setup                       # installs deps + git hooks
git add -A
git commit -m "chore(tooling): add automated quality gates"
git push -u origin chore/quality-tooling   # then open a PR
```

## Escape hatches

- Skip a specific hook for one command: `SKIP=pip-audit git push`
- Bypass all hooks (use sparingly): `git commit --no-verify`
