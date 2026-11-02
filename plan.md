# Football Data Quality & ETL Platform

## 1. Идея проекта

Построить production-like платформу для загрузки, проверки, нормализации и аналитики футбольных данных из нескольких источников.

Проект должен имитировать реальный data pipeline спортивной аналитики:

```text
Data Sources
     ↓
Raw Layer
     ↓
Staging Layer
     ↓
Entity Resolution
     ↓
Core Layer
     ↓
Data Quality
     ↓
Analytics Marts
     ↓
Football Metrics
     ↓
BI / Visualizations
```

Основной фокус проекта:

- ETL/ELT;
- Data Quality;
- интеграция нескольких источников;
- PostgreSQL;
- Airflow;
- SQL-витрины;
- футбольные метрики;
- мониторинг качества данных;
- визуализация результатов.

---

# 2. Цели проекта

Проект должен решать четыре основных задачи.

### 1. Сбор данных

Получать футбольные данные из нескольких внешних источников.

### 2. Контроль качества

Автоматически выявлять:

- пропуски;
- дубликаты;
- некорректные значения;
- нарушения ссылочной целостности;
- неполные матчи;
- несоответствия между источниками;
- аномальные данные.

### 3. Подготовка аналитического слоя

Преобразовывать сырые данные в нормализованные таблицы и аналитические витрины.

### 4. Футбольная аналитика

На основе подготовленных данных рассчитывать метрики:

- зоны начала атак;
- progressive passes;
- box entries;
- attacking sequences;
- possessions ending in shots;
- другие показатели продвижения мяча и создания моментов.

---

# 3. Источники данных

## 3.1. StatsBomb Open Data

Основной источник event-data.

Использовать данные выбранного соревнования, например:

**FIFA World Cup 2022**

Получаем:

- матчи;
- составы;
- игроков;
- события матча;
- передачи;
- удары;
- владения;
- координаты событий;
- xG;
- результаты действий.

Основной формат — JSON.

---

## 3.2. Второй источник через REST API

Использовать внешний футбольный REST API, например football-data.org.

Получать:

- competitions;
- teams;
- matches;
- match results;
- standings;
- другую базовую информацию.

Доступ через:

```text
HTTP
REST API
JSON
```

Python-клиент должен использовать, например:

```python
requests
```

Второй источник нужен не только ради дополнительных данных, но и для демонстрации:

- работы с API;
- интеграции нескольких провайдеров;
- сопоставления сущностей;
- cross-source Data Quality.

---

# 4. Технологический стек

## Основной стек

```text
Python
pandas
requests

PostgreSQL
SQL

Apache Airflow

Docker
Docker Compose

Git
GitHub
```

## Визуализация

```text
Apache Superset
Matplotlib
mplsoccer
```

## Тестирование

```text
pytest
```

## Дополнительно

При необходимости:

```text
Great Expectations
или
dbt tests
```

Добавлять их только после реализации основной логики проекта.

---

# 5. Архитектура данных

Использовать несколько логических слоёв.

```text
raw
 ↓
staging
 ↓
core
 ↓
marts
```

Отдельно:

```text
monitoring
```

для результатов Data Quality.

---

# 6. Raw Layer

Raw-слой должен хранить данные максимально близко к исходному виду.

Пример:

```text
raw.statsbomb_matches
raw.statsbomb_events
raw.statsbomb_lineups

raw.football_data_matches
raw.football_data_teams
```

Для JSON-источников можно использовать структуру:

```text
source
source_file
payload JSONB
loaded_at
batch_id
record_hash
```

Пример:

```sql
CREATE TABLE raw.statsbomb_events (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT,
    payload JSONB NOT NULL,
    batch_id UUID NOT NULL,
    record_hash TEXT,
    loaded_at TIMESTAMP DEFAULT NOW()
);
```

Raw-данные не должны модифицироваться после загрузки.

---

# 7. Staging Layer

На staging-слое JSON преобразуется в табличный формат.

Основные таблицы:

```text
stg_matches
stg_teams
stg_players
stg_lineups
stg_events
```

Пример структуры `stg_events`:

