# Known Evaluation Limits

The last recorded live Laya evaluation was 40 labeled cases: 18 correct (45%) and macro-F1 0.418. Several wrong predictions came back with very high confidence, so the returned confidence must not be treated as reliability. Classification now compares Laya with a grouped-split TF-IDF baseline, flags disagreement, and keeps automatic routing disabled by default. Rerun `scripts/evaluate_laya_classifier.py` against the refreshed 46-case grouped holdout to update Laya metrics.

The earlier retrieval benchmark covered 11 labeled questions. It scored 8/11 expected documents at rank 1 for both semantic and keyword methods, and 11/11 within the top three. A twelfth loyalty-policy question has since been added. The new policy is not yet in Milvus, so refresh the development index and rerun retrieval evaluation before reporting updated scores.

The development data now includes a synthetic loyalty ledger and prior-contact summaries, but the Neon migration and seed have not been applied. Until the three context tables exist in a development branch, the customer-context endpoint will return a dependency-unavailable response. No remote database or Milvus collection was written during these code changes.




The local fixture is refreshed in data/synthetic/ and the new grouped-split TF-IDF baseline scores 91.3% accuracy / 0.894 macro-F1 on its 46-case synthetic holdout. I’m also checking the Streamlit evidence views against the project’s required Streamlit guidance before finalizing the UI notes.