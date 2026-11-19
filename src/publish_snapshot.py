"""Publish the serving snapshot: MART -> data/snapshots/<version>/ (-> S3 artifacts/snapshots/).

The API holds this in memory instead of querying Snowflake (roadmap decision 8), so this is the
bridge between the warehouse and the product. One read of MART, about 0.01 credits; the vectors are
the bulk (23.7k x 1024 float16 = 49 MB).

A snapshot is named by a hash of its content, so republishing unchanged data is a no-op, and a
deploy can say exactly which data it serves.

Run via `just snapshot` (add --upload to also push it to S3).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

import snapshot
from connection.snowflake import get_snowflake_connection
from paths import DATA_DIR

load_dotenv()

SNAPSHOT_DIR = DATA_DIR / "snapshots"
S3_PREFIX = "artifacts/snapshots"


def _database() -> str:
    return os.environ.get("SNOWFLAKE_DATABASE", "PLOTPOINTS_DB")


def build(conn) -> tuple[np.ndarray, dict, str, str]:
    """Read MART into (vectors, catalog dict, embedding_model, providers_as_of)."""
    db = _database()
    with conn.cursor() as cur:
        cur.execute(
            f"select embedding_model from {db}.MART.MEDIA_EMBEDDINGS group by 1 "
            "order by count(*) desc limit 1"
        )
        model = cur.fetchone()[0]

        cur.execute(
            f"""
            select e.media_key, e.embedding, m.media_type, m.tmdb_id, m.title,
                   year(m.release_date), m.runtime_minutes, m.tmdb_rating, m.vote_count,
                   m.poster_path, m.franchise, m.original_title, m.backdrop_path
            from {db}.MART.MEDIA_EMBEDDINGS e
            join {db}.MART.DIM_MEDIA m on m.media_key = e.media_key
            where e.embedding_model = %s
            order by e.media_key
            """,
            (model,),
        )
        rows = cur.fetchall()

        # the quality prior's anchor is the mean over ALL rated titles, matching SCORE_SQL
        cur.execute(
            f"select avg(tmdb_rating) from {db}.MART.DIM_MEDIA "
            "where tmdb_rating is not null and vote_count > 0"
        )
        catalog_mean = float(cur.fetchone()[0])

        cur.execute(
            f"select media_key, provider_group, count(*) over (partition by provider_group) "
            f"from {db}.MART.BRIDGE_MEDIA_PROVIDER"
        )
        provider_rows = cur.fetchall()

        cur.execute(
            f"select b.media_key, g.genre_name from {db}.MART.BRIDGE_MEDIA_GENRE b "
            f"join {db}.MART.DIM_GENRE g on g.genre_id = b.genre_id"
        )
        genre_rows = cur.fetchall()

        # when TMDB's availability data was fetched: the newest catalog load
        cur.execute(f"select max(loaded_at) from {db}.RAW.TMDB_TITLES")
        loaded = cur.fetchone()[0]

    # most-available provider groups first, so the UI's quick-pick list needs no sorting
    totals: dict[str, int] = {}
    for _, group, n in provider_rows:
        totals[group] = n
    provider_names = sorted(totals, key=lambda g: (-totals[g], g))
    provider_ix = {g: i for i, g in enumerate(provider_names)}
    by_media: dict[str, set[int]] = defaultdict(set)
    for media_key, group, _ in provider_rows:
        by_media[media_key].add(provider_ix[group])
    genres: dict[str, list[str]] = defaultdict(list)
    for media_key, name in genre_rows:
        genres[media_key].append(name)

    vectors = np.asarray([r[1] for r in rows], dtype=np.float32)
    catalog = {
        "catalog_mean_rating": catalog_mean,
        "media_key": [r[0] for r in rows],
        "media_type": [r[2] for r in rows],
        "tmdb_id": [int(r[3]) for r in rows],
        "title": [r[4] for r in rows],
        "year": [r[5] for r in rows],
        "runtime": [None if r[6] is None else int(r[6]) for r in rows],
        "rating": [None if r[7] is None else round(float(r[7]), 3) for r in rows],
        "votes": [None if r[8] is None else int(r[8]) for r in rows],
        "poster": [r[9] for r in rows],
        "backdrop": [r[12] for r in rows],
        "original_title": [r[11] if r[11] and r[11] != r[4] else None for r in rows],
        "franchise": [r[10] for r in rows],
        "genres": [sorted(genres.get(r[0], [])) for r in rows],
        "providers": [sorted(by_media.get(r[0], [])) for r in rows],
        "provider_names": provider_names,
    }
    as_of = loaded.date().isoformat() if loaded else datetime.now(UTC).date().isoformat()
    return vectors, catalog, model, as_of


def run(upload: bool = False) -> dict:
    """Build a snapshot, write it under data/snapshots/<version>/, optionally push it to S3."""
    with get_snowflake_connection() as conn:
        vectors, catalog, model, providers_as_of = build(conn)

    staging = SNAPSHOT_DIR / "_building"
    if staging.exists():
        shutil.rmtree(staging)
    manifest = snapshot.save(
        staging,
        vectors=vectors,
        catalog=catalog,
        embedding_model=model,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        providers_as_of=providers_as_of,
    )
    final = SNAPSHOT_DIR / manifest["version"]
    if final.exists():
        shutil.rmtree(staging)
        print(f"Snapshot {manifest['version']} already published; nothing changed.")
    else:
        staging.rename(final)
        print(
            f"Wrote snapshot {manifest['version']}: {manifest['titles']} titles x "
            f"{manifest['dimension']} dims, {manifest['providers']} provider groups, "
            f"model {model}"
        )
    (SNAPSHOT_DIR / "LATEST").write_text(manifest["version"], encoding="utf-8")

    if upload:
        upload_to_s3(final, manifest["version"])
    return manifest


def upload_to_s3(directory: Path, version: str) -> None:
    from connection._env import require_env
    from connection.s3 import get_s3_client

    s3, bucket = get_s3_client(), require_env("AWS_S3_BUCKET")
    for path in sorted(directory.iterdir()):
        key = f"{S3_PREFIX}/{version}/{path.name}"
        s3.upload_file(str(path), bucket, key)
        print(f"  uploaded s3://{bucket}/{key} ({path.stat().st_size / 1e6:.1f} MB)")
    s3.put_object(
        Bucket=bucket,
        Key=f"{S3_PREFIX}/LATEST.json",
        Body=json.dumps({"version": version}).encode(),
    )


def latest_directory() -> Path:
    """The newest locally published snapshot."""
    pointer = SNAPSHOT_DIR / "LATEST"
    if not pointer.exists():
        raise SystemExit("No snapshot yet. Run `just snapshot` first.")
    return SNAPSHOT_DIR / pointer.read_text(encoding="utf-8").strip()


def stage(destination: Path) -> None:
    """Copy the newest published snapshot to `destination` for a Docker build.

    .dockerignore keeps data/ out of every image, so the API's build context gets its snapshot
    from a staging directory instead.
    """
    source = latest_directory()
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    print(f"Staged snapshot {source.name} -> {destination}")


def main():
    parser = argparse.ArgumentParser(description="Publish the serving snapshot from MART.")
    parser.add_argument("--upload", action="store_true", help="also push it to S3 artifacts/")
    parser.add_argument(
        "--stage",
        type=Path,
        metavar="DIR",
        help="don't publish; copy the newest local snapshot to DIR (for the API image build)",
    )
    args = parser.parse_args()
    if args.stage:
        stage(args.stage)
        return
    run(upload=args.upload)


if __name__ == "__main__":
    main()
