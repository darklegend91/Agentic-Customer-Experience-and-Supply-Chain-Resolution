"""Train and score the TF-IDF intent-classification baseline."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.intent_classifier import train_and_evaluate  # noqa: E402


if __name__ == "__main__":
    train_and_evaluate()
