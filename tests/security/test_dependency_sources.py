"""Run manifest checks against controlled files; never resolve/install packages."""

import tempfile
import unittest
import io
from contextlib import redirect_stdout
from unittest.mock import Mock, patch
from urllib.error import URLError
from pathlib import Path

from scripts.check_dependency_sources import check_lockfile, check_manifest


class DependencySourceTests(unittest.TestCase):
    def test_known_bounded_packages_and_in_repo_include_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "runtime.txt").write_text("fastapi>=0.115,<1\nPyJWT[crypto]>=2.15,<2.16\n")
            (root / "requirements.txt").write_text("-r runtime.txt\n")
            self.assertEqual(check_manifest(root / "requirements.txt", root), [])

    def test_unapproved_packages_sources_and_unbounded_versions_are_rejected(self):
        for requirement in ("evil-helper==1.0", "fastapi @ https://attacker.invalid/x.whl", "git+https://attacker.invalid/repo",
                            "--extra-index-url https://attacker.invalid/simple", "--trusted-host attacker.invalid", "fastapi>=0.115",
                            "-e .", "fastapi==1.*", "--index-url https://pypi.org/simple"):
            with self.subTest(requirement=requirement), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / "requirements.txt"
                path.write_text(requirement + "\n")
                self.assertTrue(check_manifest(path, root))

    def test_include_cannot_escape_root_or_cycle(self):
        for include in ("../outside.txt", "requirements.txt"):
            with self.subTest(include=include), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / "requirements.txt"
                path.write_text("-r " + include + "\n")
                self.assertTrue(check_manifest(path, root))

    def test_every_lock_entry_needs_exact_pin_and_sha256(self):
        for value, rejected in (("fastapi==0.162.0 --hash=sha256:" + "a" * 64, False),
                                ("fastapi>=0.115 --hash=sha256:" + "a" * 64, True),
                                ("fastapi==0.162.0", True),
                                ("fastapi==0.162.0 --hash=sha256:abc", True),
                                ("evil-helper==1.0 --hash=sha256:" + "a" * 64, True),
                                ("fastapi==0.162.0 ; python_version > '3.0' --extra-index-url https://attacker.invalid --hash=sha256:" + "a" * 64, True),
                                ("--extra-index-url https://attacker.invalid/simple", True)):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "requirements.lock"
                path.write_text(value + "\n")
                self.assertEqual(bool(check_lockfile(path)), rejected)

    def test_constraint_source_and_marker_are_validated(self):
        for value, rejected in (("numpy==2.5.4 ; python_version >= '3.12'", False),
                                ("numpy @ https://attacker.invalid/numpy.whl", True),
                                ("numpy==2.5.4 ; python_version >= '3.12' --index-url https://attacker.invalid", True)):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "requirements.constraints.txt"
                path.write_text(value + "\n")
                self.assertEqual(bool(check_lockfile(path, require_hashes=False)), rejected)

    def test_audit_includes_indented_extra_and_all_marker_versions(self):
        from scripts.audit_dependency_locks import audit_groups
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.lock"
            path.write_text("  fastapi[standard]==0.162.0 ; python_version >= '3.14' --hash=sha256:" + "a" * 64 + "\n"
                            "fastapi==0.163.2 ; python_version < '3.14' --hash=sha256:" + "b" * 64 + "\n")
            self.assertEqual(audit_groups([path]), [["fastapi==0.162.0"], ["fastapi==0.163.2"]])

    def test_prompt_report_records_unavailable_api_without_aborting(self):
        from scripts.test_prompt_injection import run
        opener = Mock()
        opener.open.side_effect = URLError("synthetic unavailable server")
        with patch("scripts.test_prompt_injection.build_opener", return_value=opener), redirect_stdout(io.StringIO()):
            rows = run("http://127.0.0.1:18001")
        self.assertEqual(len(rows), 30)
        self.assertTrue(all(not row["passed"] and row["http_status"] == 0 for row in rows))
