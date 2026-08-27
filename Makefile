.PHONY: install lint test check run

install:
	uv sync --all-groups --locked

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

test:
	uv run pytest

check: lint test

run:
	uv run python -m profileproof
