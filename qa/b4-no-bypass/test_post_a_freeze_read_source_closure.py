"""Original freeze physical read guards; no Root runtime qualification here."""

import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT = component.ROOT
FILE = component.AGENT + "authority_host_post_a_freeze.rs"


class PostAFreezeReadSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_original_files_have_distinct_actual_non_root_custody(self):
        self.check_markers(FILE, "fn retain_original_freeze(", (
            "original_root()?", "uid == 0", "gid == 0", "objective.is_zero()",
            "data.scope == [0; 32]", "!(3..=4096).contains(&data.maximum_records)",
            "PostAOriginalFile::retain_original_file(data.journal)?",
            "PostAOriginalFile::retain_original_file(data.witness)?",
            "journal.same_file(&witness)", "PostAOriginalFile::read_handle(original)?",
            "(metadata.uid(), metadata.gid(), metadata.mode() & 0o7777) != (uid, gid, 0o600)",
            "Generation::new(data.generation)"))

    def test_two_actual_locks_outlive_the_separate_reader_description(self):
        self.check_markers(FILE, "fn with_original_completion<T>(", (
            "PostAOriginalFile::read_handle(&self.journal)?",
            "PostAOriginalFile::read_handle(&self.witness)?", "journal.try_lock_shared()",
            "witness.try_lock_shared()", "image(&journal, 32 * 1024 * 1024)?",
            "image(&witness, 1024 * 1024)?", "self.read_anchor(&witness)?",
            "anchor.sequence != 3", "ReadOnlyProductEvaluationExecutionStoreV1::open(",
            "key.binding_digest", "sequence: anchor.sequence - 1",
            "history_digest: anchor.checkpoint_digest"))
        self.reject_removal(FILE, "fn with_original_completion<T>(",
                            "PostAOriginalFile::read_handle(&self.journal)?", 1)

    def test_completed_data_is_rechecked_after_the_entire_root_action(self):
        fn = "fn with_original_completion<T>("
        self.check_markers(FILE, fn, (
            "let ProductEvaluationExecutionStateV1::Completed(bytes)", "let result = action(&bytes)?",
            "!= ProductEvaluationExecutionStateV1::Completed(bytes)", "Ok(result)"))
        for occurrence in (0, 1):
            self.reject_removal(FILE, fn,
                                "ReadOnlyProductEvaluationExecutionStoreV1::readback(&mut reader, key)", occurrence)
            self.reject_removal(FILE, fn,
                                "self.require_observation(&journal, &witness, &before, anchor)?", occurrence)
        for occurrence in (0, 1, 2):
            self.reject_removal(FILE, fn, "require_end(end)?", occurrence)

    def test_witness_physical_bytes_and_paths_are_not_cached_authority(self):
        self.check_markers(FILE, "fn read_anchor(", (
            "observe_original_file_anchor_v1(", "self.scope", "self.generation",
            "self.maximum_records", ".ok_or_else("))
        self.check_markers(FILE, "fn require_observation(", (
            "original_root()?", "PostAOriginalFile::require_identity(&self.journal, journal)?",
            "PostAOriginalFile::require_identity(&self.witness, witness)?",
            "self.read_anchor(witness)? != anchor", "image(journal, 32 * 1024 * 1024)?",
            "image(witness, 1024 * 1024)?", "!= expected"))
        self.reject_removal(FILE, "fn require_observation(",
                            "PostAOriginalFile::require_identity(&self.journal, journal)?", 1)

    def test_physical_snapshot_has_original_bounds_and_exact_digest(self):
        self.check_markers(FILE, "fn image(", (
            "let length = file.metadata()?.len()", "length == 0 || length > bound",
            "file.read_exact_at(&mut bytes, 0)?", "file.metadata()?.len() != length",
            "Digest32::of_bytes(&bytes)"))


if __name__ == "__main__":
    unittest.main()
