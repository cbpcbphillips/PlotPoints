FROM astrocrpublic.azurecr.io/runtime:3.3-12

# dbt gets its own virtualenv. dbt-snowflake and Airflow pin conflicting versions of shared
# dependencies, and installing both into one environment is the classic Cosmos failure.
# Cosmos is pointed at this interpreter via ExecutionConfig(dbt_executable_path=...).
# dbt-core is pinned explicitly, not left to float: with only dbt-snowflake pinned, pip resolved
# a 1.13.0 *beta* of dbt-core here, while the host (`just dbt`, via uvx) runs stable 1.12.7.
# The adapter version matches src/run_dbt.py's DBT_PIN.
RUN python -m venv /usr/local/airflow/dbt_venv \
    && /usr/local/airflow/dbt_venv/bin/pip install --no-cache-dir \
        dbt-core==1.12.7 dbt-snowflake==1.12.0

# The pipeline modules in src/ are flat (`from enrich_tmdb import ...`), so src itself must be
# importable. The base image already sets PYTHONPATH=/usr/local/airflow; extend, don't replace.
ENV PYTHONPATH=/usr/local/airflow:/usr/local/airflow/src

# Checkpoints land in a bind-mounted directory (see docker-compose.override.yml), not in
# the image layer. src/paths.py reads this.
ENV PLOTPOINTS_DATA_DIR=/usr/local/airflow/data
