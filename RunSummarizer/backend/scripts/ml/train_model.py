"""Train the lap classifier from a labelled lap CSV and save it."""

import argparse
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split

from app.ml import MODEL_PATH


def train_lap_classifier(csv_path: str | Path, model_save_path: str | Path = MODEL_PATH):
    model_save_path = Path(model_save_path)
    model_save_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Loading data from {csv_path}...")
    df = pd.read_csv(csv_path, sep=";")

    df = df.dropna(subset=["lap_type"])

    y = df["lap_type"]

    columns_to_drop = ["activity_id", "activity_date", "lap_index", "lap_type", "pace_min_km"]
    columns_to_drop = [col for col in columns_to_drop if col in df.columns]
    X = df.drop(columns=columns_to_drop)

    feature_names = X.columns

    print("Splitting data into training and test sets...")
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    print(f"Training model on {len(X_train)} laps...")
    model = RandomForestClassifier(
        n_estimators=100, random_state=42, max_depth=5, class_weight="balanced"
    )
    model.fit(X_train, y_train)

    print("\nModel evaluation:")
    y_pred = model.predict(X_test)

    accuracy = accuracy_score(y_test, y_pred)
    print(f"Overall accuracy: {accuracy * 100:.2f}%\n")

    print("Classification report (Precision / Recall for each class):")
    target_names = ["0: Run", "1: Recovery", "2: Rest"]
    print(classification_report(y_test, y_pred, target_names=target_names))

    print("\nFeature importance:")
    importances = model.feature_importances_
    feature_importances = pd.DataFrame(
        {"Feature": feature_names, "Importance": importances}
    ).sort_values(by="Importance", ascending=False)

    for _, row in feature_importances.iterrows():
        print(f"   {row['Feature']:<15}: {row['Importance'] * 100:.1f}%")

    print(f"\nSaving model to file: {model_save_path}")
    joblib.dump(model, model_save_path)

    return model


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--csv", required=True, type=Path, help="Labelled lap CSV (';'-separated).")
    parser.add_argument(
        "--out", type=Path, default=MODEL_PATH, help=f"Model file to write (default: {MODEL_PATH})."
    )
    args = parser.parse_args()

    train_lap_classifier(args.csv, args.out)


if __name__ == "__main__":
    main()
