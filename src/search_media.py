"""Semantic search over the vectorized catalog (Phase 4 end-to-end proof).

Embeds a free-text query with the same Cortex model that built MART.MEDIA_EMBEDDINGS,
then ranks titles by VECTOR_COSINE_SIMILARITY. This is the mechanism Phase 5's
recommender runs on -- there the query vector is a user's taste vector instead of a
typed string, and watched titles get anti-joined out.

Run via `just search "a lonely robot on a dying earth"`.
"""

import argparse
import os
import sys

from dotenv import load_dotenv

from connection.snowflake import get_snowflake_connection

load_dotenv()

# Must match the dbt vars in plotpoints_dbt/dbt_project.yml -- embedding a query with
# a different model than the corpus produces silently meaningless similarity scores.
EMBEDDING_MODEL = "snowflake-arctic-embed-l-v2.0"
EMBEDDING_DIMENSION = 1024

SEARCH_SQL = """
with query_vector as (
    select snowflake.cortex.embed_text_{dimension}(%(model)s, %(query)s) as v
)
select
    m.title,
    year(m.release_date)                              as release_year,
    m.media_type,
    round(vector_cosine_similarity(e.embedding, q.v), 4) as similarity
from {database}.MART.MEDIA_EMBEDDINGS e
join {database}.MART.DIM_MEDIA m on m.media_key = e.media_key
cross join query_vector q
where e.embedding_model = %(model)s
order by similarity desc
limit %(limit)s
"""


def search(conn, query, limit):
    database = os.environ.get("SNOWFLAKE_DATABASE", "PLOTPOINTS_DB")
    sql = SEARCH_SQL.format(dimension=EMBEDDING_DIMENSION, database=database)

    with conn.cursor() as cur:
        cur.execute(sql, {"model": EMBEDDING_MODEL, "query": query, "limit": limit})
        return cur.fetchall()


def main():
    parser = argparse.ArgumentParser(description="Semantic search over the embedded catalog.")
    parser.add_argument("query", help="free-text description of what you want to watch")
    parser.add_argument("--limit", type=int, default=10, help="how many titles to return")
    args = parser.parse_args()

    # Titles and names carry non-ASCII; the Windows console defaults to cp1252 and
    # would otherwise raise UnicodeEncodeError mid-results.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    with get_snowflake_connection() as conn:
        rows = search(conn, args.query, args.limit)

    if not rows:
        print("No embeddings found. Has `just dbt build` run?")
        raise SystemExit(1)

    print(f'Top {len(rows)} for: "{args.query}"\n')
    for rank, (title, year, media_type, similarity) in enumerate(rows, start=1):
        label = f"{title} ({year})" if year else title
        kind = "TV" if media_type == "tv" else "film"
        print(f"{rank:>2}. {similarity:.4f}  {label}  [{kind}]")


if __name__ == "__main__":
    main()
