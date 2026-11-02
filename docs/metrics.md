# Football Metrics

Спецификация метрик Football Data Quality & ETL Platform.

SQL витрин реализует только определения из этого документа. Слои данных, счёт и время описаны в `docs/data_contract.md`. Правила качества — в `docs/dq_rules.md`.

Метрики считаются только по матчам со статусом `PUBLISHABLE`.

MVP-метрики:

1. box entries;
2. progressive passes;
3. shot-ending possessions.

Остальное в этом документе — либо обязательная база для них, либо явное расширение после MVP.

---

## 1. Координаты и поле

Система координат StatsBomb. Подробности контракта — в `docs/data_contract.md`, раздел «Координаты».

```text
pitch_length = 120
pitch_width  = 80
center       = (60, 40)
attack_goal  = x = 120
```

Штрафная соперника:

```text
x >= 102
18 <= y <= 62
```

Все зоны и метрики считаются в координатах команды, которая выполняет действие: она всегда атакует в сторону `x = 120`.

---

## 2. Зоны

Источник правды — таблица `config.pitch_zones`, не константы в Python.

```text
zone_id
x_min
x_max
y_min
y_max
zone_name
```

Рядом в config хранятся:

```text
pitch_length = 120
pitch_width  = 80
attack_direction_x = 120
```

Сетка 5×3. SQL и mplsoccer читают одну таблицу.

### 2.1. Границы

По `x` (от своих ворот к чужим):

| x_min | x_max | треть |
|---:|---:|---|
| 0 | 24 | defensive |
| 24 | 48 | defensive mid |
| 48 | 72 | middle |
| 72 | 96 | attacking mid |
| 96 | 120 | attacking |

Интервалы полуоткрыты слева направо: `[x_min, x_max)`, кроме последней колонки `x = 120`, которая входит в attacking.

По `y` (слева направо относительно направления атаки команды):

| y_min | y_max | канал |
|---:|---:|---|
| 0 | 80/3 | right |
| 80/3 | 160/3 | centre |
| 160/3 | 80 | left |

Интервалы полуоткрыты снизу вверх: `[y_min, y_max)`, кроме верхней границы `y = 80`, которая входит в `left`.

Имена зон StatsBomb: при атаке вправо меньший `y` — правый фланг команды.

### 2.2. Имена зон

| zone_name | x-треть | y-канал |
|---|---|---|
| def_right | defensive | right |
| def_centre | defensive | centre |
| def_left | defensive | left |
| def_mid_right | defensive mid | right |
| def_mid_centre | defensive mid | centre |
| def_mid_left | defensive mid | left |
| mid_right | middle | right |
| mid_centre | middle | centre |
| mid_left | middle | left |
| att_mid_right | attacking mid | right |
| att_mid_centre | attacking mid | centre |
| att_mid_left | attacking mid | left |
| att_right | attacking | right |
| att_centre | attacking | centre |
| att_left | attacking | left |

Для события с координатами считаются:

```text
start_zone
end_zone
```

Если координаты отсутствуют, зона не назначается.

---

## 3. Box entry

Вход в штрафную:

```text
start outside opponent box
AND
end inside opponent box
```

То есть старт не удовлетворяет границам штрафной, конец удовлетворяет:

```text
NOT (start_x >= 102 AND 18 <= start_y <= 62)
AND
(end_x >= 102 AND 18 <= end_y <= 62)
```

### 3.1. Типы действий

```text
action_type = PASS | CARRY
is_cross    = true | false
```

Кросс в StatsBomb — признак паса, не отдельный тип действия.

Счётчики:

```text
box_entries_total
pass_box_entries
carry_box_entries
cross_box_entries
```

Правила без double-count:

- `pass_box_entries` — `action_type = PASS` и `is_cross = false`;
- `cross_box_entries` — `action_type = PASS` и `is_cross = true`;
- `carry_box_entries` — `action_type = CARRY`;
- `box_entries_total` = сумма трёх счётчиков выше.

Один вход не попадает одновременно в `pass_box_entries` и `cross_box_entries`.

### 3.2. Витрина `marts.box_entries`

```text
match_id
team_id
player_id
action_type
is_cross
start_x
start_y
end_x
end_y
successful
```

`successful` берётся из outcome действия источника. Точное поле outcome фиксируется при разборе первого payload и не меняет определение входа в штрафную.

---

## 4. Progressive pass

Расстояние — евклидово, до центра ворот соперника `(120, 40)`.

```text
distance_before = hypot(120 - start_x, 40 - start_y)
distance_after  = hypot(120 - end_x,   40 - end_y)

progression =
(distance_before - distance_after) / distance_before
```

Absolute reduction:

```text
absolute_reduction = distance_before - distance_after
```

