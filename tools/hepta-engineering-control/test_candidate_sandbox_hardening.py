from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from control_engineering_v2 import CandidateEnvelope, EngineeringError, Mutation
from control_engineering_v2.candidate import generate_candidates, sandbox_candidate


class CandidateSandboxFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="lane-g-candidate-test-")
        self.root = Path(self.temporary.name) / "source"
        self.root.mkdir()
        self._git("init", "-q")
        # The production verifier deliberately ignores ambient/global Git config.
        # Freeze the fixture's checkout normalization locally as well so a Windows
        # runner cannot commit CRLF under core.autocrlf=true and then have the same
        # clean tree reinterpreted as modified by the hermetic verifier.
        self._git("config", "core.autocrlf", "false")
        self._git("config", "user.name", "Lane G Test")
        self._git("config", "user.email", "lane-g@example.invalid")
        source = self.root / "tools/hepta-engineering-control"
        source.mkdir(parents=True)
        (source / "base file.txt").write_text("base\n", encoding="utf-8")
        (source / "archive-hidden.txt").write_text("must remain\n", encoding="utf-8")
        (self.root / ".gitignore").write_text("*.ignored\n", encoding="utf-8")
        (self.root / ".gitattributes").write_text(
            "tools/hepta-engineering-control/archive-hidden.txt export-ignore\n",
            encoding="utf-8",
        )
        self._git("add", ".")
        self._git("commit", "-q", "-m", "fixture")
        self.base_commit = self._git("rev-parse", "HEAD").stdout.strip()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=check,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def envelope(self, *, strong: bool = False) -> CandidateEnvelope:
        return CandidateEnvelope(
            envelope_id="candidate-sandbox-regression",
            base_commit=self.base_commit,
            allowed_paths=("tools/hepta-engineering-control",),
            require_network_isolation=strong,
            wall_time_seconds=30,
            memory_bytes=512 * 1024 * 1024,
            processes=128,
        )

    @staticmethod
    def success_check(source: str = "print('ok')") -> tuple[str, ...]:
        return (sys.executable, "-I", "-c", source)

    def test_empty_check_set_is_rejected(self) -> None:
        envelope = self.envelope()
        candidate = generate_candidates(envelope, ())[0]
        with self.assertRaisesRegex(EngineeringError, "invalid_check"):
            sandbox_candidate(self.root, envelope, candidate, ())

    def test_exact_blob_materialization_does_not_honor_export_ignore(self) -> None:
        envelope = self.envelope()
        candidate = generate_candidates(envelope, ())[0]
        tested, receipt = sandbox_candidate(
            self.root,
            envelope,
            candidate,
            (
                self.success_check(
                    "from pathlib import Path; "
                    "assert Path('tools/hepta-engineering-control/archive-hidden.txt').read_text() == 'must remain\\n'"
                ),
            ),
        )
        self.assertEqual(tested.state, "fixture_tested")
        self.assertTrue(receipt.passed)
        self.assertFalse(receipt.filesystem_isolated)
        self.assertFalse(receipt.network_isolated)

    def test_replace_and_delete_are_path_exact_without_porcelain_parsing(self) -> None:
        path = "tools/hepta-engineering-control/base file.txt"
        replace_envelope = self.envelope()
        replace = generate_candidates(
            replace_envelope,
            (Mutation("replace_text", path, "base\n", "next\n"),),
        )[1]
        replaced, receipt = sandbox_candidate(
            self.root,
            replace_envelope,
            replace,
            (
                self.success_check(
                    "from pathlib import Path; "
                    "assert Path('tools/hepta-engineering-control/base file.txt').read_text() == 'next\\n'"
                ),
            ),
        )
        self.assertEqual(replaced.state, "fixture_tested")
        self.assertEqual(replaced.changed_paths, (path,))
        self.assertTrue(receipt.passed)

        delete_envelope = self.envelope()
        delete = generate_candidates(
            delete_envelope,
            (
                Mutation(
                    "delete_file",
                    path,
                    hashlib.sha256(b"base\n").hexdigest(),
                    "",
                ),
            ),
        )[1]
        deleted, delete_receipt = sandbox_candidate(
            self.root,
            delete_envelope,
            delete,
            (
                self.success_check(
                    "from pathlib import Path; "
                    "assert not Path('tools/hepta-engineering-control/base file.txt').exists()"
                ),
            ),
        )
        self.assertEqual(deleted.state, "fixture_tested")
        self.assertEqual(deleted.changed_paths, (path,))
        self.assertTrue(delete_receipt.passed)

    def test_hostile_but_canonical_filename_is_not_truncated(self) -> None:
        # Use characters legal on POSIX and Win32 while retaining spaces and
        # punctuation that would expose unsafe shell or porcelain parsing.
        path = "tools/hepta-engineering-control/name - safe (01).txt"
        envelope = self.envelope()
        candidate = generate_candidates(
            envelope,
            (Mutation("add_file", path, "", "safe\n"),),
        )[1]
        tested, receipt = sandbox_candidate(
            self.root,
            envelope,
            candidate,
            (
                self.success_check(
                    "from pathlib import Path; "
                    "assert Path('tools/hepta-engineering-control/name - safe (01).txt').read_text() == 'safe\\n'"
                ),
            ),
        )
        self.assertEqual(tested.changed_paths, (path,))
        self.assertEqual(tested.state, "fixture_tested")
        self.assertTrue(receipt.passed)

    def test_post_admission_protected_write_is_detected(self) -> None:
        envelope = self.envelope()
        candidate = generate_candidates(envelope, ())[0]
        check = self.success_check(
            "from pathlib import Path; "
            "p=Path('.github/workflows/late.yml'); "
            "p.parent.mkdir(parents=True, exist_ok=True); "
            "p.write_text('name: late\\n')"
        )
        with self.assertRaisesRegex(EngineeringError, "source_tree_mutated"):
            sandbox_candidate(self.root, envelope, candidate, (check,))

    def test_fixture_detects_caller_checkout_tracked_write(self) -> None:
        envelope = self.envelope()
        candidate = generate_candidates(envelope, ())[0]
        target = self.root / "tools/hepta-engineering-control/base file.txt"
        check = self.success_check(
            "from pathlib import Path; "
            f"Path({str(target)!r}).write_text('mutated\\n', encoding='utf-8')"
        )
        try:
            with self.assertRaisesRegex(EngineeringError, "source_tree_mutated"):
                sandbox_candidate(self.root, envelope, candidate, (check,))
        finally:
            self._git("checkout", "--", "tools/hepta-engineering-control/base file.txt")
        self.assertEqual(self._git("status", "--porcelain").stdout, "")

    def test_fixture_detects_caller_checkout_ignored_write(self) -> None:
        envelope = self.envelope()
        candidate = generate_candidates(envelope, ())[0]
        target = self.root / "outside.ignored"
        check = self.success_check(
            "from pathlib import Path; "
            f"Path({str(target)!r}).write_text('ignored\\n', encoding='utf-8')"
        )
        try:
            with self.assertRaisesRegex(EngineeringError, "source_tree_mutated"):
                sandbox_candidate(self.root, envelope, candidate, (check,))
        finally:
            target.unlink(missing_ok=True)
        self.assertEqual(self._git("status", "--porcelain").stdout, "")

    def test_forged_candidate_identity_is_rejected(self) -> None:
        envelope = self.envelope()
        candidate = generate_candidates(envelope, ())[0]
        forged = candidate.__class__(
            "forged",
            candidate.envelope_id,
            candidate.base_commit,
            candidate.mutation,
            candidate.semantic_digest,
            candidate.state,
            candidate.changed_paths,
            None,
        )
        with self.assertRaisesRegex(EngineeringError, "candidate_envelope_mismatch"):
            sandbox_candidate(
                self.root,
                envelope,
                forged,
                (self.success_check(),),
            )


