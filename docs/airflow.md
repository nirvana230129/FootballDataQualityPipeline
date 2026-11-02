# Airflow (phase 5)

LocalExecutor on the same `postgres:16.4` instance:

- app DB: `football`
- metadata DB: `airflow` (created by `docker/postgres/init-airflow-db.sql` or `airflow-init`)

Image pin: `apache/airflow:3.0.2-python3.12` → built as `football-airflow:3.0.2-python3.12` via [`Dockerfile.airflow`](../Dockerfile.airflow) + lean [`requirements-airflow.txt`](../requirements-airflow.txt) (no matplotlib/pandas upgrades).

DAG [`dags/football_pipeline.py`](../dags/football_pipeline.py) calls [`src/orchestration.py`](../src/orchestration.py) only — no duplicated SQL/business rules.

Operational notes (local Docker Desktop / macOS):

- use `AIRFLOW_UID=50000` (not the host UID)
- `CONNECTION_CHECK_MAX_COUNT=0` skips entrypoint `airflow db check` (can spin on this setup); migrations run in `airflow-init`
- api-server runs with `--workers 1`
- DAG parse can take ~30–40s; import/processor timeouts are raised in compose

CLI remains the primary way to run the pipeline. Airflow adds order, retries on extract, and observability.
