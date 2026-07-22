"""Snowflake connection and external stage helpers (key-pair auth)."""

import os
import re
from pathlib import Path

import snowflake.connector
from cryptography.hazmat.primitives import serialization
from dotenv import load_dotenv

from connection._env import require_env

load_dotenv()

STAGE_NAME = "RAW_S3_STAGE"

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def _validate_identifier(name: str, source: str) -> str:
    if not _SAFE_IDENTIFIER.match(name):
        raise RuntimeError(
            f"{source}={name!r} isn't a valid unquoted Snowflake identifier "
            f"(expected letters/digits/underscore, starting with a letter or underscore)."
        )
    return name


def _load_private_key(path: str, passphrase: str | None) -> bytes:
    key_path = Path(path)
    if not key_path.is_file():
        raise FileNotFoundError(
            f"Snowflake private key not found at {path} (from SNOWFLAKE_PRIVATE_KEY_PATH). "
            f"Check the path in .env — see docs/external_setup.md step 9."
        )

    key_bytes = key_path.read_bytes()
    try:
        private_key = serialization.load_pem_private_key(
            key_bytes,
            password=passphrase.encode() if passphrase else None,
        )
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            f"Could not load Snowflake private key from {path}: {exc}. Check that it's an "
            f"unencrypted PKCS8 PEM (openssl pkcs8 ... -nocrypt, per "
            f"docs/external_setup.md step 9) and that SNOWFLAKE_PRIVATE_KEY_PASSPHRASE "
            f"matches how it was generated."
        ) from exc

    return private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def get_snowflake_connection() -> snowflake.connector.SnowflakeConnection:
    """Return an authenticated Snowflake connection using key-pair auth."""
    account = require_env("SNOWFLAKE_ACCOUNT")
    user = require_env("SNOWFLAKE_USER")
    role = require_env("SNOWFLAKE_ROLE")
    warehouse = require_env("SNOWFLAKE_WAREHOUSE")
    database = require_env("SNOWFLAKE_DATABASE")
    schema = os.environ.get("SNOWFLAKE_SCHEMA") or "PUBLIC"
    passphrase = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE") or None

    private_key_der = _load_private_key(require_env("SNOWFLAKE_PRIVATE_KEY_PATH"), passphrase)

    return snowflake.connector.connect(
        account=account,
        user=user,
        role=role,
        warehouse=warehouse,
        database=database,
        schema=schema,
        private_key=private_key_der,
    )


def ensure_schema(conn: snowflake.connector.SnowflakeConnection, schema_name: str) -> None:
    """Idempotently create a schema in SNOWFLAKE_DATABASE."""
    database = _validate_identifier(require_env("SNOWFLAKE_DATABASE"), "SNOWFLAKE_DATABASE")
    schema_name = _validate_identifier(schema_name, "schema_name")

    with conn.cursor() as cur:
        try:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {database}.{schema_name}")
        except snowflake.connector.errors.ProgrammingError as exc:
            raise RuntimeError(
                f"Failed to create/verify schema {database}.{schema_name}: {exc}. "
                f"Check that SNOWFLAKE_ROLE has CREATE SCHEMA on the database "
                f"(docs/external_setup.md step 3)."
            ) from exc


def ensure_stage(conn: snowflake.connector.SnowflakeConnection) -> str:
    """Idempotently create the external stage against SNOWFLAKE_STORAGE_INTEGRATION
    and AWS_S3_BUCKET. Returns the fully-qualified stage name (no leading @)."""
    integration = require_env("SNOWFLAKE_STORAGE_INTEGRATION")
    bucket = require_env("AWS_S3_BUCKET")
    database = _validate_identifier(require_env("SNOWFLAKE_DATABASE"), "SNOWFLAKE_DATABASE")
    schema = os.environ.get("SNOWFLAKE_SCHEMA") or "PUBLIC"
    schema = _validate_identifier(schema, "SNOWFLAKE_SCHEMA")
    _validate_identifier(integration, "SNOWFLAKE_STORAGE_INTEGRATION")

    qualified_name = f"{database}.{schema}.{STAGE_NAME}"

    with conn.cursor() as cur:
        try:
            cur.execute(
                f"CREATE STAGE IF NOT EXISTS {qualified_name} "
                f"STORAGE_INTEGRATION = {integration} URL = %(url)s",
                {"url": f"s3://{bucket}/"},
            )
        except snowflake.connector.errors.ProgrammingError as exc:
            raise RuntimeError(
                f"Failed to create/verify stage {qualified_name} using storage integration "
                f"{integration}: {exc}. Check SNOWFLAKE_STORAGE_INTEGRATION and that "
                f"GRANT USAGE ON INTEGRATION was run (docs/external_setup.md step 8)."
            ) from exc

    return qualified_name
