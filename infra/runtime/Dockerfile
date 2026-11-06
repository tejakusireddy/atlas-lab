FROM python:3.11-slim@sha256:65bd3d9f1d7fa268dd1909973ba7eb4bdf41f6dcf2cfbe76ba9528b170f3fd79
COPY --from=ghcr.io/astral-sh/uv:0.10.4@sha256:4cac394b6b72846f8a85a7a0e577c6d61d4e17fe2ccee65d9451a8b3c9efb4ac /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY apps/api ./apps/api
COPY sql ./sql
RUN uv sync --locked --no-dev --no-editable --all-packages
ENV PATH="/app/.venv/bin:$PATH" HOME=/tmp PYTHONDONTWRITEBYTECODE=1 MLFLOW_DISABLE_AGENT_HINT=1
USER 10001:10001
CMD ["uvicorn", "atlas_api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
