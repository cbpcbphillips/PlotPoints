"""Check the API's inbox credential is exactly as powerful as it should be, and no more.

The hosted API drops consented imports and deletion requests into `inbox/` with a write-only key
(INBOX_AWS_ACCESS_KEY_ID / INBOX_AWS_SECRET_ACCESS_KEY). That key may `PutObject` on `inbox/*`
and nothing else: it cannot read, list or delete anything, and it cannot write outside `inbox/`. A
leaked key then exposes nothing already stored, and this script is how you prove the policy says
that.

Read-only by default (credentials present, identity). With --write it:
  1. puts a probe object under inbox/_healthcheck/ with the API key (must succeed),
  2. tries to read it, list the bucket, delete it, and write outside inbox/ with the API key
     (each must be DENIED; a permitted one is a FAIL, because the key is too powerful),
  3. removes the probe with the pipeline uploader's key (AWS_ACCESS_KEY_ID), which needs
     s3:DeleteObject on inbox/* (the same permission `just user-ingest purge` uses).

Run via `just test-inbox` (add --write for the full check). Output is ASCII-only for the Windows
console.
"""

import argparse
import os
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

from check_common import CheckWarning, run_checks
from connection._env import require_env
from connection.s3 import get_s3_client

load_dotenv()

PROBE_BODY = b"plotpoints inbox check\n"
DENIED = {"AccessDenied", "AllAccessDisabled", "Forbidden", "403"}


def _code(exc):
    return exc.response.get("Error", {}).get("Code", "")


def api_client():
    """An S3 client holding ONLY the API's inbox credential."""
    return boto3.client(
        "s3",
        aws_access_key_id=require_env("INBOX_AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=require_env("INBOX_AWS_SECRET_ACCESS_KEY"),
        region_name=os.environ.get("AWS_REGION") or "us-east-1",
    )


def check_env():
    require_env("INBOX_AWS_ACCESS_KEY_ID")
    require_env("INBOX_AWS_SECRET_ACCESS_KEY")
    bucket = require_env("AWS_S3_BUCKET")
    return f"bucket {bucket}"


def check_identity():
    try:
        arn = boto3.client(
            "sts",
            aws_access_key_id=require_env("INBOX_AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=require_env("INBOX_AWS_SECRET_ACCESS_KEY"),
            region_name=os.environ.get("AWS_REGION") or "us-east-1",
        ).get_caller_identity()["Arn"]
    except ClientError as exc:
        raise CheckWarning(
            f"sts:GetCallerIdentity denied ({_code(exc)}) -- fine for a least-privilege key"
        ) from exc
    return arn


def _must_be_denied(action, call):
    """Run `call`; PASS if S3 refuses it, FAIL if the key was allowed to do it."""

    def probe():
        try:
            call()
        except ClientError as exc:
            code = _code(exc)
            if code in DENIED:
                return f"denied ({code}), as it should be"
            raise RuntimeError(
                f"{action} failed for a reason other than permission: {code}"
            ) from exc
        raise RuntimeError(f"{action} was ALLOWED. The API key has more permission than intended.")

    return probe


def main():
    parser = argparse.ArgumentParser(description="Check the API inbox credential.")
    parser.add_argument(
        "--write",
        action="store_true",
        help="exercise the policy: one probe write, then confirm everything else is denied",
    )
    parser.add_argument("--verbose", action="store_true", help="print tracebacks on failure")
    args = parser.parse_args()

    checks = [("inbox credentials", check_env), ("caller identity", check_identity)]

    if args.write:
        bucket = require_env("AWS_S3_BUCKET")
        api = api_client()
        uploader = get_s3_client()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        probe_id = f"{stamp}-{uuid.uuid4().hex[:8]}"
        key = f"inbox/_healthcheck/{probe_id}.json"
        outside = f"_healthcheck/inbox-key-outside-{probe_id}.txt"
        state = {"written": False, "outside": False}

        def put():
            try:
                api.put_object(Bucket=bucket, Key=key, Body=PROBE_BODY)
            except ClientError as exc:
                raise RuntimeError(
                    f"put_object on inbox/ failed ({_code(exc)}). The API key needs "
                    f"s3:PutObject on inbox/* (docs/external_setup.md, API inbox user)."
                ) from exc
            state["written"] = True
            return f"wrote s3://{bucket}/{key}"

        def write_outside():
            try:
                api.put_object(Bucket=bucket, Key=outside, Body=PROBE_BODY)
            except ClientError as exc:
                code = _code(exc)
                if code in DENIED:
                    return f"denied ({code}), as it should be"
                raise RuntimeError(f"write outside inbox/ failed oddly: {code}") from exc
            state["outside"] = True
            raise RuntimeError("write outside inbox/ was ALLOWED. The API key is too broad.")

        def cleanup():
            removed = []
            for k, flag in ((key, "written"), (outside, "outside")):
                if state[flag]:
                    try:
                        uploader.delete_object(Bucket=bucket, Key=k)
                        removed.append(k)
                    except ClientError as exc:
                        raise CheckWarning(
                            f"could not remove s3://{bucket}/{k} with the uploader key "
                            f"({_code(exc)}). The uploader needs s3:DeleteObject on inbox/* "
                            f"(docs/external_setup.md, uploader policy); remove it by hand."
                        ) from exc
            return f"removed {len(removed)} probe object(s) with the uploader key"

        checks += [
            ("put into inbox/", put),
            (
                "read (denied)",
                _must_be_denied("get_object", lambda: api.get_object(Bucket=bucket, Key=key)),
            ),
            (
                "list (denied)",
                _must_be_denied("list_objects_v2", lambda: api.list_objects_v2(Bucket=bucket)),
            ),
            (
                "delete (denied)",
                _must_be_denied("delete_object", lambda: api.delete_object(Bucket=bucket, Key=key)),
            ),
            ("write elsewhere (denied)", write_outside),
            ("clean up probes", cleanup),
        ]

    raise SystemExit(run_checks("API inbox credential", checks, verbose=args.verbose))


if __name__ == "__main__":
    main()
