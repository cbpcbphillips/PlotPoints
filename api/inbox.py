"""Consented imports and deletion requests, dropped where the batch pipeline can pick them up.

The API's only AWS permission is s3:PutObject on `inbox/*`. It can add files; it cannot read,
list or delete anything, and it never touches Snowflake. A leaked key therefore exposes nothing
already stored. For local development PLOTPOINTS_INBOX=local writes to data/inbox/ instead.

Deletion is token-based because the app has no accounts: consenting returns a random token once,
and only its SHA-256 goes into the record. Possession of the token is the right to delete.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import uuid
from datetime import UTC, datetime
from pathlib import Path


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Inbox:
    def __init__(self) -> None:
        self.mode = os.environ.get("PLOTPOINTS_INBOX", "local")
        self.local_dir = Path(os.environ.get("PLOTPOINTS_DATA_DIR", "data")) / "inbox"
        self._s3 = None
        self._bucket = os.environ.get("AWS_S3_BUCKET", "")
        if self.mode == "s3":
            import boto3

            self._s3 = boto3.client(
                "s3",
                aws_access_key_id=os.environ["INBOX_AWS_ACCESS_KEY_ID"],
                aws_secret_access_key=os.environ["INBOX_AWS_SECRET_ACCESS_KEY"],
                region_name=os.environ.get("AWS_REGION") or "us-east-1",
            )

    def _put(self, key: str, record: dict) -> None:
        body = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if self._s3 is not None:
            self._s3.put_object(Bucket=self._bucket, Key=key, Body=body)
        else:
            path = self.local_dir / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)

    def store_import(self, *, source: str, username: str | None, films: list[dict]) -> dict:
        """Write one consented import. Returns the deletion token, which is not stored."""
        token = secrets.token_urlsafe(32)
        import_id = uuid.uuid4().hex
        now = datetime.now(UTC).isoformat(timespec="seconds")
        record = {
            "import_id": import_id,
            "token_hash": token_hash(token),
            "consented_at": now,
            "source": source,
            # a public Letterboxd username is only kept when it is what the person imported from
            "user_id": username.lower() if username else f"import-{import_id[:8]}",
            "films": films,
        }
        self._put(f"inbox/imports/{import_id}.json", record)
        return {"import_id": import_id, "token": token}

    def store_wanted(self, titles: list[tuple[str, int]]) -> None:
        """Films an import contained that the catalog lacks: ids only, never who asked."""
        record = {
            "requested_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "titles": [{"media_type": mt, "tmdb_id": int(tid)} for mt, tid in titles],
        }
        self._put(f"inbox/titles/{uuid.uuid4().hex}.json", record)

    def request_deletion(self, token: str) -> None:
        h = token_hash(token)
        record = {"token_hash": h, "requested_at": datetime.now(UTC).isoformat(timespec="seconds")}
        self._put(f"inbox/deletions/{h}.json", record)
