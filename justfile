set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

fetch:
    uv run fetch_diary.py

lint:
    uv run ruff check .

format:
    uv run ruff format .

check:
    uv run ruff check .
    uv run ruff format --check .

install-hooks:
    uv run pre-commit install
