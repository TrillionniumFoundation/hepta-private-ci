"""Keep historical data readback separate from writer and Root authority."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "historical_source_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
READER = "codex-rs/hepta-intelligence-eval/src/product_execution_readback.rs"
SOURCE = "codex-rs/hepta-agentd/src/circuit_task_source_history.rs"
WITNESS = "codex-rs/hepta-neuron/src/witness.rs"


class HistoricalSourceReadbackClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def check_mutation(self, path, mutation):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        source = (ROOT / path).read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(mutation(source))
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def rejects_removal(self, path, function, markers):
        for marker in markers:
            with self.subTest(path=path, marker=marker):
                def remove(source):
                    start = source.index(function)
                    end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
                    self.assertIsNotNone(end)
                    offset = source.index(marker, start, end + 1)
                    return source[:offset] + source[offset + len(marker):]
                self.check_mutation(path, remove)

    def test_exact_witnessed_terminal_cut_is_required(self):
        self.rejects_removal(READER, "fn open(", (
            "snapshot(&mut file)?", "&bytes[8..40] != binding.as_array()",
            "if checksum != next.history_digest.as_array()", "replay(&mut records, payload)?",
            "if anchor != exact", "return Err(FileError::Rollback)",
        ))

    def test_every_cached_result_checks_physical_bytes_and_retains_failure(self):
        self.rejects_removal(READER, "fn readback(", (
            "if self.poisoned", "snapshot(&mut self.file)",
            "Digest32::of_bytes(&bytes) == self.bytes_digest", "self.poisoned = true",
            "if *binding != key.binding_digest",
        ))

    def test_shared_read_is_bounded_and_releases_its_lock(self):
        self.rejects_removal(READER, "fn snapshot(", (
            "file.try_lock_shared()", "if !metadata.is_file()", "if length > MAX_FILE_BYTES",
            ".take(MAX_FILE_BYTES + 1)", "file.metadata().map_err(io_error)?.len() != length",
            "file.unlock().map_err(io_error)", "unlocked?",
        ))

    def test_source_reconstructs_the_original_complete_request(self):
        self.rejects_removal(SOURCE, "fn read_run_publication(", (
            "self.require_active(run)?", "codec::original_record(&request_bytes)?",
            "if &record.snapshot.run_id != run_id",
            "request.validate_record(&record, self.fence.generation)?",
            "codec::request(&request, &record)? != request_bytes",
            "if input != self.sources[run].input(input.operation_id.clone())",
            "codec::publication(&result_bytes, &saved_input)?",
            "codec::decision_metadata(&result_bytes)?",
        ))

    def test_witness_is_rechecked_around_read_and_fences_changes(self):
        self.rejects_removal(SOURCE, "fn state(", (
            "self.require_current()?", "self.journal.readback(&key)",
            "ProductEvaluationExecutionStoreErrorV1::Indeterminate => Error::CommitUncertain",
        ))
        self.rejects_removal(SOURCE, "fn require_current(", (
            "if self.fenced", "self.witness.current()",
            "current == anchor(self.journal.anchor())", "self.fenced = true",
        ))

    def test_pending_and_withdrawn_are_never_publications(self):
        self.rejects_removal(SOURCE, "fn require_active(", (
            'self.state("withdraw", run)', "Ok(_) => Err(Error::Unavailable)",
        ))
        self.rejects_removal(SOURCE, "fn read(", (
            "ProductEvaluationExecutionStateV1::Pending => Err(Error::ReconciliationRequired)",
        ))

    def test_physical_witness_cannot_fall_back_to_a_cached_frontier(self):
        self.rejects_removal(WITNESS, "fn current(", (
            "let cursor = file.stream_position()?", "if header != self.header",
            "history_digest != self.history_digest", "file.seek(SeekFrom::Start(cursor))",
            "self.poisoned.store(true, Ordering::Release)",
        ))

    def test_readers_cannot_acquire_writer_or_signing_operations(self):
        for path in (READER, SOURCE):
            for forbidden in (".write_all(", ".sync_data(", ".compare_and_swap(",
                              ".claim(", ".complete(", "SigningKey", "into_inner"):
                with self.subTest(path=path, marker=forbidden):
                    self.check_mutation(path, lambda source: source + "\n" + forbidden)


if __name__ == "__main__":
    unittest.main()