```text
event_id
match_id
event_index

period
minute
second

team_id
player_id

event_type

x
y

end_x
end_y

pass_recipient_id
pass_outcome

shot_xg
shot_outcome

possession
possession_team_id

loaded_at
```

На staging-слое выполняются:

- flattening JSON;
- приведение типов;
- стандартизация названий;
- базовая очистка;
- подготовка к entity resolution.

---

# 8. Core Layer

Core должен представлять нормализованную модель данных.

Основные сущности:

```text
core.competitions
core.seasons

core.teams
core.players

core.matches
core.lineups

core.events
```

Пример связей:

```text
competition
    ↓
season
    ↓
match
   ↙   ↘
teams  events
         ↓
       player
```

Core-таблицы должны использовать внутренние canonical ID, не зависящие от конкретного поставщика.

---

# 9. Entity Resolution

Одна из центральных частей проекта.

Разные поставщики используют разные ID для:

- команд;
- матчей;
- игроков.

Поэтому создаётся внутренний canonical layer.

---

## 9.1. Сопоставление команд

Создать:

```text
core.team_source_mapping
```

Например:

| canonical_team_id | provider | source_team_id | source_name |
|---:|---|---:|---|
| 1 | statsbomb | 768 | England |
| 1 | football_data | 770 | England |

Можно также использовать wide-вариант:

| canonical_team_id | statsbomb_id | football_data_id | team_name |
|---:|---:|---:|---|
| 1 | 768 | 770 | England |

---

# 10. Сопоставление матчей

Создать:

```text
core.match_source_mapping
```

Для сопоставления использовать комбинацию:

```text
competition
match_date
home_team
away_team
```

После нормализации команд:

```text
match_key =
date
+ canonical_home_team_id
+ canonical_away_team_id
```

Фиксировать:

```text
matched
unmatched
ambiguous
```

матчи.

---

# 11. Data Quality Framework

Data Quality — центральная часть проекта.

Все проверки должны выполняться автоматически.

Результаты сохраняются в:

```text
monitoring.data_quality_results
```

Структура:

```text
check_id
run_id

source
schema_name
table_name

check_name
check_type

severity
status

records_checked
records_failed
failure_rate

executed_at
details
```

---

# 12. Уровни ошибок

Использовать severity:

```text
INFO
WARNING
ERROR
CRITICAL
```

Например:

### CRITICAL

- duplicate event ID;
- event с неизвестным match_id;
- score mismatch между источниками;
- отсутствует критическая таблица;
- отсутствует значительная часть матча.

### WARNING

- подозрительно мало событий;
- несколько игроков не сопоставились;
- небольшое количество missing values;
- необычное распределение показателей.

---

# 13. Набор Data Quality проверок

## 13.1. Schema Checks

Проверить наличие обязательных колонок:

```text
match_id
event_id
event_type
team_id
```

Проверить типы:

```text
minute → integer
shot_xg → numeric
event_id → string / UUID
```

---

# 14. Null Checks

Проверять обязательные значения.

Например:

```text
match_id IS NOT NULL
event_id IS NOT NULL
team_id IS NOT NULL
event_type IS NOT NULL
```

Но учитывать тип события.

Например:

```text
event_type = Shot
→ shot_xg должен быть заполнен
```

```text
event_type = Pass
→ pass-related fields ожидаются
```

---

# 15. Duplicate Checks

Проверить уникальность:

```text
event_id
match_id + event_index
source_match_id
```

Пример:

```sql
SELECT
    event_id,
    COUNT(*)
FROM core.events
GROUP BY event_id
HAVING COUNT(*) > 1;
```

---

# 16. Referential Integrity

Проверить:

```text
event.match_id → matches.match_id
event.team_id → teams.team_id
event.player_id → players.player_id
```

Пример:

```sql
SELECT COUNT(*)
FROM core.events e
LEFT JOIN core.matches m
    ON e.match_id = m.match_id
WHERE m.match_id IS NULL;
```

---

# 17. Проверка команд

Команда события должна участвовать в соответствующем матче.

Логика:

```text
event.team_id
=
match.home_team_id
OR
match.away_team_id
```

