.PHONY: install lint fmt test up down
install:
	pip install -e ".[dev]"
lint:
	ruff check . && ruff format --check .
fmt:
	ruff check --fix . && ruff format .
test:
	pytest -m "not integration"
up:
	docker compose up -d db
down:
	docker compose down
