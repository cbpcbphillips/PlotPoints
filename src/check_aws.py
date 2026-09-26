"""Connection check for AWS S3.

Verifies the uploader credentials against the bucket the loader stages NDJSON into.
Read-only by default. Pass --write to additionally exercise the real load path
with a put/get/delete round trip on a small probe object under _healthcheck/. That
is opt-in because the uploader IAM user is write-only: it can PutObject but not
DeleteObject, so each --write run leaves a probe object behind for you to clear.

Run via `just test-aws`.
"""

import argparse
import os
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from dotenv import load_dotenv

from check_common import CheckWarning, run_checks
from connection._env import require_env
from connection.s3 import get_s3_client

load_dotenv()

PROBE_PREFIX = "_healthcheck"
PROBE_BODY = b"plotpoints connection check\n"


def _error_code(exc):
    return exc.response.get("Error", {}).get("Code", "")


def check_env():
    require_env("AWS_ACCESS_KEY_ID")
    require_env("AWS_SECRET_ACCESS_KEY")
    bucket = require_env("AWS_S3_BUCKET")
    region = os.environ.get("AWS_REGION") or "us-east-1"
    return f"bucket {bucket} in {region}"


def check_identity():
    """Who the uploader key belongs to. Often denied for a least-privilege user."""

    def probe():
        sts = boto3.client(
            "sts",
            aws_access_key_id=require_env("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=require_env("AWS_SECRET_ACCESS_KEY"),
            region_name=os.environ.get("AWS_REGION") or "us-east-1",
        )
        try:
            identity = sts.get_caller_identity()
        except ClientError as exc:
            raise CheckWarning(
                f"sts:GetCallerIdentity denied ({_error_code(exc)}) -- fine for a "
                f"least-privilege uploader"
            ) from exc
        return identity.get("Arn", "<no arn>")

    return probe


def check_bucket(client, bucket):
    def probe():
        try:
            client.head_bucket(Bucket=bucket)
        except NoCredentialsError as exc:
            raise RuntimeError(
                "boto3 found no AWS credentials. Check AWS_ACCESS_KEY_ID / "
                "AWS_SECRET_ACCESS_KEY in .env."
            ) from exc
        except ClientError as exc:
            code = _error_code(exc)
            raise RuntimeError(
                f"head_bucket failed ({code}). 404 means the bucket name in "
                f"AWS_S3_BUCKET is wrong; 403 means the uploader IAM user lacks access "
                f"(docs/external_setup.md step 5)."
            ) from exc
        return "reachable"

    return probe


def check_list(client, bucket):
    def probe():
        try:
            response = client.list_objects_v2(Bucket=bucket, MaxKeys=5)
        except ClientError as exc:
            raise RuntimeError(
                f"list_objects_v2 failed ({_error_code(exc)}). The uploader needs "
                f"s3:ListBucket on this bucket (docs/external_setup.md step 5)."
            ) from exc
        return f"{response.get('KeyCount', 0)} object(s) at the bucket root"

    return probe


def _probe_key():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{PROBE_PREFIX}/{stamp}-{uuid.uuid4().hex[:8]}.txt"


def check_round_trip(client, bucket, key, state):
    """put -> get -> delete. State is shared so the delete probe knows what landed."""

    def put():
        try:
            client.put_object(Bucket=bucket, Key=key, Body=PROBE_BODY)
        except ClientError as exc:
            raise RuntimeError(
                f"put_object failed ({_error_code(exc)}). The loader needs s3:PutObject "
                f"on this bucket (docs/external_setup.md step 5)."
            ) from exc
        state["written"] = True
        return f"wrote s3://{bucket}/{key}"

    def get():
        if not state.get("written"):
            raise CheckWarning("skipped -- nothing was written")
        try:
            body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        except ClientError as exc:
            raise CheckWarning(
                f"s3:GetObject denied ({_error_code(exc)}) -- expected if the uploader "
                f"is write-only; Snowflake reads via the storage integration, not this key"
            ) from exc
        if body != PROBE_BODY:
            raise RuntimeError(f"read back {body!r}, expected {PROBE_BODY!r}")
        return "read back byte-identical"

    def delete():
        if not state.get("written"):
            raise CheckWarning("skipped -- nothing was written")
        try:
            client.delete_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            raise CheckWarning(
                f"s3:DeleteObject denied ({_error_code(exc)}) -- probe object left at "
                f"s3://{bucket}/{key}, remove it by hand"
            ) from exc
        return "probe object removed"

    return put, get, delete


def main():
    parser = argparse.ArgumentParser(description="Check the AWS S3 connection.")
    parser.add_argument(
        "--write",
        action="store_true",
        help="also exercise s3:PutObject (leaves a probe object; the uploader cannot delete)",
    )
    parser.add_argument("--verbose", action="store_true", help="print tracebacks on failure")
    args = parser.parse_args()

    bucket = os.environ.get("AWS_S3_BUCKET", "")
    client = get_s3_client()

    checks = [
        ("credentials", check_env),
        ("caller identity", check_identity()),
        ("bucket reachable", check_bucket(client, bucket)),
        ("list objects", check_list(client, bucket)),
    ]

    if args.write:
        key = _probe_key()
        put, get, delete = check_round_trip(client, bucket, key, {})
        checks += [
            ("put object", put),
            ("get object", get),
            ("delete object", delete),
        ]

    raise SystemExit(run_checks("AWS S3", checks, verbose=args.verbose))


if __name__ == "__main__":
    main()
