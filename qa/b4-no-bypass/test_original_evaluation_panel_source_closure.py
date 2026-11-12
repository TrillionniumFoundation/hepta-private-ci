"""A panel requires original live owners, complete signatures and nonempty retention."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_evaluation_panel_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
CORE = AGENT + "neuron_cell_evaluation_panel.rs"
CONTRACT = AGENT + "neuron_cell_evaluation_panel_contract.rs"
MEMBER = AGENT + "neuron_cell_evaluation_panel_member.rs"
BINDING = AGENT + "neuron_cell_evaluation_panel_binding.rs"
PROVIDER = AGENT + "circuit_original_evaluation_provider.rs"
EXPECTED = {
    "cell_generation_original_physical_current": (MEMBER,),
    "learning_original_evaluation_panel_registration": (),
    "learning_original_evaluation_panel_owner": (),
    "learning_original_evaluation_panel_current": ("codex-rs/hepta-agentd/src/neuron_cell_evaluation_host.rs",),
    "learning_original_evaluation_panel_member_current": (CORE,),
    "learning_original_evaluation_cohort_readback_current": (PROVIDER, MEMBER),
    "learning_original_evaluation_cohort_member_binding": (BINDING,),
    "learning_original_evaluation_cohort_final_authentication": (MEMBER,),
}


class OriginalEvaluationPanelClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def code(self, source):
        return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))

    def verifies(self, path, source):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertEqual(len(rows), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})

    def rejects(self, path, function, marker, replacement=""):
        source = (ROOT / path).read_text()
        code = self.code(source)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        offset = source.index(marker, start, end + 1)
        self.verifies(path, source)
        changed = source[:offset] + replacement + source[offset + len(marker):]
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(path, changed)

    def test_exact_original_panel_edges_remain_closed(self):
        paths = {
            path for identifier in EXPECTED
            for path in (
                self.boundaries[identifier].definition_path,
                *self.boundaries[identifier].product_callers,
            )
        }
        sources = {path: self.code((ROOT / path).read_text()) for path in paths}
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, expected)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                extra = dict(sources)
                extra[AGENT + "unregistered_panel.rs"] = (
                    f"fn bypass(owner: &mut {row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())

    def test_registration_rejects_empty_duplicate_and_rebound_original_tasks(self):
        for marker in (
            "retention.is_empty() || retention.len() > MAX_RETENTION_TASKS",
            "task.task_digest.is_zero()",
            "task.cohort_rule_digest.is_zero()",
            "!plans.insert(task.plan_id.clone())",
            "!tasks.insert(task.task_digest)",
            "bytes.extend_from_slice(task.task_digest.as_array())",
            "bytes.extend_from_slice(task.cohort_rule_digest.as_array())",
            "profile: Digest32::of_bytes(&bytes)",
        ):
            self.rejects(CONTRACT, "fn new(", marker)
        for marker in (
            "retention.len() != registration.retention().len()",
            "first.training.request.evaluation_profile != registration.evaluation_profile()",
            "config.plan.product_plan().frozen_plan.plan_id != task.plan_id",
            "record.candidate.cost.identity().task_digest != task.task_digest.into_array()",
            "record.fixed_expert.cost.identity().task_digest != task.task_digest.into_array()",
            "!namespaces.insert(config.execution_namespace)",
            "!namespaces.insert(config.qualification_namespace)",
        ):
            self.rejects(BINDING, "fn validate_original_members(", marker)

    def test_each_member_retains_full_original_training_roles_and_config(self):
        for marker in (
            "let saved = original::validate_config(config)?",
            "member.qualification.saved != saved",
            "config.training != first.training",
            "config.scope != first.scope",
            "config.training_evidence != first.training_evidence",
            "config.context.generator != first.context.generator",
            "config.context.evaluator != first.context.evaluator",
            "config.verifier.trust_digest() != first.verifier.trust_digest()",
            "config.verifier.scope_digest() != first.verifier.scope_digest()",
            "config.verifier.objective_digest() != first.verifier.objective_digest()",
        ):
            self.rejects(BINDING, "fn validate_original_members(", marker)
        for marker in (
            "observed.product_evidence != config.product_evidence",
            "observed.execution_evidence != config.execution_evidence",
            "original::authenticate(config, &observed.prepared, current)?",
            "revalidate_product_qualification_v1(",
            "if observed.qualification.product().decision != decision",
        ):
            self.rejects(MEMBER, "fn authenticate(", marker)

    def test_both_physical_cells_and_actual_completed_qualification_are_read(self):
        for marker in (
            "CellGenerationJournalV2::read_current_checkpoint(&mut self.candidate)?",
            "CellGenerationJournalV2::read_current_checkpoint(&mut self.fixed_expert)?",
            "candidate != record.candidate.journal_cut",
            "fixed_expert != record.fixed_expert.journal_cut",
            "candidate_scope.run_id == source_run || baseline_scope.run_id == source_run",
        ):
            self.rejects(MEMBER, "fn read_cells(", marker)
        for marker in (
            "let before = self.read_cells()?",
            "self.qualification.completed_bytes()?",
            "OriginalCellEvaluationQualificationSourcesV1::prepare_with_training(\n"
            "            &mut sources,\n"
            "            &self.qualification.config,\n"
            "            started_at,\n"
            "            training,\n"
            "        )\n        .await?",
            "OriginalCellEvaluationQualificationOwnerV1::finish_readback_with_training(",
            "drop(sources)",
            "let after = self.read_cells()?",
            "if before != after",
        ):
            self.rejects(MEMBER, "fn read_original(", marker)
        self.rejects(MEMBER, "fn read_original(", "false", "true")
        for effect in ("owner.qualify_or_readback()", "File::open(path)", "self.qualification.config = changed"):
            with self.assertRaises(PROOF.VerificationFailure):
                self.verifies(MEMBER, (ROOT / MEMBER).read_text() + "\nfn bypass() { " + effect + "; }\n")

    def test_all_original_reads_precede_fresh_auth_and_unknown_never_rearms(self):
        self.rejects(CORE, "fn read_current(", "self.read_current_with_clock(original::now).await")
        self.rejects(
            CORE,
            "fn read_current_with_clock(",
            "self.read_current_with_training(&mut clock, &mut OriginalPanelTrainingReadV1::Individual)",
        )
        for marker in ("self.fenced = true", "if result.is_ok()", "self.read_original_panel(&mut clock, training).await"):
            self.rejects(CORE, "fn read_current_with_training(", marker)
        for marker in (
            "let before = self.read_members(clock, training).await?",
            "let after = self.read_members(clock, training).await?",
            "if before != after",
            "self.require_observed_panel(&after)?",
            "let current = clock()?",
            "original::clock_time(started_at, current)?",
            "self.primary.authenticate(&after[0], current)?",
            "owner.authenticate(observed, current)?",
            "self\n            .retained\n            .as_ref()\n            .is_some_and(|original| original != &result)",
        ):
            self.rejects(CORE, "fn read_original_panel(", marker)
        for marker in (
            "let current = clock()?",
            "original::clock_time(started_at, current)?",
            "self.authenticate(&observed, current)?",
        ):
            self.rejects(MEMBER, "fn read_original(", marker)

    def test_primary_signature_must_name_the_complete_actual_nonempty_panel(self):
        for marker in (
            "observed.is_empty()",
            "== IndependentEvaluationDispositionV1::InsufficientEvidence",
            "member_runs.iter().any(|run| runs.contains(run))",
            "member.task != self.registration.retention()[index - 1]",
            "retained_digests.push(member.qualification.product().evidence_digest)",
            "retained_digests.is_empty()",
            "retained_digests.windows(2).any(|pair| pair[0] == pair[1])",
            "self\n                .primary\n                .qualification\n                .config\n                .context\n                .retention_receipt_digests",
            "observed[0].prepared.bundle.retention_receipt_digests != retained_digests",
        ):
            self.rejects(BINDING, "fn require_observed_panel(", marker)
        for addition in (
            "impl Deserialize for OriginalCellEvaluationPanelReadbackV1 {}",
            "pub fn from_receipt() {}",
            "struct Bypass { pub retention: Vec<Receipt> }",
        ):
            with self.assertRaises(PROOF.VerificationFailure):
                self.verifies(CONTRACT, (ROOT / CONTRACT).read_text() + "\n" + addition + "\n")

    def test_each_member_consumes_exact_original_cohort_custody(self):
        self.verifies(MEMBER, (ROOT / MEMBER).read_text())
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(
                MEMBER,
                (ROOT / MEMBER).read_text().replace(
                    "pub cohort: OriginalCircuitEvaluationCohortReadbackV1",
                    "pub cohort: Option<OriginalCircuitEvaluationCohortReadbackV1>",
                    1,
                ),
            )
        for marker in (
            "OriginalCircuitEvaluationCohortReadbackV1::require_original_member(",
            "&member.cohort,",
            "registration,",
            "task,",
            "&config.training,",
            "&config.scope,",
            "&config.plan,",
            "&config.training_evidence,",
            "&config.verifier,",
        ):
            self.rejects(BINDING, "fn validate_original_members(", marker)
        self.rejects(BINDING, "fn seal_observed_panel(", "member.cohort.binding()")
        for addition in (
            "pub async fn read_current_with_clock() {}",
            "pub(crate) async fn read_current_with_clock() {}",
            "pub(super) async fn read_current_with_clock() {}",
        ):
            with self.assertRaises(PROOF.VerificationFailure):
                self.verifies(CORE, (ROOT / CORE).read_text() + "\n" + addition + "\n")

    def test_original_cohort_current_brackets_all_members_before_final_clock(self):
        self.rejects(MEMBER, "fn read_original(", "let started_at = original::now()?")
        for marker in (
            "let cohort_before =\n            OriginalCircuitEvaluationCohortReadbackV1::read_current(&mut self.cohort)?",
            "let cohort_after =\n            OriginalCircuitEvaluationCohortReadbackV1::read_current(&mut self.cohort)?",
            "cohort_before != cohort_after",
            "cohort: cohort_after",
            "let current = clock()?",
            "original::clock_time(started_at, current)?",
        ):
            self.rejects(MEMBER, "fn read_original(", marker)
        for marker in (
            "OriginalCircuitEvaluationCohortReadbackV1::authenticate_current(",
            "&mut self.cohort,",
            "&observed.cohort,",
        ):
            self.rejects(MEMBER, "fn authenticate(", marker)
        self.rejects(
            CORE,
            "fn read_original_panel(",
            "self.retention.iter_mut().zip(after.iter().skip(1))",
        )


if __name__ == "__main__":
    unittest.main()
