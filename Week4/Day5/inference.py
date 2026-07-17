"""
Inference script for the Adult Census Income model (calibrated LightGBM).

Usage:
    from inference import predict_income, load_model

    model = load_model("lgbm_calibrated_final_model.joblib")
    result = predict_income(row_dict, model)          # single row as dict
    result = predict_income(df, model)                # dataframe / CSV-loaded rows

Run this file directly to execute the unit tests:
    python inference.py
"""

import joblib
import numpy as np
import pandas as pd
import shap

CHOSEN_THRESHOLD = 0.60

REQUIRED_COLUMNS = [
    "age", "workclass", "education-num", "marital-status", "occupation",
    "relationship", "race", "sex", "capital-gain", "capital-loss",
    "hours-per-week", "native-country"
]

CATEGORICAL_COLUMNS = [
    "workclass", "marital-status", "occupation",
    "relationship", "race", "sex", "native-country"
]


class InputValidationError(Exception):
    pass


def load_model(path="lgbm_calibrated_final_model.joblib"):
    return joblib.load(path)


def build_known_categories(training_df):
    """Call once at setup time with your training X to build the reference
    category sets used for unseen-category checks."""
    return {col: set(training_df[col].dropna().unique()) for col in CATEGORICAL_COLUMNS}


def validate_input(raw_df, known_categories=None):
    """
    Checks a raw input dataframe for missing required columns and
    unseen categorical values before it's sent through the pipeline.
    Raises InputValidationError with a clear message if something is wrong.
    Returns (cleaned_df, warnings_dict).
    """
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in raw_df.columns]
    if missing_cols:
        raise InputValidationError(f"Missing required columns: {missing_cols}")

    extra_cols = [c for c in raw_df.columns if c not in REQUIRED_COLUMNS]
    if extra_cols:
        raw_df = raw_df.drop(columns=extra_cols)

    warnings_found = {}
    if known_categories:
        for col in CATEGORICAL_COLUMNS:
            if col not in raw_df.columns:
                continue
            unseen = set(raw_df[col].dropna().unique()) - known_categories.get(col, set())
            if unseen:
                warnings_found[col] = list(unseen)

    return raw_df[REQUIRED_COLUMNS], warnings_found


def predict_income(raw_input, model, threshold=CHOSEN_THRESHOLD, top_k=3, known_categories=None):
    """
    Accepts raw input as either a dict (single row) or a dataframe (same
    columns as training X, before feature engineering).

    Returns a dataframe with:
        - predicted_class (0/1)
        - predicted_label (<=50K / >50K)
        - probability_gt_50k
        - top_3_features (feature, shap_value) pairs driving this prediction
    Warnings about unseen categories (if known_categories is passed) are
    printed and attached to the result's .attrs["warnings"].
    """
    if isinstance(raw_input, dict):
        raw_df = pd.DataFrame([raw_input])
    else:
        raw_df = raw_input.copy()

    raw_df, unseen_warnings = validate_input(raw_df, known_categories)

    prob = model.predict_proba(raw_df)[:, 1]
    pred = (prob >= threshold).astype(int)

    base_pipeline = model.estimator
    X_eng = base_pipeline.named_steps["feature_engineering"].transform(raw_df)
    X_processed = base_pipeline.named_steps["preprocessor"].transform(X_eng)
    feat_names = base_pipeline.named_steps["preprocessor"].get_feature_names_out()

    row_explainer = shap.TreeExplainer(base_pipeline.named_steps["classifier"])
    row_shap_values = row_explainer.shap_values(X_processed)

    top3_list = []
    for row_vals in row_shap_values:
        idx_sorted = np.argsort(np.abs(row_vals))[::-1][:top_k]
        top3 = [(feat_names[i], round(float(row_vals[i]), 4)) for i in idx_sorted]
        top3_list.append(top3)

    results = pd.DataFrame({
        "predicted_class": pred,
        "predicted_label": np.where(pred == 1, ">50K", "<=50K"),
        "probability_gt_50k": prob,
        "top_3_features": top3_list
    }, index=raw_df.index)

    if unseen_warnings:
        results.attrs["warnings"] = unseen_warnings
        print("Warning, unseen categories found (model will still predict, but flagging this):", unseen_warnings)

    return results


# ===================== Unit Tests =====================

def _sample_row():
    return {
        "age": 39, "workclass": "Private", "education-num": 13,
        "marital-status": "Never-married", "occupation": "Adm-clerical",
        "relationship": "Not-in-family", "race": "White", "sex": "Male",
        "capital-gain": 2174, "capital-loss": 0, "hours-per-week": 40,
        "native-country": "United-States"
    }


def test_missing_column(model):
    bad_row = _sample_row()
    del bad_row["age"]
    try:
        predict_income(bad_row, model)
        print("FAILED: should have raised InputValidationError for missing column")
    except InputValidationError as e:
        print("PASSED: missing column correctly caught ->", e)


def test_unseen_category(model, known_categories):
    bad_row = _sample_row()
    bad_row["workclass"] = "TOTALLY_UNSEEN_CATEGORY_XYZ"
    out = predict_income(bad_row, model, known_categories=known_categories)
    if "warnings" in out.attrs and "workclass" in out.attrs["warnings"]:
        print("PASSED: unseen category correctly flagged ->", out.attrs["warnings"])
    else:
        print("FAILED: unseen category was not flagged")


def test_valid_input_shape(model):
    out = predict_income(_sample_row(), model)
    assert len(out) == 1
    assert "probability_gt_50k" in out.columns
    assert "top_3_features" in out.columns
    assert len(out.iloc[0]["top_3_features"]) == 3
    print("PASSED: valid input returns correct shape and expected columns")


def test_dataframe_input(model):
    df = pd.DataFrame([_sample_row(), _sample_row()])
    out = predict_income(df, model)
    assert len(out) == 2
    print("PASSED: dataframe input with multiple rows works")


if __name__ == "__main__":
    model = load_model("lgbm_calibrated_final_model.joblib")

    # known_categories is optional here since we don't have training X in this
    # script; in the notebook it's built directly from X_train
    test_missing_column(model)
    test_valid_input_shape(model)
    test_dataframe_input(model)

    print("\nAll runnable tests finished. Run test_unseen_category(model, known_categories)")
    print("separately once you've built known_categories from your training data.")
