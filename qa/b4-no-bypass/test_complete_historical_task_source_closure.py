"""Source mutations for complete historical task reads, without native claims."""
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_original_cell_physical_source_closure as cell

ROOT = cell.ROOT
PROOF = cell.PROOF
A = cell.A
TASK = A + "authority_host_historical_task.rs"
DATA = A + "authority_host_historical_task_data.rs"
HANDOFF = A + "authority_host_historical_source_handoff.rs"
RECORD = A + "authority_host_historical_source_record.rs"


def require_complete_structure(path, source):
    if path == TASK:
        code = cell.armed.component.function_code(source, "with_original_historical_task<T>")
        spans = [cell.armed.closure_span(code, marker) for marker in (
            "|handoff_digest| {", "|source| {", "|run_start| {", "|ledger| {",
        )]
        action = code.index("let value = action(&mut read)?")
        final = code.index("!matches!(read.state, ReadState::Complete)")
        if not all(start < action < final < end for start, end in spans):
            raise PROOF.VerificationFailure("all independent data arms must enclose the Root context")
        if not all(spans[i][0] < spans[i + 1][0] < spans[i + 1][1] < spans[i][1]
                   for i in range(3)):
            raise PROOF.VerificationFailure("one complete nested data context required")
    if path == DATA:
        code = cell.armed.component.function_code(source, "with_original_source_cell_data<T>")
        action = code.index("let result = action(&mut pending)?")
        final = code.index("held.require_unchanged(self, cell)?")
        cell.armed.inside(code, "|cell| {", [action, final])
        cell.armed.inside(code, "self.inspect_exact(|| {", [action, final])
    if path == HANDOFF:
        code = cell.armed.component.function_code(source, "with_finalized_source_data<T>")
        positions = [m.start() for m in re.finditer(
            r"self\s*\.\s*store\s*\.\s*load\s*\(|pin\s*\.\s*readback_digest\s*\(|action\s*\(",
            code)]
        cell.armed.inside(code, "RootDataRefusalV1::inspect(&self.refusal, || {", positions)


