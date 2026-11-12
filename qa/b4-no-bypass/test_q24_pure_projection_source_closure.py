"""The same canonical algorithm is shared; a pure projection grants nothing."""

import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT = component.ROOT
AGENT = component.AGENT
PURE = AGENT + "cell_q24_dataset_projection.rs"
MATERIALIZER = AGENT + "cell_q24_dataset_materializer.rs"


class PureProjectionSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_only_actual_materializer_calls_the_private_data_kernel(self):
        rows = {row["id"]: row for row in self.manifest["boundary"]}
        self.assertEqual(rows["q24_dataset_pure_original_projection"]["product_callers"], [AGENT + 'cell_q24_dataset_historical_ledger.rs', MATERIALIZER, AGENT + 'authority_host_post_a_derive.rs'])

    def test_kernel_keeps_complete_frozen_records_and_sequence(self):
        self.check_markers(PURE, "fn project_original_q24_dataset_v1(", (
            "!(1..=256).contains(&original_tasks.len())", "frozen.records().len() > 4096",
            "receipt.snapshot.source_record_digests.len() > 512", "receipt.inclusion_policy_digest != profile",
            "receipt.snapshot.pending_outcomes != 0", "receipt.snapshot.censored_outcomes != 0",
            "LedgerSnapshot::read_dataset_records(frozen, receipt, observed_at)? != records",
            ".insert(&value.episode_id, (record, value))",
            "decisions.len() != original_tasks.len() || outcomes.len() != decisions.len()",
            ".insert(&publication.input().scope.run_id, (publication, decision))"))

    def test_task_cell_policy_and_terminal_facts_stay_exact(self):
        self.check_markers(PURE, "fn project_original_q24_dataset_v1(", (
            "decision.run_snapshot_digest != cell_q24_dataset_run_snapshot_digest_v1(publication)",
            "decision.objective_digest != receipt.snapshot.objective_digest",
            "decision.policy_digest != Digest32::of_bytes(publication.output())",
            "decision.support_digest != publication.publication_digest()",
            "outcome.support_digest != publication.publication_digest()",
            "publication.bundle_digest() != projection.baseline_bundle",
            "decision.selected_candidate_id != original.selected_candidate",
            "decision.selected_propensity != ProbabilityQ32::ONE",
            "original_candidates.sort()", "decision.candidate_ids != original_candidates",
            ".any(|p| p.candidate_id == original.selected_candidate && p.allowed)",
            "outcome.terminality != AuthenticatedOutcomeTerminality::Terminal",
            "outcome.correction_predecessor.is_some()", "outcome.unit_profile_digest != projection.unit_profile_digest",
            "outcome_record.sequence <= record.sequence"))

    def test_native_bounds_transcript_and_full_encoding_are_preserved(self):
        self.check_markers(PURE, "fn project_original_q24_dataset_v1(", (
            "outcome.value.ok_or(", "if !(-(8_i64 << 32)..=(8_i64 << 32)).contains(&raw)",
            "codec::input(", "usize::from(projection.input_width)", "target: raw / 256",
            "transcript.extend_from_slice(digest.as_array())", "batch.encoded[..8].copy_from_slice(",
            "batch.encoded.extend_from_slice(profile.as_array())", "Digest32::of_bytes(&transcript).as_array()",
            "batch.digest = Digest32::of_bytes(&batch.encoded)"))

    def test_actual_materializer_retains_both_owner_and_evaluator_postchecks(self):
        for occurrence in (0, 1):
            self.reject_removal(MATERIALIZER, "fn materialize_live(", "task.require_current()?", occurrence)
            self.reject_removal(MATERIALIZER, "fn materialize_live(", "ledger.verifier().verify(", occurrence)
        self.check_markers(MATERIALIZER, "fn materialize_live(", (
            "project_original_q24_dataset_v1(", "ledger.witness_frontier()? != frontier",
            "ledger.snapshot()? != current", "!= selected"))
        self.reject_removal(MATERIALIZER, "fn from_original_dataset(", "batch.source = Some(source)")


if __name__ == "__main__":
    unittest.main()
