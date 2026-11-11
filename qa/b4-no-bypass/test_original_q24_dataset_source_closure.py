"""Mutation controls for original Dataset custody and source-bound Training."""

import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_q24_dataset_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
DATASET = AGENT + "cell_q24_dataset.rs"
RECOVERY = AGENT + "cell_q24_dataset_recovery.rs"
STAGE = AGENT + "cell_q24_training_stage.rs"
NATIVE = AGENT + "cell_composed_q24_training_owner.rs"
SOURCE = AGENT + "circuit_task_source.rs"
READER = AGENT + "circuit_task_source_readback.rs"
LEDGER = "codex-rs/hepta-learning-ledger/src/production.rs"
CURRENT = "source.require_current(&owners.receipts.config.dataset)?;"
CALLERS = {
    "cell_q24_original_dataset_freeze": (),
    "cell_q24_original_dataset_revalidate": (STAGE, RECOVERY),
    "cell_q24_original_training_batch_binding": (STAGE,),
    "learning_original_training_stage_source_execute": (),
    "learning_original_training_stage_source_readback": (),
    "learning_original_training_stage_source_attestation": (),
    "learning_original_ledger_dataset_freeze": (
        AGENT + "terminal_learning.rs",
        DATASET,
    ),
    "learning_original_ledger_dataset_records": (
        AGENT + "shared_terminal_cell.rs",
        "codex-rs/hepta-bellman-operator/src/owner_terminal.rs",
        DATASET,
    ),
    "circuit_original_source_run_readback": (READER,),
    "circuit_original_source_observer_run_readback": (
        AGENT + "circuit_feature_current_learning.rs",
        AGENT + "circuit_feature_current_recovery.rs",
        AGENT + "circuit_feature_current_retirement.rs",
        DATASET,
    ),
}


def function_span(source, function):
    code = PROOF._strip_rust_non_code(source)
    start = code.index(function)
    end = PROOF._rust_item_end(code, start)
    if end is None:
        raise PROOF.VerificationFailure("original function body missing")
    return start, end + 1


def verify_stage_effect_locations(source):
    """The source barrier must not be bypassed by an extra early signer call."""
    code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    start, end = function_span(code, "fn complete_training(")
    signing = list(re.finditer(r"(?:\.|::)\s*attest_original_completion\s*\(", code))
    if len(signing) != 1 or not start < signing[0].start() < end:
        raise PROOF.VerificationFailure("only completion may request original signing")
    start, end = function_span(code, "fn prepare_training(")
    fitting = list(re.finditer(r"(?:\.|::)\s*fit_or_readback\s*\(", code))
    if len(fitting) != 1 or not start < fitting[0].start() < end:
        raise PROOF.VerificationFailure("only preparation may enter the native trainer")
    for function in (
        "fn readback_from_original_dataset<",
        "fn receipt_attestation_from_original_dataset<",
    ):
        start, end = function_span(code, function)
        if re.search(
            r"(?:\.|::)\s*(?:prepare_training|complete_training|fit_or_readback|attest_original_completion|execute_training)\s*\(",
            code[start:end],
        ):
            raise PROOF.VerificationFailure(
                "source readback cannot create work or signatures"
            )


