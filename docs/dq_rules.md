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
| validate_event_location | staging/core | match | ERROR | WARNING | `0..120` / `0..80`, если location есть |
| validate_pass_end_location | staging/core | match | ERROR | WARNING | отдельно от event.location |
| validate_carry_end_location | staging/core | match | ERROR | WARNING | отдельно от event.location |
| validate_shot_end_location | staging/core | match | ERROR | WARNING | учитывает `[x,y]` и `[x,y,z]` |
| event_time_bounds | staging/core | match | ERROR | WARNING | `minute >= 0`, `second >= 0`, `period IN (1..5)` |
| missing_event_index | staging/core | match | WARNING | WARNING | пропуски индекса внутри матча |
| shot_xg_range | staging/core | match | ERROR | WARNING | `0 <= shot_xg <= 1` для Shot |
| football_data_score_arithmetic | staging | match | ERROR | WARNING | контракт арифметики счёта провайдера |
| cross_source_score_mismatch | core | match | CRITICAL | WARNING | канонический счёт без пенальти |
| cross_source_kickoff_mismatch | core | match | WARNING | WARNING | допуск, пока гипотеза `Asia/Qatar` не подтверждена |
| mapping_coverage | core | dataset | WARNING | WARNING | matched / unmatched / ambiguous / coverage_percent |
| event_volume_anomaly | core | match | WARNING | WARNING | порог не задан до профиля 64 матчей |

Правила условных полей:

```text
Pass  → pass end location, pass length
Shot  → shot_xg, shot end location
Carry → carry end location
```

`Starting XI`, `Half Start`, `Half End`, `Tactical Shift` могут не иметь location. Пустая координата у них — не ошибка.

`player_id` проверяется только там, где тип события обязан его иметь, либо когда поле уже заполнено для FK / squad checks.

Порог объёма событий вида `2500–4000` не используется. До профиля проверка `event_volume_anomaly` остаётся WARNING. После загрузки 64 матчей в этот документ дописываются:

```text
min
p05
p25
median
p75
p95
max
IQR
```

отдельно для всех событий и для `Pass`, `Shot`, `Carry`, `Pressure`, `Duel`. Формула вида `Q1 - 3 * IQR` — гипотеза, не стартовое ограничение.

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

1. Числовой порог `event_volume_anomaly` после профиля всех 64 матчей.
2. Severity четырёх location-проверок после распределения координат; заранее не фиксировать, что out-of-bounds end location — норма.
3. Подтверждение арифметики счёта football-data.org на первом сохранённом payload; пока равенство не сходится, `football_data_score_arithmetic` и связанный cross-source score нельзя переводить в `enforce`.
4. Подтверждение гипотезы `Asia/Qatar` для kickoff; до этого `cross_source_kickoff_mismatch` остаётся WARNING.
