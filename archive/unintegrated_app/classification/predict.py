import joblib
import xgboost as xgb
from pathlib import Path
from .preprocess import vectorise

MODEL_DIR = Path(__file__).resolve().parents[3] / "models" / "classifier"

# Load once at import time
_vectoriser = joblib.load(MODEL_DIR / "tfidf.joblib")
bst = xgb.Booster()
bst.load_model(str(MODEL_DIR / "xgb_classifier.json"))
label_map = joblib.load(MODEL_DIR / "label_map.joblib")

def predict_label(text: str) -> str:
    """Predict intent label for a ticket description."""
    X = _vectoriser.transform([text])
    dmatrix = xgb.DMatrix(X)
    probs = bst.predict(dmatrix)[0]
    idx = int(probs.argmax())
    return label_map[idx]

