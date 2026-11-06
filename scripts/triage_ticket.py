"""Run the review-only classifier baseline on a message or fixture ticket ID."""

import argparse
import csv
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.intent_classifier import classify_ticket  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--message", help="Ticket text to classify")
    choice.add_argument("--ticket-id", help="Ticket ID from data/raw/tickets.csv")
    args = parser.parse_args()
    message = args.message
    if args.ticket_id:
        tickets_path = PROJECT_ROOT / "data" / "raw" / "tickets.csv"
        with tickets_path.open(newline="", encoding="utf-8-sig") as stream:
            tickets = {row["ticket_id"]: row["message"] for row in csv.DictReader(stream)}
        if args.ticket_id not in tickets:
            parser.error(f"Ticket ID not found in the local fictional fixture: {args.ticket_id}")
        message = tickets[args.ticket_id]
    print(json.dumps(classify_ticket(message), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
