"""Shared env-var lookup used across the connection module."""

import os


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}. Check your .env file.")
    return value
