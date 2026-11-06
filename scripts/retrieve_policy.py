"""Search the development-only policy corpus with semantic, keyword, or both baselines."""

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.policy_retrieval import (  # noqa: E402
    KeywordPolicyRetriever,
    MilvusPolicyRetriever,
    format_evidence,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Question to search")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--mode", choices=("semantic", "keyword", "both"), default="both")
    args = parser.parse_args()
    results = {}
    if args.mode in ("keyword", "both"):
        results["keyword"] = KeywordPolicyRetriever().search(args.query, top_k=args.top_k)
    if args.mode in ("semantic", "both"):
        retriever = MilvusPolicyRetriever()
        try:
            results["semantic"] = retriever.search(args.query, top_k=args.top_k)
        finally:
            retriever.close()
    for name, hits in results.items():
        print(f"## {name} retrieval")
        print(format_evidence(hits))
        print()


if __name__ == "__main__":
    main()
