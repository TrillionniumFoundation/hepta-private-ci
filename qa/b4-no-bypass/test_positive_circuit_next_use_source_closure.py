"""Positive Model/S/C source closure only; no ordinary learning acceptance.

The original NoUpdate profile remains separately closed. These checks audit
typed production callers and mutation resistance, not deployment custody or
scientific benefit. Native qualification runs on the final combined candidate.
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
    "positive_circuit_next_use_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
EXPECTED = {
    "learning_positive_published_context_model": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_adoption.rs", "codex-rs/hepta-agentd/src/circuit_model_version_service.rs",),
    "learning_positive_published_context_selection": ("codex-rs/hepta-agentd/src/circuit_candidate_learning_completion_readiness.rs", "codex-rs/hepta-agentd/src/circuit_candidate_next_use_command.rs", "codex-rs/hepta-agentd/src/circuit_model_version_service.rs",),
    "learning_positive_published_client_bind": (),
    "learning_positive_published_client_create": (),
    "learning_positive_published_client_current": ("codex-rs/hepta-agentd/src/circuit_candidate_next_use_receipt_sources.rs", "codex-rs/hepta-agentd/src/circuit_model_selection_receipt_remote.rs",),
    "learning_positive_published_client_context": ("codex-rs/hepta-agentd/src/circuit_candidate_next_use_command_service.rs", "codex-rs/hepta-agentd/src/circuit_model_selection_command_service.rs", "codex-rs/hepta-agentd/src/circuit_model_selection_receipt_remote.rs",),
    "learning_positive_published_owner_create": ("codex-rs/hepta-agentd/src/circuit_model_version_service.rs",),
    "learning_positive_published_owner_serve": (),
    "learning_positive_published_version_serve": ("codex-rs/hepta-agentd/src/circuit_model_version_service.rs",),
    "learning_positive_c_readiness_bind": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_next_use.rs",),
    "learning_positive_c_readiness_current": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_next_use.rs",),
    "learning_positive_c_readiness_serve": (),
    "learning_positive_next_use_context": ("codex-rs/hepta-agentd/src/circuit_candidate_next_use_command_stage_binding.rs",),
    "learning_positive_next_use_owner_consume": (),
    "learning_positive_next_use_owner_factory": ("codex-rs/hepta-agentd/src/circuit_candidate_next_use_receipt_sources.rs",),
    "learning_positive_next_use_client_create": (),
    "learning_positive_next_use_client_recover": (),
    "learning_positive_next_use_client_bind": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_next_use.rs",),
    "learning_positive_next_use_client_attest": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_next_use.rs",),
    "learning_positive_next_use_client_readback": ("codex-rs/hepta-agentd/src/cell_q24_candidate_stage_next_use.rs",),
    "learning_positive_next_use_client_attestation": (),
    "learning_positive_next_use_owner_serve": (),
    "learning_positive_next_use_owner_evidence": (),
    "learning_positive_next_use_remote_attest": ("codex-rs/hepta-agentd/src/circuit_candidate_next_use_command_service.rs",),
    "learning_positive_next_use_remote_readback": ("codex-rs/hepta-agentd/src/circuit_candidate_next_use_command_service.rs", "codex-rs/hepta-agentd/src/circuit_candidate_next_use_command_evidence.rs",),
}
PROTECTED = (
    "codex-rs/hepta-agentd/src/circuit_candidate_learning_read_capability.rs",
    "codex-rs/hepta-agentd/src/circuit_candidate_learning_read_wire.rs",
    "codex-rs/hepta-agentd/src/circuit_candidate_learning_read_service.rs",
    "codex-rs/hepta-agentd/src/circuit_candidate_learning_completion_readiness.rs",
    "codex-rs/hepta-agentd/src/circuit_candidate_learning_completion_readiness_service.rs",
    "codex-rs/hepta-agentd/src/circuit_candidate_next_use_command.rs",
    "codex-rs/hepta-agentd/src/circuit_candidate_next_use_command_stage_binding.rs",
    "codex-rs/hepta-agentd/src/circuit_candidate_next_use_command_wire.rs",
    "codex-rs/hepta-agentd/src/circuit_candidate_next_use_command_service.rs",
    "codex-rs/hepta-agentd/src/circuit_candidate_next_use_command_evidence.rs",
    "codex-rs/hepta-agentd/src/circuit_candidate_next_use_receipt_sources.rs",
)
PURPOSES = {
    AGENT + "circuit_candidate_learning_read_wire.rs": (
        "pub(super) const OPERATION: &str",
        "runtime.learning.original-circuit-candidate.current-read.v1",
    ),
    AGENT + "circuit_candidate_next_use_command_wire.rs": (
        "pub(super) const OPERATION: &str",
        "runtime.learning.original-circuit-candidate-next-use.command.v1",
    ),
    AGENT + "circuit_candidate_learning_completion_readiness.rs": (
        "const PURPOSE: &str",
        "runtime.learning.original-circuit-candidate.completion-readiness.v1",
    ),
}


def function_body(source, function):
    code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    if code.count(function) != 1:
        raise AssertionError(("unique function", function))
    start = code.index(function)
    end = PROOF._rust_item_end(code, start)
    if end is None:
        raise AssertionError(("complete function", function))
    return start, end, code[start:end + 1]


def ordered(source, function, markers):
    _, _, body = function_body(source, function)
    at = 0
    for marker in markers:
        found = body.find(marker, at)
        if found < at:
            raise AssertionError((function, marker))
        at = found + len(marker)


def fixed_purpose(source, declaration, expected):
    code = PROOF._strip_rust_non_code(source)
    if code.count(declaration) != 1:
        raise AssertionError("one actual purpose declaration")
    at = code.index(declaration) + len(declaration)
    if re.match(r'\s*=\s*"' + re.escape(expected) + r'";', source[at:]) is None:
        raise AssertionError("fixed positive operation purpose")


EXPIRY = (
    "config.selection.training_no_update_v2().is_none()",
    ".min(config.training_evidence.expires_at)",
    ".min(config.selection_evidence.expires_at)",
    ".min(config.selection.request.envelope.expiry_unix_seconds)",
    "} else {",
    "expires_at",
    "if expires_at <= issued_at",
    "let mut signed = SignedLearningEvidenceV1",
    "key.sign(&signed.signing_bytes()).to_bytes()",
)


class PositiveCircuitNextUseSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {
            row.identifier: row for row in PROOF._boundary_rows(cls.manifest)
        }
        cls.rows = [
            row for row in cls.manifest["protected_file"]
            if row["path"] in PROTECTED
        ]
        if len(cls.rows) != len(PROTECTED):
            raise AssertionError("all complete positive protected records are present")

    def test_exact_typed_edges_and_unregistered_callers_are_rejected(self):
        paths = set(PROTECTED)
        for identifier in EXPECTED:
            row = self.boundaries[identifier]
            paths.add(row.definition_path)
            paths.update(row.product_callers)
        sources = {
            path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
                (ROOT / path).read_text()
            ))
            for path in paths
        }
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertIn(
                    identifier,
                    self.manifest["privileged_inventory"]["required_boundary_ids"],
                )
                self.assertEqual(row.product_callers, expected)
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                extra = dict(sources)
                extra[AGENT + "unregistered_positive_owner.rs"] = (
                    f"fn bypass(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_complete_positive_protected_records_validate(self):
        PROOF._verify_protected_files(ROOT, {"protected_file": self.rows})

    def test_security_guards_cannot_be_removed_from_their_actual_function(self):
        for row in self.rows:
            source = (ROOT / row["path"]).read_text()
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / row["path"]
                target.parent.mkdir(parents=True)
                target.write_text(source)
                PROOF._verify_protected_files(root, {"protected_file": [row]})
                for rule in row["required_function_order"]:
                    start, end, body = function_body(source, rule["function"])
                    candidates = [
                        marker for marker in rule["sequence"]
                        if body.count(marker) == 1
                        and marker not in ("return Err(", "Ok(())", "Ok(current)")
                    ]
                    self.assertTrue(candidates, rule["function"])
                    for marker in candidates:
                        with self.subTest(
                            path=row["path"], function=rule["function"], guard=marker
                        ):
                            offset = start + body.index(marker)
                            changed = source[:offset] + source[offset + len(marker):]
                            target.write_text(changed)
                            with self.assertRaises(PROOF.VerificationFailure):
                                PROOF._verify_protected_files(
                                    root, {"protected_file": [row]}
                                )

    def test_new_adapters_cannot_gain_keys_writers_task_execution_or_reconnect(self):
        forbidden = (
            "SigningKey", "File::open", "UnixStream::connect", ".commit_once(",
            ".publish(", "execute_circuit_task_record(", "execute_cell_committed(",
            "with_root_learning_stage_owners(", "LearningEvidenceVerifierV1::new",
        )
        for row in self.rows:
            source = (ROOT / row["path"]).read_text()
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / row["path"]
                target.parent.mkdir(parents=True)
                for marker in forbidden:
                    with self.subTest(path=row["path"], forbidden=marker):
                        target.write_text(source + "\n" + marker + "\n")
                        with self.assertRaises(PROOF.VerificationFailure):
                            PROOF._verify_protected_files(root, {"protected_file": [row]})

    def test_positive_purposes_are_real_code_not_comment_evidence(self):
        for path, (declaration, purpose) in PURPOSES.items():
            source = (ROOT / path).read_text()
            fixed_purpose(source, declaration, purpose)
            changed = source.replace(purpose, purpose + ".wrong", 1)
            changed += "\n// " + declaration + ' = "' + purpose + '";\n'
            with self.subTest(path=path):
                with self.assertRaises(AssertionError):
                    fixed_purpose(changed, declaration, purpose)

    def test_positive_c_signature_cannot_outlive_original_s_or_model_windows(self):
        source = (ROOT / (AGENT + "circuit_next_use_receipt_owner.rs")).read_text()
        ordered(source, "fn sign_original(", EXPIRY)
        start, end, body = function_body(source, "fn sign_original(")
        for marker in EXPIRY[:4]:
            with self.subTest(cap=marker):
                offset = start + body.index(marker)
                changed = source[:offset] + source[offset + len(marker):]
                with self.assertRaises(AssertionError):
                    ordered(changed, "fn sign_original(", EXPIRY)

    def test_original_no_update_hard_profiles_are_preserved(self):
        checks = (
            (
                "circuit_selection_command.rs", "fn authenticate(",
                ("self.training.receipts.len() != 3", "TrainingNoUpdateV2"),
            ),
            (
                "circuit_next_use_command.rs", "fn authenticate(",
                ("self.selection.receipts.len() != 4", "TrainingNoUpdateV2", "*candidate_bundle == baseline"),
            ),
            (
                "circuit_next_use_command_wire.rs", "fn authenticate_receipt(",
                ("RetainedModelNextUse", "*retained_bundle == baseline", "!task_owner_publication.is_zero()"),
            ),
            (
                "circuit_learning_read_wire.rs", "fn mode(",
                ("TrainingNoUpdateV2", "(3, Some(LearningIterationStageV1::Selection), None)",
                 "(4, Some(LearningIterationStageV1::NextUse), Some(_))"),
            ),
        )
        for path, function, markers in checks:
            with self.subTest(path=path):
                ordered((ROOT / (AGENT + path)).read_text(), function, markers)


if __name__ == "__main__":
    unittest.main()
