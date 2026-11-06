"""Check embedding loading resolves an existing local Hub snapshot."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import embeddings  # noqa: E402


class EmbeddingCacheResolutionTests(unittest.TestCase):
    def test_model_loader_passes_cached_snapshot_path_without_downloading(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            model_repo = cache / "models--test-org--test-model"
            snapshot = model_repo / "snapshots" / "abc123"
            snapshot.mkdir(parents=True)
            (model_repo / "refs").mkdir()
            (model_repo / "refs" / "main").write_text("abc123", encoding="utf-8")
            (snapshot / "config.json").write_text("{}", encoding="utf-8")
            (snapshot / "modules.json").write_text("[]", encoding="utf-8")

            embeddings.load_embedding_model.cache_clear()
            try:
                with patch.object(embeddings.constants, "HF_HUB_CACHE", str(cache)):
                    with patch.object(embeddings, "SentenceTransformer") as constructor:
                        with patch.object(embeddings, "snapshot_download") as download:
                            result = embeddings.load_embedding_model("test-org/test-model")

            finally:
                embeddings.load_embedding_model.cache_clear()

        self.assertIs(result, constructor.return_value)
        constructor.assert_called_once_with(
            str(snapshot), local_files_only=True, trust_remote_code=False
        )
        download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
