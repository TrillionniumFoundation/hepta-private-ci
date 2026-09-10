from __future__ import annotations

import hashlib
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
        self._git("config", "user.name", "Lane G Test")
        self._git("config", "user.email", "lane-g@example.invalid")
        source = self.root / "tools/hepta-engineering-control"
        source.mkdir(parents=True)
        (source / "base file.txt").write_text("base\n", encoding="utf-8")
        (self.root / ".gitignore").write_text("*.ignored\n", encoding="utf-8")
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
            processes=32,
        )

    @staticmethod
    def success_check(source: str = "print('ok')") -> tuple[str, ...]:
        return (sys.executable, "-I", "-c", source)

    def test_empty_check_set_is_rejected(self) -> None:
        envelope = self.envelope()
        candidate = generate_candidates(envelope, ())[0]
        with self.assertRaisesRegex(EngineeringError, "invalid_check"):
            sandbox_candidate(self.root, envelope, candidate, ())

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
            (self.success_check("from pathlib import Path; assert Path('tools/hepta-engineering-control/base file.txt').read_text() == 'next\\n'"),),
        )
        self.assertEqual(replaced.state, "fixture_tested")
        self.assertEqual(replaced.changed_paths, (path,))
        self.assertTrue(receipt.passed)
        self.assertFalse(receipt.filesystem_isolated)

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
            (self.success_check("from pathlib import Path; assert not Path('tools/hepta-engineering-control/base file.txt').exists()"),),
        )
        self.assertEqual(deleted.state, "fixture_tested")
        self.assertEqual(deleted.changed_paths, (path,))
        self.assertTrue(delete_receipt.passed)

    def test_hostile_but_canonical_filename_is_not_truncated(self) -> None:
        path = "tools/hepta-engineering-control/name -> safe.txt"
        envelope = self.envelope()
        candidate = generate_candidates(
            envelope,
            (Mutation("add_file", path, "", "safe\n"),),
        )[1]
        tested, receipt = sandbox_candidate(
            self.root,
            envelope,
            candidate,
            (self.success_check("from pathlib import Path; assert Path('tools/hepta-engineering-control/name -> safe.txt').read_text() == 'safe\\n'"),),
        )
        self.assertEqual(tested.changed_paths, (path,))
        self.assertEqual(tested.state, "fixture_tested")
        self.assertTrue(receipt.passed)

    def test_post_admission_protected_write_is_detected(self) -> None:
        envelope = self.envelope()
        candidate = generate_candidates(envelope, ())[0]
        check = self.success_check(
            "from pathlib import Path; p=Path('.github/workflows/late.yml'); "
            "p.parent.mkdir(parents=True, exist_ok=True); p.write_text('name: late\\n')"
        )
        with self.assertRaisesRegex(EngineeringError, "source_tree_mutated"):
            sandbox_candidate(self.root, envelope, candidate, (check,))

    def test_fixture_detects_caller_checkout_write_and_grants_no_sandbox_state(self) -> None:
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


@unittest.skipUnless(
    sys.platform.startswith("linux") and shutil.which("bwrap") is not None,
    "strong sandbox qualification requires Linux bubblewrap",
)
class CandidateSandboxStrongIsolation(CandidateSandboxFixture):
    def test_strong_boundary_hides_source_git_and_rejects_workspace_writes(self) -> None:
        envelope = self.envelope(strong=True)
        candidate = generate_candidates(envelope, ())[0]
        source_root = str(self.root)
        check = self.success_check(
            "from pathlib import Path; "
            "assert not Path('.git').exists(); "
            f"assert not Path({source_root!r}).exists(); "
            "p=Path('.github/workflows/late.yml'); failed=False; "
            "\ntry:\n p.parent.mkdir(parents=True, exist_ok=True); p.write_text('late')\n"
            "except OSError:\n failed=True\n"
            "assert failed"
        )
        tested, receipt = sandbox_candidate(self.root, envelope, candidate, (check,))
        self.assertEqual(tested.state, "sandbox_tested")
        self.assertTrue(receipt.passed)
        self.assertTrue(receipt.filesystem_isolated)
        self.assertTrue(receipt.network_isolated)
        self.assertEqual(receipt.isolation_adapter, "bubblewrap-unshare-all-ro-workspace-v1")
        self.assertEqual(receipt.candidate_state_digest_before, receipt.candidate_state_digest_after)
        self.assertRegex(receipt.check_set_digest, r"^[0-9a-f]{64}$")
        self.assertEqual(self._git("status", "--porcelain").stdout, "")

    def test_nonzero_check_cannot_receive_sandbox_tested(self) -> None:
        envelope = self.envelope(strong=True)
        candidate = generate_candidates(envelope, ())[0]
        tested, receipt = sandbox_candidate(
            self.root,
            envelope,
            candidate,
            ((sys.executable, "-I", "-c", "raise SystemExit(9)"),),
        )
        self.assertEqual(tested.state, "rejected")
        self.assertFalse(receipt.passed)
        self.assertTrue(receipt.filesystem_isolated)
        self.assertTrue(receipt.network_isolated)


if __name__ == "__main__":
    unittest.main()