class OriginalQ24DatasetSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {
            row.identifier: row for row in PROOF._boundary_rows(cls.manifest)
        }

    def verify_source(self, path, source):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
        if path == STAGE:
            verify_stage_effect_locations(source)

    def rejects(self, path, function, marker, replacement="", occurrence=0):
        source = (ROOT / path).read_text()
        self.verify_source(path, source)
        start, end = function_span(source, function)
        matches = list(re.finditer(re.escape(marker), source[start:end]))
        self.assertGreater(len(matches), occurrence, (function, marker, occurrence))
        offset = start + matches[occurrence].start()
        changed = source[:offset] + replacement + source[offset + len(marker) :]
        with self.assertRaises(PROOF.VerificationFailure):
            self.verify_source(path, changed)

    def rejects_each(self, path, function, markers):
        for marker in markers:
            with self.subTest(path=path, function=function, marker=marker):
                self.rejects(path, function, marker)

    def test_only_explicit_existing_readers_and_internal_dataset_calls_are_admitted(
        self,
    ):
        paths = {STAGE, NATIVE, DATASET, SOURCE, READER, LEDGER}
        for name, callers in CALLERS.items():
            paths.update(callers)
            paths.add(self.boundaries[name].definition_path)
        sources = {
            path: PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code((ROOT / path).read_text())
            )
            for path in paths
        }
        for name, callers in CALLERS.items():
            with self.subTest(boundary=name):
                row = self.boundaries[name]
                self.assertIn(
                    name, self.manifest["privileged_inventory"]["required_boundary_ids"]
                )
                self.assertEqual(set(row.product_callers), set(callers))
                PROOF._verify_boundary(ROOT, row, sources, ())
                changed = dict(sources)
                method = row.symbol.rsplit("::", 1)[-1]
                changed[AGENT + "unregistered_original_dataset.rs"] = (
                    f"fn bypass(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, changed, ())
        self.assertEqual(
            self.boundaries["root_learning_original_stage_assembly"].product_callers, ()
        )
        self.assertTrue(
            all(flag is False for flag in self.manifest["authority"].values())
        )

    def test_training_pre_fit_post_fit_pre_sign_and_post_sign_barriers_each_reject_removal(
        self,
    ):
        function = "fn execute_training_from_original_dataset<"
        for occurrence in range(3):
            with self.subTest(barrier=occurrence):
                self.rejects(STAGE, function, CURRENT, occurrence=occurrence)
        self.rejects_each(
            STAGE,
            function,
            (
                "self.require_dataset(dataset)?",
                "CellQ24TrainingOwnerV1::require_original_batch(",
                "&owners.training",
                "source.material.batch()",
                "owners.prepare_training(&cancellation)?",
                "owners.complete_training(prepared)?",
            ),
        )

    def test_source_barrier_cannot_move_after_signing_or_hide_in_dead_code(self):
        source = (ROOT / STAGE).read_text()
        self.verify_source(STAGE, source)
        start, end = function_span(source, "fn execute_training_from_original_dataset<")
        body = source[start:end]
        positions = [m.start() for m in re.finditer(re.escape(CURRENT), body)]
        self.assertEqual(len(positions), 3)
        before_sign = positions[1]
        body = body[:before_sign] + body[before_sign + len(CURRENT) :]
        signing = "let completed = owners.complete_training(prepared)?;"
        body = body.replace(signing, signing + "\n" + CURRENT, 1)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verify_source(STAGE, source[:start] + body + source[end:])
        self.rejects(
            STAGE,
            "fn execute_training_from_original_dataset<",
            CURRENT,
            "if false { " + CURRENT + " }",
            occurrence=1,
        )

    def test_prepare_cannot_sign_and_readback_cannot_fit_or_complete(self):
        self.rejects(
            STAGE,
            "fn prepare_training(",
            "let owners = self;",
            "let owners = self; owners.receipts.attest_original_completion(&mut owners.training)?;",
        )
        self.rejects(
            STAGE,
            "fn readback_from_original_dataset<",
            "self.in_lane(move |owners| {",
            "self.in_lane(move |owners| { owners.prepare_training(&AtomicBool::new(false))?;",
        )

    def test_cold_readback_and_attestation_keep_both_source_checks_and_exact_receipt(
        self,
    ):
        function = "fn readback_from_original_dataset<"
        for occurrence in range(2):
            with self.subTest(barrier=occurrence):
                self.rejects(STAGE, function, CURRENT, occurrence=occurrence)
        self.rejects_each(
            STAGE,
            function,
            (
                "self.require_dataset(dataset)?",
                "CellQ24TrainingOwnerV1::require_original_batch(",
                "&owners.training",
                "source.material.batch()",
                "owners.read_original_completion()?",
            ),
        )
        self.rejects_each(
            STAGE,
            "fn receipt_attestation_from_original_dataset<",
            (
                "self.readback_from_original_dataset(dataset, source).await?",
                "if &completed.receipt != expected",
            ),
        )

    def test_source_context_and_full_batch_identity_cannot_be_rebound(self):
        self.rejects_each(
            STAGE,
            "fn require_current(",
            (
                "profile.principal_id != request.principal_id",
                "profile.agent_id.as_str() != request.agent_id.as_str()",
                "profile.cell_id != request.cell_id",
                "profile.objective_digest != request.envelope.objective_digest",
                "profile.selected_bundle",
                "self.ledger.try_lock()",
                ".revalidate(&ledger, &self.source, &self.identity)?",
            ),
        )
        self.rejects_each(
            NATIVE,
            "fn require_original_batch(",
            (
                "self.batch.digest() != batch.digest()",
                "self.batch.encoded() != batch.encoded()",
                "self.require_current()",
            ),
        )

    def test_trigger_run_and_completion_must_match_the_same_original_publication(self):
        self.rejects_each(
            STAGE,
            "fn require_current(",
            (
                ".require_request_source(",
                "&request.source_run_id",
                "request.completed_task_receipt",
            ),
        )
        self.rejects_each(
            DATASET,
            "fn require_request_source(",
            (
                "if !self.publications.iter().any(|publication| {",
                "&publication.input().scope.run_id == run_id",
                "&& publication",
                "== Some(completed_task_receipt)",
            ),
        )
        self.rejects(
            DATASET,
            "fn require_request_source(",
            "&& publication",
            "|| publication",
        )

    def test_freeze_keeps_original_signed_profile_and_pre_post_frontier_reads(self):
        self.rejects_each(
            DATASET,
            "fn freeze<",
            (
                "let before = current_ledger(ledger, identity, &profile)?;",
                "plan.objective_digest != profile.objective_digest",
                "plan.inclusion_policy_digest != profile.digest()?",
                "dataset_freeze_signing_payload_v2(&ledger.snapshot()?, &plan)?",
                "LedgerWriter::freeze_dataset(ledger, plan, &evidence, now()?)?",
                "collect(ledger, source, identity, &profile, &dataset)?",
                "current_ledger(ledger, identity, &profile)? != before",
                "material.revalidate(ledger, source, identity)?",
            ),
        )

    def test_revalidation_keeps_signature_producer_exact_material_and_frontiers(self):
        self.rejects_each(
            DATASET,
            "fn revalidate<",
            (
                "let before = current_ledger(ledger, identity, &self.profile)?;",
                "LearningEvidenceRoleV1::Evaluator",
                "&self.evidence",
                "&self.freeze_payload",
                "now()?",
                "signed.principal() != &self.dataset.producer",
                "collect(ledger, source, identity, &self.profile, &self.dataset)?",
                "batch.encoded() != self.batch.encoded()",
                "publications != self.publications",
                "current_ledger(ledger, identity, &self.profile)? != before",
            ),
        )

    def test_rows_reject_missing_duplicate_nonterminal_and_unbound_original_material(
        self,
    ):
        self.rejects_each(
            DATASET,
            "fn collect<",
            (
                "dataset.inclusion_policy_digest != profile.digest()?",
                "dataset.snapshot.pending_outcomes != 0",
                "dataset.snapshot.censored_outcomes != 0",
                "LedgerWriter::read_dataset_records(ledger, dataset, now()?)?",
                "!training.contains_key(&value.episode_id)",
                "!seen.insert(value.episode_id.clone())",
                "outcomes.insert(value.episode_id.clone(), value).is_some()",
                "decisions.len() != training.len() || outcomes.len() != training.len()",
                "decision.record_id != run",
                "decision.policy_digest != profile.selected_bundle",
                "decision.run_snapshot_digest != training[&decision.episode_id].run_snapshot_digest",
                "decision.support_digest != training[&decision.episode_id].decision_support_digest",
                "source.read_run_publication(identity, &run)?",
                "input.scope.principal_digest != profile.principal_digest",
                "input.scope.run_id != run",
                "published.bundle_digest() != profile.selected_bundle",
                "require_selection(",
                "outcome.terminality != AuthenticatedOutcomeTerminality::Terminal",
                "outcome.observed_at.is_none()",
                "outcome.finalized_at.is_none()",
                "outcome.censoring_reason.is_some()",
                "outcome.unit_profile_digest != profile.outcome_unit_profile",
                "outcome.support_digest != published.publication_digest()",
                "target_q24(raw)?",
                "codec::input(&input.observation, usize::from(profile.input_width))",
                "CellQ24TrainingBatchV1::new(dataset.snapshot.dataset_digest, samples)?",
            ),
        )

    def test_profile_partition_bounds_and_ledger_independent_witness_cannot_be_removed(
        self,
    ):
        self.rejects_each(
            DATASET,
            "fn digest(",
            (
                "!(1..=64).contains(&self.input_width)",
                "!(1..=64).contains(&self.training_episodes.len())",
                "self.excluded_episodes.len() > 64",
                "pair[0].episode_id >= pair[1].episode_id",
                "pair[0] >= pair[1]",
                "row.run_snapshot_digest.is_zero()",
                "row.decision_support_digest.is_zero()",
                ".binary_search(&row.episode_id)",
                "if digest.is_zero()",
            ),
        )
        self.rejects_each(
            DATASET,
            "fn current_ledger(",
            (
                "ledger.binding_digest() != profile.ledger_binding",
                "ledger.verifier().trust_digest() != profile.evidence_trust_digest",
                "ledger.verifier().objective_digest() != profile.objective_digest",
                "ledger.witness_frontier()?",
                "witness.anchor.sequence > 4096",
                "snapshot.head_digest != witness.anchor.chain_digest",
                "witness.segment != Some(checkpoint.segment) || witness.sealed != checkpoint.sealed",
            ),
        )

    def test_original_selection_and_fixed_precision_targets_cannot_be_substituted(self):
        self.rejects_each(
            DATASET,
            "fn require_selection(",
            (
                ".filter(|mask| mask.allowed)",
                "!bytes.starts_with(prefix)",
                "Some(published.input().scope.digest().as_array())",
                "Some(published.bundle_digest().as_array())",
                "length != selected.as_str().len()",
                "Some(selected.as_str().as_bytes())",
                "allowed != declared",
                "declared.len() != candidates.len()",
                "!allowed.contains(selected)",
            ),
        )
        self.rejects_each(
            DATASET,
            "fn target_q24(",
            (
                "if !(-(8_i64 << 32)..=(8_i64 << 32)).contains(&raw)",
                "Ok(raw / 256)",
            ),
        )

    def test_original_readers_preserve_active_source_exact_input_and_authenticated_records(
        self,
    ):
        self.rejects_each(
            SOURCE,
            "fn read_run_publication(",
            (
                "identity != &owner.identity",
                "owner.require_active(run_id.as_str())?",
                "&record.snapshot.run_id != run_id",
                "self.read_publication(identity, &record)",
            ),
        )
        self.rejects_each(
            SOURCE,
            "fn read_publication(",
            (
                "owner.require_bytes(",
                "input != source.input(input.operation_id.clone())",
                "owner.require_current()?",
            ),
        )
        self.rejects_each(
            LEDGER,
            "fn freeze_dataset(",
            (
                "self.backend.snapshot()?",
                "dataset_freeze_signing_payload_v2(&snapshot, &plan)?",
                "self.trust.verifier().verify(",
                "require_role(&verified, LearningEvidenceRoleV1::Evaluator)?",
            ),
        )
        self.rejects_each(
            LEDGER,
            "fn read_dataset_records(",
            (
                "receipt.snapshot.source_record_digests.len() > 4096",
                "self.revalidate_dataset_snapshot(receipt, now)?",
                ".active_record_by_digest(digest)?",
                "records.sort_unstable_by_key(|record| record.sequence)",
            ),
        )


if __name__ == "__main__":
    unittest.main()
