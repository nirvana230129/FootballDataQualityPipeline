# Data Quality Rules

Реестр проверок Football Data Quality & ETL Platform.

Этот документ — спецификация до появления `config/checks.yml`. Контракт данных — в `docs/data_contract.md`. Метрики — в `docs/metrics.md`.

---

## 1. Модель результатов

Результаты каждого запуска пишутся в:

```text
monitoring.data_quality_results
```

Поля:

```text
check_id
run_id

source
schema_name
table_name
canonical_match_id

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

Правила:

- `details` — JSONB с примерами ключей, не больше 20 записей;
- при `records_checked = 0` значение `failure_rate` не считается;
- определения проверок живут отдельно от результатов: сначала этот документ, затем `config/checks.yml` или `monitoring.check_definitions`.

У каждой проверки в реестре есть:

```text
check_name
layer
grain
enforce_severity
initial_status
```

`grain`:

```text
dataset
match
```

---

## 2. Severity

```text
INFO
WARNING
ERROR
CRITICAL
```

### 2.1. Глобальный CRITICAL

Останавливает публикацию целиком в режимах `observe` и `enforce`:

- источник недоступен;
- загружено 0 матчей;
- таблица mapping отсутствует;
- обязательная таблица или колонка отсутствует.

Это поломка пайплайна, не спорное качество одного матча.

### 2.2. Матчевый CRITICAL

В `enforce` матч уходит в карантин. Остальные матчи публикуются.

Один битый матч не снимает турнир с витрин.

---

## 3. Режимы

```text
DQ_MODE=observe
DQ_MODE=enforce
```

### `observe`

Используется на первой полной загрузке 64 матчей.

- проверки качества не поднимаются выше `WARNING`;
- матчи не карантинятся;
- глобальный CRITICAL по-прежнему останавливает publish.

### `enforce`

- включаются настроенные `ERROR` и `CRITICAL` из реестра;
- матчевый CRITICAL меняет publication status.

Перевод проверки из WARNING в ERROR или CRITICAL делается после профиля реальных данных, не из схемы «на бумаге».

---

## 4. Публикация

```text
monitoring.match_publication_status
```

Поля:

```text
canonical_match_id
dq_status
publication_status
is_quarantined
critical_check_count
warning_check_count
last_checked_at
```

`publication_status`:

```text
PUBLISHABLE
QUARANTINED
```

Витрины читают только:

```sql
WHERE publication_status = 'PUBLISHABLE'
```

В `observe` все успешно загруженные матчи остаются `PUBLISHABLE`.

---

## 5. Реестр проверок

Колонки таблицы ниже:

- `enforce_severity` — severity, которую проверка получает после калибровки в `enforce`;
- `initial_status` — поведение до профиля / в `observe`.

| check_name | layer | grain | enforce_severity | initial_status | notes |
|---|---|---|---|---|---|
| missing_required_table_or_column | staging/core | dataset | CRITICAL | CRITICAL | глобальный CRITICAL; схема и обязательные колонки |
| staging_events_required_columns | staging | dataset | CRITICAL | CRITICAL | обязательны `match_id`, `event_id`, `event_type` |
| pass_required_fields | staging/core | match | ERROR | WARNING | Pass: end location и pass length |
| shot_required_fields | staging/core | match | ERROR | WARNING | Shot: `shot_xg` и shot end location |
| carry_required_fields | staging/core | match | ERROR | WARNING | Carry: end location |
| duplicate_event_id | staging/core | match | CRITICAL | WARNING | `event_id` внутри матча |
| duplicate_event_index | staging/core | match | CRITICAL | WARNING | `match_id + event_index` |
| duplicate_source_match_mapping | core | dataset | CRITICAL | CRITICAL | `(provider, source_match_id)` |
| event_count_raw_staging_core | raw/staging/core | match | CRITICAL | WARNING | сверка числа событий по матчу |
| fk_event_match | core | match | CRITICAL | WARNING | `event.match_id → matches` |
| fk_event_team | core | match | ERROR | WARNING | `event.team_id → teams`, если заполнен |
| fk_event_player | core | match | ERROR | WARNING | `event.player_id → players`, если заполнен |
| event_team_not_in_match | core | match | ERROR | WARNING | team события не home/away матча |
| player_not_in_squad | core | match | ERROR | WARNING | player_id отсутствует в заявке матча |
| validate_event_location | staging/core | match | ERROR | WARNING | `0..120` / `0..80`; на WC2022 oob=0, готово к ERROR в будущем enforce |
| validate_pass_end_location | staging/core | match | ERROR | WARNING | на WC2022 oob=0; готово к ERROR в будущем enforce |
| validate_carry_end_location | staging/core | match | ERROR | WARNING | на WC2022 oob=0; готово к ERROR в будущем enforce |
| validate_shot_end_location | staging/core | match | ERROR | WARNING | учитывает `[x,y]`/`[x,y,z]`; на WC2022 oob x/y=0 |
| event_time_bounds | staging/core | match | ERROR | WARNING | `minute >= 0`, `second >= 0`, `period IN (1..5)` |
| missing_event_index | staging/core | match | WARNING | WARNING | пропуски индекса внутри матча |
| shot_xg_range | staging/core | match | ERROR | WARNING | `0 <= shot_xg <= 1` для Shot |
| football_data_score_arithmetic | staging | match | ERROR | WARNING | контракт арифметики счёта провайдера; WC2022: 64/64 PASS |
| cross_source_score_mismatch | core | match | CRITICAL | WARNING | канонический счёт без пенальти; WC2022: 64/64 PASS, финал 3:3 |
| cross_source_kickoff_mismatch | core | match | WARNING | WARNING | WC2022: max Δ=0ч, гипотеза Asia/Qatar подтверждена; остаётся WARNING |
| mapping_coverage | core | dataset | WARNING | WARNING | WC2022 football-data: matched=64 unmatched=0 ambiguous=0 coverage=100% |
| event_volume_anomaly | core | match | WARNING | WARNING | порог не задан до профиля 64 матчей |

Правила условных полей:

```text
Pass  → pass end location, pass length
Shot  → shot_xg, shot end location
Carry → carry end location
```

Типы с location всегда пустым на WC2022 (не ошибка):

```text
Substitution
Injury Stoppage
Half End
Half Start
Tactical Shift
Starting XI
Player On
Player Off
Bad Behaviour
```

`player_id` проверяется только там, где тип события обязан его иметь, либо когда поле уже заполнено для FK / squad checks.

### Профиль объёма событий WC2022

Источник: `staging.statsbomb_events`, 64 матча, 234637 событий. Команда: `python -m src.pipeline profile --competition WC2022`.

| metric | min | p05 | p25 | median | p75 | p95 | max | IQR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| all | 2827 | 3140.65 | 3377.25 | 3588 | 3810.75 | 4542.65 | 5145 | 433.5 |
| Pass | 776 | 919.3 | 977.5 | 1039 | 1107.75 | 1345.1 | 1484 | 130.25 |
| Shot | 9 | 13 | 18 | 22.5 | 28 | 37.85 | 38 | 10 |
| Carry | 531 | 661 | 762.5 | 829.5 | 901 | 1076.3 | 1257 | 138.5 |
| Pressure | 177 | 194.15 | 231.75 | 254 | 283.75 | 327.35 | 406 | 52 |
| Duel | 46 | 51 | 59 | 67.5 | 76 | 93.7 | 106 | 17 |

Порог вида `2500–4000` не используется: даже минимум турнира выше 2800.

Кандидат для `event_volume_anomaly` (только WARNING, не blocking):

```text
value < Q1 - 3 * IQR
для all: 3377.25 - 3 * 433.5 = 2076.75
```

На WC2022 ни один матч не падает ниже этого порога. Правило остаётся кандидатом и не переводится в `enforce`.

### Профиль координат WC2022

| field | present | out_of_bounds | rate |
|---|---:|---:|---:|
| event.location | 232512 | 0 | 0 |
| pass.end_location | 68515 | 0 | 0 |
| carry.end_location | 53764 | 0 | 0 |
| shot.end_location | 1494 | 0 | 0 |

На этом турнире out-of-bounds по x/y не встретился. Четыре location-проверки можно готовить к `ERROR` в будущем `enforce`. Режим по умолчанию остаётся `observe`; карантин матчей не включается.

### Cross-source профиль WC2022 (фаза 3)

Команда: `python -m src.pipeline phase3 --competition WC2022` (или `dq-cross`).

| check_name | status | checked | failed |
|---|---|---:|---:|
| football_data_score_arithmetic | PASS | 64 | 0 |
| cross_source_score_mismatch | PASS | 64 | 0 |
| cross_source_kickoff_mismatch | PASS | 64 | 0 |
| mapping_coverage | PASS | 64 | 0 |

Coverage football-data → StatsBomb: matched=64, unmatched=0, ambiguous=0 (100%).

Финал: StatsBomb `3869685` ↔ football-data `903869685` → канон `3:3`, пенальти `4:2`.

---

## 6. Пять проверок вертикального среза

Фаза 1, матч `3869685`, обязательный минимальный набор:

1. `event_count_raw_staging_core`
2. `duplicate_event_id`
3. `shot_required_fields` и `pass_required_fields`
4. `event_team_not_in_match`
5. `player_not_in_squad`

Эти пять проверок реализуются раньше полного реестра.

---

## 7. Испорченные фикстуры

Только pytest. Основной CLI и DAG турнира эти файлы не загружают.

```text
tests/fixtures/valid/
tests/fixtures/corrupted/
```

Тест проверяет множество пар:

```python
expected = {
    ("duplicate_event_id", "event-123"),
    ("unknown_team", "event-456"),
    ("score_mismatch", "match-789"),
}
```

Нельзя утверждать хрупкое равенство:

```text
injected anomalies == detected anomalies
```

Сеть в pytest не вызывается.

Отдельный unit-тест нормализатора счёта: сырой JSON финала даёт канонические `3:3` и серию `4:2`.

---

## 8. Открытые вопросы DQ

1. Включать ли кандидат `event_volume_anomaly` (`all < 2076.75`) в `enforce` на других соревнованиях — на WC2022 срабатываний нет.
2. Когда переводить четыре location-проверки из WARNING в ERROR: на WC2022 oob=0, но решение для `enforce` отложено до явного включения режима.
3. Когда переводить `football_data_score_arithmetic` / `cross_source_score_mismatch` в ERROR/CRITICAL `enforce`: на WC2022 оба PASS 64/64, но режим по умолчанию остаётся `observe`.
4. ~~Гипотеза `Asia/Qatar`~~ — подтверждена на WC2022 (Δkickoff=0). `cross_source_kickoff_mismatch` остаётся WARNING для других турниров.
