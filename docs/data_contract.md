# Data Contract

Спецификация данных Football Data Quality & ETL Platform.

Этот документ — контракт, по которому пишутся extract, SQL и проверки. Определения метрик живут в `docs/metrics.md`. Реестр DQ — в `docs/dq_rules.md`.

Соревнование: FIFA World Cup 2022.

- StatsBomb: competition `43`, season `106`.
- Первый вертикальный срез: match id `3869685` (финал).
- football-data.org: competition code `WC`.

---

## 1. Источники

### 1.1. StatsBomb Open Data

Источник событий и заявок. Формат JSON из open-data. Это не REST API матча.

Даёт:

- матчи;
- составы (полная заявка матча, не только стартовые 11);
- игроков;
- события;
- координаты;
- `shot.statsbomb_xg`.

Полный JSON в Git не коммитится. Extract скачивает payload и кладёт его в raw.

Лицензия open-data и атрибуция StatsBomb указываются в README.

### 1.2. football-data.org v4

Второй источник для API, сопоставления сущностей и cross-source проверки. Это не второй поток событий.

Даёт на бесплатном тарифе:

- соревнования, включая World Cup (`WC`);
- команды;
- матчи;
- счёт;
- таблицы.

Не даёт в бесплатный тариф:

- составы;
- заявки;
- события.

Player mapping между провайдерами в MVP не входит. Игроки и события есть только у StatsBomb.

Секрет API хранится в `.env` как:

```text
FOOTBALL_DATA_ORG_API_KEY
```

Запросы кэшируются в raw. Повторный прогон читает текущую версию raw и не ходит в API, пока payload не изменился. Лимит бесплатного тарифа: 10 запросов в минуту.

Исторический турнир загружается целиком. Инкрементальная синхронизация не нужна.

---

## 2. Слои

```text
RAW
точная копия внешнего payload

STAGING
типизированное распакованное представление одного провайдера

CORE
каноническая модель проекта

MARTS
аналитическое представление публикуемых матчей
```

| Слой | Можно | Нельзя |
|---|---|---|
| raw | добавить новую версию payload | обновлять или чистить уже записанный payload |
| staging | типизировать и разложить поля провайдера | склеивать провайдеров и подменять их ID на канонические |
| core | канонические ID, нормализованные время и счёт | считать продуктовые метрики |
| marts | агрегаты и метрики по публикуемым матчам | читать матчи в карантине |

Схемы PostgreSQL:

```text
raw
staging
core
marts
monitoring
config
```

Отдельной схемы `analytics` нет. Витрины и представления живут в `marts`.

---

## 3. Raw

Одна строка — один внешний объект: файл матча, ответ API, список матчей. Не одно событие.

### 3.1. Таблицы

```text
raw.statsbomb_matches
raw.statsbomb_lineups
raw.statsbomb_events

raw.football_data_competitions
raw.football_data_teams
raw.football_data_matches
raw.football_data_standings
```

### 3.2. Общая форма строки

```text
id
provider
entity_type
source_id
payload JSONB
record_hash
batch_id
loaded_at
```

### 3.3. Версии и идемпотентность

Уникальность версии:

```text
(provider, entity_type, source_id, record_hash)
```

Повторная вставка того же хеша — успешный no-op. Это не ошибка задачи.

Новый payload того же `source_id` пишется новой строкой. Старая строка не обновляется и не удаляется.

```text
source_id=3869685  hash=A  loaded_at=t1
source_id=3869685  hash=B  loaded_at=t2
```

Staging читает только текущую версию: последняя строка по `(provider, entity_type, source_id)`.

Для этого создаются view:

```text
raw.statsbomb_matches_current
raw.statsbomb_lineups_current
raw.statsbomb_events_current
raw.football_data_competitions_current
raw.football_data_teams_current
raw.football_data_matches_current
raw.football_data_standings_current
```

---

## 4. Staging

Таблицы разделены по провайдерам. Общих `stg_matches` и `stg_events` нет.

### 4.1. Таблицы

```text
staging.statsbomb_matches
staging.statsbomb_teams
staging.statsbomb_players
staging.statsbomb_lineups
staging.statsbomb_events

staging.football_data_teams
staging.football_data_matches
staging.football_data_standings
```

### 4.2. Поля `staging.statsbomb_events`

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
end_z

pass_recipient_id
pass_outcome
pass_length
is_cross

shot_xg
shot_outcome

carry_end_x
carry_end_y

possession
possession_team_id

