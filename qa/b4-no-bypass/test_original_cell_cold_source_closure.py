"""Mutation checks for actual cold Cell IO and retained original identities.

These checks do not execute Root or establish complete learning qualification.
"""
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_original_cell_physical_source_closure as cell

ROOT = cell.ROOT
PROOF = cell.PROOF
PATH = cell.A + "authority_host_historical_cell_readback.rs"


def require_inside_existing_arm(source):
    for name, marker in (
        ("open_captured", "RootDataRefusalV1::inspect(&refusal, || {"),
        ("with_original_cell_data<T>", "RootDataRefusalV1::inspect(&self.refusal, || {"),
    ):
        code = cell.armed.component.function_code(source, name)
        operations = re.compile(
            r"HostAuthorityFrontierStore::open\s*\(|(?:self\s*\.\s*)?store\s*\.\s*load\s*\("
            r"|OriginalCellFiles::retain_original_cell\s*\(|open_original_files\s*\(|action\s*\("
        )
        positions = [match.start() for match in operations.finditer(code)]
        if not positions:
            raise PROOF.VerificationFailure("actual cold Cell reads required")
        cell.armed.inside(code, marker, positions)


class OriginalCellColdSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject = cell.OriginalCellSourceClosureTests.reject

    def mutate(self, path, change):
        rows = [r for r in self.manifest["protected_file"] if r["path"] == path]
        self.assertTrue(rows)
        original = (ROOT / path).read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)

            def verify(text):
                target.write_text(text)
                PROOF._verify_protected_files(root, {"protected_file": rows})
                require_inside_existing_arm(text)

            verify(original)
            changed = change(original)
            self.assertNotEqual(changed, original)
            with self.assertRaises(PROOF.VerificationFailure):
                verify(changed)

    def test_cold_open_requires_existing_captured_full_registration(self):
        for marker in (
            "RootDataRefusalV1::open_existing(", "RootDataKind::CellSnapshot",
            "expected.schema != 1", "expected.purpose != CELL_PURPOSE",
            "&expected.target != target", "expected.publisher.uid == 0",
            "expected.peer_gid == 0", "expected.publisher_epoch == 0",
            "CellPhase::Captured", "expected.files != *files.file_pins()",
            "expected.context != files.context_digest().to_string()",
        ):
            self.reject(PATH, "fn open_captured(", marker)

    def test_cold_open_reconstructs_only_the_exact_registered_original_identity(self):
        for marker in (
            "serde_json::from_str(&expected.registered_identity)",
            "serde_json::to_string(&registered)",
            "neuron_generation_process_identity_digest_v1(&registered.identity()?)",
            "registered.agent_id.as_str() != target.scope().agent_id",
        ):
            self.reject(PATH, "fn open_captured(", marker)
        for marker in (
            "registered.identity()?", "!= self.original.expected.registered_identity",
            "!= self.original.expected.identity",
        ):
            self.reject(PATH, "fn original_cell_publisher_identity(", marker)

    def test_source_and_cell_must_share_every_actual_original_binding(self):
        for marker in (
            "source_pin.fenced", "*retained_source != digest.to_string()",
            "*source_publication != publication.publication_digest().to_string()",
            "source_pin.pin.initial_profile != record.initial_profile",
            "source_pin.pin.identity != record.identity", "source_pin.pin.writer != record.writer",
            "source_pin.pin.publisher != record.publisher",
            "source_pin.pin.publisher_epoch != record.publisher_epoch",
            "source_pin.pin.target != record.target",
        ):
            self.reject(PATH, "fn read_original_cell_decision(", marker)

    def test_actual_cell_physical_receipt_and_cut_are_required(self):
        for marker in (
            "original.files.read_original_cell_data(", "&inputs.definition", "&inputs.source",
            "&record.target", "observed.anchor.sequence != *sequence",
            "observed.anchor.checkpoint_digest.to_string() != *checkpoint",
            "original_decision_digest(&observed)?.to_string() != *decision",
        ):
            self.reject(PATH, "fn read_original_cell_decision(", marker)

    def test_complete_recipient_action_precedes_exact_primary_postcheck(self):
        for occurrence in (0, 1):
            self.reject(PATH, "fn with_original_cell_data<T>(",
                        "self.store.load(&self.owner)", occurrence)
        self.reject(PATH, "fn with_original_cell_data<T>(",
                    "action(&OriginalRetainedCellReadV1 { original: self })?")

    def test_open_and_primary_cannot_escape_the_independent_arm(self):
        self.mutate(PATH, lambda text: text.replace(
            "let (store, expected, files) = RootDataRefusalV1::inspect(&refusal, || {",
            "open_original_files()?;\n"
            "        let (store, expected, files) = RootDataRefusalV1::inspect(&refusal, || {", 1))
        self.mutate(PATH, lambda text: text.replace(
            "RootDataRefusalV1::inspect(&self.refusal, || {",
            "self.store.load(&self.owner)?;\n"
            "        RootDataRefusalV1::inspect(&self.refusal, || {", 1))


if __name__ == "__main__":
    unittest.main()