@unittest.skipUnless(
    sys.platform.startswith("linux")
    and shutil.which("bwrap") is not None
    and Path("/usr/bin/python3").is_file(),
    "strong sandbox qualification requires Linux Bubblewrap and system Python",
)
class CandidateSandboxStrongIsolation(unittest.TestCase):
    _git = CandidateSandboxFixture._git
    envelope = CandidateSandboxFixture.envelope
    tearDown = CandidateSandboxFixture.tearDown

    def setUp(self) -> None:
        CandidateSandboxFixture.setUp(self)
        from control_engineering_v2.candidate import _admit_bubblewrap
        workspace = Path(self.temporary.name) / "probe"
        workspace.mkdir()
        try:
            _admit_bubblewrap(workspace, self.envelope(strong=True))
        except EngineeringError:
            if os.environ.get("HEPTA_REQUIRE_STRONG_SANDBOX") == "1":
                raise
            self.skipTest("host cannot admit Bubblewrap isolation; strict CI sets HEPTA_REQUIRE_STRONG_SANDBOX=1")

    @staticmethod
    def success_check(source: str = "print('ok')") -> tuple[str, ...]:
        return ("/usr/bin/python3", "-I", "-c", source)

    def test_strong_boundary_hides_source_git_and_rejects_workspace_writes(self) -> None:
        envelope = self.envelope(strong=True)
        candidate = generate_candidates(envelope, ())[0]
        source_root = str(self.root)
        check = self.success_check(
            "from pathlib import Path; "
            "assert not Path('.git').exists(); "
            f"assert not Path({source_root!r}).exists(); "
            "assert not Path('/home/runner/work').exists(); "
            "p=Path('.github/workflows/late.yml'); failed=False\n"
            "try:\n p.parent.mkdir(parents=True, exist_ok=True); p.write_text('late')\n"
            "except OSError:\n failed=True\n"
            "assert failed"
        )
        tested, receipt = sandbox_candidate(self.root, envelope, candidate, (check,))
        self.assertEqual(tested.state, "sandbox_tested")
        self.assertTrue(receipt.passed)
        self.assertTrue(receipt.filesystem_isolated)
        self.assertTrue(receipt.network_isolated)
        self.assertEqual(
            receipt.isolation_adapter,
            "bubblewrap-unshare-all-ro-workspace-v2",
        )
        self.assertEqual(
            receipt.candidate_state_digest_before,
            receipt.candidate_state_digest_after,
        )
        self.assertRegex(receipt.check_set_digest, r"^[0-9a-f]{64}$")
        self.assertEqual(self._git("status", "--porcelain").stdout, "")

    def test_nonzero_check_cannot_receive_sandbox_tested(self) -> None:
        envelope = self.envelope(strong=True)
        candidate = generate_candidates(envelope, ())[0]
        tested, receipt = sandbox_candidate(
            self.root,
            envelope,
            candidate,
            (("/usr/bin/python3", "-I", "-c", "raise SystemExit(9)"),),
        )
        self.assertEqual(tested.state, "rejected")
        self.assertFalse(receipt.passed)
        self.assertTrue(receipt.filesystem_isolated)
        self.assertTrue(receipt.network_isolated)


if __name__ == "__main__":
    unittest.main()
