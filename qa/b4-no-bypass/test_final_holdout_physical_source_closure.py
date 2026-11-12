"""Guard physical holdout observations; these are not native execution receipts."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "final_holdout_physical_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
PREFIX = "codex-rs/hepta-intelligence-eval/src/"
STORE = PREFIX + "fenced_holdout_file.rs"
REPLAY = PREFIX + "fenced_holdout_file_replay.rs"


class FinalHoldoutPhysicalSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.rows = [row for row in manifest["protected_file"] if row["path"] in (STORE, REPLAY)]
        assert {row["path"] for row in cls.rows} == {STORE, REPLAY}

    def reject_removal(self, path, function, markers):
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
                    target.write_text(source[:offset] + "/* " + marker + " */" + source[offset + len(marker):])
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_actual_protected_files_pass(self):
        PROOF._verify_protected_files(ROOT, {"protected_file": self.rows})

    def test_live_read_poison_precedes_io_and_only_verified_image_clears(self):
        self.reject_removal(STORE, "fn require_physical_current(", (
            "if self.poisoned", "self.poisoned = true", "physical::read_stable_image(&mut self.file)",
            "bytes.len() as u64 != self.length", "Digest32::of_bytes(&bytes) != self.image_digest",
            "physical::replay_image(&bytes, self.binding,", "!= self.state", "self.poisoned = false"))

    def test_load_cannot_return_cached_state_without_physical_observation(self):
        self.reject_removal(STORE, "fn load(", (
            "if self.poisoned", "binding != self.binding", "self.require_physical_current()?"))

    def test_idempotent_cas_cannot_skip_physical_observation(self):
        self.reject_removal(STORE, "fn compare_and_swap(", (
            "self.require_physical_current()?", "next.validate(binding)", "current_digest != expected"))

    def test_cas_ack_requires_post_sync_exact_image_and_replayed_state(self):
        self.reject_removal(STORE, "fn compare_and_swap(", (
            "expected_image.extend_from_slice(&frame)", "self.poisoned = true",
            ".and_then(|()| self.file.sync_all())", "physical::read_stable_image(&mut self.file)",
            "observed != expected_image", "physical::replay_image(&observed, binding,",
            "!= Some(next)", "self.image_digest = Digest32::of_bytes(&observed)",
            "self.poisoned = false"))

    def test_recovery_keeps_original_minimum_and_second_physical_image(self):
        self.reject_removal(STORE, "fn recover(", (
            "acquire(file, binding)?", "physical::replay_image(&bytes, binding, minimum)?",
            "if physical::read_stable_image(&mut file)? != bytes",
            "image_digest: Digest32::of_bytes(&bytes)"))

    def test_shared_image_reader_is_bounded_and_observes_twice(self):
        self.reject_removal(REPLAY, "fn read_stable_image(", (
            "let first = read_image(file)?", "if read_image(file)? != first"))
        self.reject_removal(REPLAY, "fn read_image(", (
            "length > MAX_BYTES", "SeekFrom::Start(0)", ".take(MAX_BYTES + 1)",
            "bytes.len() as u64 != length", "file.metadata().map_err(io_error)?.len() != length"))

    def test_shared_frame_replay_retains_checksums_and_minimum_prefix(self):
        self.reject_removal(REPLAY, "fn replay_image(", (
            "bytes.len() < HEADER", "&bytes[8..40] != binding.as_array()",
            "&bytes[40..HEADER] != Digest32::of_bytes(&bytes[..40]).as_array()",
            "!(1..=MAX_FRAME).contains(&count)", "checksum != Digest32::of_bytes(payload).as_array()",
            "state = Some(replay_event(binding, state, payload)?)",
            "minimum_witnessed = true", "validate_minimum(state.as_ref(), minimum, minimum_witnessed)?"))


if __name__ == "__main__":
    unittest.main()