Иначе:

```text
event_team_not_in_match
```

---

# 18. Проверка игроков

Игрок события должен присутствовать в составе соответствующего матча.

Проверка:

```text
event
 ↓
player
 ↓
lineup
 ↓
match
```

Ошибка:

```text
player_not_in_lineup
```

---

# 19. Проверка координат

Проверять корректность координат:

```text
0 <= x <= pitch_length
0 <= y <= pitch_width
```

Аналогично:

```text
end_x
end_y
```

Некорректное значение:

```text
x = 999
```

должно приводить к DQ error.

---

# 20. Проверка времени

Проверять:

```text
minute >= 0
second >= 0
period valid
```

Также проверять последовательность:

```text
event_index
```

Выявлять:

```text
duplicate_event_index
missing_event_index
```

---

# 21. Проверка xG

Для ударов:

```text
0 <= shot_xg <= 1
```

Также:

```text
event_type = Shot
→ shot_xg expected
```

---

# 22. Cross-source Data Quality

После сопоставления матчей сравнивать данные поставщиков.

Проверять:

```text
match date
home team
away team
home score
away score
```

Например:

```text
StatsBomb:
Argentina 3:0 Croatia

Provider B:
Argentina 2:0 Croatia
```

→

```text
cross_source_score_mismatch
```

---

# 23. Coverage Checks

Рассчитывать:

```text
provider_matches
matched_matches
unmatched_matches
coverage_percent
```

Например:

```text
Provider A matches: 64
Provider B matches: 64

Mapped: 63
Unmatched: 1

Coverage: 98.4%
```

---

# 24. Аномалии объёма данных

Для каждого матча рассчитывать:

```text
event_count
pass_count
shot_count
foul_count
card_count
player_count
```

Определять матчи с необычным количеством событий.

Например:

```text
обычно:
2500–4000 events

матч X:
482 events
```

→

```text
abnormally_low_event_count
```

Можно использовать:

- IQR;
- z-score;
- robust z-score;
- percentile thresholds.

ML для этого не обязателен.

---

# 25. Corrupted Data Test Set

Создать набор намеренно повреждённых данных:

```text
tests/fixtures/corrupted/
```

В тестовых данных намеренно:

1. удалить часть событий;
2. создать duplicate event;
3. добавить NULL;
4. указать неизвестный team ID;
5. установить `x = 999`;
6. изменить счёт матча;
7. удалить игрока из lineup;
8. создать неизвестный match ID.

Система должна автоматически обнаружить проблемы.

Например:

```text
Injected anomalies: 8
Detected anomalies: 8
```

---

# 26. Airflow Pipeline

Создать основной DAG:

```text
football_data_pipeline
```

Пример:

```text
extract_statsbomb
        ↓
load_statsbomb_raw
        ↓
transform_statsbomb
        │
        │
        ├─────────────────┐
        │                 │
extract_provider_api      │
        ↓                 │
load_provider_raw         │
        ↓                 │
transform_provider        │
        │                 │
        └────────┬────────┘
                 ↓
          resolve_entities
                 ↓
            build_core
                 ↓
          run_dq_checks
                 ↓
             dq_gate
                 ↓
           build_marts
                 ↓
       refresh_visualizations
```

---

# 27. Поведение DAG

Настроить:

```text
retries
retry_delay
logging
dependencies
```

При ошибках API использовать retry.

Например:

```text
retries = 3
```

---

# 28. Idempotency

Повторный запуск pipeline не должен создавать дубликаты.

Использовать:

```sql
INSERT ... ON CONFLICT
```

или:

```text
staging
 ↓
MERGE / UPSERT
 ↓
core
```

Каждая загрузка должна иметь:

```text
batch_id
loaded_at
```

---

# 29. Data Quality Gate

После core-layer запускаются проверки.

Если есть:

```text
CRITICAL
```

pipeline должен остановиться.

```text
RAW
 ↓
STAGING
 ↓
CORE
 ↓
DQ
 ├── PASS → MARTS
 └── FAIL → STOP
```

Плохие данные не должны попадать в аналитические витрины.

---

# 30. Data Quality Report

