"""Original native work DATA must precede Root B plan and Generator signing."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
AGENT = "codex-rs/hepta-agentd/src/"
SPEC = importlib.util.spec_from_file_location("native_work_proof", ROOT / "scripts/verify_hepta_callers.py")
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)

BOUNDARIES = {
    "q24_native_original_work_read": ("cell_q24_training_stage_operation.rs",),
    "q24_native_original_work_verify": ("authority_host_q24_evaluation_model_data.rs",),
    "q24_training_original_work_evidence": ("root_independent_b_plan.rs",),
    "root_b_original_work_model": ("authority_host_q24_evaluation_benchmark.rs",),
    "root_b_original_work_read": ("authority_host_q24_evaluation_execution.rs", "authority_host_q24_evaluation_prepare.rs"),
}


class OriginalTrainingWorkSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def guards(self, name, function, markers, occurrence=0):
        path = AGENT + name + ".rs"
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        source = (ROOT / path).read_text()
        code = PROOF._strip_rust_non_code(source)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            for marker in markers:
                offset = start
                for _ in range(occurrence + 1):
                    offset = source.index(marker, offset, end + 1)
                    after = offset + len(marker)
                    if _ < occurrence:
                        offset = after
                for replacement in ("", "/* removed: " + marker + " */"):
                    with self.subTest(path=path, marker=marker, occurrence=occurrence, replacement=replacement):
                        target.write_text(source[:offset] + replacement + source[after:])
                        with self.assertRaises(PROOF.VerificationFailure):
                            PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_work_read_has_exact_callers_without_new_origin_authority(self):
        rows = {row.identifier: row for row in PROOF._boundary_rows(self.manifest)}
        paths = {rows[name].definition_path for name in BOUNDARIES}
        paths.update(AGENT + caller for callers in BOUNDARIES.values() for caller in callers)
        sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / path).read_text())) for path in paths}
        for name, callers in BOUNDARIES.items():
            row = rows[name]
            self.assertIn(name, self.manifest["privileged_inventory"]["required_boundary_ids"])
            self.assertEqual(row.product_callers, tuple(AGENT + caller for caller in callers))
            PROOF._verify_boundary(ROOT, row, sources, ())
            for caller in row.product_callers:
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_boundary(ROOT, replace(row, product_callers=tuple(p for p in row.product_callers if p != caller)), sources, ())
            changed = dict(sources)
            changed[AGENT + "unregistered_native_work.rs"] = f"fn unexpected() {{ {row.symbol}(); }}"
            with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                PROOF._verify_boundary(ROOT, row, changed, ())

    def test_writer_and_observer_share_the_exact_header_parser(self):
        self.guards("cell_composed_q24_training", "fn digest_for_original_batch(", (
            "!(1..=256).contains(&self.epochs)", "!(1..=codec::Q).contains(&self.learning_rate_q24)",
            "&self.epochs.to_le_bytes()", "&self.learning_rate_q24.to_le_bytes()", "batch.as_array()",
        ))
        self.guards("cell_composed_q24_training_owner", "fn decode(", (
            "result_data::decode_header(&mut bytes)?", "if binding != self.key.binding_digest",
            "metrics.batch_digest != self.batch.digest()",
            "metrics.optimizer_steps != u64::from(self.rule.epochs) * u64::from(self.batch.rows())",
        ))
        self.guards("cell_composed_q24_training_result_data", "fn decode_header(", (
            "if take::<8>(bytes)? !=", "binding: Digest32::from_array(take::<32>(bytes)?)",
            "tag: take::<1>(bytes)?[0]", "optimizer_steps: u64::from_le_bytes(take::<8>(bytes)?)",
            "elapsed_microseconds: u64::from_le_bytes(take::<8>(bytes)?)",
            "length: u32::from_le_bytes(take::<4>(bytes)?) as usize",
        ))

    def test_actual_read_rechecks_source_and_preserves_no_update(self):
        for occurrence in (0, 1):
            self.guards("cell_composed_q24_training_work", "fn read_original_work_with_source(",
                        ("self.require_current_with_source(source)?",), occurrence)
        self.guards("cell_composed_q24_training_work", "fn read_original_work_with_source(", (
            "original_dataset_cut != &self.plan.prefix", "self.journal.readback(&self.key)?",
            "self.decode(&payload)?", "prefix: payload[..PREFIX_BYTES].to_vec()",
            "epochs: self.rule.epochs", "learning_rate_q24: self.rule.learning_rate_q24",
            "CellQ24TrainingOutcomeV1::NoUpdate { .. } => None",
        ))
        self.guards("cell_q24_training_stage_operation", "fn read_original_training_evidence(", (
            "Self::read_original_completion_in_operation(self)?", "cut.record(",
            "CellQ24TrainingOwnerV1::read_original_work_with_source(", "&mut self.owners.training",
            "work,", "snapshot: cut.snapshot().clone()",
        ))

    def test_job_and_full_signed_preimage_bind_all_work_fields(self):
        self.guards("cell_composed_q24_training_work", "fn verify_original_training(", (
            "self.digest()?", "decode_header(&mut self.prefix.as_slice())?",
            "rows.replace(*actual).is_some()", "rule.digest_for_original_batch(header.metrics.batch_digest)?",
            "FrozenLearningScopeV2::freeze(", "receipt.predecessor.as_array()",
            "scope.binding().as_array()", "baseline.effective_weights_digest().as_array()",
            "header.metrics.batch_digest.as_array()", "optimizer.as_array()",
            "payload.extend_from_slice(heads)", "header.tag != 1", "header.binding != binding",
            "baseline.components() != &training.request.selected_bundle.components",
            "header.length != heads.len()", "header.length > 32_780",
            "model.original_head_bytes() != heads", "header.metrics.optimizer_rule != optimizer",
            "header.metrics.update_rule != update", "lineage.update_rule != update",
            "header.metrics.optimizer_steps != *steps", "*steps != u64::from(rows) * u64::from(self.epochs)",
            "*milliseconds != header.metrics.elapsed_microseconds.div_ceil(1_000).max(1)",
            "*artifact_bytes != heads.len() as u64", "receipt.evidence_digest",
            "header.binding.as_array()", "&payload",
        ))

    def test_capacity_is_from_actual_matrices_and_rule_not_manifest_claims(self):
        self.guards("cell_composed_q24_training_work", "fn verify_original_training(", (
            "usize::from(index) >= model.output_width()",
            "model.base.values.len() + model.encoder.values.len() + model.heads.values.len()",
            "adapter.down.values.len() + adapter.up.values.len()", "model.heads.cols as u64",
            ".checked_mul(width)", "examples_seen: u64::from(rows)", "optimizer_steps: *steps",
            "parameter_updates: updates", "compute_units: updates",
        ))
        self.guards("authority_host_q24_evaluation_protocol_comparison", "fn require_original_training_work(", (
            "self.candidate.capacity() != actual.capacity", "self.candidate.cumulative() != actual.cumulative",
            "self.candidate.selective_update() != actual.selective_update",
        ))
        self.guards("authority_host_q24_evaluation_protocol", "fn plans(", (
            "self.comparison.require_original_training_work(work)?",
        ))

    def test_root_uses_fixed_original_model_and_physical_candidate_twice(self):
        self.guards("authority_host_q24_evaluation_model_data", "fn observe_original_training_work(", (
            "self.load_baseline(baseline)?", "read_single_head_candidate_data(baseline, candidate, self.head, heads)",
            "OriginalQ24TrainingWorkDataV1::verify_original_training(", "&original_baseline,",
            "self.head,", "self.require_baseline(baseline)?",
        ))
        for occurrence in (0, 1):
            self.guards("authority_host_q24_evaluation_benchmark", "fn read_original_b_training_work(",
                        (".require_digest(candidate.components.heads, 32_780)?",), occurrence)

    def test_prepare_complete_and_readback_all_require_actual_work(self):
        self.guards("authority_host_q24_evaluation_prepare", "fn prepare_original_candidate<T>(", (
            "require_training(&authorities, &training, attestation, now)?",
            ".is_some_and(|old| old != training_work)", "enrollment.original_training_work = Some(training_work.clone())",
            "benchmark::prepare_original_cells(", "benchmark::read_original_b_training_work(files, enrollment, &training)?",
            "protocol.plans(&training, &actual_work)?", "training_work_digest: training_work",
            "benchmark::require_original_cells(files, enrollment, &training, &protocol)?",
        ))
        self.guards("authority_host_q24_evaluation_prepare", "fn prepare_original_candidate<T>(",
                    ("benchmark::require_original_cells(files, enrollment, &training, &protocol)?",), 1)
        for function in ("fn prepare_original_cells(", "fn require_original_cells("):
            self.guards("authority_host_q24_evaluation_benchmark", function, (
                "read_original_b_training_work(files, enrollment, training)?", "protocol.plans(training, &work)?",
            ))
        self.guards("authority_host_q24_evaluation_execution", "fn open(", (
            "super::benchmark::read_original_b_training_work(files, enrollment, training)?",
            "protocol.plans(training, &actual_work)?",
        ))

    def test_work_is_monotonic_before_ready_and_bound_to_generator_challenge(self):
        self.guards("authority_host_q24_evaluation_record", "fn register<T>(", ("enrollment.original_training_work.is_some()",))
        self.guards("authority_host_q24_evaluation_record", "fn inspect<T>(", (
            "immutable.original_training_work = original.original_training_work.clone()",
            ".is_some_and(|old| enrollment.original_training_work.as_ref() != Some(old))",
        ))
        self.guards("root_independent_b_plan", "fn require_original_training(", (
            "self.data.training_work_digest",
            "original\n                    .original_training_work()?\n                    .digest()",
        ))
        self.guards("cell_q24_training_b_plan", "fn attest_original_root_b_plan(", (
            "challenge.require_original_training(&original, &scope)?", ".commit_once(&key, ||",
            "challenge.require_original_training(&after, &scope)? != payload",
        ))

    def test_fixture_does_not_copy_fixed_work_into_the_candidate(self):
        protocol = (ROOT / AGENT / "ordinary_q24_b_evaluation_protocol_tests.rs").read_text()
        fixed = (ROOT / AGENT / "ordinary_q24_b_evaluation_fixed_tests.rs").read_text()
        self.assertIn("candidate: candidate_declaration", protocol)
        self.assertNotIn("candidate: control.arm", protocol)
        self.assertIn("fn declare_candidate(", fixed)
        self.assertIn("bytes.len() as u64 == 12 + 8 * rows * cols", fixed)
        self.assertIn("let optimizer_steps = examples_seen * u64::from(EPOCHS)", fixed)
        self.assertIn("worker.execute(&NeuronFeatureRequestV1", fixed)
        self.assertIn("updates += 1", fixed)


if __name__ == "__main__":
    unittest.main()
