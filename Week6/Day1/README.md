# Week 6 Day 1: AFL Data Foundations (EDA, Feature Engineering & Prediction Targets)

## Overview
This is the first day of Week 6, and the goal was to get the AFL data ready before any modeling or agent building starts later this week. I worked with three files: player round by round stats, team match results (home and away), and the season level player table I built back in Week 2 (merged_players.csv). The idea was to understand exactly what each table holds, check the data is clean, lock in what "team win" and "top player" actually mean, explore the data, and build a feature table that Day 2 onwards can just load instead of redoing this work.

---

## Objectives
- Document what each of the three files actually represents and how they connect to each other
- Check the data for missing values, duplicates, and naming problems
- Write clear, exact definitions for the match winner target and the top player target
- Explore the data with visuals to see what patterns are actually there
- Build rolling and form based features without letting any future information leak in
- Build a reusable function to split the data by time instead of randomly
- Save a versioned feature table so the rest of the week can reuse it

---

## Dataset
Three files were used, all provided, nothing pulled in from outside:

- **afl_players_round_by_round_stats_raw.csv** — one row per player per match. Has stuff like kicks, disposals, goals, tackles, fantasy points, for every game a player played.
- **team_matches_home_away_raw.csv** — one row per team per match, so every match shows up twice (once from each team's side). Has scores, result, margin, venue.
- **merged_players.csv** — one row per player per season per team, from Week 2. This is the round by round stats already aggregated into season totals and averages, joined with player bio info like height, weight, debut date.

Data covers 1983 to 2025 (43 seasons), 20 teams, and just over 3,100 unique players.

---

## Tasks Completed

### **Task 1: Data Inventory & Understanding**

Went through all three files and wrote down what each row means, how they join together (mainly on team + opponent + match date, or player_id + year), and the date range each one covers. Also flagged a few real structural changes in the data: the 2020 season is short because of COVID, and Fitzroy Lions and Brisbane Bears both stop appearing after 1996 since they merged into Brisbane Lions in 1997.

**Data quality checks**

Found that team_matches had messy team names, some had extra whitespace or tab characters, and the Western Bulldogs were recorded as "W. Bulldogs" instead of the full name used everywhere else. That turned 20 real teams into 40 "different" looking names. Wrote a small cleaning function to fix this. Also found 723 rows where disposals came out negative, which isn't possible since disposals is just kicks plus handballs added together. Flagged this instead of guessing a fix, since it's a small chunk of rows and there's no reliable way to know the real number.

### **Task 2: Prediction Targets**

Defined the match winner target as a 3 class label (home win, away win, draw) instead of trying to predict the exact margin, since the real question is who wins, not by how much. Also defined two versions of "top player": one based on disposals, one based on goals, and a third composite version using the fantasy_points column that's already in the data (didn't reinvent this formula since AFL Fantasy scoring is already built into that column).

### **Task 3: Exploratory Data Analysis**

Built five visuals:
- Home team win rate by season (home teams win more often than not, most seasons)
- Match margin distribution (pretty wide spread, matches can swing by well over 100 points)
- Top 10 all time leaders in disposals and goals
- Player consistency (average fantasy points vs how much it swings game to game)
- Recent form vs win probability (teams on a hot streak really are more likely to win next match)

One honest gap here: the data has no position column for players, so I couldn't do the forward vs midfielder vs defender comparison the task asked for. Flagged this instead of faking it with a guess.

### **Task 4: Feature Engineering**

Built rolling and form based features for both teams and players, things like last 5 game win rate, average score, win or loss streaks, days of rest, ladder position before the match, head to head record against the specific opponent, and venue history. Every single one of these is built using shift and rolling logic, so a feature for any given match only ever uses information from matches strictly before it. No future leakage anywhere.

### **Task 5: Train/Holdout Split**

Wrote a reusable function that splits the data by season instead of randomly, training on earlier years and holding out the most recent season to test on. A random split would leak future information since these rolling features depend on a team's whole history. Also wrote up a short note on realistic accuracy expectations, somewhere around 65 to 72 percent for match winner is realistic, and anything close to 90 percent plus would actually be a red flag for leakage, not a good result.

---

## Visualizations Included
- 📈 Line Chart — Home team win rate by season
- 📊 Histogram — Match margin distribution (home score minus away score)
- 📊 Bar Chart — Top 10 all time leaders, disposals and goals
- 🔵 Scatter Plot — Player consistency, average fantasy points vs variation
- 📊 Bar Chart — Win rate in next match by recent form bucket

---

## Technologies Used
- Python
- Pandas
- NumPy
- Matplotlib
- Seaborn
- Jupyter Notebook

---

## Project Structure
```
Week6_Day1/
│
├── afl_players_round_by_round_stats_raw.csv
├── team_matches_home_away_raw.csv
├── merged_players.csv
├── week6_day1_afl_data_foundations.ipynb
├── team_match_features_v1_2026-07-27.csv
├── player_match_features_v1_2026-07-27.csv
├── data_dictionary_and_targets.md
└── README.md
```

---

## Key Insights
- Home ground advantage is real and shows up clearly in the data, home teams win more than half their matches in almost every season
- Teams on a winning streak really are more likely to win their next match, confirming that form based features are worth building
- Player output and consistency are linked, the higher a player's average, the bigger their game to game swings tend to be
- The dataset has real structural quirks (short 2020 season, club mergers) that need to be understood before building any model on top of it
- Small data quality issues (messy team names, a handful of negative disposal values) needed cleaning or flagging before anything downstream could trust the numbers

---

## Skills Demonstrated
- Data Cleaning
- Exploratory Data Analysis
- Data Visualization
- Feature Engineering
- Time Series Aware Train/Test Splitting
- Leakage Prevention
- Python Programming (Pandas, NumPy)
- Documentation

---

## Future Improvements
- Add a player position field if it becomes available, to properly compare forwards, midfielders, and defenders
- Try longer and shorter rolling windows (last 3, last 10 games) alongside the last 5 game window already built
- Build the actual match winner model on top of this feature table (planned for Day 2)
- Add travel distance or interstate flag as a feature, since it wasn't available in the current files
- Automate the feature table versioning so old versions don't need to be deleted manually

---

## Author
Imama Zubair
AI & Data Science Intern @ Netixsol