После каждого запуска формировать отчёт.

Например:

```text
DATA QUALITY REPORT

Run: 2026-xx-xx

Tables checked: 8
Checks executed: 27

Passed:   24
Warnings: 2
Critical: 1

Provider coverage:
StatsBomb           100%
Provider B           98.4%

Entity mapping:
Teams               100%
Matches              98.4%
Players              97.6%

Issues:
- 1 score mismatch
- 3 unmapped players
- 1 anomalous event count
```

---

# 31. Analytics Marts

После прохождения Data Quality создаются аналитические витрины.

Основные:

```text
marts.team_match_summary
marts.player_match_summary
marts.possessions
marts.box_entries
marts.progressive_passes
marts.attacking_sequences
marts.team_attacking_profile
```

---

# 32. Team Match Summary

Например:

```text
match_id
team_id

goals
shots
shots_on_target
xg

passes
completed_passes
pass_completion

progressive_passes

box_entries

possessions
shot_possessions

turnovers
```

---

# 33. Зоны поля

Разделить поле на зоны.

Например:

```text
              направление атаки →

┌──────┬──────┬──────┬──────┬──────┐
│  1   │  4   │  7   │ 10   │ 13   │
├──────┼──────┼──────┼──────┼──────┤
│  2   │  5   │  8   │ 11   │ 14   │
├──────┼──────┼──────┼──────┼──────┤
│  3   │  6   │  9   │ 12   │ 15   │
└──────┴──────┴──────┴──────┴──────┘
```

Для каждого события рассчитывать:

```text
start_zone
end_zone
```

Эти значения можно хранить в analytics/core layer.

---

# 34. Football Metric №1 — Box Entries

Определить вход в штрафную:

```text
действие начинается вне штрафной
AND
заканчивается внутри штрафной
```

Отдельно считать:

```text
passes into box
carries into box
crosses into box
```

Итоговая таблица:

```text
match_id
team_id
player_id

entry_type

start_x
start_y

end_x
end_y

successful
```

---

# 35. Football Metric №2 — Progressive Passes

Определить передачу, существенно приближающую мяч к воротам соперника.

Необходимо задокументировать используемое определение.

Например:

```text
distance_to_goal_before
distance_to_goal_after

progression =
(distance_before - distance_after)
/
distance_before
```

После этого определить threshold.

---

# 36. Сравнение определений Progressive Pass

Реализовать несколько вариантов:

### Variant A

```text
progression >= 20%
```

### Variant B

```text
progression >= 25%
```

### Variant C

Разные требования в зависимости от зоны поля.

Сравнить:

```text
number of progressive passes
players ranking
teams ranking
field distribution
```

Обосновать выбранный вариант.

---

# 37. Football Metric №3 — Attacking Sequences

Использовать possession ID.

Для каждого владения определить:

```text
possession_id

team_id

start_x
start_y
start_zone

end_x
end_y
end_zone

event_count
pass_count

duration

has_shot
has_goal

total_xg
```

---

# 38. Possessions Ending in Shots

Создать витрину:

```text
marts.shot_possessions
```

Рассчитывать:

```text
start_zone

possessions
shot_possessions

shot_conversion_rate

total_xg
avg_xg
```

Это позволяет отвечать на вопрос:

> Из каких зон чаще начинаются атаки, которые заканчиваются ударом?

---

# 39. Football Metric №4 — Chance Creation

Определить события, предшествующие удару.

Например анализировать:

```text
последние N событий владения
```

до:

```text
Shot
```

Рассчитать:

```text
pass_before_shot
zone_before_shot
player_before_shot
sequence_length
```

---

# 40. Team Attacking Profile

Создать итоговую view:

```text
analytics.v_team_attacking_profile
```

Например:

```text
team
matches

goals_per_90
shots_per_90
xg_per_90

progressive_passes_per_90

final_third_entries_per_90

box_entries_per_90

shot_possessions_per_90
```

---

# 41. SQL Queries

В репозитории создать:

```text
sql/analytics/
```

Добавить примеры аналитических запросов.

Например:

### Откуда начинаются атаки с ударом?

