from sentence_transformers import SentenceTransformer
import numpy as np

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_encoder = SentenceTransformer(MODEL_NAME)

def embed_texts(texts: list[str]):
    """Return normalized embeddings (numpy array) for a list of texts."""
    vecs = _encoder.encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False)
    return np.array(vecs, dtype=np.float32)

