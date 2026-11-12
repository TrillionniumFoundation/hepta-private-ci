"""Guard actual positive Model readback without granting ordinary Root authority."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_model_selection_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
OWNER = AGENT + "circuit_model_selection_receipt_owner.rs"
SOURCES = AGENT + "circuit_model_selection_receipt_sources.rs"
BINDING = AGENT + "circuit_model_selection_receipt_binding.rs"
FUNCTIONS = {
    OWNER: {
        "fn create(", "fn recover(", "fn attest_original_selection(", "fn readback(",
        "fn read_original(", "fn authenticate_completed(",
    },
    SOURCES: {
        "fn prepare(", "fn predecessors(", "fn read_original(",
    },
    BINDING: {
        "fn validate_config(", "fn authenticate_roles(", "fn authenticate(",
        "fn receipt(", "fn sign_original(", "fn signature_expiry(",
        "fn new_work_time(", "fn now(",
    },
}


class OriginalModelSelectionClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def rejects(self, path, function, marker):
        source = (ROOT / path).read_text()
        start = source.index(function)
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
        self.assertIsNotNone(end)
        offset = source.index(marker, start, end + 1)
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertEqual(len(rows), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(source[:offset] + source[offset + len(marker):])
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_each_original_owner_and_fresh_signature_guard_is_effective(self):
        for path, expected in FUNCTIONS.items():
            rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
            self.assertEqual(len(rows), 1)
            functions = rows[0]["required_function_order"]
            self.assertEqual({row["function"] for row in functions}, expected)
            for function in functions:
                for marker in function["sequence"]:
                    with self.subTest(path=path, function=function["function"], marker=marker):
                        self.rejects(path, function["function"], marker)

    def test_selection_binds_original_completed_task_before_version_readback(self):
        path = AGENT + "circuit_feature_current_learning.rs"
        for marker in (
            "self.task.require_current()?",
            "if previous.source.history_digest().as_str()",
            "!= coordinator\n                .snapshot()\n                .request\n                .completed_task_receipt\n                .to_string()",
            "return Err(invalid(\n                \"learning selection differs from original completed source\",",
        ):
            with self.subTest(marker=marker):
                self.rejects(path, "fn read_learning_selection(", marker)

    def test_actual_model_execution_and_publication_edges_are_exact(self):
        expected = {
            "learning_source_bound_training_stage_model_readback": (SOURCES,),
            "cell_original_completed_evaluation_evidence_readback": (SOURCES, AGENT + "neuron_cell_evaluation_qualification_sources.rs"),
            "product_original_execution_evidence_revalidate": (BINDING, AGENT + "neuron_cell_evaluation_qualification_binding.rs"),
            "circuit_feature_original_selection_observation": ("codex-rs/hepta-agentd/src/circuit_selection_receipt_owner.rs", "codex-rs/hepta-agentd/src/circuit_model_selection_receipt_sources.rs", "codex-rs/hepta-agentd/src/circuit_learning_read_service.rs", "codex-rs/hepta-agentd/src/circuit_learning_completion_readiness_service.rs", "codex-rs/hepta-agentd/src/circuit_retained_version_c_task.rs", "codex-rs/hepta-agentd/src/circuit_candidate_learning_read_service.rs", "codex-rs/hepta-agentd/src/circuit_candidate_learning_completion_readiness_service.rs",),
            "learning_original_owner_physical_current": (
                AGENT + "learning_owner_journal.rs",
                AGENT + "cell_composed_q24_training_owner.rs",
                AGENT + "cell_q24_model_proposal.rs",
                AGENT + "neuron_cell_evaluation_execution_store.rs",
                AGENT + "circuit_task_source_journal.rs",
            ),
        }
        paths = {path for identifier in expected for path in (
            self.boundaries[identifier].definition_path,
            *self.boundaries[identifier].product_callers,
        )}
        sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
            (ROOT / path).read_text())) for path in paths}
        for identifier, callers in expected.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, callers)
                PROOF._verify_boundary(ROOT, row, sources, ())
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_boundary(ROOT, replace(row, product_callers=()), sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                changed = dict(sources)
                changed[AGENT + "unregistered_positive_model.rs"] = (
                    f"fn unexpected(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, changed, ())

    def test_new_selector_owner_and_root_route_remain_closed(self):
        sources = {OWNER: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
            (ROOT / OWNER).read_text()))}
        for suffix in ("create", "recover", "attest", "readback"):
            identifier = "learning_original_circuit_model_selection_receipt_" + suffix
            row = self.boundaries[identifier]
            self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
            self.assertEqual(row.product_callers, ())
            PROOF._verify_boundary(ROOT, row, sources, ())
            method = row.symbol.rsplit("::", 1)[-1]
            changed = dict(sources)
            changed[AGENT + "unregistered_model_selector.rs"] = (
                f"fn unexpected(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
            )
            with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                PROOF._verify_boundary(ROOT, row, changed, ())
        self.assertEqual(self.boundaries["root_learning_original_stage_assembly"].product_callers, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_sources_cannot_replace_source_bound_model_or_original_execution_witness(self):
        source = (ROOT / SOURCES).read_text()
        rows = [row for row in self.manifest["protected_file"] if row["path"] == SOURCES]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / SOURCES
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            for old, new in (
                ("SourceBoundCellQ24TrainingStageV1", "OriginalCellQ24TrainingStageV1"),
                ("pub executions: &'a mut OriginalCellEvaluationExecutionStoreV1<W>",
                 "pub executions: Vec<u8>"),
                ("OriginalCellEvaluationExecutionStoreV1::readback_only(",
                 "OriginalCellEvaluationExecutionStoreV1::create("),
            ):
                with self.subTest(old=old):
                    target.write_text(source.replace(old, new))
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_selector_cannot_execute_model_holdout_publication_or_provision_custody(self):
        for path in (OWNER, SOURCES, BINDING):
            source = (ROOT / path).read_text()
            rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / path
                target.parent.mkdir(parents=True)
                target.write_text(source)
                PROOF._verify_protected_files(root, {"protected_file": rows})
                for mutation in (
                    "SigningKey::from_bytes(value);",
                    "LearningEvidenceVerifierV1::new(value);",
                    "owner.fit_or_readback(value);",
                    "owner.evaluate_or_readback(value);",
                    "owner.commit_model_or_readback(value);",
                    "owner.publish(value);",
                    "owner.claim_final_use(value);",
                    "File::open(value);",
                    "UnixStream::connect(value);",
                ):
                    with self.subTest(path=path, mutation=mutation):
                        target.write_text(source + "\nfn extra() { " + mutation + " }\n")
                        with self.assertRaises(PROOF.VerificationFailure):
                            PROOF._verify_protected_files(root, {"protected_file": rows})


if __name__ == "__main__":
    unittest.main()
