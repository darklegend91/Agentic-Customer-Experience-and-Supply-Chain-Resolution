"""Quality checks for the prepared Day 2 data artifacts."""

import csv
import hashlib
import json
import re
import unittest
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW = PROJECT_ROOT / "data" / "raw"
PROCESSED = PROJECT_ROOT / "data" / "processed"
SYNTHETIC = PROJECT_ROOT / "data" / "synthetic"


def read_rows(path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


class Day2PreparationTests(unittest.TestCase):
    def test_manifest_tracks_current_sources_and_output_counts(self):
        manifest = json.loads((PROCESSED / "data_quality_manifest.json").read_text(encoding="utf-8"))
        for filename, expected_hash in manifest["source_files_sha256"].items():
            digest = hashlib.sha256((RAW / filename).read_bytes()).hexdigest()
            self.assertEqual(digest, expected_hash, filename)
        for name, count in manifest["output_row_counts"].items():
            path = SYNTHETIC / "ticket_order_mapping.csv" if name == "ticket_order_mapping" else PROCESSED / f"{name}.csv"
            self.assertEqual(len(read_rows(path)), count, name)

    def test_classifier_holdout_is_disjoint_and_balanced(self):
        training = read_rows(PROCESSED / "classifier_train.csv")
        evaluation = read_rows(PROCESSED / "intent_evaluation.csv")
        training_ids = {row["ticket_id"] for row in training}
        evaluation_ids = {row["ticket_id"] for row in evaluation}
        self.assertFalse(training_ids & evaluation_ids)
        self.assertEqual(len(evaluation), 40)
        self.assertEqual(set(Counter(row["expected_intent"] for row in evaluation).values()), {2})

    def test_ticket_order_map_keeps_missing_references_unmapped(self):
        source = {row["ticket_id"]: row["order_id"] for row in read_rows(RAW / "tickets.csv")}
        mappings = read_rows(SYNTHETIC / "ticket_order_mapping.csv")
        self.assertEqual(len(mappings), len(source))
        self.assertEqual({row["ticket_id"] for row in mappings}, set(source))
        for row in mappings:
            expected_order = source[row["ticket_id"]]
            self.assertEqual(row["order_id"], expected_order)
            expected_status = "mapped" if expected_order else "unmapped_missing_order_reference"
            self.assertEqual(row["mapping_status"], expected_status)

    def test_clean_outputs_omit_contact_fields_and_email_addresses(self):
        outputs = list(PROCESSED.glob("*.csv")) + [SYNTHETIC / "ticket_order_mapping.csv"]
        for path in outputs:
            rows = read_rows(path)
            if rows:
                self.assertFalse({"email", "full_name"} & set(rows[0]), path.name)
            self.assertIsNone(re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", path.read_text(encoding="utf-8-sig"), re.I), path.name)

    def test_demo_knowledge_documents_are_versioned_and_development_only(self):
        knowledge_base = PROJECT_ROOT / "knowledge_base"
        documents = (
            list((knowledge_base / "policies").glob("*/*.md"))
            + list((knowledge_base / "faqs").glob("*/*.md"))
            + list((knowledge_base / "escalation_rules").glob("*/*.yaml"))
        )
        self.assertEqual(len(documents), 5)
        for path in documents:
            content = path.read_text(encoding="utf-8")
            self.assertIn("version: 1.0.0", content, path.name)
            self.assertIn("status: draft", content, path.name)
            self.assertIn("environment_scope: development-only", content, path.name)
            self.assertIn("synthetic_demo: true", content, path.name)


if __name__ == "__main__":
    unittest.main()
