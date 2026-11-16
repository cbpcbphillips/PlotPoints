"""Where pipeline artifacts live on disk.

Checkpoints used to be hard-coded relative to the working directory, which only worked
because every script was launched from the repo root. A container worker makes no such
promise -- an orchestrator can start a task from anywhere -- so the location is now an
env var (PLOTPOINTS_DATA_DIR) with the old relative path as the default. Local `just`
usage is unchanged; the Airflow image points it at the bind-mounted data directory.
"""

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("PLOTPOINTS_DATA_DIR", "data"))
CHECKPOINT_DIR = DATA_DIR / "checkpoints"
