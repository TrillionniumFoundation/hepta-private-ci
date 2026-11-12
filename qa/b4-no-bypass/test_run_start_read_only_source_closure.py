"""Keep original RunStart physical observation separate from ACK authority."""

import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "run_start_read_only_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
OWNER = "codex-rs/hepta-learning-ledger/src/run_start.rs"
FRAMES = "codex-rs/hepta-learning-ledger/src/run_start_frames.rs"
READER = "codex-rs/hepta-learning-ledger/src/run_start_read_only.rs"
GENERIC = "fn with_observation<T>("


def function_bounds(source, marker):
    code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    if code.count(marker) != 1:
        raise PROOF.VerificationFailure("unique actual read-view function required")
    start = code.index(marker)
    end = PROOF._rust_item_end(code, start)
    if end is None or code[end] != "}":
        raise PROOF.VerificationFailure("complete read-view function required")
    return code, start, end


class RunStartReadOnlySourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.rows = [
            row for row in manifest["protected_file"]
            if row["path"] in (OWNER, FRAMES, READER)
        ]
        assert len(cls.rows) == 3
        cls.sources = {row["path"]: (ROOT / row["path"]).read_text() for row in cls.rows}

    def verify(self, root):
        PROOF._verify_protected_files(root, {"protected_file": self.rows})
        # The unchanged global checker deliberately accepts only nongeneric
        # function markers. Apply its order primitive to this exact, uniquely
        # located generic body as an additional scoped proof, never normalize it
        # into a different function or allow another helper to supply its gates.
        source = (root / READER).read_text()
        code, start, end = function_bounds(source, GENERIC)
        body = code[start:end + 1]
        if re.search(r"\bfn\s+", body[len(GENERIC):]):
            raise PROOF.VerificationFailure("nested function cannot supply observation gates")
        row = next(row for row in self.rows if row["path"] == READER)
        PROOF._verify_required_order(row, body, READER + ":" + GENERIC)

    def check_mutation(self, path, mutation):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative, source in self.sources.items():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source)
            self.verify(root)
            (root / path).write_text(mutation(self.sources[path]))
            with self.assertRaises(PROOF.VerificationFailure):
                self.verify(root)

    def rejects_removal(self, path, function, markers):
        for marker in markers:
            with self.subTest(path=path, marker=marker):
                def remove(source):
                    _, start, end = function_bounds(source, function)
                    body = source[start:end + 1]
                    self.assertEqual(body.count(marker), 1)
                    offset = source.index(marker, start, end + 1)
                    return source[:offset] + source[offset + len(marker):]
                self.check_mutation(path, remove)

    def test_existing_writer_keeps_shared_parser_and_ack_before_repair(self):
        self.rejects_removal(OWNER, "fn recover(", (
            "LockedRunStartFile::acquire(file)?",
            "replay_frames(&mut file.0, binding, max_records)?",
            "if record.chain_digest != anchor.chain_digest", "if cursor != length",
            ".set_len(cursor)", ".sync_all()",
        ))

    def test_reader_stays_explicitly_unix(self):
        marker = '#[cfg(unix)]\n#[path = "run_start_read_only.rs"]'
        self.check_mutation(OWNER, lambda source: source.replace(marker, '#[path = "run_start_read_only.rs"]', 1))

    def test_shared_parser_preserves_original_framing_chain_and_physical_ranges(self):
        self.rejects_removal(FRAMES, "fn replay_reader(", (
            "if length > MAX_FILE_BYTES", "file.read_exact(&mut header)?",
            "Digest32::of_bytes(&header[..40]).as_array() != &header[40..]",
            "&header[8..40] != binding.as_array()",
            "(size as u32) != !complement", "if records.len() >= max_records",
            "Digest32::of_bytes(&frame[..total - 32]).as_array() != &frame[total - 32..]",
            "if sequence != records.len() as u64 + 1", "if predecessor != expected_predecessor",
            "decode_outcome_record(&frame[48..payload_end])?",
            "if by_run.contains_key(record.run_id())",
            "chain_digest != digest_chain(predecessor, sequence, record_digest)",
            "frame_ranges.push((cursor, cursor + total as u64))", "cursor += total as u64",
        ))

    def test_existing_fd_mode_type_and_identity_are_physical(self):
        self.rejects_removal(READER, "fn file_stamp(", (
            "fcntl_getfl(file).map_err(io::Error::from)?",
            "if flags & OFlags::ACCMODE != OFlags::RDONLY", "if !metadata.is_file()",
            "metadata.dev()", "metadata.ino()", "metadata.mtime_nsec()", "metadata.ctime_nsec()",
        ))
        self.rejects_removal(READER, "fn read_image(", (
            "if (before.device, before.inode) != self.identity", "if before.length > MAX_FILE_BYTES",
            ".read_exact_at(&mut bytes,", "if file_stamp(&self.file)? != before",
        ))

    def test_external_profile_anchor_and_same_image_prefix_do_not_mint_ack(self):
        self.rejects_removal(READER, GENERIC, (
            "usize::try_from(self.anchor.sequence - 1)",
            "if anchor.chain_digest != self.anchor.chain_digest",
            "if record_profile(&anchor.record) != self.profile",
        ))
        self.rejects_removal(READER, "fn read_frame(", (
            "self.with_observation(|bytes, replay|", "Digest32::of_bytes(original) != digest",
            "if stored.sequence > self.anchor.sequence", "if record_profile(&stored.record) != self.profile",
            "let StoredRunStartRecord::Run(record) = &stored.record", ".frame_ranges",
            "sequence: stored.sequence", "record_digest: stored.record_digest", "chain_digest: stored.chain_digest",
        ))

    def test_partial_tail_and_seen_prefix_rollback_fail_closed(self):
        self.rejects_removal(READER, GENERIC, (
            "if state.poisoned", "if let Some((length, digest)) = state.prefix",
            "bytes.get(..length).map(Digest32::of_bytes) != Some(digest)",
            "if replay.valid_length != replay.observed_length",
        ))

    def test_second_physical_read_precedes_success_and_all_errors_poison(self):
        self.rejects_removal(READER, GENERIC, (
            "let (before, bytes) = self.read_image()?", "&mut io::Cursor::new(&bytes)",
            "let value = observe(&bytes, &replay)?", "let (after, confirmed) = self.read_image()?",
            "if before != after || bytes != confirmed", "state.prefix = Some((bytes.len(), Digest32::of_bytes(&bytes)))",
            "if result.is_err()", "state.poisoned = true",
        ))

    def test_comments_cannot_supply_a_removed_physical_gate(self):
        needle = "if before != after || bytes != confirmed"
        self.check_mutation(READER, lambda source: source.replace(needle, "if false", 1) + "\n// " + needle)

    def test_unrelated_function_cannot_supply_generic_observation_gates(self):
        def move(source):
            _, start, end = function_bounds(source, GENERIC)
            brace = source.index("{", start, end)
            body = source[brace:end + 1]
            return source[:brace] + "{ Err(RunStartStoreError::Indeterminate) }" + source[end + 1:] + "\nfn unrelated<T>() " + body
        self.check_mutation(READER, move)

    def test_data_view_cannot_gain_writer_lock_repair_signing_or_authority(self):
        for marker in (
            "pub file:", "pub fn append", "pub fn recover", "pub fn create",
            "File::open", "OpenOptions", ".write_all(", ".set_len(", ".sync_all(",
            ".try_lock(", ".try_lock_shared(", "SigningKey", "AlwaysCurrent",
            "impl RunStartJournal", "impl LedgerJournal", "unsafe", "into_inner",
        ):
            with self.subTest(marker=marker):
                self.check_mutation(READER, lambda source: source + "\n" + marker)


if __name__ == "__main__":
    unittest.main()
