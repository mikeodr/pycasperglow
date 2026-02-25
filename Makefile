.PHONY: setup install-hooks format lint typecheck check test clean

VENV := .venv
PYTHON := $(VENV)/bin/python
RUFF := $(VENV)/bin/ruff
MYPY := $(VENV)/bin/mypy
PYTEST := $(VENV)/bin/pytest

# Create the virtual environment and install dev dependencies
$(VENV):
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --quiet --upgrade pip
	$(VENV)/bin/pip install --quiet -e ".[dev]"

setup: $(VENV)

# Install the git hooks from the hooks/ directory
install-hooks:
	cp hooks/pre-commit .git/hooks/pre-commit
	chmod +x .git/hooks/pre-commit

# Auto-fix lint issues in-place
format: $(VENV)
	$(RUFF) format src/ tests/

# Check for lint issues (read-only)
lint: $(VENV)
	$(RUFF) check src/ tests/

# Static type checking
typecheck: $(VENV)
	$(MYPY) src/ tests/ examples/ --strict

# Fast check used by pre-commit (no coverage)
check: lint typecheck
	$(PYTEST) tests/ -v

# Full test suite with coverage (for local dev / CI)
test: lint typecheck
	$(PYTEST) tests/ -v --cov=pycasperglow

clean:
	rm -rf $(VENV) .mypy_cache .ruff_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +
