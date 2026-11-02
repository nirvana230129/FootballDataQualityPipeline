# Football Data Quality & ETL Platform

Local pipeline for StatsBomb / football-data.org load, data quality, and football metrics.

## Status

### Phase 1

Vertical slice for StatsBomb World Cup 2022 final (`match_id=3869685`):

1. raw ingest
2. staging / core
3. five DQ checks
4. box entries, progressive passes, shot possessions
5. box entry pitch map

### Phase 2

Full StatsBomb WC 2022 tournament in `DQ_MODE=observe`:

- 64 matches through raw → staging → core
- DQ on every match
- marts rebuild for all `PUBLISHABLE` matches
- profiles for event volumes, coordinates, and types without location

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
```

One match:

```bash
python -m src.pipeline run --match-id 3869685
```

Full tournament:

```bash
DQ_MODE=observe python -m src.pipeline run --competition WC2022
python -m src.pipeline profile --competition WC2022
```

Step by step:

```bash
python -m src.pipeline init
python -m src.pipeline ingest --competition WC2022
python -m src.pipeline build --competition WC2022
python -m src.pipeline dq --competition WC2022
python -m src.pipeline marts
python -m src.pipeline viz --match-id 3869685
python -m src.pipeline profile --competition WC2022
```

Artifacts:

- map: `artifacts/box_entries_3869685.png`
- profiles: `artifacts/profiles/`