```sql
SELECT
    start_zone,
    COUNT(*) AS possessions,
    SUM(has_shot::INT) AS shot_possessions,
    AVG(total_xg) AS avg_xg
FROM marts.possessions
GROUP BY start_zone
ORDER BY shot_possessions DESC;
```

### Какие игроки чаще продвигают мяч?

```sql
SELECT
    player_id,
    COUNT(*) AS progressive_passes
FROM marts.progressive_passes
GROUP BY player_id
ORDER BY progressive_passes DESC;
```

### Через какие зоны команды входят в штрафную?

```sql
SELECT
    team_id,
    start_zone,
    COUNT(*) AS box_entries
FROM marts.box_entries
GROUP BY team_id, start_zone;
```

---

# 42. Визуализация

В проекте должно быть два типа визуализации:

1. Data Quality Monitoring;
2. Football Analytics.

---

# 43. Data Quality Dashboard

Реализовать в Superset.

Основные KPI:

```text
Checks passed
Warnings
Critical errors

Data coverage

Mapped matches
Mapped teams
Mapped players

Last pipeline run
Last successful load
```

---

# 44. Event Volume Monitoring

Построить график:

```text
match
vs
number_of_events
```

Он должен позволять визуально обнаруживать неполные матчи.

Пример:

```text
ARG-FRA     ███████████████
FRA-MAR     █████████████
ARG-CRO     ██████████████
ENG-FRA     ██
```

Последний матч должен быть отмечен как потенциальная аномалия.

---

# 45. Football Dashboard

Создать одну основную страницу:

## Team Attacking Profile

Фильтры:

```text
Competition
Team
Match
Player
```

Основные KPI:

```text
Goals
xG
Shots

Box entries
Progressive passes

Shot possessions
```

---

# 46. Attacking Zone Heatmap

Построить карту поля:

```text
Where do shot-ending possessions start?
```

Каждая зона показывает:

```text
number of possessions
number of shot possessions
total xG
```

Использовать:

```text
mplsoccer
```

или другую специализированную футбольную визуализацию.

---

# 47. Box Entry Map

Показывать действия, которыми команда входит в штрафную.

Например:

```text
start coordinate
      ↓
arrow
      ↓
end coordinate
```

Фильтры:

```text
Pass
Carry
Cross

Successful only
Player
Match
Team
```

---

# 48. Progressive Pass Map

Для команды или игрока показывать progressive passes.

Визуализация:

```text
start_x/start_y
        ↓
      arrow
        ↓
end_x/end_y
```

Рядом выводить:

```text
Progressive passes / 90

Completion %

Final-third entries / 90

Box entries / 90
```

---

# 49. Zone-to-Zone Matrix

Показать переходы между зонами.

Например:

| From ↓ / To → | Left final | Centre final | Right final | Box |
|---|---:|---:|---:|---:|
| Left middle | 31 | 18 | 3 | 12 |
| Centre middle | 14 | 47 | 16 | 21 |
| Right middle | 4 | 21 | 29 | 11 |

Можно строить отдельно:

```text
team
player
match
```

---

# 50. Визуализация сравнения метрик

Для progressive passes показать влияние разных определений.

Например:

```text
Definition A — 20%
Definition B — 25%
Definition C — contextual
```

Сравнить:

```text
количество найденных передач
ranking игроков
ranking команд
распределение по зонам
```

Это должно быть частью анализа корректности метрики.

---

# 51. Автоматические тесты

Использовать:

```text
pytest
```

Покрыть минимум:

### Transformations

```text
JSON flattening
coordinate parsing
zone assignment
```

### Entity resolution

```text
team mapping
match mapping
```

### Data Quality

```text
duplicates
missing values
invalid coordinates
foreign keys
score mismatches
```

### Metrics

```text
box entry
progressive pass
shot possession
```

---

# 52. Структура репозитория

