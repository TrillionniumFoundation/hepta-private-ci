"""Guard the original state lease without granting new effect authority.

Mutation checks complement the Rust cancellation, identity and contention tests.
Historical authorization and effect-order guards still run in their own suites.
"""
from pathlib import Path
import tempfile
import unittest

import test_current_caller_migrations as migration

ROOT = migration.ROOT
PROOF = migration.PROOF
AGENT = "codex-rs/hepta-agentd/src/"
SLOT = AGENT + "cell_q24_original_state_slot.rs"
OWNERS = AGENT + "cell_q24_no_update_stage_owners.rs"
EXECUTE = AGENT + "cell_q24_no_update_stage_execute.rs"
READBACK = AGENT + "cell_q24_candidate_stage_readback.rs"
EVALUATION = AGENT + "cell_q24_candidate_stage_evaluation.rs"
OPERATION = AGENT + "cell_q24_candidate_stage_operation.rs"
ADOPTION = AGENT + "cell_q24_candidate_stage_adoption.rs"
NEXT_USE = AGENT + "cell_q24_candidate_stage_next_use.rs"


class OriginalStateSlotSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = PROOF._load_manifest(ROOT / "CALLERS.toml")

    def verifies(self, path, source):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertEqual(len(rows), 1, path)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})

    def rejects(self, path, before, after="", occurrence=0):
        source = (ROOT / path).read_text()
        self.verifies(path, source)
        start = -1
        for _ in range(occurrence + 1):
            start = source.index(before, start + 1)
        changed = source[:start] + after + source[start + len(before):]
        self.assertNotEqual(changed, source)
        # A copied comment cannot satisfy the live production closure.
        changed += "\n/*\n" + source.replace("*/", "* /") + "\n*/\n"
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(path, changed)

    def test_slot_moves_and_returns_the_exact_original_box(self):
        for before, after in (
            ("state: Mutex::new(Some(Box::new(state)))", "state: Mutex::new(None)"),
            ("slot.take().ok_or(Error::QueueFull)?",
             "slot.as_ref().cloned().ok_or(Error::QueueFull)?"),
            ("state: Some(state)", "state: None"),
            ("*slot = self.state.take();", "*slot = None;"),
            ("*slot = self.state.take();",
             "let _ = self.state.take();\n            *slot = self.state.take();"),
            ("&& slot.is_none()", "&& slot.is_some()"),
        ):
            with self.subTest(before=before, after=after):
                self.rejects(SLOT, before, after)

    def test_contention_empty_slots_and_poisoning_keep_their_fail_closed_results(self):
        for before, after in (
            ("TryLockError::WouldBlock => Error::QueueFull",
             "TryLockError::WouldBlock => Error::CommitUncertain"),
            ("TryLockError::Poisoned(_) => Error::CommitUncertain",
             "TryLockError::Poisoned(_) => Error::QueueFull"),
            ("slot.take().ok_or(Error::QueueFull)?",
             "slot.take().unwrap_or_else(|| Box::new(Default::default()))"),
            ("if let Ok(mut slot) = self.slot.state.lock()",
             "if let Ok(mut slot) = self.slot.state.lock().or_else(|e| Ok(e.into_inner()))"),
        ):
            with self.subTest(before=before):
                self.rejects(SLOT, before, after)

    def test_private_lease_cannot_gain_copy_clone_raw_guards_or_unsafe_escape(self):
        source = (ROOT / SLOT).read_text()
        self.verifies(SLOT, source)
        for addition in (
            "impl<T: Clone> Clone for OriginalStateLease<'_, T> {}",
            "impl<T: Copy> Copy for OriginalStateLease<'_, T> {}",
            "unsafe fn escape() {}",
            "struct Escape<'a, T> { held: std::sync::MutexGuard<'a, T> }",
            "fn escape<T>(state: T) { std::mem::forget(state); }",
            "fn escape<T>(state: T) { std::mem::ManuallyDrop::new(state); }",
            "fn reset() { failed = false; }",
            "async fn hold_guard() { pending().await; }",
        ):
            with self.subTest(addition=addition):
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(SLOT, source + "\n" + addition + "\n")
        self.rejects(SLOT, "state: Mutex<Option<Box<T>>>",
                     "pub(super) state: Mutex<Option<Box<T>>>")
        self.rejects(SLOT, "slot: &'a OriginalStateSlot<T>",
                     "pub(super) slot: &'a OriginalStateSlot<T>")

    def test_live_take_and_access_checks_cannot_move_to_test_only_or_dead_code(self):
        self.rejects(SLOT, "pub(super) fn try_take(",
                     "#[cfg(test)]\n    pub(super) fn try_take(")
        self.rejects(SLOT, "let state = slot.take().ok_or(Error::QueueFull)?;",
                     "if false { let state = slot.take().ok_or(Error::QueueFull)?; }")
        self.rejects(SLOT, "self.state.as_deref().ok_or(Error::CommitUncertain)",
                     "self.state.as_deref().unwrap()")
        self.rejects(SLOT, "self.state.as_deref_mut().ok_or(Error::CommitUncertain)",
                     "self.state.as_deref_mut().unwrap()")

    def test_continuation_and_lane_io_require_a_checked_lease(self):
        for path, marker in (
            (OWNERS, "self.continuation.try_take()?"),
            (EXECUTE, "self.continuation.try_take()?"),
            (READBACK, "self.candidate.try_take()?"),
            (EVALUATION, "self.evaluation.try_take()?"),
            (OPERATION, "owners.operation.try_take()?"),
            (ADOPTION, "self.common.continuation.try_take()?"),
            (NEXT_USE, "self.common.continuation.try_take()?"),
        ):
            with self.subTest(path=path):
                self.rejects(path, marker, marker.replace("try_take()?", "try_lock().unwrap()"))
        self.rejects(OWNERS, "let state = state_lease.state_mut()?;")
        self.rejects(OWNERS, "let state = state_lease.state_mut()?;", occurrence=1)
        self.rejects(EXECUTE, "let state = state_lease.state_mut()?;")
        self.rejects(READBACK, "let lane = lane_lease.state_mut()?;")
        self.rejects(EVALUATION, "let lane = lane_lease.state_mut()?;")
        self.rejects(OPERATION, "let common = common_lease.state_mut()?;")
        self.rejects(OPERATION, "let common = common_lease.state_mut()?;", occurrence=1)

    def test_error_and_cancellation_latches_are_set_before_original_io(self):
        self.rejects(OPERATION, "if lane.state()?.failed", "if false")
        self.rejects(OPERATION, "lane.state_mut()?.failed = true",
                     "lane.state_mut()?.failed = false")
        for path in (READBACK, EVALUATION):
            with self.subTest(path=path):
                self.rejects(path, "if lane.failed", "if false")
                self.rejects(path, "lane.failed = true", "lane.failed = false")

    def test_no_latch_can_reopen_before_verified_completion(self):
        for path, marker, reset in (
            (READBACK, "lane.failed = true;", "lane.failed = false;"),
            (EVALUATION, "lane.failed = true;", "lane.failed = false;"),
            (OPERATION, "let fresh = self.0.authenticate_prefix(auth::now()?)?;",
             "self.0.lane.state_mut()?.failed = false;"),
            (OPERATION, "let signatures = self.authenticate_result(snapshot, observed)?;",
             "self.operation.0.lane.state_mut()?.failed = false;"),
        ):
            with self.subTest(path=path, marker=marker):
                self.rejects(path, marker, reset + "\n        " + marker)
        self.rejects(OPERATION, "drop(common_lease);", "drop(common);")
        source = (ROOT / OPERATION).read_text()
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(OPERATION, source +
                          "\nimpl Drop for CandidateOriginalOperation<'_> {}\n")


if __name__ == "__main__":
    unittest.main()
