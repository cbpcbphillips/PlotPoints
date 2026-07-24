"""Smoke-test the Snowflake + S3 connection layer (Phase 3 wiring).

Verifies auth, role/warehouse/database/schema context, external stage
creation, and S3 list access. Does not load any real data.
"""

import os

from botocore.exceptions import ClientError, NoCredentialsError
from dotenv import load_dotenv
from snowflake.connector.errors import ProgrammingError

from connection.s3 import get_s3_client
from connection.snowflake import ensure_stage, get_snowflake_connection
from raw_schema import (
    ensure_diary_entries_table,
    ensure_json_file_format,
    ensure_tmdb_titles_table,
)

load_dotenv()

AWS_S3_BUCKET = os.environ["AWS_S3_BUCKET"]


def check_snowflake():
    with get_snowflake_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT CURRENT_ROLE(), CURRENT_WAREHOUSE(), CURRENT_DATABASE(), CURRENT_SCHEMA()"
            )
            role, warehouse, database, schema = cur.fetchone()
            print(
                f"Connected: role={role} warehouse={warehouse} database={database} schema={schema}"
            )

            stage_name = ensure_stage(conn)
            print(f"Stage ready: {stage_name}")

            try:
                cur.execute(f"LIST @{stage_name}")
                rows = cur.fetchall()
            except ProgrammingError as exc:
                integration = os.environ.get("SNOWFLAKE_STORAGE_INTEGRATION", "<unset>")
                raise RuntimeError(
                    f"LIST @{stage_name} failed: {exc}. If this mentions Access Denied / "
                    f"AssumeRole / AuthorizationFailure, run DESC STORAGE INTEGRATION "
                    f"{integration} and confirm STORAGE_AWS_IAM_USER_ARN and "
                    f"STORAGE_AWS_EXTERNAL_ID exactly match the trust policy on the AWS IAM "
                    f"role (see docs/external_setup.md steps 7-8)."
                ) from exc

            print(f"LIST @{stage_name} -> {len(rows)} object(s)")

            table_name = ensure_diary_entries_table(conn)
            print(f"Table ready: {table_name}")

            titles_table_name = ensure_tmdb_titles_table(conn)
            print(f"Table ready: {titles_table_name}")

            file_format_name = ensure_json_file_format(conn)
            print(f"File format ready: {file_format_name}")


def check_s3():
    client = get_s3_client()
    try:
        response = client.list_objects_v2(Bucket=AWS_S3_BUCKET, MaxKeys=5)
    except NoCredentialsError as exc:
        raise RuntimeError(
            "boto3 found no AWS credentials. Check AWS_ACCESS_KEY_ID / "
            "AWS_SECRET_ACCESS_KEY in .env."
        ) from exc
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        raise RuntimeError(
            f"S3 list_objects_v2 on {AWS_S3_BUCKET} failed ({code}): {exc}. Check the "
            f"uploader IAM user's access key is active and has s3:ListBucket on this "
            f"bucket (docs/external_setup.md step 5)."
        ) from exc

    count = response.get("KeyCount", 0)
    print(f"S3 list on {AWS_S3_BUCKET} OK — {count} object(s) returned (showing up to 5)")


def main():
    print("== Snowflake ==")
    check_snowflake()
    print("\n== S3 ==")
    check_s3()
    print("\nAll connections verified.")


if __name__ == "__main__":
    main()