```text
football-data-quality-pipeline/

├── README.md
├── docker-compose.yml
├── requirements.txt
├── .env.example
│
├── dags/
│   └── football_pipeline.py
│
├── src/
│   ├── extract/
│   │   ├── statsbomb.py
│   │   └── football_api.py
│   │
│   ├── transform/
│   │   ├── matches.py
│   │   ├── teams.py
│   │   ├── players.py
│   │   ├── lineups.py
│   │   └── events.py
│   │
│   ├── entity_resolution/
│   │   ├── teams.py
│   │   └── matches.py
│   │
│   ├── quality/
│   │   ├── schema_checks.py
│   │   ├── null_checks.py
│   │   ├── duplicate_checks.py
│   │   ├── integrity_checks.py
│   │   ├── football_checks.py
│   │   ├── anomaly_checks.py
│   │   └── cross_source_checks.py
│   │
│   ├── metrics/
│   │   ├── zones.py
│   │   ├── progressive_passes.py
│   │   ├── box_entries.py
│   │   └── possessions.py
│   │
│   ├── visualization/
│   │   ├── pitch.py
│   │   ├── zone_heatmap.py
│   │   ├── pass_map.py
│   │   └── box_entries.py
│   │
│   └── utils/
│
├── sql/
│   ├── ddl/
│   │   ├── raw.sql
│   │   ├── staging.sql
│   │   ├── core.sql
│   │   ├── monitoring.sql
│   │   └── marts.sql
│   │
│   ├── staging/
│   ├── core/
│   ├── quality/
│   ├── marts/
│   └── analytics/
│
├── tests/
│   ├── test_transformations.py
│   ├── test_entity_resolution.py
│   ├── test_quality.py
│   ├── test_metrics.py
│   │
│   └── fixtures/
│       ├── valid/
│       └── corrupted/
│
├── notebooks/
│   └── metric_validation.ipynb
│
└── docs/
    ├── architecture.png
    ├── data_model.png
    ├── airflow_dag.png
    ├── dq_dashboard.png
    ├── attacking_heatmap.png
    ├── box_entries.png
    └── progressive_passes.png
```

---

# 53. Docker Compose

Через `docker-compose.yml` запускать:

```text
PostgreSQL

Airflow Webserver
Airflow Scheduler

Superset
```

Цель:

```bash
docker compose up
```

должен поднимать основную инфраструктуру проекта.

---

# 54. Конфигурация

API keys и credentials нельзя коммитить в Git.

Использовать:

```text
.env
```

В репозиторий добавить:

```text
.env.example
```

Например:

```text
POSTGRES_HOST=
POSTGRES_DB=
POSTGRES_USER=
POSTGRES_PASSWORD=

FOOTBALL_API_TOKEN=
```

---

# 55. Logging

Каждый этап pipeline должен логировать:

```text
source
batch_id
records_received
records_loaded
records_rejected
execution_time
status
```

Например:

```text
[extract_statsbomb]

matches_received=64
events_received=191374
status=SUCCESS
```

---

# 56. Metadata загрузок

Создать:

```text
monitoring.pipeline_runs
```

Пример:

```text
run_id
dag_id

started_at
finished_at

status

source

records_extracted
records_loaded

error_message
```

---

# 57. README

README должен быть полноценной документацией проекта.

Структура:

```text
# Football Data Quality & ETL Platform

## Overview

## Problem

## Architecture

## Technology Stack

## Data Sources

## Data Model

## ETL Pipeline

## Entity Resolution

## Data Quality Framework

## Data Quality Checks

## Football Metrics

## Analytics Marts

## Visualizations

## Testing

## How to Run

## Project Structure

## Limitations

## Future Improvements
```

---

# 58. Что показать в README визуально

В начале README:

### Architecture diagram

```text
Sources → Raw → Staging → Core → DQ → Marts → Analytics
```

Дальше:

### Airflow screenshot

Показать DAG.

### Data Quality dashboard

Показать:

```text
passed
warning
critical
coverage
```

### Football visualizations

Минимум:

```text
Attacking Zone Heatmap
Box Entry Map
Progressive Pass Map
```

---

# 59. Пример пользовательского сценария

README должен показывать систему как единый workflow.

## Step 1

Airflow загружает данные:

```text
StatsBomb
+
Football API
```

## Step 2

Raw данные сохраняются.

## Step 3

Данные преобразуются и нормализуются.

