.PHONY: install lint fmt test test-int up down verify verify-quick demo
install:
	pip install -e ".[dev]"
lint:
	ruff check . && ruff format --check .
fmt:
	ruff check --fix . && ruff format .
test:
	pytest -m "not integration"
test-int:
	pytest -m integration
up:
	docker compose up -d db
down:
	docker compose down
verify:
	python tools/verify.py
verify-quick:
	python tools/verify.py --quick
demo:
	python tools/demo.py
