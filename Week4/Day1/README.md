# Week 4 Day 1: ML Foundations — Problem Framing, Hold-Out Test & Baseline

## Overview
This project sets up the foundational pipeline for predicting whether an individual earns more than $50K per year using the UCI Adult Census Income dataset. This task mirrors real-world business applications such as targeted marketing and credit risk screening. The focus for Day 1 is establishing a reproducible train/hold-out test split, defining a business-driven evaluation metric, evaluating rule-based baselines, and conducting an initial error analysis to guide future feature engineering and modeling.

---

## Objectives
- Frame the Census Income prediction problem with a clear business objective and success metric.
- Load, clean missing values (`?` → `NaN`), and conduct Exploratory Data Analysis (EDA) on the Adult dataset.
- Create a stratified hold-out test set (~20%) to prevent data leakage during model iteration and hyperparameter tuning.
- Implement simple baseline models (Majority Class, Education Rule, Capital Gain Rule) to establish performance benchmarks.
- Perform initial error analysis on false positives and false negatives to identify dataset patterns and plan subsequent modeling steps.

---

## Dataset
- **Source:** UCI "Adult" Census Income Dataset (`sklearn.datasets.fetch_openml('adult')`).
- **Target Variable:** `income` (binary classification: `>50K` as positive class `1`, `<=50K` as negative class `0`).
- **Key Features:** Age, Education Level, Capital Gain, Capital Loss, Hours per Week, Occupation, Relationship Status, Native Country.
- **Data Quality Notes:** Missing values represented as `'?'` in categorical attributes and converted to `NaN` during cleaning.

---

## Tasks / Features
- **Problem Framing:** Defined positive class (`>50K`) and selected Precision as the primary evaluation metric to minimize wasted outreach in targeted marketing.
- **Data Preprocessing & EDA:** Converted targets to binary flags, parsed missing values, analyzed class distributions, and generated numerical summaries.
- **Reproducible Data Splitting:** Created a 20% stratified hold-out test set with a fixed random state (`random_state=42`) reserved strictly for final model evaluation.
- **Baseline Implementations:** Built and evaluated majority-class, education-level (`education-num >= 13`), and capital-gain (`capital-gain > 0`) rule-based classifiers.
- **Error Analysis:** Sampled false positive and false negative cases to identify key failure modes of basic heuristics.

---

## Baseline Results

| Model / Baseline | Accuracy | Precision | Recall | F1 Score | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Majority Class** | 0.761 | 0.000 | 0.000 | 0.000 | Predicts all negative (`<=50K`) |
| **Education Rule** (`education-num >= 13`) | 0.753 | 0.484 | 0.497 | 0.491 | Flags individuals with higher education |
| **Capital Gain Rule** (`capital-gain > 0`) | **0.782** | **0.625** | 0.225 | 0.331 | Best Precision & Accuracy baseline |

---

## Visualizations Included
- 📊 **Bar Chart — Target Class Distribution:** Visualizes positive vs. negative income class proportions to identify class imbalance.
- 📈 **Histogram — Capital Gain & Hours Worked:** Displays distribution and skewness across high and low earners.
- 📦 **Box Plot — Feature Distributions by Target:** Compares age and education years across income groups.

---

## Technologies Used
- **Python**
- **Pandas** & **NumPy**
- **Scikit-Learn**
- **Matplotlib** & **Seaborn**
- **Jupyter Notebook**

---

## Project Structure

```
Week4_Day1_ML_Foundations/
│
├── data/
│   └── adult_census.csv
├── notebooks/
│   └── week4_day1_ml_foundations.ipynb
├── outputs/
│   ├── baseline_metrics.csv
│   └── error_analysis_sample.csv
├── deliverable_summary.pdf
└── README.md
```

---

## Key Insights
- **Class Imbalance:** High-income earners (`>50K`) represent approximately 24% of the dataset, establishing a majority class baseline accuracy of 76.1%.
- **Capital Gain Rule Superiority:** Screening by `capital-gain > 0` yielded the highest baseline Precision (0.625) and Accuracy (0.782), directly aligning with the business goal of minimizing wasted contacts.
- **Failure Mode of Heuristics:** False negatives in the Capital Gain baseline averaged higher education (11.49 vs 9.87 years) and longer work hours (45.42 vs 40.61 hours/week) than false positives, proving that relying solely on capital gain misses substantial high-earning individuals without investment income.
- **Modeling Requirement:** Future models must incorporate multi-feature interactions (combining education, hours worked, occupation, and marital status) to boost Recall while maintaining or improving the 62.5% Precision baseline.

---

## Skills Demonstrated
- Machine Learning Problem Framing & Objective Setting
- Stratified Train/Test Hold-Out Splitting
- Exploratory Data Analysis & Preprocessing
- Heuristic / Rule-Based Model Baseline Building
- Error Analysis & Qualitative Model Diagnostics
- Metric Selection (Precision vs. Recall Trade-offs)

---

## Future Improvements
- Impute missing values across categorical variables (e.g., `workclass`, `occupation`, `native-country`).
- Perform one-hot encoding for categorical variables and feature scaling for numeric predictors.
- Train complex classifiers (Logistic Regression, Random Forest, XGBoost) to optimize Precision.
- Apply probability threshold tuning to optimize for target precision levels.

---

## Author
Imama Zubair  
AI & Data Science Intern — Netixsol
