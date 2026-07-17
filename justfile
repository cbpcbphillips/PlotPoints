set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

fetch:
    uv run src/fetch_diary.py

smoke-test:
    uv run src/smoke_test_connections.py

lint:
    uv run ruff check .

format:
    uv run ruff format .

check:
    uv run ruff check .
    uv run ruff format --check .

install-hooks:
    uv run pre-commit install
