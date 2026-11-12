"""Original B data must come from live Source and independent signed Outcomes.

These mutations close source boundaries; actual file mechanisms are tested
separately and are never evidence of ordinary deployed B or learning benefit.
"""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_evaluation_provider_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
CORE = AGENT + "circuit_original_evaluation_provider.rs"
CONTRACT = AGENT + "circuit_original_evaluation_provider_contract.rs"
BINDING = AGENT + "circuit_original_evaluation_provider_binding.rs"
RECORDS = AGENT + "circuit_original_evaluation_provider_records.rs"
READ = AGENT + "circuit_original_evaluation_provider_read.rs"
POLICY = AGENT + "circuit_task_source_policy.rs"
SOURCE = AGENT + "circuit_task_source.rs"
CURRENT = AGENT + "circuit_original_evaluation_cohort_readback.rs"
EXPECTED = {
    "learning_original_evaluation_cohort_capture": (),
    "learning_original_evaluation_holdout_provider": (),
    "learning_original_evaluation_material_current": (CORE,),
    "learning_original_source_policy_projection": (RECORDS,),
    "learning_original_evaluation_cohort_readback_retain": (CORE,),
    "learning_original_evaluation_cohort_readback_after_release": (),
    "learning_original_evaluation_cohort_readback_cold": (),
    "learning_original_evaluation_cohort_readback_current": (CORE,),
    "learning_original_evaluation_cohort_member_binding": (),
    "learning_original_evaluation_cohort_final_authentication": (),
}


class OriginalEvaluationProviderClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def code(self, source):
        return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))

    def verifies(self, path, source):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})

    def rejects(self, path, function, marker, replacement="", *, after=None):
        source = (ROOT / path).read_text()
        code = self.code(source)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        marker_start = start if after is None else source.index(after, start, end + 1) + len(after)
        offset = source.index(marker, marker_start, end + 1)
        self.verifies(path, source)
        changed = source[:offset] + replacement + source[offset + len(marker):]
        with self.assertRaises(PROOF.VerificationFailure, msg=f"{path}: {function}: {marker}"):
            self.verifies(path, changed)

    def test_exact_cohort_capture_provider_and_original_policy_edges(self):
        paths = {CORE, CONTRACT, BINDING, RECORDS, READ, POLICY, SOURCE, CURRENT}
        sources = {path: self.code((ROOT / path).read_text()) for path in paths}
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, expected)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                extra = dict(sources)
                extra[AGENT + "unregistered_B_provider.rs"] = (
                    f"fn bypass(owner: &mut {row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())

    def test_complete_preregistered_rule_binds_units_time_and_all_original_runs(self):
        for marker in (
            "self.validate()?", "self.unit_profile_digest", "self.expected_delay_profile_digest",
            "self.candidate_plan.canonical_digest()?", "self.baseline_plan.canonical_digest()?",
            "self.history_start_unix_seconds", "self.evaluation_end_unix_seconds",
            "&row.episode_id", "&row.behavior_run_id", "&row.candidate_run_id",
            "&row.baseline_run_id",
        ):
            self.rejects(CONTRACT, "fn canonical_digest(", marker)
        for marker in (
            "self.history.is_empty()", "self.targets.is_empty()",
            "self.history.len() + self.targets.len() > MAX_EPISODES",
            "self.candidate_plan.fold != self.baseline_plan.fold",
            "!episodes.insert(&row.episode_id)", "!runs.insert(&row.candidate_run_id)",
        ):
            self.rejects(CONTRACT, "fn validate(", marker)
        for marker in (
            "member.cohort_rule_digest != digest",
            "config.training.request.evaluation_profile != config.registration.evaluation_profile()",
            "config.freeze_plan.inclusion_policy_digest != digest",
            "owners.ledger.verifier().trust_digest() != config.verifier.trust_digest()",
            "actual != rule.run_ids()", "actual.contains(&config.training.request.source_run_id)",
        ):
            self.rejects(BINDING, "fn validate_configuration(", marker)

    def test_original_candidate_training_and_full_signature_are_revalidated(self):
        for marker in (
            "config.scope.validate_snapshot(&config.training)?",
            "original.next_stage() != Some(LearningIterationStageV1::Evaluation)",
            "config.training.receipts.len() != 3",
            "current >= config.training.request.envelope.expiry_unix_seconds",
            "LearningIterationObservationV1::Training { candidate, .. }",
            "config.training_evidence.principal_id != receipt.actor_id",
            "config.training_evidence.issued_at != receipt.observed_unix_seconds",
            "config.verifier.verify(", "learning_iteration_receipt_signing_bytes_v1(receipt)?",
            "if candidate == baseline",
        ):
            self.rejects(BINDING, "fn authenticate_training(", marker)
        for marker in (
            "evidence.signing_bytes()", "full.extend_from_slice(&evidence.signature)",
            "observed.publication_digest().as_array()",
        ):
            self.rejects(READ, "fn read_original_material(", marker)
        for marker in ("expected != observed.manifest", "expected != &observed.dataset"):
            self.rejects(CORE, "fn read_current_with_clock(", marker)
        for marker in (
            "registration != &config.registration", "task != registered",
            "task.cohort_rule_digest != self.original.rule_digest",
            "training != &config.training", "scope != &config.scope",
            "plan != &self.plan", "training_evidence != &config.training_evidence",
            "verifier.trust_digest() != config.verifier.trust_digest()",
            "verifier.scope_digest() != config.verifier.scope_digest()",
            "verifier.objective_digest() != config.verifier.objective_digest()",
        ):
            self.rejects(CURRENT, "fn require_original_member(", marker)
        for marker in (
            "self.original.read_current_with_clock(clock)?",
            "material.manifest != frozen.final_holdout_digest",
            "material.dataset.snapshot.dataset_digest != frozen.dataset_digest",
            "&self.original.config.training_evidence", "&self.original.config.freeze_evidence",
            "evidence.signing_bytes()", "full.extend_from_slice(&evidence.signature)",
            "bytes.extend_from_slice(&material.freeze_payload)",
            "if self.last.as_ref().is_some_and(|last| last != &observed)",
        ):
            self.rejects(CURRENT, "fn read_current_with_clock(", marker)

    def test_original_policy_projection_is_bounded_exact_and_never_smooths_zero_support(self):
        for marker in (
            "publication.result_bytes()", "result.blob()? != publication.output()",
            "decision.id()? != input.scope.run_id",
            "decision.digest()? != publication.bundle_digest()",
            "decision.digest()? != publication.checkpoint_digest()",
            "probability_ppm != expected", "(probability_ppm != 0 && !allowed)",
            "decision.end()?", "result.end()?", "output.id()? != selected",
            "output.u32()? != entry.probability_ppm", "output.end()?",
        ):
            self.rejects(POLICY, "fn read(", marker)
        self.rejects(POLICY, "fn new(", "bytes.len() > 65_536")
        self.rejects(POLICY, "fn blob(", "split_at_checked(length)")
        self.rejects(RECORDS, "fn probability(", "0 => Ok(ProbabilityQ32::ZERO)")
        for addition in ("fn bypass() { ProbabilityQ32::from_raw(1); }",
                         "fn bypass() { let reward = receipt.prediction_q24; }"):
            with self.assertRaises(PROOF.VerificationFailure):
                self.verifies(RECORDS, (ROOT / RECORDS).read_text() + "\n" + addition)

    def test_actual_independent_outcomes_join_original_execution_without_completion_labels(self):
        for marker in (
            "circuit_learning_run_id_v1(", "&owner.identity.agent_id",
            "decision.record_id != requested.behavior_run_id",
            "decision.run_snapshot_digest != input.ndu_snapshot_digest",
            "decision.selected_candidate_id != *policy.selected()",
            "decision.selected_propensity != ProbabilityQ32::ONE",
            "outcome.value.ok_or", "outcome.terminality != AuthenticatedOutcomeTerminality::Terminal",
            "outcome.unit_profile_digest != config.rule.unit_profile_digest",
            "outcome.expected_delay_profile_digest != config.rule.expected_delay_profile_digest",
            "training.generator.principal().principal_id == outcome.observer_id",
            "training.generator.controller_id() == &outcome.observer_controller_id",
            "training.generator.principal().credential_chain_digest == outcome.observer_credential_chain_digest",
            "training.generator.principal().signing_key_digest == outcome.observer_signing_key_digest",
            "decision.generator_id == outcome.observer_id",
            "decision.generator_controller_id == outcome.observer_controller_id",
            "decision.generator_credential_chain_digest == outcome.observer_credential_chain_digest",
            "decision.generator_signing_key_digest == outcome.observer_signing_key_digest",
        ):
            self.rejects(RECORDS, "fn read_episode(", marker)
        self.rejects(
            RECORDS, "fn read_episode(", "&requested.episode_id",
            after="circuit_learning_run_id_v1(",
        )
        for marker in ("outcomes.insert", "outcomes.keys()", "outcome: row.value"):
            self.rejects(RECORDS, "fn assemble(", marker)

    def test_two_actual_arms_preserve_inputs_lineage_and_unsupported_actions(self):
        for marker in (
            "arm.bundle_digest() != bundle", "left.scope.principal_digest != right.scope.principal_digest",
            "left.observation != right.observation", "left.source_frontier != right.source_frontier",
            "left.ndu_snapshot_digest != right.ndu_snapshot_digest",
            "left.candidates != right.candidates",
            "admitted_at < config.rule.candidate_plan.fold.evaluation_start",
        ):
            self.rejects(RECORDS, "fn require_arm(", marker)
        for marker in (
            "row.admitted_at < rule.history_start_unix_seconds",
            "row.observed_at > rule.candidate_plan.fold.training_watermark",
            "row.admitted_at < rule.candidate_plan.fold.evaluation_start",
            "CircuitTaskSourcePublicationV1::original_policy(candidate)?",
            "CircuitTaskSourcePublicationV1::original_policy(baseline)?",
            "cluster_id: row.principal",
        ):
            self.rejects(RECORDS, "fn assemble(", marker)
        for marker in (
            "behavior_probability: probability(behavior.probability_ppm)?",
            "evaluation_probability: probability(evaluated.probability_ppm)?",
            "finalized_outcome: Some(row.value)", "outcome_evidence: row.evidence",
        ):
            self.rejects(RECORDS, "fn observation(", marker)

    def test_all_physical_reads_precede_fresh_original_windows_and_sticky_fence(self):
        for marker in (
            "LedgerWriter::read_current_durable_snapshot(",
            "record.event.record_id() == &self.config.training.request.source_run_id",
            "receipt.snapshot.pending_outcomes != 0", "receipt.snapshot.censored_outcomes != 0",
            "if actual != receipt.snapshot.source_record_digests",
            "let sources = self.read_sources()?", "if self.read_sources()? != sources",
            "let fresh_now = clock()?", "if fresh_now < started_at",
            "binding::authenticate_training(&self.config, fresh_now)?",
            "verify_signed_role_separation(&fresh_training.generator, &fresh_evaluator, fresh_now)?",
        ):
            self.rejects(READ, "fn read_original_material(", marker)
        for marker in ("self.fenced = true", "if started_at < self.last_observed_at",
                       "OriginalCircuitEvaluationCohortV1::read_original_material("):
            self.rejects(CORE, "fn read_current_with_clock(", marker)
        self.rejects(CORE, "fn read_original(", "Self::read_original_with_clock(owners, config, now)")
        self.rejects(CURRENT, "fn read_current(", "self.read_current_with_clock(super::now)")
        for marker in (
            "self.fenced = true", "self.last.as_ref() != Some(observed)",
            "current < self.original.last_observed_at",
            "binding::authenticate_training(config, current)?",
            "&observed.freeze_payload",
            "verify_signed_role_separation(&training.generator, &evaluator, current)?",
            "LedgerWriter::freeze_dataset(", "!= observed.dataset",
            "LedgerWriter::read_dataset_records(", "self.original.last_observed_at = current",
        ):
            self.rejects(CURRENT, "fn authenticate_current(", marker)
        for addition in (
            "fn bypass() { File::open(path); }",
            "fn bypass() { owner.read_current_durable_snapshot(); }",
            "fn bypass() { owner.request(); }",
        ):
            with self.assertRaises(PROOF.VerificationFailure):
                self.verifies(CURRENT, (ROOT / CURRENT).read_text() + "\n" + addition)

    def test_only_the_original_consumed_holdout_releases_rows_once_without_authority(self):
        for marker in (
            "binding::require_plan(&self, &plan)?", "original: self", "release_attempted: false",
            "release_completed: false",
        ):
            self.rejects(CORE, "fn into_final_holdout_provider(", marker)
        self.rejects(CORE, "fn release_after_consumption(", "self.release_with_clock(receipt, now)")
        for marker in (
            "if self.release_attempted", "self.release_attempted = true",
            "receipt.disposition != HoldoutUseDispositionV1::Recorded",
            "used.disposition != HoldoutUseDispositionV1::Recorded",
            "used.plan_digest != plan.plan_digest", "used.dataset_digest != plan.dataset_digest",
            "used.holdout_digest != plan.final_holdout_digest",
            "receipt.authority.grants_any()", "used.authority.grants_any()",
            "read_current_with_clock(clock)", "Ok(observed.inputs)",
            "self.release_completed = true",
        ):
            self.rejects(CORE, "fn release_with_clock(", marker)
        self.rejects(CORE, "fn into_original_readback(", "!self.release_completed")
        self.rejects(CORE, "fn into_original_readback(", "self.original.fenced")
        for marker in (
            "binding::require_plan(&self, &plan)?",
            "OriginalCircuitEvaluationCohortReadbackV1::read_current(&mut readback)?",
        ):
            self.rejects(CORE, "fn into_readback_only(", marker)
        for addition in (
            "impl Clone for OriginalCircuitEvaluationCohortV1 {}",
            "impl Deserialize for OriginalCircuitEvaluationCohortV1 {}",
            "pub fn reset() {}",
            "fn bypass() { File::open(path); }",
        ):
            with self.assertRaises(PROOF.VerificationFailure):
                self.verifies(CORE, (ROOT / CORE).read_text() + "\n" + addition)


if __name__ == "__main__":
    unittest.main()
