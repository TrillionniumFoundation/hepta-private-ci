"""Guard positive Model publication, original Version and Selector ownership.

These checks preserve source boundaries; they do not attest deployment custody,
ordinary adoption, native execution or benefits over time.
"""
import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "positive_model_version_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
EXPECTED = {
    "learning_positive_model_original_context": [
        "codex-rs/hepta-agentd/src/circuit_learning_model_context.rs"
    ],
    "learning_positive_model_original_predecessors": [
        "codex-rs/hepta-agentd/src/circuit_learning_model_context.rs"
    ],
    "learning_positive_publication_context_model": [],
    "learning_positive_publication_context_receipt": [],
    "learning_positive_publication_context_authenticate": [
        "codex-rs/hepta-agentd/src/circuit_candidate_learning_read_wire.rs",
        "codex-rs/hepta-agentd/src/circuit_learning_model_binding.rs",
        "codex-rs/hepta-agentd/src/circuit_learning_model_publication.rs",
        "codex-rs/hepta-agentd/src/circuit_learning_model_recovery.rs",
        "codex-rs/hepta-agentd/src/circuit_model_version_client.rs",
        "codex-rs/hepta-agentd/src/circuit_model_version_wire.rs",
        "codex-rs/hepta-agentd/src/circuit_model_version_state.rs",
        "codex-rs/hepta-agentd/src/circuit_model_version_task.rs",
        "codex-rs/hepta-agentd/src/circuit_model_version_service.rs"
    ],
    "learning_positive_publication_context_material": [
        "codex-rs/hepta-agentd/src/circuit_learning_model_publication.rs",
        "codex-rs/hepta-agentd/src/circuit_learning_model_recovery.rs",
        "codex-rs/hepta-agentd/src/circuit_model_selection_receipt_remote.rs",
        "codex-rs/hepta-agentd/src/circuit_model_version_effect.rs",
        "codex-rs/hepta-agentd/src/circuit_model_version_state.rs"
    ],
    "learning_positive_publication_context_version_pin": [
        "codex-rs/hepta-agentd/src/circuit_model_version_wire.rs",
        "codex-rs/hepta-agentd/src/circuit_model_version_client.rs",
        "codex-rs/hepta-agentd/src/circuit_model_version_state.rs",
        "codex-rs/hepta-agentd/src/circuit_model_version_service.rs"
    ],
    "learning_positive_publication_prepare": [],
    "learning_positive_publication_publish": [],
    "learning_positive_publication_task": [],
    "learning_positive_publication_recover": [],
    "learning_positive_selection_owner_consume": [],
    "learning_positive_selection_owner_profile": [
        "codex-rs/hepta-agentd/src/circuit_model_selection_command_service.rs"
    ],
    "learning_positive_selection_owner_factory": [
        "codex-rs/hepta-agentd/src/circuit_model_selection_receipt_owner.rs"
    ],
    "learning_positive_selection_remote_attest": [
        "codex-rs/hepta-agentd/src/circuit_model_selection_command_service.rs"
    ],
    "learning_positive_selection_remote_readback": [
        "codex-rs/hepta-agentd/src/circuit_model_selection_command_service.rs",
        "codex-rs/hepta-agentd/src/circuit_model_selection_command_evidence.rs"
    ],
    "learning_positive_selection_client_create": [],
    "learning_positive_selection_client_recover": [],
    "learning_positive_selection_client_bind": [],
    "learning_positive_selection_client_attest": [],
    "learning_positive_selection_client_readback": [],
    "learning_positive_selection_client_evidence": [],
    "learning_positive_selection_receipt_context": [
        "codex-rs/hepta-agentd/src/circuit_candidate_learning_read_capability.rs"
    ],
    "learning_positive_selection_owner_serve": [],
    "learning_positive_selection_owner_evidence": [],
    "learning_positive_version_client_bind": [],
    "learning_positive_version_client_recover": [],
    "learning_positive_version_client_publish": [],
    "learning_positive_version_client_readback": [],
    "learning_positive_version_owner_create": [],
    "learning_positive_version_owner_recover": [],
    "learning_positive_version_owner_publish": [
        "codex-rs/hepta-agentd/src/circuit_model_version_service.rs"
    ],
    "learning_positive_version_owner_readback": [
        "codex-rs/hepta-agentd/src/circuit_model_version_service.rs"
    ],
    "learning_positive_version_owner_serve": [],
    "learning_positive_version_owner_ordinary": [],
    "learning_positive_version_owner_run_c": [],
    "learning_positive_version_owner_selection_read": [],
    "learning_positive_version_owner_next_use_read": [],
    "learning_positive_version_owner_readiness": [],
    "learning_positive_version_original_issuer_attenuation": [
        "codex-rs/hepta-agentd/src/circuit_model_version_host.rs"
    ],
    "learning_positive_version_original_issuer_request": [
        "codex-rs/hepta-agentd/src/circuit_model_version_effect.rs"
    ],
    "learning_positive_published_next_use_version_serve": [
        "codex-rs/hepta-agentd/src/circuit_model_version_service.rs"
    ],
    "learning_positive_published_readiness_version_serve": [
        "codex-rs/hepta-agentd/src/circuit_model_version_service.rs"
    ]
}
FUNCTIONS = {
    "codex-rs/hepta-agentd/src/circuit_learning_model_context.rs": [
        "fn with_original_model(",
        "fn from_original_model(",
        "fn from_original_receipt(",
        "fn authenticate_at_current(",
        "fn duplicate_response_pin(",
        "fn original_version_binding(",
        "fn authenticate_material("
    ],
    "codex-rs/hepta-agentd/src/circuit_learning_model_binding.rs": [
        "fn require_previous(",
        "fn require_published("
    ],
    "codex-rs/hepta-agentd/src/circuit_learning_model_publication.rs": [
        "fn into_original_task(",
        "fn publish_original_model_task(",
        "fn load_original_selection(",
        "fn drop(",
        "fn require_not_cancelled(",
        "fn require_predecessor_window("
    ],
    "codex-rs/hepta-agentd/src/circuit_learning_model_recovery.rs": [],
    "codex-rs/hepta-agentd/src/root_model_version_issuer.rs": [
        "fn into_original_model_version_issuer(",
        "fn request_for_original_model_version("
    ],
    "codex-rs/hepta-agentd/src/circuit_model_version_wire.rs": [
        "fn new(",
        "fn require_initial(",
        "fn require_context(",
        "fn decode(",
        "fn digest("
    ],
    "codex-rs/hepta-agentd/src/circuit_model_version_client.rs": [
        "fn drop(",
        "fn bind_original_stage_channel(",
        "fn recover_original_stage_channel(",
        "fn bind(",
        "fn exchange("
    ],
    "codex-rs/hepta-agentd/src/circuit_model_version_host.rs": [
        "fn from_original_owners(",
        "fn recover_from_original_owners(",
        "fn new(",
        "fn require_lifetime(",
        "fn original_predecessors("
    ],
    "codex-rs/hepta-agentd/src/circuit_model_version.rs": [
        "fn require_clock("
    ],
    "codex-rs/hepta-agentd/src/circuit_model_version_effect.rs": [
        "fn drop(",
        "fn publish_original(",
        "fn require_not_cancelled("
    ],
    "codex-rs/hepta-agentd/src/circuit_model_version_state.rs": [
        "fn require_prepared_control(",
        "fn read_original("
    ],
    "codex-rs/hepta-agentd/src/circuit_model_version_artifact.rs": [
        "fn new(",
        "fn read_current(",
        "fn require_same("
    ],
    "codex-rs/hepta-agentd/src/circuit_model_version_task.rs": [
        "fn require_completed_a(",
        "fn install_original(",
        "fn observe("
    ],
    "codex-rs/hepta-agentd/src/circuit_model_version_service.rs": [
        "fn serve_commands(",
        "fn command_response(",
        "fn serve_original_ordinary(",
        "fn run_original_c(",
        "fn wait_installed(",
        "fn serve_original_selection_readback(",
        "fn original_next_use_reader(",
        "fn remaining_lifetime(",
        "fn drop(",
        "fn require_not_cancelled(",
        "fn serve_original_next_use_readback(",
        "fn serve_original_completion_readiness("
    ],
    "codex-rs/hepta-agentd/src/circuit_model_selection_receipt_owner.rs": [
        "fn create(",
        "fn recover(",
        "fn attest_original_selection(",
        "fn readback(",
        "fn read_original(",
        "fn authenticate_completed(",
        "fn into_command_owner(",
        "fn original_command_profile("
    ],
    "codex-rs/hepta-agentd/src/circuit_model_selection_receipt_binding.rs": [
        "fn validate_config(",
        "fn authenticate_roles(",
        "fn authenticate(",
        "fn receipt(",
        "fn sign_original(",
        "fn signature_expiry(",
        "fn new_work_time(",
        "fn now(",
        "fn sign_original_until("
    ],
    "codex-rs/hepta-agentd/src/circuit_model_selection_receipt_remote.rs": [
        "fn attest_original_remote_selection(",
        "fn readback_remote(",
        "fn remote_result(",
        "fn remote_operation("
    ],
    "codex-rs/hepta-agentd/src/circuit_model_selection_command_wire.rs": [
        "fn require_context(",
        "fn require_request(",
        "fn encode_completed(",
        "fn decode_completed(",
        "fn authenticate_completed(",
        "fn require_selection_context(",
        "fn authenticate_receipt("
    ],
    "codex-rs/hepta-agentd/src/circuit_model_selection_command.rs": [
        "fn original_publication_context(",
        "fn drop(",
        "fn from_original_stream(",
        "fn recover_from_original_stream(",
        "fn bind_original_stage_channel(",
        "fn bind_original_stream(",
        "fn execute_selection(",
        "fn readback(",
        "fn receipt_attestation(",
        "fn exchange(",
        "fn require_clock("
    ],
    "codex-rs/hepta-agentd/src/circuit_model_selection_command_service.rs": [
        "fn from_original_receipt_owner(",
        "fn serve_command_channel(",
        "fn command_response(",
        "fn original_response(",
        "fn original_state(",
        "fn serve_commands(",
        "fn serve_evidence_readback("
    ],
    "codex-rs/hepta-agentd/src/circuit_model_selection_command_evidence.rs": [
        "fn serve_evidence_channel(",
        "fn evidence_response("
    ],
    "codex-rs/hepta-agentd/src/circuit_candidate_learning_read_service.rs": [
        "fn from_original_owners(",
        "fn serve_readback(",
        "fn serve_original_candidate_channel(",
        "fn response(",
        "fn require_task_input_current(",
        "fn require_original_selection(",
        "fn read_original(",
        "fn serve_original_next_use_channel(",
        "fn serve_original_readiness_channel("
    ],
    "codex-rs/hepta-agentd/src/cell_q24_model_command.rs": [
        "fn require_original_context(",
        "fn original_predecessors_for_publication("
    ]
}
MODEL = "codex-rs/hepta-agentd/src/cell_q24_model_command.rs"


