"""Regression checks for Matrix CI startup and non-waivable security gates.

These source checks guard the GitHub Actions expression contexts after an
invalid job-level `runner.temp` reference caused no-job workflow failures.
They do not substitute for actually running Actions or cargo-deny.
"""

from pathlib import Path
import re
import unittest


WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github/workflows/hepta-matrix-security-qualification.yml"
)


class WorkflowContextContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text(encoding="utf-8")
        cls.lines = cls.source.splitlines()

    def test_job_environment_uses_only_available_expression_contexts(self):
        job_env_sections = 0
        for index, line in enumerate(self.lines):
            if line != "    env:":
                continue
            job_env_sections += 1
            for field in self.lines[index + 1 :]:
                if field.strip() and not field.startswith("      "):
                    break
                if field.lstrip().startswith("#"):
                    continue
                # The runner context is unavailable in jobs.<job_id>.env:
                # GitHub rejects the entire workflow before creating jobs.
                self.assertNotIn("${{ runner.", field)
        self.assertGreater(job_env_sections, 0)

    def test_disposable_stage_is_unique_and_outside_repository(self):
        matching = [
            line.strip()
            for line in self.lines
            if re.match(r"^      STAGE: ", line)
        ]
        self.assertEqual(len(matching), 1)
        stage = matching[0]
        self.assertIn("${{ github.workspace }}/../hepta-matrix-stage-", stage)
        self.assertIn("${{ github.run_id }}", stage)
        self.assertIn("${{ matrix.sqlite_arm }}", stage)
        self.assertNotIn("runner.temp", stage)
        self.assertIn('git worktree add --detach "$STAGE" "$SOURCE_SHA"', self.source)
        self.assertIn('git worktree remove --force "$STAGE"', self.source)

    def test_crypto_gate_remains_non_waivable_and_independently_blocking(self):
        start = self.source.index("  no-waiver-crypto-migration:")
        end = self.source.index("  pinned-upstream-source-probe:", start)
        gate = self.source[start:end]
        self.assertIn("matrix_dependency_gate.py --root . --require-safe", gate)
        self.assertNotIn("continue-on-error: true", gate)
        self.assertIn("name: Non-waivable dependency security gate", gate)
        self.assertIn("matrix-sdk-sqlite-*/**", self.source)

    def test_integrated_secure_cargo_metadata_remains_locked_and_non_authorizing(self):
        source = self.source
        self.assertIn('sqlite_arm: [audit_integrated_secure_lock]', source)
        self.assertIn('git worktree add --detach "$STAGE" "$SOURCE_SHA"', source)
        self.assertIn('cargo +1.96.0 metadata --locked', source)
        self.assertIn('versions[\'anymap2\'] or not versions[\'anymap3\']', source)
        self.assertIn('versions[\'matrix-sdk-crypto\'] != [\'0.19.1\']', source)
        self.assertIn('Integrated exact Cargo.lock metadata failed (not waived).', source)
        self.assertIn('matrix_dependency_gate.py --root . --require-safe', source)
        self.assertNotIn('continue-on-error: true', source)
        self.assertNotIn('cargo deny --disable', source)
        self.assertNotIn('cargo update --aggressive', source)

    def test_accepted_triggers_and_pinned_upstream_candidates(self):
        self.assertIn("  workflow_dispatch:", self.source)
        self.assertIn("  pull_request:", self.source)
        self.assertIn("b18166c68bb958a21f0bca8b2d8320cb53583362", self.source)
        self.assertIn("9c5fdd2cf5be1b7b8b20541e56d7a109db968534", self.source)
        self.assertIn("b3c07ea6ba6e8e46e30811c0500b04505c4be9f9", self.source)


if __name__ == "__main__":
    unittest.main()
