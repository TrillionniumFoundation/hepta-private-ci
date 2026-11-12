"""Keep Dataset material bound to live original sources without publication authority."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = "codex-rs/hepta-agentd/src/cell_q24_dataset.rs"
SPEC = importlib.util.spec_from_file_location(
    "q24_dataset_caller_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)


class Q24DatasetSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.rows = [row for row in manifest["protected_file"] if row["path"] == SOURCE]
        cls.source = (ROOT / SOURCE).read_text()

    def rejects(self, changed):
        self.assertEqual(len(self.rows), 1)
        self.assertNotEqual(changed, self.source)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / SOURCE
            target.parent.mkdir(parents=True)
            target.write_text(self.source)
            manifest = {"protected_file": self.rows}
            PROOF._verify_protected_files(root, manifest)
            target.write_text(changed)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, manifest)

    def test_original_current_and_freeze_cannot_be_replaced_by_cached_material(self):
        for marker in (
            "let before = self.ledger.read_current_durable_snapshot()?;",
            "self.ledger.read_current_durable_snapshot()? != before",
            ".freeze_dataset(plan.clone(), freeze_evidence, started_at)?",
            ".freeze_dataset(plan, freeze_evidence, fresh_now)?",
            "!= receipt\n",
            "self.ledger.read_dataset_records(&receipt, fresh_now)?;",
            "if actual != receipt.snapshot.source_record_digests",
            "if request.source_run_id != original_run",
        ):
            with self.subTest(marker=marker):
                self.assertEqual(self.source.count(marker), 1)
                self.rejects(self.source.replace(marker, "", 1))

        # Keeping the original signed recheck while accepting a different
        # receipt must also fail the source-order gate.
        self.rejects(self.source.replace("!= receipt\n", "== receipt\n", 1))

    def test_clock_and_expiry_guards_cannot_be_exposed_or_disabled(self):
        self.rejects(
            self.source.replace(
                "    fn read_current_with_clock(",
                "    pub fn read_current_with_clock(",
                1,
            )
        )
        for marker in (
            "let fresh_now = clock()?;",
            "if fresh_now < started_at",
            "if require_work_deadline && fresh_now >= request.envelope.expiry_unix_seconds",
        ):
            with self.subTest(marker=marker):
                self.assertEqual(self.source.count(marker), 1)
                self.rejects(self.source.replace(marker, "", 1))
        clock = "SystemTime::now()"
        self.assertEqual(self.source.count(clock), 2)
        self.rejects(self.source.replace(clock, "", 1))
        before, _, after = self.source.rpartition(clock)
        self.rejects(before + after)
        # The public new-material path always enforces its work deadline; the
        # separate closed receipt path can only re-read original completed work.
        self.rejects(self.source.replace("true, clock)", "false, clock)", 1))
        guard = "if fresh_now < started_at"
        self.rejects(self.source.replace(guard, "if false && fresh_now < started_at", 1))

    def test_target_requires_independent_authenticated_exact_outcome(self):
        for marker in (
            "decision.generator_controller_id == outcome.observer_controller_id",
            "decision.generator_signing_key_digest == outcome.observer_signing_key_digest",
            "outcome.terminality != AuthenticatedOutcomeTerminality::Terminal",
            "outcome.authentication_digest.is_zero()",
            "raw % 256 != 0",
            "!(-8 * codec::Q..=8 * codec::Q).contains(&(raw / 256))",
        ):
            with self.subTest(marker=marker):
                self.assertEqual(self.source.count(marker), 1)
                self.rejects(self.source.replace(marker, "", 1))

    def test_consumer_requires_the_exact_original_source_profile_and_policy(self):
        for marker in (
            "terminal_target(&records, request, &source, rule.unit_profile_digest)?",
            "let policy = CircuitTaskSourcePublicationV1::original_policy(source)?;",
            "candidates.sort();",
            ".div_ceil(1_000_000)",
        ):
            with self.subTest(marker=marker):
                self.assertEqual(self.source.count(marker), 1)
                self.rejects(self.source.replace(marker, "", 1))

        for marker in (
            "decision.run_snapshot_digest != source.input().ndu_snapshot_digest",
            "decision.policy_digest != Digest32::of_bytes(source.output())",
            "decision.support_digest != source.publication_digest()",
            "decision.candidate_ids != candidates",
            "decision.selected_candidate_id != *policy.selected()",
            "decision.selected_propensity != ProbabilityQ32::ONE",
            "outcome.support_digest != source.publication_digest()",
            "admitted_at == 0",
            "outcome.observed_at.is_some_and(|at| at < admitted_at)",
            ".is_some_and(|at| at < outcome.latest_observable_at)",
        ):
            with self.subTest(marker=marker):
                self.assertEqual(self.source.count(marker), 1)
                self.rejects(self.source.replace(marker, "", 1))
                if " != " in marker:
                    reversed_marker = marker.replace(" != ", " == ")
                elif " == " in marker:
                    reversed_marker = marker.replace(" == ", " != ")
                else:
                    reversed_marker = marker.replace(" < ", " >= ")
                self.rejects(self.source.replace(marker, reversed_marker, 1))

        for marker, replacement in (
            ("original-dataset.v2", "original-dataset.v1"),
            ("run-snapshot=source-input-ndu", "run-snapshot=full-run-start"),
            ("observed-at-or-after-ceil-source-admission", "unbound-source-age"),
        ):
            with self.subTest(marker=marker):
                self.assertEqual(self.source.count(marker), 1)
                self.rejects(self.source.replace(marker, replacement, 1))

    def test_material_cannot_acquire_signing_training_or_publication_effects(self):
        for statement in (
            "owner.sign(value);",
            "owner.claim(value);",
            "owner.complete(value);",
            "trainer.fit_or_readback(value);",
            "config.with_root_learning_stage_owners(value);",
            "let target = value.clamp(low, high);",
        ):
            with self.subTest(statement=statement):
                self.rejects(self.source + "\nfn extra() { " + statement + " }\n")


if __name__ == "__main__":
    unittest.main()
