.PHONY: setup lint format typecheck unit science check audit
setup:
	uv sync --locked --all-packages
lint:
	uv run --locked ruff check .
	uv run --locked ruff format --check .
format:
	uv run --locked ruff check --fix .
	uv run --locked ruff format .
typecheck:
	uv run --locked mypy packages tests
unit:
	uv run --locked pytest tests/unit
science:
	uv run --locked pytest tests/scientific
check: lint typecheck unit science
audit:
	uv run --locked pip-audit
