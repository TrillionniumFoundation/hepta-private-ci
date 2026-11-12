"""Strict physical CURRENT must not invoke the original repairing recovery."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "cell_generation_physical_current_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
NEURON = "codex-rs/hepta-neuron/src/"
CURRENT = NEURON + "cell_generation_physical_current.rs"
JOURNAL = NEURON + "cell_generation_journal.rs"
BOUNDARY = "cell_generation_original_physical_current"


class CellGenerationPhysicalCurrentClosureTests(unittest.TestCase):
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

    def test_physical_current_has_an_exact_closed_caller_set(self):
        row = self.boundaries[BOUNDARY]
        self.assertEqual(row.product_callers, ("codex-rs/hepta-agentd/src/neuron_cell_evaluation_panel_member.rs",))
        self.assertIn(BOUNDARY, self.manifest["privileged_inventory"]["required_boundary_ids"])
        sources = {path: self.code((ROOT / path).read_text()) for path in (CURRENT, *row.product_callers)}
        PROOF._verify_boundary(ROOT, row, sources, ())
        sources[NEURON + "unregistered_current.rs"] = (
            "fn extra(owner: &mut CellGenerationJournalV2<W>) { owner.read_current_checkpoint(); }"
        )
        with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
            PROOF._verify_boundary(ROOT, row, sources, ())

    def test_full_original_descriptor_replay_and_same_retained_state_are_required(self):
        for marker in (
            "length != self.length || !(HEADER_BYTES as u64..=MAX_BYTES).contains(&length)",
            "Read::take(&mut *self.file, length + 1)",
            "if bytes.len() as u64 != length",
            "if bytes[..HEADER_BYTES] != self.header",
            "while offset < bytes.len()",
            ".get(offset..offset + 4)",
            ".filter(|end| *end <= bytes.len())",
            "let (next, event) = decode_frame(",
            "state.apply(&self.config, &event)?",
            "if state != self.state || head != self.head || offset as u64 != self.length",
        ):
            self.rejects(CURRENT, "fn read_physical_frames(", marker)
        for marker in (
            "if next.sequence > max_records || next.checkpoint_digest.as_array() != checksum",
            "serde_json::from_slice(payload)",
            "serde_json::to_vec(&event)",
            "!= payload",
        ):
            self.rejects(CURRENT, "fn decode_frame(", marker)
        self.rejects(JOURNAL, "fn recover(", "physical_current::decode_frame(")

    def test_both_witness_observations_and_cursor_restoration_precede_success(self):
        for marker in (
            "self.require_healthy()?",
            "if before != self.head",
            "let position = self",
            "let observed = self.read_physical_frames();",
            ".seek(SeekFrom::Start(position))",
            "restored?",
            "let checkpoint = observed?",
            "let after = self",
            "if after != before || after != self.head",
            "self.require_current()?",
        ):
            self.rejects(CURRENT, "fn read_physical_current(", marker)

    def test_any_failure_fences_recovery_even_after_original_bytes_are_restored(self):
        for marker in (
            "if result.is_err()",
            "self.physical_fenced = true;",
            "self.healthy = false;",
        ):
            self.rejects(CURRENT, "fn read_current_checkpoint(", marker)
        self.rejects(JOURNAL, "fn recover(", "if self.physical_fenced")
        self.rejects(JOURNAL, "fn require_current(", "if self.physical_fenced")
        self.rejects(JOURNAL, "fn require_healthy(", "if self.healthy && !self.physical_fenced")
        source = (ROOT / CURRENT).read_text()
        for effect in (
            "self.recover()",
            "self.file.set_len(0)",
            "self.file.sync_all()",
            "self.witness.compare_and_swap(None, next)",
            "File::open(path)",
            "self.physical_fenced = false",
            "self.state = state",
        ):
            with self.subTest(effect=effect):
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(CURRENT, source + "\nfn bypass() { " + effect + "; }\n")


if __name__ == "__main__":
    unittest.main()
