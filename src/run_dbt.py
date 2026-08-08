"""Run dbt against the plotpoints_dbt project with .env loaded and pinned tooling.

Wrapper so `just dbt <args>` works cross-platform: it loads .env into the environment
(dbt's profiles.yml reads the connection via env_var()), then invokes dbt isolated from
the app venv via uvx. Examples:
    uv run src/run_dbt.py debug
    uv run src/run_dbt.py build
    uv run src/run_dbt.py test
"""

import subprocess
import sys

from dotenv import load_dotenv

DBT_PIN = "dbt-snowflake==1.12.0"
PROJECT_DIR = "plotpoints_dbt"


def main():
    load_dotenv()  # populates os.environ; the dbt subprocess inherits it
    cmd = [
        "uvx",
        "--from",
        DBT_PIN,
        "dbt",
        *sys.argv[1:],
        "--project-dir",
        PROJECT_DIR,
        "--profiles-dir",
        PROJECT_DIR,
    ]
    sys.exit(subprocess.run(cmd).returncode)


if __name__ == "__main__":
    main()
