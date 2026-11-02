"""Airflow DAG: football_data_pipeline.

Thin orchestration over src.orchestration / CLI — no duplicated business rules.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator

from src.orchestration import (
    run_extract,
    run_dq,
    run_init,
    run_resolve_entities,
    run_sql_step,
)

DEFAULT_ARGS = {
    "owner": "football",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}

EXTRACT_ARGS = {
    **DEFAULT_ARGS,
    "retries": 3,
    "retry_delay": timedelta(minutes=2),
}


with DAG(
    dag_id="football_data_pipeline",
    description="WC2022 StatsBomb + football-data.org ETL / DQ / marts",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2022, 11, 20),
    schedule=None,
    catchup=False,
    tags=["football", "wc2022"],
) as dag:
    init_schemas = PythonOperator(
        task_id="init_schemas",
        python_callable=run_init,
    )

    extract_load_statsbomb = PythonOperator(
        task_id="extract_load_statsbomb",
        python_callable=run_extract,
        op_kwargs={"provider": "statsbomb", "competition": "WC2022"},
        retries=3,
        retry_delay=timedelta(minutes=2),
    )

    transform_statsbomb = PythonOperator(
        task_id="transform_statsbomb",
        python_callable=run_sql_step,
        op_kwargs={"step": "build", "competition": "WC2022"},
    )

    extract_load_transform_football_data = PythonOperator(
        task_id="extract_load_transform_football_data",
        python_callable=run_extract,
        op_kwargs={"provider": "football_data", "competition": "WC2022"},
        retries=3,
        retry_delay=timedelta(minutes=2),
    )

    resolve_entities = PythonOperator(
        task_id="resolve_entities",
        python_callable=run_resolve_entities,
    )

    run_dq_checks = PythonOperator(
        task_id="run_dq_checks",
        python_callable=run_dq,
        op_kwargs={"competition": "WC2022"},
    )

    publish_rebuild_marts = PythonOperator(
        task_id="publish_rebuild_marts",
        python_callable=run_sql_step,
        op_kwargs={"step": "marts"},
    )

    # StatsBomb branch and football-data branch run in parallel after init.
    init_schemas >> [extract_load_statsbomb, extract_load_transform_football_data]
    extract_load_statsbomb >> transform_statsbomb
    [transform_statsbomb, extract_load_transform_football_data] >> resolve_entities
    resolve_entities >> run_dq_checks >> publish_rebuild_marts
