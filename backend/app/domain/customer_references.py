"""Customer references are lookup hints. The workflow authenticates their scope."""

import re


CUSTOMER_REFERENCE = re.compile(r"(?<![\w-])CUS-[0-9A-F]{10}(?![\w-])", re.IGNORECASE)


def customer_references(message: str) -> set[str]:
    return {match.upper() for match in CUSTOMER_REFERENCE.findall(message)}
