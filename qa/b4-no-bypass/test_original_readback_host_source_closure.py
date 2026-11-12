"""Fence the two consuming original Selector/C command-host constructors.

These are source-mutation checks through the unchanged protected-file verifier.
They do not execute a receipt owner, grant authority, or prove a full ordinary
learning loop. Existing caller-set QA keeps its complete collection and unknown
caller assertions; this sibling only protects the newly audited host bodies.
"""
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_readback_host_source_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
SELECTOR = AGENT + "circuit_selection_readback_host.rs"
NEXT_USE = AGENT + "circuit_next_use_readback_host.rs"
FUNCTION = "fn into_command_owner_from_original_readbacks("


class OriginalReadbackHostSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.rows = {}
        for path in (SELECTOR, NEXT_USE):
            rows = [row for row in manifest["protected_file"] if row["path"] == path]
            if len(rows) != 1:
                raise AssertionError((path, "one original host protected row required"))
            cls.rows[path] = rows
        PROOF._verify_protected_files(
            ROOT, {"protected_file": [cls.rows[path][0] for path in (SELECTOR, NEXT_USE)]}
        )

    def assert_rejected(self, path, changed):
        self.assertNotEqual(changed, (ROOT / path).read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(changed)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": self.rows[path]})

    def mutate(self, path, marker, replacement=""):
        original = (ROOT / path).read_text()
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(original))
        self.assertEqual(code.count(FUNCTION), 1)
        start = code.index(FUNCTION)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        body = original[start:end + 1]
        self.assertEqual(body.count(marker), 1, (path, marker))
        changed = body.replace(marker, replacement, 1)
        self.assert_rejected(path, original[:start] + changed + original[end + 1:])

    def test_selector_rejects_changed_cut_signature_or_observation_time(self):
        for marker, replacement in (
            ("actual.snapshot() != &self.config.decision", "false"),
            ("training.attestation() != &self.config.training_evidence", "false"),
            ("training.receipt().observed_unix_seconds", "0"),
        ):
            with self.subTest(marker=marker):
                self.mutate(SELECTOR, marker, replacement)

    def test_selector_constructor_keeps_consuming_original_custody(self):
        self.mutate(SELECTOR, "        self,\n", "        &self,\n")
        self.mutate(
            SELECTOR,
            "OriginalCellQ24TrainingReadbackConnectionV1::bind_original_training",
            "OriginalCellQ24TrainingReadbackConnectionV1::bind_other_training",
        )
        original = (ROOT / SELECTOR).read_text()
        marker = "training.attestation() != &self.config.training_evidence"
        changed = original.replace(marker, "false", 1)
        # A copy in unrelated code cannot replace the check in the real function.
        self.assert_rejected(
            SELECTOR, changed + "\nfn unrelated_signature_check() { let _ = " + marker + "; }\n"
        )

    def test_next_use_rejects_different_original_cuts_or_any_full_signature(self):
        for marker in (
            "actual.snapshot() != &self.config.selection",
            "selection.snapshot() != &self.config.selection",
            "training.attestation() != &self.config.training_evidence",
            "selection.training_attestation() != &self.config.training_evidence",
            "selection.attestation() != &self.config.selection_evidence",
        ):
            with self.subTest(marker=marker):
                self.mutate(NEXT_USE, marker, "false")
        for marker in (
            "training.receipt().observed_unix_seconds",
            "selection.receipt().observed_unix_seconds",
        ):
            with self.subTest(marker=marker):
                self.mutate(NEXT_USE, marker, "0")

    def test_next_use_keeps_distinct_consuming_trainer_and_selector_bindings(self):
        self.mutate(
            NEXT_USE,
            "        self,\n        live: OriginalCircuitLearningReadClientV1,",
            "        &self,\n        live: OriginalCircuitLearningReadClientV1,",
        )
        for owner, original, replacement in (
            ("OriginalCellQ24TrainingReadbackConnectionV1", "bind_original_training", "bind_other_training"),
            ("OriginalCircuitSelectionReadbackConnectionV1", "bind_original_selection", "bind_other_selection"),
        ):
            with self.subTest(owner=owner):
                self.mutate(NEXT_USE, owner + "::" + original, owner + "::" + replacement)

    def test_hosts_cannot_acquire_a_new_path_key_or_execute_a_predecessor(self):
        for path in (SELECTOR, NEXT_USE):
            original = (ROOT / path).read_text()
            for marker in (
                'std::fs::File::open("other")',
                "SigningKey::generate()",
                "owner.recover_from_original_stream()",
            ):
                with self.subTest(path=path, marker=marker):
                    self.assert_rejected(path, original + "\nfn bypass() { " + marker + "; }\n")


if __name__ == "__main__":
    unittest.main()

