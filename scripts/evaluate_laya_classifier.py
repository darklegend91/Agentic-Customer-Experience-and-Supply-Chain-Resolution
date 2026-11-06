"""Evaluate Laya and its TF-IDF corroborator on the isolated fixture holdout."""

from __future__ import annotations

import csv
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from sklearn.metrics import accuracy_score, classification_report, f1_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.classification.laya import LayaClassifierError, classify_with_laya  # noqa: E402
from backend.app.guardrails.input_validation import normalize_ticket_message  # noqa: E402
from backend.app.intent_classifier import classify_ticket as classify_baseline  # noqa: E402
from backend.app.runtime import load_project_environment  # noqa: E402
from backend.app.security.pii_masking import mask_sensitive_text  # noqa: E402

INPUT = ROOT / "data" / "processed" / "intent_evaluation.csv"
OUTPUT_JSON = ROOT / "data" / "processed" / "laya_intent_evaluation_v1.json"
OUTPUT_CSV = ROOT / "data" / "processed" / "laya_intent_predictions_v1.csv"


def read_cases() -> list[dict[str, str]]:
    with INPUT.open(newline="", encoding="utf-8-sig") as stream:
        cases = list(csv.DictReader(stream))
    if not cases:
        raise ValueError(f"No held-out cases in {INPUT}")
    return cases


def evaluate() -> dict[str, Any]:
    load_project_environment()
    cases = read_cases()
    rows: list[dict[str, Any]] = []
    expected = [row["expected_intent"] for row in cases]
    labels = sorted(set(expected))
    laya_predictions: list[str] = []
    baseline_predictions: list[str] = []
    consensus_predictions: list[str] = []
    laya_scores: list[float] = []
    accepted = 0
    accepted_correct = 0
    high_confidence_errors = 0
    laya_errors = 0
    latencies: list[float] = []
    try:
        baseline_threshold = float(os.getenv("CLASSIFIER_BASELINE_MIN_CONFIDENCE", "0.60"))
    except ValueError as exc:
        raise ValueError("CLASSIFIER_BASELINE_MIN_CONFIDENCE must be numeric") from exc
    if not 0 <= baseline_threshold <= 1:
        raise ValueError("CLASSIFIER_BASELINE_MIN_CONFIDENCE must be between 0 and 1")

    for row in cases:
        message = mask_sensitive_text(normalize_ticket_message(row["message"]))
        started = time.perf_counter()
        try:
            prediction = classify_with_laya(message)
            elapsed = time.perf_counter() - started
            latencies.append(elapsed)
            laya_intent = str(prediction["candidate_intent"])
            score = float(prediction["top_class_probability"])
            threshold = float(prediction["review_threshold"])
            abstained = bool(prediction.get("laya_abstained") or prediction.get("force_review"))
            provider_error = ""
        except (LayaClassifierError, ValueError, KeyError, TypeError) as exc:
            elapsed = time.perf_counter() - started
            laya_intent = "__laya_error__"
            score = 0.0
            threshold = 1.0
            abstained = True
            provider_error = type(exc).__name__
            laya_errors += 1
        try:
            baseline = classify_baseline(message)
            baseline_intent = str(baseline["candidate_intent"])
            baseline_score = float(baseline["top_class_probability"])
        except Exception:
            baseline_intent = "__baseline_error__"
            baseline_score = 0.0

        actual = row["expected_intent"]
        laya_predictions.append(laya_intent)
        baseline_predictions.append(baseline_intent)
        laya_scores.append(score)
        if laya_intent == actual and score >= threshold and not abstained:
            accepted += 1
            accepted_correct += 1
        elif score >= threshold and not abstained:
            accepted += 1
            high_confidence_errors += 1

        consensus = (
            laya_intent == baseline_intent
            and score >= threshold
            and baseline_score >= baseline_threshold
            and not abstained
            and not provider_error
        )
        consensus_predictions.append(laya_intent if consensus else "__review__")
        rows.append({
            **row,
            "laya_intent": laya_intent,
            "laya_top_probability": f"{score:.6f}",
            "laya_threshold": f"{threshold:.6f}",
            "laya_abstained": str(abstained).lower(),
            "laya_correct": str(laya_intent == actual).lower(),
            "laya_provider_error_type": provider_error,
            "baseline_intent": baseline_intent,
            "baseline_probability": f"{baseline_score:.6f}",
            "models_agree": str(laya_intent == baseline_intent).lower(),
            "consensus_routing_candidate": str(consensus).lower(),
            "latency_seconds": f"{elapsed:.4f}",
        })

    valid_laya = [value for value in laya_predictions if value != "__laya_error__"]
    summary = {
        "evaluation_set": str(INPUT.relative_to(ROOT)),
        "evaluation_grouping": "linked customer or normalized message-template groups",
        "case_count": len(cases),
        "label_count": len(labels),
        "labels": labels,
        "laya_successful_calls": len(valid_laya),
        "laya_errors": laya_errors,
        "laya_accuracy": float(accuracy_score(expected, laya_predictions)),
        "laya_macro_f1": float(f1_score(expected, laya_predictions, labels=labels, average="macro", zero_division=0)),
        "laya_classification_report": classification_report(
            expected, laya_predictions, labels=labels, output_dict=True, zero_division=0
        ),
        "mean_top_probability": sum(laya_scores) / len(laya_scores),
        "high_confidence_accepted_count": accepted,
        "high_confidence_accepted_accuracy": accepted_correct / accepted if accepted else None,
        "high_confidence_errors": high_confidence_errors,
        "strict_consensus_candidate_count": sum(value != "__review__" for value in consensus_predictions),
        "strict_consensus_accuracy": (
            sum(prediction == actual for prediction, actual in zip(consensus_predictions, expected)
                if prediction != "__review__")
            / sum(value != "__review__" for value in consensus_predictions)
            if any(value != "__review__" for value in consensus_predictions) else None
        ),
        "average_latency_seconds": sum(latencies) / len(latencies) if latencies else None,
        "intent_counts": dict(sorted(Counter(expected).items())),
        "confidence_calibrated": False,
        "automatic_routing_enabled": False,
        "interpretation": (
            "Small synthetic evaluation only. Laya probability is not calibrated; a high score is not proof of correctness. "
            "Consensus candidates must still be reviewed until a production-approved labeled set validates selective risk."
        ),
    }
    OUTPUT_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as stream:
        columns = list(rows[0])
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return summary


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2, ensure_ascii=False))
    print(f"Predictions: {OUTPUT_CSV.relative_to(ROOT)}")