def function_body(source, function):
    code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    if code.count(function) != 1:
        raise AssertionError(("unique actual function", function))
    start = code.index(function)
    end = PROOF._rust_item_end(code, start)
    if end is None:
        raise AssertionError(("complete actual function", function))
    return start, end, code[start:end + 1]


def version_locks_do_not_span_io(source):
    _, _, body = function_body(source, "fn publish_original(")
    locks = list(re.finditer(r"self\s*\.\s*state\s*\.\s*try_lock\s*\(", body))
    if len(locks) != 3:
        raise AssertionError("only three explicit bounded Version state scopes")
    for match in locks:
        stack = []
        for offset, char in enumerate(body[:match.start()]):
            if char == "{":
                stack.append(offset)
            elif char == "}":
                stack.pop()
        if len(stack) != 2:
            raise AssertionError("Version mutex must be confined to a local block")
        end = stack[-1] + 1
        depth = 1
        while depth:
            if body[end] == "{":
                depth += 1
            elif body[end] == "}":
                depth -= 1
            end += 1
        scope = body[stack[-1]:end]
        if re.search(r"\bawait\b|request_for_original_model_version|begin_original_model_read|install_original|::publish\s*\(", scope):
            raise AssertionError("no peer or native effect while Version mutex is held")


class PositiveModelVersionSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}
        cls.rows = []
        for path, expected in FUNCTIONS.items():
            rows = [row for row in cls.manifest["protected_file"] if row["path"] == path]
            if path == MODEL:
                rows = [row for row in rows if {
                    "fn require_original_context(", "fn original_predecessors_for_publication("
                } == {item["function"] for item in row.get("required_function_order", [])}]
            if len(rows) != 1:
                raise AssertionError(("one complete owned contract record", path))
            row = rows[0]
            if set(expected) != {
                item["function"] for item in row.get("required_function_order", [])
            }:
                raise AssertionError(("complete exact owned function inventory", path))
            cls.rows.append(row)

    def test_complete_positive_owner_records_validate(self):
        PROOF._verify_protected_files(ROOT, {"protected_file": self.rows})
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_exact_private_edges_and_unregistered_callers(self):
        paths = set(FUNCTIONS)
        for identifier in EXPECTED:
            row = self.boundaries[identifier]
            paths.add(row.definition_path)
            paths.update(row.product_callers)
        for name in (
            "circuit_candidate_learning_read_capability.rs",
            "circuit_candidate_learning_read_wire.rs",
            "circuit_model_version.rs", "circuit_model_version_host.rs",
            "cell_q24_model_command_client.rs", "cell_q24_model_command_context.rs",
            "neuron_cell_evaluation_model_material.rs",
        ):
            paths.add("codex-rs/hepta-agentd/src/" + name)
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
                changed = dict(sources)
                method = row.symbol.rsplit("::", 1)[-1]
                if row.receiver_type:
                    injection = f"fn bypass(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                else:
                    injection = f"fn bypass() {{ {row.symbol}(); }}"
                changed["codex-rs/hepta-agentd/src/unregistered_model_publication.rs"] = injection
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, changed, ())

    def test_each_actual_function_keeps_a_security_guard_in_code(self):
        for row in self.rows:
            source = (ROOT / row["path"]).read_text()
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / row["path"]
                target.parent.mkdir(parents=True)
                target.write_text(source)
                PROOF._verify_protected_files(root, {"protected_file": [row]})
                for rule in row.get("required_function_order", []):
                    start, _, body = function_body(source, rule["function"])
                    candidates = [
                        marker for marker in rule["sequence"]
                        if body.count(marker) == 1 and not marker.startswith("fn ")
                        and marker not in ("Ok(())", "Ok(current)", "Ok(original)")
                    ]
                    self.assertTrue(candidates, (row["path"], rule["function"]))
                    marker = max(candidates, key=len)
                    offset = start + body.index(marker)
                    with self.subTest(path=row["path"], function=rule["function"], guard=marker):
                        changed = source[:offset] + source[offset + len(marker):]
                        target.write_text(changed + "\n/* " + marker + " */\n")
                        with self.assertRaises(PROOF.VerificationFailure):
                            PROOF._verify_protected_files(root, {"protected_file": [row]})

    def test_generic_publication_and_cold_recovery_keep_actual_order(self):
        for row in self.rows:
            source = (ROOT / row["path"]).read_text()
            code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / row["path"]
                target.parent.mkdir(parents=True)
                for sequence in row.get("required_order", []):
                    candidates = [
                        marker for marker in sequence
                        if code.count(marker) == 1 and not marker.startswith("fn ")
                    ]
                    self.assertTrue(candidates, row["path"])
                    for marker in candidates:
                        offset = code.index(marker)
                        with self.subTest(path=row["path"], guard=marker):
                            changed = source[:offset] + source[offset + len(marker):]
                            target.write_text(changed + "\n/* " + marker + " */\n")
                            with self.assertRaises(PROOF.VerificationFailure):
                                PROOF._verify_protected_files(root, {"protected_file": [row]})

    def test_version_releases_mutex_before_original_model_root_and_native_io(self):
        path = "codex-rs/hepta-agentd/src/circuit_model_version_effect.rs"
        source = (ROOT / path).read_text()
        version_locks_do_not_span_io(source)
        _, _, body = function_body(source, "fn publish_original(")
        self.assertEqual(body.count("request_for_original_model_version("), 1)
        start, _, _ = function_body(source, "fn publish_original(")
        open_brace = PROOF._strip_rust_non_code(source).index("{", start)
        changed = source[:open_brace + 1] + (
            "\nlet leaked = self.state.try_lock();\n"
        ) + source[open_brace + 1:]
        with self.assertRaises(AssertionError):
            version_locks_do_not_span_io(changed)

    def test_owner_provisioning_reconnect_and_public_capability_mutations_fail(self):
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

    def test_version_and_selector_purposes_remain_distinct_real_constants(self):
        for path, declaration, purpose in (
            ("circuit_model_version_wire.rs", "pub(super) const PURPOSE: &str",
             "runtime.learning.original-circuit-model-version.command.v1"),
            ("circuit_model_selection_command_wire.rs", "pub(super) const OPERATION: &str",
             "runtime.learning.original-circuit-model-selection.command.v1"),
            ("root_model_version_issuer.rs", "const DESTINATION: &str",
             "agentd.cell-generation.replace-drained"),
        ):
            source = (ROOT / "codex-rs/hepta-agentd/src" / path).read_text()
            def check(text):
                code = PROOF._strip_rust_non_code(text)
                self.assertEqual(code.count(declaration), 1)
                offset = code.index(declaration) + len(declaration)
                self.assertIsNotNone(re.match(
                    r'\s*=\s*"' + re.escape(purpose) + r'";', text[offset:]
                ))
            check(source)
            changed = source.replace(purpose, purpose + ".wrong", 1)
            changed += "\n// " + declaration + ' = "' + purpose + '";\n'
            with self.subTest(purpose=purpose):
                with self.assertRaises(AssertionError):
                    check(changed)


if __name__ == "__main__":
    unittest.main()
