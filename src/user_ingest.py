"""Carry consented imports and deletion requests from the S3 inbox into the warehouse.

The API (stateless, public) drops two kinds of small JSON files into `inbox/` with a write-only
credential. This is the batch side that picks them up, and it is deliberately several small steps,
each runnable alone (`just user-ingest <step>`) and each safe to repeat:

  land      COPY the inbox into RAW.USER_IMPORTS / RAW.USER_DELETIONS. COPY skips files it already
            loaded, so a retry loads nothing twice.
  delete    Physically delete imports whose deletion token has been requested. dbt also filters
            them out in staging, so a missed run can never leak a deleted import into the marts.
  titles    Find imported films the catalog has never heard of, enrich them (the same
            source-agnostic TMDB enrichment the catalog uses) and land them in
            RAW.TMDB_TITLES, so the next dbt build can embed them and the recommender can see them.
  purge     Delete inbox files that are now safely in Snowflake. Personal data should not sit in
            S3 once it has a better home. Only files recorded in RAW are removed, never unseen ones.

Order matters in one place: `land` before `delete`, so a deletion that arrives in the same batch as
its import still removes it.
"""

from __future__ import annotations

import argparse
import json
import os

from dotenv import load_dotenv

from connection._env import require_env
from connection.s3 import get_s3_client
from connection.snowflake import get_snowflake_connection
from enrich_tmdb import APPEND_BY_TYPE_LEAN, enrich_entries_iter
from paths import CHECKPOINT_DIR
from raw_schema import (
    DELETIONS_PREFIX,
    IMPORTS_PREFIX,
    _qualified,
    copy_user_deletions,
    copy_user_imports,
    ensure_json_file_format,
    ensure_user_deletions_table,
    ensure_user_imports_table,
)

load_dotenv()

TITLES_OUTPUT = CHECKPOINT_DIR / "user_titles_enriched.jsonl"


def land() -> dict:
    with get_snowflake_connection() as conn:
        ensure_json_file_format(conn)
        ensure_user_imports_table(conn)
        ensure_user_deletions_table(conn)
        imports = copy_user_imports(conn)
        deletions = copy_user_deletions(conn)
    print(f"Landed {imports} import(s) and {deletions} deletion request(s)")
    return {"imports": imports, "deletions": deletions}


def apply_deletions() -> int:
    """Delete imports whose token hash has a deletion request. Returns rows removed."""
    with get_snowflake_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"delete from {_qualified('USER_IMPORTS')} where token_hash in "
            f"(select token_hash from {_qualified('USER_DELETIONS')})"
        )
        removed = cur.fetchone()[0]
    print(f"Deleted {removed} import(s) with a deletion request")
    return removed


def missing_titles() -> list[dict]:
    """Imported films with no row in RAW.TMDB_TITLES, as enrichment entries."""
    sql = f"""
        select distinct f.value:media_type::string, f.value:tmdb_id::number
        from {_qualified("USER_IMPORTS")} i, lateral flatten(input => i.record:films) f
        left join {_qualified("TMDB_TITLES")} t
          on t.media_type = f.value:media_type::string and t.tmdb_id = f.value:tmdb_id::number
        where t.tmdb_id is null and f.value:tmdb_id is not null
        order by 1, 2
    """
    with get_snowflake_connection() as conn, conn.cursor() as cur:
        cur.execute(sql)
        return [{"tmdb_media_type": mt, "tmdb_id": int(tid)} for mt, tid in cur.fetchall()]


def enrich_missing(limit: int = 500) -> dict:
    """Enrich imported films the catalog lacks. Capped per run, so a hostile or enormous import
    can't turn into an unbounded run of TMDB calls; the rest wait for the next run."""
    entries = missing_titles()
    pending = entries[:limit]
    TITLES_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    TITLES_OUTPUT.write_text("", encoding="utf-8")  # a fresh file per run: it is loaded whole
    matched = 0
    with TITLES_OUTPUT.open("a", encoding="utf-8") as fh:
        for enriched in enrich_entries_iter(pending, append_by_type=APPEND_BY_TYPE_LEAN):
            if enriched.get("matched"):  # an unmatched id has no title to land
                fh.write(json.dumps(enriched, separators=(",", ":"), ensure_ascii=False) + "\n")
                matched += 1
    deferred = len(entries) - len(pending)
    summary = {"missing": len(entries), "enriched": matched, "deferred": deferred}
    print(f"Titles: {summary}")
    return summary


def purge() -> int:
    """Remove inbox files already recorded in RAW. Needs s3:DeleteObject on inbox/*."""
    with get_snowflake_connection() as conn, conn.cursor() as cur:
        cur.execute(f"select source_file from {_qualified('USER_IMPORTS')}")
        landed = {r[0] for r in cur.fetchall()}
        cur.execute(f"select source_file from {_qualified('USER_DELETIONS')}")
        landed |= {r[0] for r in cur.fetchall()}
    landed = {key.lstrip("/") for key in landed if key}

    s3, bucket = get_s3_client(), require_env("AWS_S3_BUCKET")
    removed = 0
    for prefix in (IMPORTS_PREFIX, DELETIONS_PREFIX):
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                if obj["Key"] in landed:
                    s3.delete_object(Bucket=bucket, Key=obj["Key"])
                    removed += 1
    print(f"Purged {removed} inbox file(s) already landed in Snowflake")
    return removed


STEPS = {"land": land, "delete": apply_deletions, "titles": enrich_missing, "purge": purge}


def main():
    parser = argparse.ArgumentParser(description="Process the user inbox, one step at a time.")
    parser.add_argument("step", choices=sorted(STEPS) + ["all"])
    args = parser.parse_args()
    if os.environ.get("PLOTPOINTS_INBOX") == "local":
        raise SystemExit("PLOTPOINTS_INBOX=local writes to disk, not S3; nothing to ingest.")
    for name in ["land", "delete", "titles", "purge"] if args.step == "all" else [args.step]:
        STEPS[name]()


if __name__ == "__main__":
    main()
