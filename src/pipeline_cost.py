"""Warehouse cost of recent pipeline activity, from INFORMATION_SCHEMA.QUERY_HISTORY.

PLOTPOINTS_ROLE cannot read SNOWFLAKE.ACCOUNT_USAGE, but it can read the information-schema
QUERY_HISTORY table function, which is enough to see how long the warehouse worked. That is
an *estimate* of billed credits, not the bill: Snowflake meters per-second with a 60 s
minimum each time a warehouse resumes, and concurrent queries share one meter, so summed
query time overstates a busy warehouse and understates a cold-start one. For billed truth,
ACCOUNTADMIN can read SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY in Snowsight.

AI (Cortex) credits are not warehouse credits and don't appear here -- they are derived from
token counts against the published per-million-token rate (see CLAUDE.md).

Run via `just cost [--minutes N]`; the Airflow `transform` DAG calls warehouse_cost() as its
final task so every run records what it spent.
"""

import argparse
import os

from dotenv import load_dotenv

from connection.snowflake import get_snowflake_connection

load_dotenv()

# Credits per hour by warehouse size (standard Snowflake warehouse sizing).
CREDITS_PER_HOUR = {
    "X-Small": 1,
    "Small": 2,
    "Medium": 4,
    "Large": 8,
    "X-Large": 16,
}

# QUERY_HISTORY returns only 100 rows unless told otherwise, and a full dbt build issues more
# queries than that -- silently truncating the sum and under-reporting cost.
RESULT_LIMIT = 10_000

QUERY = """
select warehouse_size, count(*), sum(total_elapsed_time) / 1000.0
from table(information_schema.query_history(
    end_time_range_start => dateadd('minute', -%(minutes)s, current_timestamp()),
    end_time_range_end   => current_timestamp(),
    result_limit         => %(limit)s
))
where warehouse_name = %(warehouse)s
group by warehouse_size
"""


def warehouse_cost(minutes: int = 60) -> dict:
    """Estimated warehouse credits for queries that finished in the last `minutes`."""
    warehouse = os.environ["SNOWFLAKE_WAREHOUSE"]

    with get_snowflake_connection() as conn, conn.cursor() as cur:
        cur.execute(QUERY, {"minutes": minutes, "limit": RESULT_LIMIT, "warehouse": warehouse})
        rows = cur.fetchall()

    queries = 0
    seconds = 0.0
    credits = 0.0
    for size, count, elapsed in rows:
        elapsed = float(elapsed or 0)
        queries += count
        seconds += elapsed
        credits += elapsed / 3600 * CREDITS_PER_HOUR.get(size, 1)

    return {
        "warehouse": warehouse,
        "window_minutes": minutes,
        "queries": queries,
        "elapsed_seconds": round(seconds, 1),
        "estimated_credits": round(credits, 4),
        "truncated": queries >= RESULT_LIMIT,
    }


def main():
    parser = argparse.ArgumentParser(description="Estimate recent warehouse credit usage.")
    parser.add_argument("--minutes", type=int, default=60, help="look-back window")
    args = parser.parse_args()

    result = warehouse_cost(args.minutes)
    print(
        f"{result['warehouse']}: {result['queries']} queries, "
        f"{result['elapsed_seconds']}s elapsed in the last {result['window_minutes']} min "
        f"-> ~{result['estimated_credits']} credits (estimate)"
    )
    if result["truncated"]:
        print(f"WARNING: hit the {RESULT_LIMIT}-row cap; the true figure is higher.")


if __name__ == "__main__":
    main()
