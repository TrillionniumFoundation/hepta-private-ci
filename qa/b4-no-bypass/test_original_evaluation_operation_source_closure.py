"""Mutation closure for one actual Evaluator/Model-material operation.

These are source checks. Fixture journals and signed native mechanisms must be
executed separately; no ordinary adoption or daemon restart is claimed here.
"""
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_evaluation_operation_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
OP = AGENT + "neuron_cell_evaluation_training_operation.rs"
RECEIPT = AGENT + "neuron_cell_evaluation_receipt_operation.rs"
OWNER = AGENT + "neuron_cell_evaluation_receipt_owner.rs"
HOST = AGENT + "neuron_cell_evaluation_host.rs"
PANEL = AGENT + "neuron_cell_evaluation_panel.rs"
MEMBER = AGENT + "neuron_cell_evaluation_panel_member.rs"
SOURCE = AGENT + "neuron_cell_evaluation_qualification_sources.rs"
EXPORT = AGENT + "neuron_cell_evaluation_model_material_export.rs"
FACTORY = AGENT + "neuron_cell_evaluation_host_training_readback.rs"
CONNECTION = AGENT + "neuron_cell_evaluation_model_material_connection.rs"
MODEL_READ = AGENT + "neuron_cell_evaluation_model_read_operation.rs"
EXPECTED = {
    "learning_original_evaluation_operation_begin": (HOST,),
    "learning_original_evaluation_operation_finish": (HOST, EXPORT),
    "learning_original_evaluation_operation_member": (MEMBER, EXPORT),
    "learning_original_evaluation_operation_qualification": (SOURCE,),
    "learning_original_evaluation_operation_receipt": (RECEIPT,),
    "learning_original_evaluation_receipt_operation_attest": (OWNER, HOST),
    "learning_original_evaluation_receipt_operation_read": (OWNER, HOST),
    "learning_original_evaluation_panel_operation_current": (HOST,),
    "learning_original_evaluation_shared_training_host": (),
    "learning_original_evaluation_model_read_begin": (),
    "learning_original_evaluation_model_read_finish": (),
    "learning_original_evaluation_model_read_borrow": (),
}


class OriginalEvaluationOperationClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def rows(self, path):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows, path)
        return rows

    def reject_change(self, path, changed):
        original = (ROOT / path).read_text()
        self.assertNotEqual(original, changed)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(original)
            manifest = {"protected_file": self.rows(path)}
            PROOF._verify_protected_files(root, manifest)
            target.write_text(changed)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, manifest)

    def mutate_function_rules(self, path, selected=None):
        source = (ROOT / path).read_text()
        for row in self.rows(path):
            for rule in row.get("required_function_order", []):
                if selected is not None and rule["function"] not in selected:
                    continue
                for index, marker in enumerate(rule["sequence"]):
                    with self.subTest(path=path, function=rule["function"], marker=marker, index=index):
                        start = source.index(rule["function"])
                        code = PROOF._strip_rust_non_code(source)
                        end = PROOF._rust_item_end(code, start)
                        self.assertIsNotNone(end)
                        cursor = start
                        for token in rule["sequence"][:index + 1]:
                            at = source.index(token, cursor, end + 1)
                            cursor = at + len(token)
                        self.reject_change(path, source[:at] + source[cursor:])

    def test_private_original_operation_edges_have_exact_typed_callers(self):
        paths = {path for identifier in EXPECTED for path in (
            self.boundaries[identifier].definition_path,
            *self.boundaries[identifier].product_callers,
        )}
        sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
            (ROOT / path).read_text())) for path in paths}
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, expected)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                changed = dict(sources)
                changed[AGENT + "unregistered_evaluation_operation.rs"] = (
                    f"fn bypass(owner: &mut {row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, changed, ())

    def test_actual_before_after_full_context_and_same_connection_cannot_be_removed(self):
        self.mutate_function_rules(OP)
        source = (ROOT / OP).read_text()
        for marker in ("impl Clone for TrainingOperation", "Deserialize", "pub struct TrainingOperation"):
            with self.subTest(marker=marker):
                self.reject_change(OP, source + "\n" + marker + "\n")

    def test_whole_completion_and_export_finish_original_training_before_final_authentication(self):
        self.mutate_function_rules(HOST, {
            "fn begin_training_operation(", "fn complete_original_operation(",
            "fn read_original_completion(", "fn finish_original_completion(", "fn read_panel(",
        })
        self.mutate_function_rules(EXPORT)

    def test_consuming_factory_and_independent_public_paths_cannot_share_claimed_observations(self):
        self.mutate_function_rules(FACTORY)
        self.mutate_function_rules(SOURCE, {"fn read_training("})
        source = (ROOT / OWNER).read_text()
        for call in (
            "self.attest_with_training(source, TrainingRead::Independent).await",
            "self.readback_with_training(source, TrainingRead::Independent).await",
        ):
            self.assertEqual(source.count(call), 1)
            self.reject_change(OWNER, source.replace(call, "unchecked_original()"))

    def test_staged_material_keeps_original_channel_full_body_clock_and_cancellation(self):
        self.mutate_function_rules(CONNECTION)
        self.mutate_function_rules(MODEL_READ)

    def test_unfinished_material_cannot_restore_client_or_publish_a_transferable_proof(self):
        source = (ROOT / MODEL_READ).read_text()
        for marker in (
            "pub struct", "Clone", "Deserialize", "Serialize", "UnixStream::connect",
            "*self.expected", "*self.channel", "*self.retained", "SigningKey",
        ):
            with self.subTest(marker=marker):
                self.reject_change(MODEL_READ, source + "\n" + marker + "\n")
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_native_inventory_keeps_original_panels_and_adds_only_explicit_operation_mechanisms(self):
        spec = importlib.util.spec_from_file_location(
            "evaluation_operation_inventory", ROOT / "scripts/hepta_c_observer_coverage.py"
        )
        assert spec is not None and spec.loader is not None
        inventory = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(inventory)
        groups = {name: cases for name, _, cases in inventory.OWNER_GROUPS}
        self.assertEqual(groups["original_evaluation_host"], inventory.ORIGINAL_EVALUATION_HOST_CASES)
        self.assertEqual(groups["original_evaluation_model_material"], inventory.ORIGINAL_EVALUATION_MODEL_MATERIAL_CASES)
        self.assertEqual(groups["original_evaluation_operation"], inventory.ORIGINAL_EVALUATION_OPERATION_CASES)
        source = (ROOT / AGENT / "circuit_original_evaluation_operation_tests.rs").read_text()
        for case in inventory.ORIGINAL_EVALUATION_OPERATION_CASES:
            self.assertEqual(source.count("async fn " + case.rsplit("::", 1)[-1] + "("), 1)


if __name__ == "__main__":
    unittest.main()
