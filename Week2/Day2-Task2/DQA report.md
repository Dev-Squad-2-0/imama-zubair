# AFL Player Data: Data Quality Assessment Report

## Scope
The datasets prior to cleaning:
- `afl_players_info_raw.csv` : 2,848 rows, 16 columns (player biographical data)
- `afl_players_seasonal_stats_raw.csv` : 25,491 rows, 54 columns (season-by-season performance stats)

## Methodology
Each dataset was checked for: exact duplicate records, missing values, invalid/impossible
values, internal logical consistency (e.g. date ordering), format inconsistencies in key
fields, and referential integrity between the two datasets (matching player ids).

Gotta check for:
- dupes
- missing vals
- invalid vals (e.g. 0 weight)
- inconsistent logic
- messed up weight/height
- 
## Findings of `players_info`

#### 1. Duplicated Rows: 5
I found 5 duplicate rows in the dataset where the same player ID and all information were repeated.

#### 2. Weight == 0: 2 found
There were 2 players with a weight of 0, which is not a valid value because a person's weight cannot be zero.

#### 3. Missing profile_pic: 2211
The profile_pic column had 2,211 missing values. Since this is only an optional profile picture field, the missing values were left as they are, we dont need to touch that.

#### 4. Missing player_common_names: 2773
The player_common_names column had 2,773 missing values. This field stores player nicknames, so leaving these values blank does not affect the analysis either

#### 5. Missing player_teams: 94
The player_teams column had 94 missing values. This means some players do not have a recorded team list, which is acceptable.

There were also no unrealistic height or weight values. Although some players were very short (163 cm) or very tall (211 cm), these are real players and not data errors.

## Findings of `seasonal_stats`

#### 1. player_id format inconsistency : 10 rows found
I found **10 `player_id` values** that were written as `ID_xxxxx` instead of just numbers. These were converted to a numeric format so the datasets could be merged correctly.

#### 2. Duplicated rows: 10
There were **10 duplicate rows** where the same player statistics were repeated. These duplicate records were removed.

#### 3. Negative rows for `game_played` : 4
I found **4 rows with negative `games_played` values**, which is not possible. These were identified as data entry errors and corrected during cleaning.

#### 4. Negative rows for `total_fantasy_points` : 10

There were **10 rows with negative `total_fantasy_points` values**. These were **not changed** because fantasy points can sometimes be negative based on the scoring system.

#### 5. `team` inconsistency: 114 raw str variants, had mixed case
The `team` column had inconsistent names due to different letter cases and extra spaces. These were standardized so each team has a consistent name.

#### 6. Missing val columns: 45
Missing values were found in **45 out of 54 columns**, mostly in advanced statistics such as `hit_outs`, `brownlow_votes`, and `contested_possessions`. These values were left unchanged because these statistics were not recorded for every player or season.

The data covers the years **1983 to 2025**, and all year values were valid, so no changes were needed.


## Merged findings
- 266 distinct `player_id` values present in `seasonal_stats` have **no matching record** in `players_info` (after id-format normalization).
- 0 `id` values in `players_info` are missing from `seasonal_stats` (every player on file has at least one season of stats recorded).
- This unmatched set accounts for 400 season-stat rows (~1.6% of cleaned `seasonal_stats`) that cannot be enriched with biographical data and are excluded from the inner-joined `merged_players.csv`.

## Overall Assessment
The datasets are fundamentally sound: the issues found are well-scoped, low in volume relative
to total record counts, and fall into clearly resolvable categories (format normalization,
exact-duplicate removal, a small number of impossible values, and expected era-based
missingness). No issue required discarding a meaningful share of the data. Full
detail is in `cleaning_log.txt`; full before/after counts are in `validation_report.txt`.