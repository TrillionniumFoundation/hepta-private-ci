"""Protect physical execution observations, not evaluator authentication."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "execution_physical_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
PREFIX = "codex-rs/hepta-intelligence-eval/src/"
STORE = PREFIX + "product_execution_file.rs"
PHYSICAL = PREFIX + "product_execution_physical.rs"
READER = PREFIX + "product_execution_readback.rs"


class ExecutionPhysicalSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.rows = [row for row in manifest["protected_file"]
                    if row["path"] in (STORE, PHYSICAL, READER)]
        assert {row["path"] for row in cls.rows} == {STORE, PHYSICAL, READER}

    def rejects_removal(self, path, function, markers):
        source = (ROOT / path).read_text()
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        self.assertEqual(code.count(function), 1)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        rows = [row for row in self.rows if row["path"] == path]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            for marker in markers:
                with self.subTest(function=function, marker=marker):
                    offset = source.index(marker, start, end + 1)
                    target.write_text(source[:offset] + "/* " + marker + " */"
                                      + source[offset + len(marker):])
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_actual_protected_files_pass(self):
        PROOF._verify_protected_files(ROOT, {"protected_file": self.rows})

    def test_every_live_observation_poison_precedes_io_and_exact_state_clears(self):
        self.rejects_removal(STORE, "fn ensure_ready(", (
            "if self.poisoned", "self.poisoned = true",
            "physical::read_stable_image(&mut self.file)",
            "physical::replay_image(&bytes, self.binding, self.anchor)",
            "bytes.len() as u64 != self.length", "Digest32::of_bytes(&bytes) != self.image_digest",
            "replayed.anchor != self.anchor", "replayed.records != self.records",
            "self.poisoned = false"))

    def test_claim_completion_and_readback_cannot_return_cached_success(self):
        for function in ("fn claim(", "fn complete(", "fn readback("):
            self.rejects_removal(STORE, function, ("self.ensure_ready()?",))
        self.rejects_removal(STORE, "fn complete(", (
            "if *binding != key.binding_digest", "self.append(&event)?"))

    def test_append_requires_original_preimage_before_poison_sync_and_exact_postimage(self):
        self.rejects_removal(STORE, "fn append(", (
            ".filter(|length| *length <= MAX_FILE_BYTES)", "let mut expected = self.ensure_ready()?",
            "expected.extend_from_slice(&frame);\n        self.poisoned = true;",
            ".and_then(|()| self.file.sync_all())", "physical::read_stable_image(&mut self.file)",
            "physical::replay_image(&observed, self.binding, next)",
            "if observed != expected || replayed.anchor != next",
            "self.image_digest = Digest32::of_bytes(&observed)", "self.poisoned = false"))

    def test_recover_retains_witnessed_prefix_and_rechecks_after_sync(self):
        self.rejects_removal(STORE, "fn recover(", (
            "acquire(file, binding)?", "physical::read_stable_image(&mut file)?",
            "physical::replay_image(&bytes, binding, minimum)?", "file.sync_all()",
            "if physical::read_stable_image(&mut file)? != bytes",
            "image_digest: Digest32::of_bytes(&bytes)", "anchor: replayed.anchor"))

    def test_new_empty_owner_verifies_the_actual_synced_header(self):
        self.rejects_removal(STORE, "fn create(", (
            "acquire(file, binding)?", "file.metadata().map_err(io_error)?.len() != 0",
            ".and_then(|()| file.sync_all())", "store.ensure_ready()"))

    def test_two_complete_bounded_images_are_equal(self):
        self.rejects_removal(PHYSICAL, "fn read_stable_image(", (
            "for _ in 0..2", "if !metadata.is_file()", "if length > MAX_FILE_BYTES",
            "file.seek(SeekFrom::Start(0))", ".take(MAX_FILE_BYTES + 1)",
            "bytes.len() as u64 != length", "file.metadata().map_err(io_error)?.len() != length",
            "previous.as_ref().is_some_and(|original| original != &bytes)"))

    def test_one_shared_replay_retains_the_original_grammar_and_witnessed_prefix(self):
        self.rejects_removal(PHYSICAL, "fn replay_image(", (
            "if bytes.len() < HEADER", "&bytes[..8] != MAGIC", "&bytes[8..40] != binding.as_array()",
            "&bytes[40..HEADER] != Digest32::of_bytes(&bytes[..40]).as_array()",
            "if !(36..=MAX_FRAME).contains(&count)", "let payload = take(&mut remaining, count)?",
            "if checksum != next.history_digest.as_array()", "replay(&mut records, payload)?",
            "witnessed |= anchor == minimum", "if !witnessed", "return Err(FileError::Rollback)"))

    def test_readonly_data_cut_remains_exact_and_shared_lock_released(self):
        self.rejects_removal(READER, "fn open(", (
            "physical::replay_image(&bytes, binding, exact)?", "if replayed.anchor != exact"))
        self.rejects_removal(READER, "fn snapshot(", (
            "file.try_lock_shared()", "physical::read_stable_image(file)",
            "let unlocked = file.unlock().map_err(io_error)", "let bytes = result?", "unlocked?"))


if __name__ == "__main__":
    unittest.main()
