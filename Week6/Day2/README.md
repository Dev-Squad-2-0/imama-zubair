# Week 6 Day 2: AFL Prediction Models (Match Winner & Top Player)

## Overview

Day 2 focused on building the first machine learning models using the feature tables created on Day 1. The goal was to predict **match winners** and **top player performances**, compare them against simple baseline models, understand which features influenced the predictions, and package everything into reusable prediction functions ready to be integrated into the chat agent later in the week.

---

## Objectives

* Build baseline models for match winner and top player prediction
* Train and compare machine learning models against the baselines
* Evaluate models using appropriate performance metrics
* Analyze feature importance and check for possible data leakage
* Perform a manual "sniff test" on holdout matches
* Save the trained models and package them into reusable prediction functions

---

## Dataset

The versioned feature tables created on Day 1 were used throughout today's work.

* **team_match_features_v1_2026-07-27.csv** : engineered team-level features used for predicting match winners.
* **player_match_features_v1_2026-07-27.csv** : engineered player-level rolling features used for predicting player performance.

Before modeling, opponent team names were standardized to match the formatting used in the `team_name` column. A match-level dataset was then created by merging the home and away team rows so that each match appeared only once, which is the correct format for the match winner model. Draws made up less than 1% of the data and were removed so the problem could be treated as binary classification (home win vs away win).

---

## Tasks Completed

### Task 1: Baseline Models

Built two baseline models for match winner prediction:

* **Always Home Win** baseline
* **Higher Ladder Team Wins** baseline

The higher-ladder baseline achieved **67.4% accuracy**, providing a much stronger benchmark than always predicting the home team.

For top player prediction, used each player's **last five-game average disposals** as the baseline prediction. This achieved:

* MAE: **4.04**
* Top-5 Hit Rate: **86.1%**

These baselines served as the minimum performance that the machine learning models needed to beat.

---

### Task 2: Match Winner Model

Built a preprocessing pipeline using **ColumnTransformer**, median imputation, and feature scaling before training two classification models:

* Logistic Regression
* Gradient Boosting Classifier

Both models were evaluated using:

* Accuracy
* F1 Score
* ROC AUC
* Brier Score

Logistic Regression performed the best overall:

* Accuracy: **69.8%**
* F1 Score: **0.762**
* ROC AUC: **0.753**

Although Gradient Boosting had a slightly lower Brier Score, the difference was extremely small, so Logistic Regression was selected as the final model because it achieved better classification performance while remaining easier to interpret.

---

### Task 3: Top Player Model

Framed the task as a **regression problem**, predicting each player's expected:

* Disposals
* Goals
* Fantasy Points

Players were then ranked by their predicted values to identify the expected top performers.

Three **Gradient Boosting Regressor** models were trained (one for each statistic) using the rolling features created on Day 1.

Results:

| Target         |       MAE | Top-5 Hit Rate |
| -------------- | --------: | -------------: |
| Disposals      |  **3.82** |      **98.1%** |
| Goals          |  **0.75** |      **94.4%** |
| Fantasy Points | **18.18** |      **89.1%** |

The disposals model clearly outperformed the baseline, reducing MAE from **4.04** to **3.82** while improving the Top-5 Hit Rate from **86.1%** to **98.1%**.

---

### Task 4: Feature Importance & Sanity Checks

Analyzed the Logistic Regression coefficients to understand which features influenced predictions the most.

The strongest predictors were:

* Points before the match
* Average score over the last five games
* Venue win rate

These features made football sense and there were no obvious signs of data leakage.

A manual sniff test was also carried out on three matches from the holdout season. Two predictions matched the expected outcome based on team form and ladder position, while one upset result highlighted the natural unpredictability of sports rather than a modeling issue.

---

### Task 5: Packaging the Models

Saved all trained models as `.joblib` files so they can be reused without retraining.

Created a reusable `predict.py` module containing two callable functions:

* `predict_match_winner(home_team, away_team)`
* `predict_top_player(team, stat_type, top_n)`

The functions automatically load the trained models, retrieve the latest available team or player features, validate user input, and return predictions in a clean format. These functions are designed to be wrapped as tools for the chat agent later in the week.

---

## Models Built

### Match Winner

* Logistic Regression *(Final Model)*
* Gradient Boosting Classifier

### Top Player

* Gradient Boosting Regressor (Disposals)
* Gradient Boosting Regressor (Goals)
* Gradient Boosting Regressor (Fantasy Points)

---

## Evaluation Metrics

### Match Winner

* Accuracy
* F1 Score
* ROC AUC
* Brier Score

### Top Player

* MAE
* RMSE
* Top-5 Hit Rate

---

## Technologies Used

* Python
* Pandas
* NumPy
* Scikit-learn
* Joblib
* Matplotlib
* Seaborn
* Jupyter Notebook

---

## Project Structure

```text
Week6_Day2/
│
├── team_match_features_v1_2026-07-27.csv
├── player_match_features_v1_2026-07-27.csv
├── week6_day2_models.ipynb
├── predict.py
├── models/
│   ├── match_winner_model.joblib
│   ├── top_player_model_disposals.joblib
│   ├── top_player_model_goals.joblib
│   ├── top_player_model_fantasy_points.joblib
│   ├── latest_team_features.joblib
│   ├── latest_player_features.joblib
│   └── valid_teams.joblib
└── README.md
```

---

## Key Insights

* The higher-ladder baseline was a strong benchmark, but Logistic Regression still improved on it.
* Rolling player statistics were useful predictors of future performance and significantly outperformed the simple baseline.
* Team points before the match, recent scoring, and venue history were the strongest predictors of match outcomes.
* The models generalized well to the holdout season, while still reflecting the natural uncertainty of sports.

---

## Skills Demonstrated

* Machine Learning
* Classification
* Regression
* Model Evaluation
* Baseline Comparison
* Feature Importance Analysis
* Model Packaging
* Input Validation
* Scikit-learn Pipelines
* Python Programming

---

## Future Improvements

* Add more contextual features such as weather, travel distance, and player availability.
* Experiment with additional regression and ensemble models for top player prediction.
* Tune model hyperparameters to further improve performance.
* Connect the prediction functions to live fixture data instead of using the latest historical features.
* Integrate the prediction functions into the LangChain/LangGraph chat agent.

---

## Author

*Imama Zubair*
**AI & Data Science Intern @ Netixsol**
