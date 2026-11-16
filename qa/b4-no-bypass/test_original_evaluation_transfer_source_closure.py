"""E same-operation source guards; native/ordinary acceptance remains separate."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_evaluation_transfer_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
EXPECTED = {
    "learning_original_evaluation_model_read_owned_begin": [
        "codex-rs/hepta-agentd/src/cell_q24_model_read_host_operation.rs"
    ],
    "learning_original_evaluation_model_read_current": [
        "codex-rs/hepta-agentd/src/cell_q24_model_read_host_operation.rs"
    ],
    "learning_original_evaluation_model_body": [
        "codex-rs/hepta-agentd/src/cell_q24_model_read_host_operation.rs"
    ],
    "learning_original_evaluation_model_body_decode": [
        "codex-rs/hepta-agentd/src/cell_q24_model_read_operation.rs"
    ],
    "learning_original_evaluation_publication_expiry": [
        "codex-rs/hepta-agentd/src/circuit_learning_model_context.rs"
    ],
    "learning_original_evaluation_selector_material": [
        "codex-rs/hepta-agentd/src/circuit_model_selection_receipt_remote.rs"
    ],
    "learning_original_evaluation_material_serve": []
}
PATHS = [
    "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_export.rs",
    "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_service.rs",
    "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_read_operation.rs",
    "codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material.rs"
]


class OriginalEvaluationTransferSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}
        cls.rows = [row for row in cls.manifest["protected_file"] if row["path"] in PATHS]
        if len(cls.rows) != len(PATHS):
            raise AssertionError("one complete record for each E transfer file")

    def test_all_e_transfer_records_validate(self):
        PROOF._verify_protected_files(ROOT, {"protected_file": self.rows})
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_new_private_edges_have_exact_typed_callers(self):
        paths = set(PATHS)
        for identifier in EXPECTED:
            row = self.boundaries[identifier]
            paths.add(row.definition_path)
            paths.update(row.product_callers)
        for file in (
            "cell_q24_model_read_host_operation.rs", "cell_q24_model_read_operation.rs",
            "cell_q24_model_command_host.rs", "cell_q24_model_command_client.rs",
            "neuron_cell_evaluation_model_material_connection.rs",
            "circuit_learning_model_context.rs", "circuit_model_selection_receipt_remote.rs",
        ):
            paths.add("codex-rs/hepta-agentd/src/" + file)
        sources = {
            path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
                (ROOT / path).read_text()
            )) for path in paths
        }
        fields = {}
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, tuple(expected))
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, sources, (), fields_by_receiver_type=fields)
                method = row.symbol.rsplit("::", 1)[-1]
                extra = dict(sources)
                extra["codex-rs/hepta-agentd/src/unregistered_e_transfer.rs"] = (
                    f"fn bypass(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())

    def test_guards_cannot_move_to_comments_or_out_of_function(self):
        for row in self.rows:
            source = (ROOT / row["path"]).read_text()
            code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / row["path"]
                target.parent.mkdir(parents=True)
                target.write_text(source)
                PROOF._verify_protected_files(root, {"protected_file": [row]})
                for rule in row["required_function_order"]:
                    function = rule["function"]
                    self.assertEqual(code.count(function), 1)
                    start = code.index(function)
                    end = PROOF._rust_item_end(code, start)
                    self.assertIsNotNone(end)
                    body = code[start:end + 1]
                    markers = [
                        marker for marker in rule["sequence"]
                        if body.count(marker) == 1 and marker not in ("Ok(())", "Ok(expiry)")
                    ]
                    self.assertTrue(markers, function)
                    for marker in markers:
                        offset = start + body.index(marker)
                        with self.subTest(path=row["path"], function=function, marker=marker):
                            changed = source[:offset] + source[offset + len(marker):]
                            target.write_text(changed + "\n/* " + marker + " */\n")
                            with self.assertRaises(PROOF.VerificationFailure):
                                PROOF._verify_protected_files(root, {"protected_file": [row]})

    def test_private_observations_cannot_gain_clone_decode_public_state_or_reconnect(self):
        for row in self.rows:
            source = (ROOT / row["path"]).read_text()
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / row["path"]
                target.parent.mkdir(parents=True)
                for marker in row["forbidden"]:
                    with self.subTest(path=row["path"], forbidden=marker):
                        target.write_text(source + "\n" + marker + "\n")
                        with self.assertRaises(PROOF.VerificationFailure):
                            PROOF._verify_protected_files(root, {"protected_file": [row]})


if __name__ == "__main__":
    unittest.main()
