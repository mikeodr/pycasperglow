# Contributing to pycasperglow

Thanks for your interest in contributing! This document covers the workflow and conventions used in this project.

## Getting Started

1. Fork and clone the repository
2. Set up the virtual environment and install dev dependencies:

```bash
make setup
```

3. Install the git hooks:

```bash
make install-hooks
```

   This copies `hooks/pre-commit` into `.git/hooks/` so that ruff, mypy, and
   the test suite run automatically before every commit.

4. Create a branch for your changes:

```bash
git checkout -b your-branch-name
```

## Running Checks

Before submitting a PR, make sure all checks pass (lint + typecheck + tests with
coverage):

```bash
make test
```

Run the same fast check the pre-commit hook uses (no coverage):

```bash
make check
```

Auto-fix lint issues in-place:

```bash
make format
```

Targets at a glance:

| Target | What it does |
|--------|--------------|
| `make setup` | Create `.venv` and install `.[dev]` |
| `make install-hooks` | Install git hooks from `hooks/` |
| `make format` | Auto-fix lint issues (`ruff --fix`) |
| `make lint` | Check lint (read-only) |
| `make typecheck` | Run `mypy --strict` |
| `make check` | lint + typecheck + tests (no coverage) |
| `make test` | lint + typecheck + tests with coverage |
| `make clean` | Remove `.venv` and caches |

## Commit Message Style

This project follows the [Linux kernel commit message style](https://www.kernel.org/doc/html/latest/process/submitting-patches.html#describe-your-changes). Every commit message should have the following format:

```
subsystem: short summary in imperative mood

Optional longer description that explains *why* the change is being
made. Wrap the body at 72 characters. Separate the subject from the
body with a blank line.
```

### Rules

- **Subject line**: Use a lowercase subsystem prefix followed by a colon and a short imperative summary (e.g. `protocol: add brightness packet builder`)
- **72-character wrap**: Keep the subject under ~72 characters. Wrap the body at 72 characters.
- **Imperative mood**: Write the subject as a command — "add", "fix", "remove" — not "added", "fixes", or "removing".
- **Body explains why**: The diff shows *what* changed. Use the body to explain *why*.
- **No trailing period**: Do not end the subject line with a period.

### Common Subsystem Prefixes

| Prefix | Usage |
|--------|-------|
| `protocol` | Protocol encoding/decoding logic |
| `device` | `CasperGlow` client and BLE state machine |
| `discovery` | Device scanning and identification |
| `ci` | GitHub Actions, Dependabot, CI config |
| `tests` | Test additions or changes |
| `docs` | Documentation updates |

### Examples

```
protocol: add varint decoding for session tokens

The Glow firmware encodes session tokens as protobuf varints. Add a
decoder so we can extract tokens from notification payloads.
```

```
ci: add GitHub Actions workflow for PR validation

Add a CI workflow that runs on pull requests to main and master
branches. Tests are executed across Python 3.11, 3.12, and 3.13
with coverage reporting. Linting runs ruff and mypy in strict mode.
```

```
device: fix connection leak when handshake times out
```

## Pull Requests

- Keep PRs focused — one logical change per PR.
- Ensure CI passes before requesting review.
- Link any related issues in the PR description.

## Architecture

See the [CLAUDE.md](CLAUDE.md) file for an overview of the codebase structure and key design decisions.