loaded_at
source_batch_id
```

Правила типов:

- `event_id` — текст (UUID StatsBomb).
- `end_z` заполняется только у удара, если конец пришёл как `[x, y, z]`.
- `is_cross` — признак паса. Кросс не является отдельным типом действия.

На staging:

- распаковывается JSON;
- приводятся типы;
- сохраняются имена и ID провайдера;
- выставляется `is_cross` у паса;
- канонические ID не подставляются;
- «плохие» строки не отбрасываются — их должны видеть проверки.

### 4.3. Ключи счёта football-data.org

Фактический payload WC2022 (bootstrap / API) использует внутри `fullTime`, `regularTime`, `extraTime`, `penalties`:

```text
home
away
```

Ключи `homeTeam` / `awayTeam` в узлах счёта не встречаются. Парсер в `src/transform/score.py` принимает оба варианта, канон для этого турнира — `home` / `away`.

---

## 5. Core

Внутренние ID не зависят от провайдера.

### 5.1. Таблицы

```text
core.competitions
core.seasons
core.teams
core.players
core.matches
core.lineups
core.events

core.team_source_mapping
core.match_source_mapping
```

События, игроки и составы приходят из StatsBomb. Матч и команды обогащаются вторым источником после сопоставления.

### 5.2. Поля матча

```text
canonical_match_id
competition_id
season_id
canonical_home_team_id
canonical_away_team_id
kickoff_utc

score_regular_time_home
score_regular_time_away
score_extra_time_only_home
score_extra_time_only_away
score_after_extra_time_home
score_after_extra_time_away
score_penalties_home
score_penalties_away

home_score
away_score
```

`home_score` / `away_score` — канонический счёт без серии пенальти. Он совпадает с тем, что StatsBomb хранит в `home_score` / `away_score`.

---

## 6. Entity resolution

### 6.1. Команды

Для 32 сборных основной способ — ручной seed.

Таблица:

```text
core.team_source_mapping
```

```text
canonical_team_id
provider
source_team_id
source_name
mapping_method
mapping_status
created_at
```

`mapping_method`:

```text
manual_seed
fuzzy_suggested
manual_confirmed
```

`mapping_status`:

```text
confirmed
suggested
rejected
```

Seed лежит в `seeds/team_source_mapping.csv` и загружается в core.

Fuzzy matching только предлагает кандидата для несопоставленной сущности. Автоматически подтверждать fuzzy-пару нельзя.

### 6.2. Матчи

Таблица:

```text
core.match_source_mapping
```

```text
canonical_match_id
provider
source_match_id
mapping_status
```

Уникальность строки источника:

```text
(provider, source_match_id)
```

Идентичность матча в core — суррогатный `canonical_match_id`.

Кандидат для сопоставления двух источников:

```text
competition_id
season_id
canonical_home_team_id
canonical_away_team_id
```

Дата в этот ключ не входит. Kickoff подтверждает или отклоняет кандидата.

Одинаковая пара команд второй раз за турнир не создаёт ещё одну строку под тем же ключом. Статус такого случая — `ambiguous`.

Уникального ограничения на `(competition, season, home, away)` нет.

Статусы сопоставления:

```text
matched
unmatched
ambiguous
```

`± 1 day` — запасное правило только для пар, которые не подтвердились по timezone. Это не основной ключ.

---

## 7. Время

Из каждого источника сохраняются исходные поля:

```text
source_match_date
source_kickoff
source_timezone
```

В core хранится:

```text
kickoff_utc TIMESTAMPTZ
```

football-data.org отдаёт `utcDate`.

StatsBomb отдаёт дату и время без timezone offset.

### 7.1. Гипотеза для ЧМ-2022 — подтверждена

`match_date` и `kick_off` StatsBomb — локальное время стадиона в зоне `Asia/Qatar`.

Правило нормализации:

1. склеить дату и kickoff;
2. локализовать в `Asia/Qatar`;
3. перевести в UTC;
4. записать в `kickoff_utc`.

Сверка со всеми 64 матчами football-data.org `utcDate` на WC2022: max |Δkickoff| = 0 часов. Гипотеза подтверждена. `cross_source_kickoff_mismatch` остаётся WARNING в `observe` (допуск на другие турниры).

---

## 8. Счёт

### 8.1. Поля football-data.org v4

`fullTime` — текущий и итоговый счёт. В серии пенальти он включает голы серии.

`regularTime` — счёт после 90 минут. У обычного матча поле может быть пустым.

`extraTime` — только голы дополнительного времени. Это не накопительный счёт.

`penalties` — только голы серии.

Официальный пример документации, четвертьфинал Евро-1996:

```text
duration      PENALTY_SHOOTOUT
regularTime   1:1
extraTime     0:0
penalties     6:5
fullTime      7:6
```

Проверка арифметики примера: `1 + 0 + 6 = 7`, `1 + 0 + 5 = 6`.

Складывать `fullTime + extraTime` нельзя: дополнительное время уже входит в `fullTime`.

### 8.2. Канонический счёт без серии пенальти

```text
duration = REGULAR            → fullTime
duration = EXTRA_TIME         → fullTime
duration = PENALTY_SHOOTOUT   → regularTime + extraTime
```

Серия хранится отдельно и в `home_score` / `away_score` не входит.

### 8.3. Финал ЧМ-2022

Проверено на matched паре StatsBomb `3869685` ↔ football-data `903869685`:

```text
StatsBomb home_score:away_score     3:3
canonical football-data.org         3:3
penalties                           4:2
status                              PASS
```

Сырой `fullTime` этого финала в сравнение со StatsBomb не подставляется. Фактический payload:

```text
duration      PENALTY_SHOOTOUT
regularTime   2:2
extraTime     1:1
penalties     4:2
fullTime      7:5
```

Unit-тест `tests/test_score_normalization.py` кормит нормализатор сырым JSON и сравнивает канон `3:3` / пенальти `4:2`.

### 8.4. Контракт арифметики провайдера

Перед cross-source сравнением проверяется внутренняя арифметика football-data.org:

```text
REGULAR
  если regularTime заполнен → fullTime = regularTime

