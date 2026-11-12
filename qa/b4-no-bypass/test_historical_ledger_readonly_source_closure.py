"""Physical Ledger/signature source guards; not native or cold admission proof."""

from pathlib import Path
import tempfile
import tomllib
import unittest

import test_initial_artifact_readview_source_closure as component

ROOT = component.ROOT
PROOF = component.PROOF
AGENT = component.AGENT
LEDGER = "codex-rs/hepta-learning-ledger/src/"


class HistoricalLedgerReadonlySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def reject_removal(self, path, function, marker, occurrence=0):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        source = (ROOT / path).read_text()
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        self.assertEqual(code.count(function), 1)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        offset = start
        for _ in range(occurrence + 1):
            offset = source.index(marker, offset, end + 1) + len(marker)
        offset -= len(marker)
        mutation = source[:offset] + "/* " + marker + " */" + source[offset + len(marker):]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(mutation)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def check_markers(self, path, function, markers):
        for marker in markers:
            with self.subTest(marker=marker):
                self.reject_removal(path, function, marker)

    def test_only_original_root_four_file_reader_is_listed(self):
        rows = {row["id"]: row for row in self.manifest["boundary"]}
        for identifier in ("ledger_original_readonly_capture", "ledger_original_readonly_retained",
                           "q24_original_terminal_history_signatures"):
            self.assertEqual(rows[identifier]["product_callers"],
                             [AGENT + "authority_host_historical_ledger_files.rs"])

    def test_descriptor_is_readonly_regular_single_link_and_immutable(self):
        self.check_markers(LEDGER + "durable_read_only_file.rs", "fn stamp(", (
            "flags & OFlags::ACCMODE != OFlags::RDONLY", "!metadata.is_file()",
            "metadata.nlink() != 1", "device: metadata.dev()", "inode: metadata.ino()",
            "owner: metadata.uid()", "group: metadata.gid()", "mode: metadata.mode()",
            "length: metadata.len()", "modified: (metadata.mtime(), metadata.mtime_nsec())",
            "changed: (metadata.ctime(), metadata.ctime_nsec())"))

    def test_both_original_files_retain_distinct_shared_locks(self):
        self.check_markers(LEDGER + "durable_read_only_file.rs", "fn acquire(", (
            "let original = stamp(&file)?", "file.try_lock_shared()",
            "Err(TryLockError::WouldBlock)", "stamp(&retained.file)? != original"))
        self.check_markers(LEDGER + "durable_read_only.rs", "fn open(", (
            "physical::ReadOnlyFile::acquire(ledger, MAX_BYTES)?",
            "physical::ReadOnlyFile::acquire(witness, 72 + 88 * max_records as u64)?",
            "ledger.identity() == witness.identity()", "view.observe()?"))

    def test_full_physical_read_has_pre_and_post_stat_checks(self):
        self.check_markers(LEDGER + "durable_read_only_file.rs", "fn read_image(", (
            "before != self.original", "before.length > self.maximum",
            "usize::try_from(before.length)", "stamp(&self.file)? != before"))

    def test_observed_failure_is_poisoned_before_io_and_only_success_clears(self):
        self.check_markers(LEDGER + "durable_read_only.rs", "fn observe(", (
            "if state.poisoned", "state.poisoned = true", "self.ledger.read_image()?",
            "self.witness.read_image()?", "state.expected = ExpectedCut::Retained(cut)",
            "state.poisoned = false"))

    def test_ledger_replay_requires_exact_witnessed_tail(self):
        self.check_markers(LEDGER + "durable_read_only.rs", "fn observe(", (
            "inspect_ordinary_witness(", "LedgerRecovery::Acknowledged(frontier.anchor)",
            "validate_recovery(recovery, self.max_records)?", "replay_reader(",
            "cursor != length", "core.records().len() as u64 != frontier.anchor.sequence"))

    def test_retained_joint_cut_must_match_and_cannot_be_recaptured(self):
        self.reject_removal(LEDGER + "durable_read_only.rs", "fn open_at_retained_cut(",
                            "expected.binding != binding")
        self.check_markers(LEDGER + "durable_read_only.rs", "fn observe(", (
            "ExpectedCut::Retained(expected)", "expected != cut",
            "self.ledger.read_image()? != ledger || self.witness.read_image()? != witness"))

    def test_witness_has_no_partial_tail_or_segment_recovery(self):
        self.check_markers(LEDGER + "witness_read_only.rs", "fn inspect_ordinary_witness(", (
            "bytes.len() < HEADER", "bytes.len() > HEADER + FRAME * max_records",
            "&header[8..40] != binding.as_array()",
            "!(bytes.len() - HEADER).is_multiple_of(FRAME)",
            "next.segment.is_some() || next.sealed", "validate_advance(frontier, next)?",
            "encode_frontier(next)? != frame"))

    def test_shared_writer_parser_keeps_original_canonical_semantics(self):
        self.check_markers(LEDGER + "durable.rs", "fn replay_reader(", (
            "size != !complement || size == 0 || size as usize > MAX_EVENT",
            "core.records().len() >= max_records", "decode_event(&frame[48..48 + size as usize])?",
            "prepared.disposition != AppendDisposition::Appended",
            "encode_frame(&prepared.record)? != frame", "record.chain_digest != anchor.chain_digest"))

    def test_history_requires_real_source_cell_and_exact_two_facts(self):
        self.check_markers(AGENT + "cell_q24_task_ledger_history.rs", "fn verify_original_terminal(", (
            "observed.cut.frontier.anchor.sequence != 2", "observed.snapshot.records().len() != 2",
            "replay.active_records().len() != 2", ".require_decision(cell)",
            "projection::decision(self.config, self.definition, self.source, publication, cell)?",
            "projection::require_outcome(self.config, publication, &outcome)?"))

    def test_generator_signature_retains_original_preimage_and_claim_window(self):
        self.check_markers(AGENT + "cell_q24_task_ledger_history.rs", "fn verify_original_terminal(", (
            "decision_payload != decision_signing_payload_v2(&decision)?",
            "decision_signed.evidence_id != keys[0].plan_id", "decision_signed.issued_at > now",
            "decision_signed.issued_at >= self.config.claim_deadline_unix_seconds",
            ".is_none_or(|lifetime| lifetime > self.config.maximum_signature_lifetime_seconds)"))

    def test_both_signatures_use_enrolled_roles_and_original_issue_times(self):
        file = AGENT + "cell_q24_task_ledger_history.rs"
        function = "fn verify_original_terminal("
        for occurrence in (0, 1):
            self.reject_removal(file, function, "self.verifier.require_signer_binding(", occurrence)
            self.reject_removal(file, function, "self.verifier.verify(", occurrence)
        for marker in ("decision_signed.issued_at,", "outcome_signed.issued_at,"):
            for occurrence in (0, 1):
                self.reject_removal(file, function, marker, occurrence)

    def test_observer_facts_cannot_describe_a_future_business_outcome(self):
        self.check_markers(AGENT + "cell_q24_task_ledger_history.rs", "fn verify_original_terminal(", (
            "outcome_signing_payload_v2(&outcome) != outcome_payload", "outcome_signed.issued_at > now",
            "outcome.watermark.latest_observable_at > now", "outcome.observed_at.is_some_and(|at| at > now)",
            "outcome.watermark.finalized_at.is_some_and(|at| at > now)"))

    def test_generator_observer_independence_and_current_revocation_are_kept(self):
        self.check_markers(AGENT + "cell_q24_task_ledger_history.rs", "fn verify_original_terminal(", (
            "generator.principal() != &self.config.generator.principal",
            "observer.principal() != &self.config.observer.principal",
            "generator.principal().principal_id == observer.principal().principal_id",
            "generator.principal().credential_chain_digest", "observer.principal().credential_chain_digest",
            "generator.principal().signing_key_digest == observer.principal().signing_key_digest",
            "generator.controller_id() == observer.controller_id()",
            "self.config.generator.revoked_at.is_some_and(|at| now >= at)",
            "self.config.observer.revoked_at.is_some_and(|at| now >= at)"))

    def test_both_ledger_events_and_original_predecessors_are_reconstructed(self):
        self.check_markers(AGENT + "cell_q24_task_ledger_history.rs", "fn verify_original_terminal(", (
            "original_decision.sequence.get() != 1", "original_outcome.sequence.get() != 2",
            "original_decision.predecessor_chain_digest != decision_predecessor",
            "original_outcome.predecessor_chain_digest != original_decision.chain_digest",
            "original_outcome.predecessor_chain_digest != outcome_predecessor",
            "binding::decision_event(&decision, &decision_signed, &self.config.generator)?",
            "projection::outcome_event(&outcome, &outcome_signed, &self.config.observer)"))


    def test_dataset_resolvers_have_only_actual_writer_and_physical_reader_callers(self):
        rows = {row["id"]: row for row in self.manifest["boundary"]}
        for identifier in ("ledger_dataset_active_sources", "ledger_dataset_sequence_records"):
            self.assertEqual(rows[identifier]["product_callers"],
                             [LEDGER + "production.rs", LEDGER + "durable_read_only.rs"])
        self.assertEqual(rows["ledger_readonly_dataset_records"]["product_callers"], [])

    def test_dataset_resolution_keeps_active_indexes_and_sequence_order(self):
        self.check_markers(LEDGER + "dataset_records.rs", "fn require_active_dataset_sources(", (
            "&receipt.snapshot.source_record_digests", "self.active_record_by_digest(digest)?.is_none()",
            "return Err("))
        self.check_markers(LEDGER + "dataset_records.rs", "fn resolve_active_dataset_records(", (
            ".active_record_by_digest(digest)?", ".ok_or(ProductionLedgerError::Binding(",
            "records.sort_unstable_by_key(|record| record.sequence)"))

    def test_writer_keeps_receipt_and_record_bounds_before_shared_lookup(self):
        self.check_markers(LEDGER + "production.rs", "fn revalidate_dataset_snapshot(", (
            "verify_dataset_snapshot_receipt_v3(receipt, now)?", "self.backend.core()?",
            "LearningLedger::require_active_dataset_sources(ledger, receipt)"))
        self.check_markers(LEDGER + "production.rs", "fn read_dataset_records(", (
            "receipt.snapshot.source_record_digests.len() > 4096",
            "self.revalidate_dataset_snapshot(receipt, now)?", "self.backend.core()?",
            "LearningLedger::resolve_active_dataset_records(ledger, receipt)"))

    def test_readonly_dataset_lookup_replays_and_rechecks_owned_records(self):
        self.check_markers(LEDGER + "durable_read_only.rs", "fn read_dataset_records(", (
            "receipt.snapshot.source_record_digests.len() > 4096",
            "verify_dataset_snapshot_receipt_v3(receipt, now)?", "let before = self.observe()?",
            "LearningLedger::from_snapshot(before.snapshot.clone())?",
            "LearningLedger::require_active_dataset_sources(&ledger, receipt)?",
            "LearningLedger::resolve_active_dataset_records(&ledger, receipt)?", ".cloned()",
            "self.observe()? != before", "DurableLedgerError::Indeterminate.into()"))


if __name__ == "__main__":
    unittest.main()
