"""Audit every locked platform/version variant in an isolated pip-audit venv."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.check_dependency_sources import check_lockfile


def audit_groups(paths: list[Path]) -> list[list[str]]:
    versions: dict[str, set[str]] = defaultdict(set)
    for path in paths:
        if check_lockfile(path):
            raise ValueError("Refusing to audit an unapproved or malformed dependency lock")
        for line in path.read_text().splitlines():
            match = re.match(r"^([A-Za-z0-9_.-]+)(?:\[[A-Za-z0-9_,.-]+\])?==([A-Za-z0-9.+!-]+)", line.strip())
            if match:
                name = re.sub(r"[-_.]+", "-", match[1]).lower()
                versions[name].add(name + "==" + match[2])
    groups: list[list[str]] = [[] for _ in range(max(map(len, versions.values()), default=0))]
    for name in sorted(versions):
        for index, pin in enumerate(sorted(versions[name])):
            groups[index].append(pin)
    return groups


def main() -> int:
    groups = audit_groups([ROOT / "requirements.lock", ROOT / "requirements-security.lock"])
    if not groups:
        raise ValueError("No locked packages were found to audit")
    failed = False
    with tempfile.TemporaryDirectory(prefix="agent-dependency-audit-") as directory:
        for index, group in enumerate(groups):
            path = Path(directory) / f"pins-{index}.txt"
            path.write_text("\n".join(group) + "\n")
            print(f"Auditing {len(group)} pins in group {index + 1}; all platform markers included", flush=True)
            result = subprocess.run([sys.executable, "-m", "pip_audit", "--requirement", str(path),
                                     "--no-deps", "--disable-pip", "--progress-spinner", "off"], check=False)
            failed |= result.returncode != 0
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