Передача считается только для `event_type = Pass` с заполненными start и end координатами. Направление прогрессии: мяч становится ближе к `(120, 40)`.

### 4.1. Определения для сравнения

```text
A: progression >= 0.20
B: progression >= 0.25
C: progression >= 0.25 AND absolute_reduction >= 10 yards
```

Сравнение A/B/C живёт в `notebooks/metric_validation.ipynb`. Смотреть:

- число передач;
- устойчивость рейтинга игроков;
- устойчивость рейтинга команд;
- распределение по зонам.

### 4.2. Определение витрины

До завершения эксперимента витрина `marts.progressive_passes` использует **определение B**.

Определение C с порогом 10 ярдов остаётся кандидатом. После эксперимента выбранное определение и итоговое значение абсолютного порога переносятся в этот раздел, а витрина переключается на него.

Варианты A и C не удаляются из ноутбука и теста сравнения.

### 4.3. Поля витрины

```text
match_id
team_id
player_id
start_x
start_y
end_x
end_y
start_zone
end_zone
distance_before
distance_after
progression
absolute_reduction
definition_used
```

`definition_used` для текущего MVP = `B`.

---

## 5. Possession

Владение берётся из StatsBomb `possession`. Заново собирать владение из смены команды не нужно.

### 5.1. Служебные события

В аналитическое владение не входят:

```text
Starting XI
Half Start
Half End
Tactical Shift
```

Список можно расширить после профиля типов событий. Расширения дописываются сюда явно.

### 5.2. Витрина `marts.possessions`

```text
possession_id
match_id
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

`start_*` и `end_*` берутся по первому и последнему аналитическому событию владения после исключения служебных типов.

`has_shot` = владение содержит хотя бы один `Shot`.  
`has_goal` = владение содержит гол.  
`total_xg` = сумма `shot_xg` по ударам владения.

### 5.3. Витрина `marts.shot_possessions`

Отвечает на вопрос: из каких зон начинаются владения, которые заканчиваются ударом.

Зерно агрегации по умолчанию:

```text
start_zone
```

Поля:

```text
start_zone
possessions
shot_possessions
shot_conversion_rate
total_xg
avg_xg
```

```text
shot_conversion_rate = shot_possessions / possessions
avg_xg = total_xg / shot_possessions
```

При `shot_possessions = 0` значение `avg_xg` не считается.

---

## 6. Chance creation

Расширение после трёх MVP-метрик.

Смотрятся последние **3** аналитических события владения до удара.

Поля анализа:

```text
pass_before_shot
zone_before_shot
player_before_shot
sequence_length
```

`sequence_length` — фактическое число событий в окне, не больше 3.

В MVP витрина chance creation не обязательна.

---

## 7. Per 90 и профиль команды

```text
metric_per_90 = metric / minutes * 90
```

### 7.1. Минуты команды

Знаменатель команды — фактическая длина матча без серии пенальти:

```text
REGULAR     → 90
EXTRA_TIME  → 120
PENALTY_SHOOTOUT → 120
```

Серия пенальти минуты не добавляет.

Минуты игрока из интервалов позиций и замен в MVP не входят.

### 7.2. Extra time и пенальти

Канонический счёт без серии пенальти описан в `docs/data_contract.md`.

Для метрик:

- голы в `goals` / `goals_per_90` берутся из канонического счёта без пенальти;
- удары и xG серии пенальти в MVP-метрики атаки не включаются, если они появляются как отдельные события после окончания игры в open-data; окончательное правило фиксируется после профиля финала и матчей с серией;
- знаменатель per 90 не включает время серии.

### 7.3. Витрина `marts.team_attacking_profile`

```text
team
matches

goals_per_90
shots_per_90
xg_per_90

progressive_passes_per_90
box_entries_per_90
shot_possessions_per_90
```

`box_entries_per_90` использует `box_entries_total`.  
`progressive_passes_per_90` использует определение B, пока эксперимент не заменит его.

---

## 8. Порядок реализации метрик

1. Зоны из `config.pitch_zones`.
2. `marts.box_entries`.
3. `marts.progressive_passes` по определению B.
4. `marts.possessions` и `marts.shot_possessions`.
5. `marts.team_match_summary` и `marts.team_attacking_profile`.
6. Сравнение A/B/C в ноутбуке.
7. Chance creation как расширение.

---

## 9. Открытые вопросы метрик

1. Итоговое определение progressive pass после `metric_validation.ipynb`: остаётся B или переключается на C / другое значение абсолютного порога.
2. Полный список служебных типов событий для possession после профиля.
3. Точное поле success/outcome для box entry после первого разбора StatsBomb payload.
4. Правило включения или исключения ударов серии пенальти в shots/xG после профиля матчей с `PENALTY_SHOOTOUT`.
