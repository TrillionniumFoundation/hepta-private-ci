"""Original task retirement capability and caller mutation controls."""

import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as reference

ROOT = reference.ROOT
PROOF = reference.PROOF
AGENT = reference.AGENT


class OriginalTaskRetirementSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = reference.HistoricalLedgerReadonlySourceTests.reject_removal

    def test_completed_active_owner_and_same_source_bracket_original_drain(self):
        markers = (
            "let before = self.status(state, ledger, captured)?;",
            "OriginalCellQ24TaskLedgerStatusV1::Complete { .. }",
            "return Err(Error::PendingOutcome);",
            "OriginalTaskCustodyV1::Active { cell, published } = &self.task",
            "PublishedCircuitFeatureTaskV1::drain_completed_task(",
            "completed.source_publication() != &captured.publication",
            "self.status(state, ledger, captured)? != before",
        )
        for marker in markers:
            with self.subTest(marker=marker):
                self.reject_removal(AGENT + "cell_q24_task_ledger_outcome.rs",
                                    "fn resume_original_outcome(", marker)

    def test_readonly_observer_cannot_become_an_unlisted_retirement_caller(self):
        boundary = next(b for b in PROOF._boundary_rows(self.manifest)
                        if b.identifier == "q24_task_original_completed_drain")
        ignored = PROOF._string_tuple(self.manifest, "ignored_path_fragments")
        index = {p.relative_to(ROOT).as_posix():
                 PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(p.read_text()))
                 for p in PROOF._source_files(ROOT, PROOF._string_tuple(self.manifest, "source_roots"))}
        PROOF._verify_boundary(ROOT, boundary, index, ignored, fields_by_receiver_type={})
        path = AGENT + "cell_q24_task_observation_control.rs"
        self.assertIn(path, index)
        index[path] += """
fn unowned_retirement_probe(published: &PublishedCircuitFeatureTaskV1,
    cell: &PublishedCircuitCellOwnerV1<FileAnchorWitnessStore>,
    source: &CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>, identity: &AgentdIdentity) {
    let _ = PublishedCircuitFeatureTaskV1::drain_completed_task(published, cell, source, identity);
}
"""
        with self.assertRaises(PROOF.VerificationFailure) as raised:
            PROOF._verify_boundary(ROOT, boundary, index, ignored, fields_by_receiver_type={})
        self.assertIn(path, str(raised.exception))

    def test_new_c_retirement_keeps_actual_owner_and_pre_post_custody(self):
        path = AGENT + "production_post_a_continuation.rs"
        function = "fn run_original_prepared_continuation("
        source = (ROOT / path).read_text()
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        new = code.index("PreparedCTask::New(original) => {", start, end)
        existing = code.index("PreparedCTask::Existing(original) => {", new, end)
        offset = new
        markers = (
            "OriginalCircuitFeatureIngressV1::submit_until(",
            "require_continuation(&state, &identity, &cancelled, end)?",
            "task_custody.require_original()?",
            "artifact_custody.require_original()?",
            "material.require_unchanged()?",
            "if installed.identity != identity",
            "return Err(refused(",
            "let retirement_task = installed.published_task();",
            "let retirement_cell = installed.cell();",
            "let retirement_source = installed.source();",
            "require_continuation(&state, &identity, &cancelled, end)?",
            "PublishedCircuitFeatureTaskV1::drain_completed_task(",
            "&retirement_task,",
            "&retirement_cell,",
            "retirement_source.as_ref(),",
            "&installed.identity,",
            "require_continuation(&state, &identity, &cancelled, end)?",
            "task_custody.require_original()?",
            "artifact_custody.require_original()?",
            "material.require_unchanged()?",
            "OriginalGenerationFiles::into_original_handoff(",
        )
        for marker in markers:
            position = source.index(marker, offset, existing)
            occurrence = source.count(marker, start, position)
            with self.subTest(marker=marker, occurrence=occurrence):
                self.reject_removal(path, function, marker, occurrence)
            offset = position + len(marker)


if __name__ == "__main__":
    unittest.main()
