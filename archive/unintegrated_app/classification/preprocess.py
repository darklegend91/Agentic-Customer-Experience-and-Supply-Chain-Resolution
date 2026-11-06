import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import TfidfVectorizer
import joblib
from pathlib import Path

# Paths relative to the repository root
DATA_PATH = Path(__file__).resolve().parents[3] / "data" / "raw" / "tickets.csv"
MODEL_DIR = Path(__file__).resolve().parents[3] / "models" / "classifier"

def load_and_split(test_size: float = 0.2, random_state: int = 42):
    """Load tickets CSV and split into train/validation sets.
    Assumes columns `description` (text) and `category` (label). Adjust if needed.
    """
    df = pd.read_csv(DATA_PATH)
    X, y = df["description"].astype(str), df["category"]
    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=test_size, stratify=y, random_state=random_state
    )
    return X_train, X_val, y_train, y_val

def vectorise(
    X_train: pd.Series, X_val: pd.Series, max_features: int = 10_000
) -> tuple:
    """Fit a TF‑IDF vectoriser on the training data and transform both splits.
    The fitted vectoriser is persisted for inference.
    """
    vec = TfidfVectorizer(
        max_features=max_features, ngram_range=(1, 2), stop_words="english"
    )
    X_tr = vec.fit_transform(X_train)
    X_va = vec.transform(X_val)

    # Persist the vectoriser
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(vec, MODEL_DIR / "tfidf.joblib")
    return X_tr, X_va, vec

