# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.11.19 AS uv

FROM python:3.12-slim-bookworm AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm AS runtime
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    PROFILEPROOF_ENVIRONMENT=production
RUN addgroup --system --gid 10001 profileproof \
    && adduser --system --uid 10001 --ingroup profileproof --home /nonexistent profileproof
WORKDIR /app
COPY --from=builder --chown=10001:10001 /app/.venv /app/.venv
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "profileproof"]
