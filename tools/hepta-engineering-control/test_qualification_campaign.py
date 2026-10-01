"""Real owner measurement and evaluator preparation regressions.

Portable execution below checks actual baseline and mutant bytes. It deliberately
does not produce a strong-sandbox campaign or a production acceptance receipt.
"""

from dataclasses import asdict, replace
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from control_engineering_v2 import EngineeringError
from control_engineering_v2.candidate import generate_candidates, sandbox_candidate
from control_engineering_v2.control_plane import semantic_digest
from control_engineering_v2.mutation_testing import MutationTestingReceipt
from control_engineering_v2 import qualification_mutation, stress_profile


class StressProfileTests(unittest.TestCase):
    def test_concurrent_owner_writes_reopen_and_wal_observe_exact_records(self):
        profile = stress_profile.build_stress_profile(
            records=12, writers=3, reopen_cycles=3
        )
        self.assertEqual(profile["auditAnchor"]["sequence"], 12)
        self.assertEqual(profile["capacity"]["auditEvents"], 12)
        self.assertEqual(profile["capacity"]["activeClaims"], 0)
        self.assertEqual(profile["capacity"]["hardFailures"], ())
        self.assertEqual(profile["walCheckpoint"][0], 0)
        self.assertGreaterEqual(profile["walCheckpoint"][1], profile["walCheckpoint"][2])
        self.assertGreaterEqual(
            profile["write"]["maximumMillis"], profile["write"]["medianMillis"]
        )
        self.assertGreaterEqual(profile["write"]["totalMillis"], 0)
        self.assertGreaterEqual(profile["reopen"]["maximumMillis"], 0)
        self.assertFalse(profile["capacity"]["productionAccepted"])
        for flag in (
            "runtimeAuthority", "mergeAuthority", "releaseAuthority", "deploymentAccepted"
        ):
            self.assertIs(profile[flag], False)

    def test_invalid_measurement_budgets_fail_before_creating_an_owner(self):
        limits = (
            ("records", "stress_records", (True, 1.0, "1", 0, 100_001)),
            ("writers", "stress_writers", (True, 1.0, "1", 0, 33)),
            ("reopen_cycles", "stress_reopen_cycles", (True, 1.0, "1", 0, 1001)),
        )
        with patch.object(stress_profile.tempfile, "TemporaryDirectory") as temporary:
            for field, message, values in limits:
                for value in values:
                    with self.subTest(field=field, value=value):
                        arguments = {"records": 1, "writers": 1, "reopen_cycles": 1}
                        arguments[field] = value
                        with self.assertRaisesRegex(ValueError, message):
                            stress_profile.build_stress_profile(**arguments)
            temporary.assert_not_called()

    def test_cli_retains_real_profile_and_failed_run_creates_no_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "nested/profile.json"
            self.assertEqual(
                stress_profile.main([
                    "--records", "2", "--writers", "1", "--reopen-cycles", "1",
                    "--output", str(output),
                ]),
                0,
            )
            retained = json.loads(output.read_text())
            self.assertEqual(retained["auditAnchor"]["sequence"], 2)
            output.unlink()
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                self.assertEqual(
                    stress_profile.main(["--records", "0", "--output", str(output)]),
                    1,
                )
            self.assertEqual(json.loads(stdout.getvalue())["error"], "stress_records")
            self.assertFalse(output.exists())


class MutationCampaignTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def prepare(self, root):
        root.mkdir()
        qualification_mutation._git(root, "init", "-q")
        qualification_mutation._git(root, "config", "user.name", "Fixture")
        qualification_mutation._git(root, "config", "user.email", "fixture@example.invalid")
        (root / "data.txt").write_text("data\n")
        qualification_mutation._git(root, "add", "-A")
        qualification_mutation._git(root, "commit", "-qm", "fixture")

    def test_preparation_ignores_git_repository_and_config_redirection(self):
        other = self.root / "other"
        self.prepare(other)
        subject = self.root / "subject"
        with patch.dict(os.environ, {
            "GIT_DIR": str(other / ".git"),
            "GIT_WORK_TREE": str(other),
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "user.name",
            "GIT_CONFIG_VALUE_0": "ambient-attacker",
        }):
            self.prepare(subject)
            self.assertEqual(
                qualification_mutation._git(subject, "config", "user.name"), "Fixture"
            )
        self.assertTrue((subject / ".git").is_dir())
        self.assertEqual(qualification_mutation._git(other, "status", "--porcelain"), "")

    @unittest.skipUnless(os.name == "posix", "hook fixture uses a shell")
    def test_pre_sandbox_preparation_cannot_run_ambient_or_local_git_hooks(self):
        hooks = self.root / "hooks"
        hooks.mkdir()
        marker = self.root / "hook-fired"
        hook = hooks / "pre-commit"
        hook.write_text(f'#!/bin/sh\ntouch "{marker}"\n')
        hook.chmod(0o700)
        config = self.root / "global.config"
        config.write_text(f"[core]\n\thooksPath = {hooks}\n")
        subject = self.root / "subject"
        with patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(config)}):
            self.prepare(subject)
            qualification_mutation._git(subject, "config", "core.hooksPath", str(hooks))
            (subject / "data.txt").write_text("next\n")
            qualification_mutation._git(subject, "add", "-A")
            qualification_mutation._git(subject, "commit", "-qm", "next")
        self.assertFalse(marker.exists())

    def source_fixture(self):
        package = self.root / "tools/hepta-engineering-control/control_engineering_v2"
        package.mkdir(parents=True)
        for name in ("time_policy.py", "capacity_policy.py", "deployment_evidence.py"):
            (package / name).write_text("# fixture\n")
        for name in ("test_control_engineering_extensions.py", "test_deployment_evidence.py"):
            (package.parent / name).write_text("# fixture\n")
        return package

    @unittest.skipUnless(hasattr(os, "symlink"), "source escape fixture requires symlinks")
    def test_source_symlink_is_rejected_before_copy_or_git_preparation(self):
        package = self.source_fixture()
        outside = self.root / "host-file"
        outside.write_text("host-only\n")
        (package / "host-data").symlink_to(outside)
        with patch.object(qualification_mutation, "_git") as git:
            with self.assertRaisesRegex(ValueError, "mutation_campaign_source_not_regular"):
                qualification_mutation.build_mutation_campaign(self.root)
            git.assert_not_called()

    def test_campaign_packages_real_source_and_kills_mutants_in_portable_evaluator(self):
        repository = Path(__file__).resolve().parents[2]

        def portable_evaluator(root, envelope, baseline, mutants, checks, coordinator):
            self.assertTrue(envelope.require_network_isolation)
            subject = Path(root) / "subject/control_engineering_v2"
            self.assertFalse(any(subject.rglob("*.pyc")))
            self.assertFalse(any(subject.rglob("__pycache__")))
            fixture_envelope = replace(envelope, require_network_isolation=False)
            fixture_candidates = generate_candidates(
                fixture_envelope, tuple(mutant.mutation for mutant in mutants)
            )
            execution_receipts = []
            for index, fixture_candidate in enumerate(fixture_candidates):
                candidate, receipt = sandbox_candidate(
                    root, fixture_envelope, fixture_candidate, checks
                )
                self.assertIs(receipt.network_isolated, False)
                self.assertEqual(receipt.passed, index == 0)
                self.assertEqual(candidate.state, "fixture_tested" if index == 0 else "rejected")
                execution_receipts.append(semantic_digest(asdict(receipt)))
            # Successful portable tests must still fail the retained strong
            # campaign. This test never fabricates a qualifying sandbox result.
            return MutationTestingReceipt(
                baseline.candidate_id, execution_receipts[0], 1,
                tuple(mutant.candidate_id for mutant in mutants),
                tuple((mutant.candidate_id, execution_receipts[index + 1], 1)
                      for index, mutant in enumerate(mutants)),
                tuple(mutant.candidate_id for mutant in mutants), (),
                semantic_digest(checks), "1" * 64, False,
            )

        with patch.object(qualification_mutation, "run_mutation_testing", side_effect=portable_evaluator):
            with self.assertRaisesRegex(RuntimeError, "mutation_campaign_survivors"):
                qualification_mutation.build_mutation_campaign(repository)

    def test_missing_campaign_sources_fail_cli_without_retained_success(self):
        output = self.root / "campaign.json"
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.assertEqual(
                qualification_mutation.main([
                    "--repository", str(self.root), "--output", str(output)
                ]),
                1,
            )
        self.assertEqual(
            json.loads(stdout.getvalue())["error"], "mutation_campaign_source_missing"
        )
        self.assertFalse(output.exists())

    def test_unavailable_sandbox_cannot_be_converted_to_campaign_success(self):
        self.source_fixture()
        with patch.object(
            qualification_mutation, "run_mutation_testing",
            side_effect=EngineeringError("strong_sandbox_unavailable"),
        ):
            with self.assertRaisesRegex(EngineeringError, "strong_sandbox_unavailable"):
                qualification_mutation.build_mutation_campaign(self.root)


if __name__ == "__main__":
    unittest.main()