class CompleteHistoricalTaskSourceTests(unittest.TestCase):
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
                require_complete_structure(path, text)

            verify(original)
            changed = change(original)
            self.assertNotEqual(changed, original)
            with self.assertRaises(PROOF.VerificationFailure):
                verify(changed)

    def test_complete_task_cannot_omit_any_existing_original_owner(self):
        for marker in (
            "RootHistoricalSourceHandoffV1::open_finalized(",
            "RootHistoricalSourcePinV1::open_existing(",
            "RootRetainedCellDataV1::open_captured(",
            "RootRetainedRunStartDataV1::open_finalized(",
        ):
            self.reject(TASK, "fn open_existing(", marker)
        for marker in (
            ".with_finalized_source_data(", ".with_original_source_cell_data(",
            ".with_original_run_start_data(", "service.with_retained_original_ledger(",
            "let value = action(&mut read)?", "!matches!(read.state, ReadState::Complete)",
        ):
            self.reject(TASK, "fn with_original_historical_task<T>(", marker)

    def test_original_target_and_read_attempts_are_consumed_before_validation(self):
        for function, state in (
            ("fn require_original_target(", "ReadState::AwaitingTarget"),
            ("fn observe_original_task(", "ReadState::Bound"),
        ):
            for marker in ("std::mem::replace(&mut self.state, ReadState::Verifying)",
                           state, "Instant::now() >= self.end"):
                self.reject(TASK, function, marker)
        self.reject(TASK, "fn require_original_target(", "target != &self.original.target")

    def test_original_run_start_is_full_record_joined_before_actual_ledger(self):
        for marker in (
            ".read_original_retired_source_cell(load_original_source)?",
            "RootOriginalRunStartReadV1::require_original_publisher(", "&pin.publisher", "pin.publisher_epoch",
            "&pin.initial_profile", "&pin.writer", "&pin.target_files",
            "load_original_run_start()?",
            "&run_start.observed.record != source.source.publication().original_record()",
            "PendingOriginalLedgerHistoryV1::observe_original_terminal(", "&source.source",
            "&source.definition", "&source.cell",
        ):
            self.reject(TASK, "fn observe_original_task(", marker)

    def test_complete_cut_commits_every_root_retained_data_kind(self):
        for marker in (
            "RootOriginalRunStartReadV1::retained_digest(self.run_start)?", "RootOriginalHistoricalLedgerObservationV1::data_cut_digest(&ledger)?",
            "self.original.target.digest()", "self.handoff_digest.as_array()",
            "source.source_pin_digest.as_array()", "source.cell_cut_digest.as_array()",
            "run_start_digest.as_array()", "ledger_digest.as_array()",
            "source.source.publication().publication_digest().as_array()",
            "self.state = ReadState::Complete",
        ):
            self.reject(TASK, "fn observe_original_task(", marker)

    def test_kernel_retirement_and_registered_identity_precede_source_loader(self):
        for marker in (
            "std::mem::replace(&mut self.state, ReadState::Verifying)", "ReadState::Unobserved",
            "self.cell.original_cell_publisher_identity()?", "self.cell.original_cell_peer_gid()",
            "pin.spawn_generation != identity.spawn_generation",
            "RetiredCheckpointPublisher::observe(pin.publisher.clone())",
            "load_original_source(&identity)?", "require_target(&pin.target, &inputs.definition, &inputs.source)?",
        ):
            self.reject(DATA, "fn read_original_retired_source_cell(", marker)

    def test_physical_source_custody_and_cut_cannot_be_substituted(self):
        for marker in (
            "FilePin::readonly(&inputs.journal", "FilePin::readonly(&inputs.witness",
            "!= pin.source_files", "witness.metadata()?.len() == 0",
            "FileAnchorWitnessStore::open(", "HistoricalCircuitTaskSourceV1::open(",
            "observed.original_identity() != &identity", "observed.original_fence() != &inputs.fence",
            "observed.original_source() != &inputs.source",
            "observed.binding_digest().to_string() != pin.source_configuration",
            "observed.journal_anchor().sequence != pin.source_sequence",
            "observed.journal_anchor().checkpoint_digest.to_string() != pin.source_checkpoint",
            "observed.publication().publication_digest().to_string() != pin.publication",
            "observed.publication().history_digest().as_str() != pin.completed_task",
            "self.cell.read_original_cell_decision(",
        ):
            self.reject(DATA, "fn read_original_retired_source_cell(", marker)

    def test_held_readers_and_physical_postchecks_outlive_recipient_context(self):
        for marker in (
            "let result = action(&mut pending)?", "let ReadState::Complete(mut held)",
            "held.require_unchanged(self, cell)?",
        ):
            self.reject(DATA, "fn with_original_source_cell_data<T>(", marker)
        for marker in (
            "!= self.observed.source", "!= self.observed.cell", "!= original.source_files",
            "physical_metadata(inputs)? != self.physical",
            "RetiredCheckpointPublisher::observe(original.publisher.clone())",
        ):
            self.reject(DATA, "fn require_unchanged(", marker)
        for occurrence in (0, 1):
            self.reject(DATA, "fn require_unchanged(", "observe_original_file_anchor_v1(", occurrence)

    def test_handoff_and_source_primary_are_rechecked_after_the_whole_action(self):
        self.reject(HANDOFF, "fn with_finalized_source_data<T>(", "let result = action(digest)?")
        for occurrence in (0, 1):
            self.reject(HANDOFF, "fn with_finalized_source_data<T>(",
                        "pin.readback_digest()?.to_string() != self.expected.pin", occurrence)
            self.reject(RECORD, "fn inspect_exact<T>(", "self.store.load(&self.owner)", occurrence)

    def test_primary_io_outside_handoff_arm_is_rejected(self):
        self.mutate(HANDOFF, lambda text: text.replace(
            "RootDataRefusalV1::inspect(&self.refusal, || {",
            "pin.readback_digest()?;\n        RootDataRefusalV1::inspect(&self.refusal, || {", 1))


if __name__ == "__main__":
    unittest.main()