## Step 4

Матчи и команды разных источников сопоставляются.

## Step 5

Запускаются Data Quality checks.

Например система обнаруживает:

```text
Match X

expected event count:
2500–4000

actual:
482

status:
WARNING
```

## Step 6

При критической ошибке DQ gate блокирует обновление marts.

## Step 7

После исправления данных pipeline завершается успешно.

## Step 8

Обновляются аналитические витрины.

## Step 9

Данные появляются в:

```text
Superset
Football visualization module
```

---

# 60. MVP проекта

Минимально готовая версия должна содержать:

- StatsBomb;
- один REST API;
- Python ETL;
- PostgreSQL;
- raw/staging/core/marts;
- mapping команд;
- mapping матчей;
- 15+ Data Quality checks;
- таблицу DQ results;
- Airflow DAG;
- DQ gate;
- 3 аналитические витрины;
- box entries;
- progressive passes;
- shot-ending possessions;
- одну карту поля;
- один DQ dashboard;
- pytest;
- Docker Compose;
- полноценный README.

---

# 61. Расширенная версия

После MVP добавить:

- 25–30 DQ checks;
- anomaly detection;
- более сложное entity resolution;
- player mapping;
- metric comparison;
- Superset dashboard;
- несколько football pitch visualizations;
- автоматический DQ report;
- additional competitions;
- Great Expectations или dbt tests;
- alerting при критических ошибках.

---

# 62. Приоритет разработки

Рекомендуемый порядок:

## Этап 1 — Infrastructure

```text
Docker
PostgreSQL
Airflow
repository structure
```

## Этап 2 — Data ingestion

```text
StatsBomb
REST API
raw layer
```

## Этап 3 — Data model

```text
staging
core
canonical IDs
```

## Этап 4 — Entity resolution

```text
teams
matches
```

## Этап 5 — Data Quality

```text
schema
nulls
duplicates
integrity
football rules
cross-source
anomalies
```

## Этап 6 — Airflow orchestration

```text
full DAG
retries
idempotency
DQ gate
```

## Этап 7 — Analytics marts

```text
team summaries
possessions
progressive passes
box entries
```

## Этап 8 — Metric validation

```text
alternative definitions
comparison
chosen methodology
```

## Этап 9 — Visualization

```text
DQ dashboard
zone heatmap
box entry map
progressive pass map
```

## Этап 10 — Testing and documentation

```text
pytest
corrupted fixtures
README
architecture
screenshots
```

---

# 63. Итоговая архитектура

```text
┌────────────────────────┐
│    StatsBomb Open Data │
└────────────┬───────────┘
             │
             │
             ▼
        Python Extract
             │
             │
┌────────────┴───────────┐
│                       │
│                       │
│   Football REST API   │
│                       │
└────────────┬──────────┘
             │
             ▼
      ┌─────────────┐
      │    RAW      │
      └──────┬──────┘
             │
             ▼
      ┌─────────────┐
      │   STAGING   │
      └──────┬──────┘
             │
             ▼
     Entity Resolution
             │
             ▼
      ┌─────────────┐
      │    CORE     │
      └──────┬──────┘
             │
             ▼
      DATA QUALITY
             │
       ┌─────┴─────┐
       │           │
     FAIL         PASS
       │           │
       ▼           ▼
      STOP      ANALYTICS
                   MARTS
                     │
             ┌───────┴────────┐
             │                │
             ▼                ▼
         Superset       Football Maps
             │
             ▼
       DQ / Analytics
         Dashboards
```

---

# 64. Конечный результат

После завершения проект должен представлять собой не набор ноутбуков, а небольшую data platform, которую можно:

```bash
git clone ...
docker compose up
```

запустить локально, после чего:

1. Airflow получает футбольные данные;
2. данные сохраняются в raw layer;
3. выполняются transformations;
4. сущности разных источников сопоставляются;
5. запускаются Data Quality checks;
6. критические ошибки блокируют pipeline;
7. корректные данные загружаются в marts;
8. рассчитываются футбольные метрики;
9. обновляются BI-дашборды;
10. строятся специализированные футбольные визуализации.