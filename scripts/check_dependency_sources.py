"""Reject unreviewed direct dependencies and unsafe pip manifest directives.

This validates source configuration, not the behavior or integrity of a package.
Use a clean environment, hash-locked installs and an advisory audit as well.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

APPROVED_PACKAGES = frozenset({
    "scikit-learn", "joblib", "pyyaml", "sentence-transformers", "pymilvus",
    "python-dotenv", "fastapi", "uvicorn", "httpx", "psycopg2-binary", "langgraph",
    "langgraph-checkpoint-postgres", "psycopg", "pyjwt", "mcp", "langfuse", "laya", "pip-audit",
})
_REQUIREMENT = re.compile(r"([A-Za-z0-9_.-]+)(?:\[[A-Za-z0-9_,.-]+\])?((?:(?:~=|==|!=|<=|>=|<|>)[A-Za-z0-9.*+!-]+)(?:,(?:~=|==|!=|<=|>=|<|>)[A-Za-z0-9.*+!-]+)*)")
_PIN = re.compile(r"[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9.+!-]+(?:\s*;\s*[^\\]+)?")
_HASH = re.compile(r"--hash=sha256:[0-9a-f]{64}")
APPROVED_RESOLVED_PACKAGES = frozenset(json.loads(
    (Path(__file__).resolve().parents[1] / ".security/dependency_allowlist.json").read_text()
)["approved_resolved_packages"])


def check_manifest(path: Path, root: Path, _stack: frozenset[Path] = frozenset()) -> list[str]:
    path, root = path.resolve(), root.resolve()
    if not path.is_relative_to(root) or path in _stack or not path.is_file():
        return ["Missing, recursive or out-of-project requirement include"]
    errors = []
    for number, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-r "):
            errors.extend(check_manifest(path.parent / line[3:].strip(), root, _stack | {path}))
            continue
        match = _REQUIREMENT.fullmatch(line)
        valid = bool(match)
        if match:
            name = re.sub(r"[-_.]+", "-", match[1]).lower()
            spec = match[2]
            valid = name in APPROVED_PACKAGES and "*" not in spec and bool(
                re.search(r"(?:^|,)(?:==|~=|<|<=)", spec))
        if not valid:
            errors.append(f"{path.relative_to(root)}:{number}: unapproved dependency, source or version range")
    return errors


def check_lockfile(path: Path, *, require_hashes: bool = True) -> list[str]:
    if not path.is_file():
        return ["Missing hash lockfile"]
    logical, buffer = [], ""
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        continued = line.endswith("\\")
        buffer += " " + line.removesuffix("\\").strip()
        if not continued:
            logical.append(buffer.strip())
            buffer = ""
    if buffer or not logical:
        return ["Empty or incomplete hash lockfile"]
    errors = []
    for number, line in enumerate(logical, 1):
        start = line.find(" --hash=")
        hashes = line[start + 1:].split() if start >= 0 else []
        requirement = line[:start] if start >= 0 else line
        valid = bool(_PIN.fullmatch(requirement)) and not any(
            token in requirement for token in ("--", "://", "@", "git+"))
        name = re.sub(r"[-_.]+", "-", requirement.split("==", 1)[0].split("[", 1)[0]).lower()
        valid = valid and name in APPROVED_RESOLVED_PACKAGES
        if require_hashes:
            valid = valid and bool(hashes) and all(_HASH.fullmatch(token) for token in hashes)
        elif hashes:
            valid = False
        if not valid:
            errors.append(f"{path.name}:entry {number}: exact package pin and SHA256 hashes required")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    errors = []
    for manifest in ("requirements.txt", "backend/requirements.txt", "requirements-security.in"):
        errors.extend(check_manifest(args.root / manifest, args.root))
    for lock in ("requirements.lock", "requirements-security.lock"):
        errors.extend(check_lockfile(args.root / lock))
    errors.extend(check_lockfile(args.root / "requirements.constraints.txt", require_hashes=False))
    for error in errors:
        print(error)
    if not errors:
        print("Dependency source allowlist and hash lockfiles passed")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
