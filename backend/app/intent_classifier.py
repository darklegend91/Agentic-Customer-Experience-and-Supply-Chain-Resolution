"""TF-IDF + logistic-regression intent baseline with review-only predictions."""

from __future__ import annotations

import csv
import json
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.pipeline import Pipeline

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
MODEL_PATH = PROJECT_ROOT / "models" / "intent_tfidf_logreg_v1.joblib"
MODEL_VERSION = "intent-tfidf-logreg-v1"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def build_pipeline() -> Pipeline:
    """Build a small, reproducible lexical classifier baseline."""
    return Pipeline([
        ("tfidf", TfidfVectorizer(
            lowercase=True,
            strip_accents="unicode",
            # Keep negations such as "not received"; they change ticket meaning.
            stop_words=None,
            ngram_range=(1, 2),
            sublinear_tf=True,
            min_df=1,
        )),
        ("classifier", LogisticRegression(
            C=4.0,
            class_weight="balanced",
            max_iter=2000,
            random_state=20261102,
        )),
    ])


def train_and_evaluate(
    train_path: Path = PROCESSED_DIR / "classifier_train.csv",
    evaluation_path: Path = PROCESSED_DIR / "intent_evaluation.csv",
    model_path: Path = MODEL_PATH,
) -> dict[str, Any]:
    training = read_csv(train_path)
    evaluation = read_csv(evaluation_path)
    if not training or not evaluation:
        raise ValueError("Training and evaluation CSVs must both contain labeled examples")
    if any(not row.get("message", "").strip() or not row.get("intent", "").strip() for row in training):
        raise ValueError("Training rows require non-empty message and intent fields")
    if any(not row.get("message", "").strip() or not row.get("expected_intent", "").strip() for row in evaluation):
        raise ValueError("Evaluation rows require non-empty message and expected_intent fields")

    train_ids = {row["ticket_id"] for row in training}
    eval_ids = {row["ticket_id"] for row in evaluation}
    if train_ids & eval_ids:
        raise ValueError("Classifier training and evaluation ticket IDs overlap")

    x_train = [row["message"] for row in training]
    y_train = [row["intent"] for row in training]
    x_eval = [row["message"] for row in evaluation]
    y_eval = [row["expected_intent"] for row in evaluation]

    model = build_pipeline()
    model.fit(x_train, y_train)
    predicted = model.predict(x_eval)
    probabilities = model.predict_proba(x_eval)
    classes = list(model.named_steps["classifier"].classes_)
    confidence = probabilities.max(axis=1)
    accuracy = float(accuracy_score(y_eval, predicted))
    macro_f1 = float(f1_score(y_eval, predicted, labels=classes, average="macro", zero_division=0))
    weighted_f1 = float(f1_score(y_eval, predicted, labels=classes, average="weighted", zero_division=0))

    report = classification_report(
        y_eval,
        predicted,
        labels=classes,
        output_dict=True,
        zero_division=0,
    )
    matrix = confusion_matrix(y_eval, predicted, labels=classes)
    metrics = {
        "model_version": MODEL_VERSION,
        "model_type": "word_unigram_bigram_tfidf_logistic_regression",
        "training_rows": len(training),
        "evaluation_rows": len(evaluation),
        "label_count": len(classes),
        "labels": classes,
        "train_label_counts": dict(sorted(Counter(y_train).items())),
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "weighted_f1": weighted_f1,
        "mean_top_class_probability": float(confidence.mean()),
        "per_class": report,
        "confidence_is_calibrated": False,
        "automatic_routing_enabled": False,
        "evaluation_limit": (
            "Synthetic fixture only; two held-out customer/message-template groups per label. "
            "This is not a production accuracy estimate."
        ),
    }

    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "model_version": MODEL_VERSION, "labels": classes}, model_path)

    predictions_path = PROCESSED_DIR / "intent_predictions_v1.csv"
    predictions_path.parent.mkdir(parents=True, exist_ok=True)
    with predictions_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "evaluation_set_version", "ticket_id", "expected_intent", "predicted_intent",
            "top_class_probability", "requires_human_review", "model_version",
        ])
        writer.writeheader()
        for row, actual, guess, score in zip(evaluation, y_eval, predicted, confidence):
            writer.writerow({
                "evaluation_set_version": row.get("evaluation_set_version", "intent-eval-v1"),
                "ticket_id": row["ticket_id"],
                "expected_intent": actual,
                "predicted_intent": guess,
                "top_class_probability": f"{float(score):.6f}",
                "requires_human_review": "true",
                "model_version": MODEL_VERSION,
            })

    confusion_path = PROCESSED_DIR / "intent_confusion_matrix_v1.csv"
    with confusion_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["expected_intent\\predicted_intent", *classes])
        for label, values in zip(classes, matrix.tolist()):
            writer.writerow([label, *values])

    metrics_path = PROCESSED_DIR / "intent_baseline_metrics_v1.json"
    metrics_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    metrics["artifact_paths"] = {
        "model": str(model_path.relative_to(PROJECT_ROOT)),
        "metrics": str(metrics_path.relative_to(PROJECT_ROOT)),
        "predictions": str(predictions_path.relative_to(PROJECT_ROOT)),
        "confusion_matrix": str(confusion_path.relative_to(PROJECT_ROOT)),
    }
    print(f"Classifier baseline: accuracy={accuracy:.3f}, macro_f1={macro_f1:.3f}, weighted_f1={weighted_f1:.3f}")
    print(f"Model: {model_path.relative_to(PROJECT_ROOT)}")
    print(f"Metrics: {metrics_path.relative_to(PROJECT_ROOT)}")
    return metrics


@lru_cache(maxsize=2)
def load_model(model_path: Path = MODEL_PATH) -> tuple[Pipeline, str]:
    artifact = joblib.load(model_path)
    return artifact["model"], artifact["model_version"]


def classify_ticket(message: str, model_path: Path = MODEL_PATH) -> dict[str, Any]:
    """Return a triage suggestion; every baseline result remains human-reviewed."""
    text = (message or "").strip()
    if not text:
        raise ValueError("Ticket message must not be empty")
    model, version = load_model(model_path)
    probabilities = model.predict_proba([text])[0]
    class_names = model.named_steps["classifier"].classes_
    best_index = int(probabilities.argmax())
    return {
        "candidate_intent": str(class_names[best_index]),
        "top_class_probability": float(probabilities[best_index]),
        "model_version": version,
        "prediction_status": "baseline_suggestion",
        "requires_human_review": True,
        "confidence_calibrated": False,
    }
