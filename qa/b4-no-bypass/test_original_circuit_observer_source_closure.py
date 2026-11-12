"""Source and mutation checks for original, pinned C Observer custody.

Native ordinary-C tests are separate; these checks grant no enrollment authority.
"""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_c_observer_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
OWNER = AGENT + "circuit_next_use_receipt_owner.rs"
READERS = (
    AGENT + "learning_iteration_evaluation_evidence.rs",
    AGENT + "learning_iteration_generation_evidence.rs",
    AGENT + "neuron_cell_evaluation_training_operation.rs",
    OWNER,
    AGENT + "circuit_selection_receipt_owner.rs",
    AGENT + "cell_q24_training_source.rs",
        AGENT + "circuit_model_selection_receipt_sources.rs",
    AGENT + "neuron_cell_evaluation_qualification_sources.rs",
)
FUNCTIONS = {
    "fn create(", "fn recover(", "fn validate_config(", "fn prepare(",
    "fn attest_source(", "fn readback_source(", "fn predecessors(",
    "fn authenticate_completed(", "fn authenticate_predecessors(",
    "fn receipt(", "fn require_new_attestation(", "fn sign_original(", "fn now(",
    "fn attest_original_completion(", "fn attest_original_remote_completion(",
    "fn readback(", "fn readback_remote(", "fn read_local_next_use(",
    "fn read_remote_next_use(", "fn remote_predecessors(",
    "fn original_command_profile(", "fn into_command_owner(",
}


class OriginalCircuitObserverSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}
        cls.rows = [row for row in cls.manifest["protected_file"] if row["path"] == OWNER]
        cls.source = (ROOT / OWNER).read_text()
        identifiers = ["learning_evidence_original_owner_readback",
                       "circuit_feature_original_next_use_observation"]
        identifiers += ["learning_original_circuit_next_use_receipt_" + suffix
                        for suffix in ("create", "recover", "attest", "readback")]
        paths = {path for identifier in identifiers for path in (
            cls.boundaries[identifier].definition_path,
            *cls.boundaries[identifier].product_callers)}
        cls.sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
            (ROOT / path).read_text())) for path in paths}

    def rejects(self, changed):
        self.assertEqual(len(self.rows), 1)
        self.assertNotEqual(self.source, changed)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / OWNER
            path.parent.mkdir(parents=True)
            path.write_text(self.source)
            PROOF._verify_protected_files(root, {"protected_file": self.rows})
            path.write_text(changed)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": self.rows})

    def mutate_function(self, function, marker, replacement=""):
        code = PROOF._strip_rust_non_code(self.source)
        self.assertEqual(code.count(function), 1, function)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        assert end is not None
        body = self.source[start:end + 1]
        self.assertIn(marker, body, (function, marker))
        offset = start + body.index(marker)
        self.rejects(self.source[:offset] + replacement + self.source[offset + len(marker):])

    def test_real_read_edges_are_registered_and_owner_constructors_remain_closed(self):
        expected = {
            "learning_evidence_original_owner_readback": READERS,
            "circuit_feature_original_next_use_observation": (OWNER, AGENT + "circuit_learning_read_service.rs"),
            **{"learning_original_circuit_next_use_receipt_" + suffix: ()
               for suffix in ("create", "recover", "attest", "readback")},
        }
        for identifier, callers in expected.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                self.assertEqual(row.product_callers, callers)
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                changed = dict(self.sources)
                changed[AGENT + "unregistered_original_observer.rs"] = (
                    f"fn bypass(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_boundary(ROOT, row, changed, ())
                if callers:
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=()), self.sources, ())
        for name in ("learning_evidence_original_owner_constructor",
                     "root_learning_original_stage_assembly"):
            self.assertEqual(self.boundaries[name].product_callers, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_each_source_role_and_clock_constraint_remains_present_in_order(self):
        self.assertEqual(len(self.rows), 1)
        functions = self.rows[0]["required_function_order"]
        self.assertEqual({row["function"] for row in functions}, FUNCTIONS)
        self.assertGreater(sum(len(row["sequence"]) for row in functions), 100)
        for row in functions:
            for marker in row["sequence"]:
                with self.subTest(function=row["function"], marker=marker):
                    self.mutate_function(row["function"], marker)

    def test_configuration_and_physical_read_guards_cannot_be_dead_branches(self):
        for function in ("fn create(", "fn recover("):
            statement = "let saved = validate_config(&config, &key)?;"
            self.mutate_function(function, statement, "if false { " + statement + " }")
        for function, marker in (
            ("fn prepare(", "self.config.scope.validate_snapshot(source.snapshot())?;"),
            ("fn authenticate_completed(", "let current = now()?;"),
        ):
            self.mutate_function(function, marker, "if false { " + marker + " }")

    def test_pinned_predecessor_bytes_and_original_journal_binding_cannot_be_renewed(self):
        for marker in (
            "config.training_evidence.clone()", "config.selection_evidence.clone()",
            "&config.training_evidence.signing_bytes()", "&config.training_evidence.signature",
            "&config.selection_evidence.signing_bytes()", "&config.selection_evidence.signature",
        ):
            with self.subTest(marker=marker):
                self.mutate_function("fn validate_config(", marker)
        for marker in (
            "evidence[0] != config.training_evidence",
            "evidence[1] != config.selection_evidence",
        ):
            self.mutate_function("fn authenticate_predecessors(", marker)
            self.mutate_function("fn authenticate_predecessors(", marker, marker.replace("!=", "=="))

    def test_new_attestation_deadline_and_readback_window_are_distinct(self):
        self.mutate_function(
            "fn attest_source(",
            "self.authenticate_completed(&source, &observed, &bytes, started_at, true)",
            "self.authenticate_completed(&source, &observed, &bytes, started_at, false)",
        )
        for marker in (
            "if current < started_at", "if new_attestation",
            "require_new_attestation(&self.config, started_at, current)?",
            "receipt(&self.config, observed, signed.issued_at)?",
        ):
            self.mutate_function("fn authenticate_completed(", marker)
        marker = "current >= config.selection.request.envelope.expiry_unix_seconds"
        self.mutate_function("fn require_new_attestation(", marker, marker.replace(">=", ">"))
        self.mutate_function("fn now(", "SystemTime::now()")

    def test_no_key_generation_execution_or_unbound_stage_assembly_is_added(self):
        for marker in (
            "SigningKey::generate", "SigningKey::from_bytes",
            "LearningEvidenceVerifierV1::new", "LearningEvidenceTrustV1",
            "File::open", "UnixStream::connect", "with_root_learning_stage_owners(",
            "LearningIterationStageOwnerPortsV1 for", "fit_or_readback(",
            "evaluate_or_readback(", "qualify_and_persist(", "unwrap_or", "permit_all",
        ):
            with self.subTest(marker=marker):
                self.rejects(self.source + "\n" + marker + "\n")


if __name__ == "__main__":
    unittest.main()