EXTRA_TIME
  fullTime = regularTime + extraTime

PENALTY_SHOOTOUT
  fullTime = regularTime + extraTime + penalties
```

Если равенство не сходится, формула канонического счёта под сомнением. Такую проверку нельзя переводить в `enforce`, пока расхождение не разобрано.

---

## 9. Игроки и заявки

Lineup-файл StatsBomb уже содержит всю заявку матча. Отдельно складывать стартовые 11 и скамейку не нужно.

Если у события заполнен `player_id`, он должен существовать среди игроков обоих составов этого матча.

Проверка «был ли игрок на поле в эту секунду по таймлайну позиций» в контракт MVP не входит.

Player mapping между StatsBomb и football-data.org в MVP не входит.

---

## 10. Координаты

Система координат StatsBomb:

- поле `120 x 80` ярдов;
- центр `(60, 40)`;
- команда события всегда атакует в сторону `x = 120`;
- штрафная соперника: `x >= 102` и `18 <= y <= 62`.

Общего валидатора на любое поле координат нет. Четыре отдельные проверки:

```text
validate_event_location
validate_pass_end_location
validate_carry_end_location
validate_shot_end_location
```

Границы поля для проверки:

```text
0 <= x <= 120
0 <= y <= 80
```

У удара третья компонента `end_z` — высота. Её нельзя сравнивать с шириной поля.

### 10.1. Профиль WC2022

На всех 64 матчах ЧМ-2022 out-of-bounds по x/y для `event.location`, `pass.end_location`, `carry.end_location` и `shot.end_location` = 0.

В `observe` severity координат — WARNING. В `enforce` (`phase4`) — ERROR. Default `.env` остаётся `observe`.

---

## 11. Публикация

Публикация зависит от Data Quality. Полный реестр проверок — в `docs/dq_rules.md` и `config/checks.yml`.

Витрины читают только матчи со статусом:

```text
PUBLISHABLE
```

Матч с матчевым CRITICAL в режиме `enforce` уходит в карантин. Остальные матчи публикуются. После match DQ и cross-source вызывается `sql/quality/reconcile_publication.sql`.

Глобальный CRITICAL (`sql/quality/global_checks.sql`) останавливает публикацию целиком в **обоих** режимах. Реализовано:

- обязательная таблица или колонка отсутствует;
- загружено 0 матчей (`core.matches`);
- `core.team_source_mapping` отсутствует или пуст.

CLI: `python -m src.pipeline phase4 --competition WC2022` (всегда `enforce`). Демо карантина: `--demo-quarantine` (синтетический CRITICAL-матч, затем cleanup). Default `.env` остаётся `DQ_MODE=observe`.

Прогон WC2022 phase4: global PASS, quarantined=0, publishable=64, marts пересобраны.

---

## 12. Открытые вопросы

Фиксируются здесь до закрытия фактом из данных:

1. ~~Фактические ключи счёта football-data.org~~ — закрыто: `home` / `away` (§4.3).
2. ~~Гипотеза `Asia/Qatar` для StatsBomb kickoff~~ — закрыто на WC2022 (§7.1).
3. Есть ли легитимные координаты за пределами `120 x 80` у `event.location`, конца паса, конца carry и конца удара.
4. Полный список служебных типов событий, которые исключаются из аналитического владения: базовый список стартует с `Starting XI`, `Half Start`, `Half End`, `Tactical Shift` и дописывается в `docs/metrics.md`.
