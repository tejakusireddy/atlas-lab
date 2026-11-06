.PHONY: setup lint format typecheck unit science check audit db-up migrate integration \
        sim-image sim workflow reference-workflow runtime-image isolation faults
setup:
	uv sync --locked --all-packages
lint:
	uv run --locked ruff check .
	uv run --locked ruff format --check .
format:
	uv run --locked ruff check --fix .
	uv run --locked ruff format .
typecheck:
	uv run --locked mypy packages apps tests
unit:
	uv run --locked pytest tests/unit
science:
	uv run --locked pytest tests/scientific
check: lint typecheck unit science
audit:
	uv run --locked pip-audit

db-up:
	docker compose -f infra/compose/compose.yaml up -d --wait
migrate:
	uv run --locked atlas-migrate
integration:
	ATLAS_TEST_DATABASE_URL=$${ATLAS_TEST_DATABASE_URL:-postgresql://atlas:atlas-local-only@127.0.0.1:55432/atlas} uv run --locked pytest tests/integration

sim-image:
	docker build -t atlas-opentrons-sim:10.1.0 workers/opentrons_sim
sim:
	uv run --locked pytest tests/golden_protocols

workflow:
	ATLAS_TEST_DATABASE_URL=$${ATLAS_TEST_DATABASE_URL:-postgresql://atlas:atlas-local-only@127.0.0.1:55432/atlas} uv run --locked pytest tests/workflow

reference-workflow:
	ATLAS_TEST_DATABASE_URL=$${ATLAS_TEST_DATABASE_URL:-postgresql://atlas:atlas-local-only@127.0.0.1:55432/atlas} uv run --locked pytest tests/reference_workflow

runtime-image:
	docker compose -f infra/compose/compose.yaml -f infra/compose/isolated.yaml build api
isolation:
	uv run --locked pytest tests/isolation

faults:
	ATLAS_TEST_DATABASE_URL=$${ATLAS_TEST_DATABASE_URL:-postgresql://atlas:atlas-local-only@127.0.0.1:55432/atlas} uv run --locked pytest tests/faults
