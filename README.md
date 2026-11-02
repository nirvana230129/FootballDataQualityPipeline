# Football Data Quality & ETL Platform

Local pipeline for StatsBomb / football-data.org load, data quality, and football metrics.

## Phase 1 status

Vertical slice for StatsBomb World Cup 2022 final (`match_id=3869685`):

1. raw ingest
2. staging / core
3. five DQ checks
4. box entries, progressive passes, shot possessions
5. box entry pitch map

## Specs

- [docs/data_contract.md](docs/data_contract.md)
- [docs/metrics.md](docs/metrics.md)
- [docs/dq_rules.md](docs/dq_rules.md)

## How to run

```bash
cp .env.example .env
# set FOOTBALL_DATA_ORG_API_KEY later for phase 3

docker compose up -d
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python -m src.pipeline run --match-id 3869685
```

Step by step:

```bash
python -m src.pipeline init
python -m src.pipeline ingest --match-id 3869685
python -m src.pipeline build --match-id 3869685
python -m src.pipeline dq --match-id 3869685
python -m src.pipeline marts
python -m src.pipeline viz --match-id 3869685
```

Output map: `artifacts/box_entries_3869685.png`
