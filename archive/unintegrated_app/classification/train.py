import xgboost as xgb
import joblib
from pathlib import Path
from .preprocess import load_and_split, vectorise

MODEL_DIR = Path(__file__).resolve().parents[3] / "models" / "classifier"

def train():
    X_train, X_val, y_train, y_val = load_and_split()
    X_tr, X_va, vec = vectorise(X_train, X_val)
    dtrain = xgb.DMatrix(X_tr, label=y_train)
    dval = xgb.DMatrix(X_va, label=y_val)

    params = {
        "objective": "multi:softprob",
        "num_class": len(y_train.unique()),
        "eval_metric": "mlogloss",
        "learning_rate": 0.1,
        "max_depth": 6,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
    }

    bst = xgb.train(
        params,
        dtrain,
        num_boost_round=200,
        evals=[(dval, "validation")],
        early_stopping_rounds=20,
        verbose_eval=False,
    )
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    bst.save_model(str(MODEL_DIR / "xgb_classifier.json"))
    # Save label map for inference
    label_map = {i: lbl for i, lbl in enumerate(sorted(y_train.unique()))}
    joblib.dump(label_map, MODEL_DIR / "label_map.joblib")
    print("✅ Model and label map saved.")
    return bst

if __name__ == "__main__":
    train()

