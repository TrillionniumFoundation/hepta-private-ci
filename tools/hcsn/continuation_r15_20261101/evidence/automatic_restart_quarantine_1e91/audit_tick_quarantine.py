#!/usr/bin/env python3
"""Run the complete source-extracted tick_slot method with explicit stubs.

Storage, process polling/spawn, registry and release-continuation helpers below
are synthetic boundaries. The entire outer tick_slot control flow is extracted
without edits from each tree. Native integration coverage is separately added
to the repository and must run on the combined new head.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


STUBS = r'''
use std::marker::PhantomData;
use std::path::Path;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::{Duration, Instant};
type AgentId = String;
#[derive(Clone, Debug, Eq, PartialEq)]
enum SupervisorError { NoPreviousCommand(AgentId), Invalid(String), StartFailure, PollFailure }
trait ProcessDriver { type Process; }
struct Driver;
impl ProcessDriver for Driver { type Process = (); }
#[derive(Clone, Debug, Eq, PartialEq)]
struct AgentRelease;
impl AgentRelease { fn unversioned(_: ()) -> Result<Self, SupervisorError> { Ok(Self) } }
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum SignedIntentStatus { RecoveryRequired, Queued, Committed, RolledBack }
#[derive(Clone, Debug, Eq, PartialEq)]
struct SignedIntent { status: SignedIntentStatus, digest: &'static str }
struct Runtime<P> { marker: PhantomData<P> }
#[derive(Clone, Copy)]
enum ReleaseChange { Upgrade, Rollback }
struct AgentSlot<P> { runtime: Option<Runtime<P>>, release_change: Option<ReleaseChange>, restart_pending: bool, restart_not_before: Option<Instant>, active_release: Option<AgentRelease>, last_command: Option<()>, signed_intent: Option<SignedIntent> }
struct Supervisor<D: ProcessDriver> { automatic_starts: usize, release_starts: usize, matrix_ticks: usize, exit: bool, fail_poll: bool, fail_start: bool, marker: PhantomData<D> }
struct Layout;
impl Layout { fn run_root(&self) -> &Path { Path::new("synthetic-run-root") } }
struct Record { layout: Layout }
mod restart_budget {
    use super::*;
    pub static COMPLETIONS: AtomicUsize = AtomicUsize::new(0);
    pub fn complete_restart(_: &Path) -> Result<(), &'static str> { COMPLETIONS.fetch_add(1, Ordering::SeqCst); Ok(()) }
}
impl<D: ProcessDriver> Supervisor<D> {
    fn tick_runtime(&mut self, _: &AgentId, _: &mut AgentSlot<D::Process>, _: &mut Runtime<D::Process>, _: Instant) -> Result<RuntimeTickOutcome, SupervisorError> {
        if self.fail_poll { return Err(SupervisorError::PollFailure); }
        Ok(if self.exit { RuntimeTickOutcome::Exited { restart_fault: None } } else { RuntimeTickOutcome::Keep })
    }
    fn continue_release_change_after_exit(&mut self, _: &AgentId, slot: &mut AgentSlot<D::Process>, _: Instant) -> Result<bool, SupervisorError> {
        // Explicit stand-in for an already admitted upgrade/rollback owner.
        // Only whether tick_slot calls this branch is asserted here.
        if slot.release_change.is_some() { self.release_starts += 1; slot.runtime = Some(Runtime { marker: PhantomData }); Ok(true) } else { Ok(false) }
    }
    fn start_release_slot(&mut self, _: &AgentId, slot: &mut AgentSlot<D::Process>, _: AgentRelease, _: Instant) -> Result<(), SupervisorError> {
        if self.fail_start { return Err(SupervisorError::StartFailure); }
        self.automatic_starts += 1; slot.runtime = Some(Runtime { marker: PhantomData }); Ok(())
    }
    fn record(&self, _: &AgentId) -> Result<Record, SupervisorError> { Ok(Record { layout: Layout }) }
    fn tick_matrix_companion(&mut self, _: &AgentId, _: &mut AgentSlot<D::Process>, _: Instant) -> Result<(), SupervisorError> { self.matrix_ticks += 1; Ok(()) }
}
'''

TESTS = r'''
fn setup(now: Instant) -> (Supervisor<Driver>, AgentSlot<()>) {
    restart_budget::COMPLETIONS.store(0, Ordering::SeqCst);
    (Supervisor { automatic_starts: 0, release_starts: 0, matrix_ticks: 0, exit: false, fail_poll: false, fail_start: false, marker: PhantomData }, AgentSlot { runtime: None, release_change: None, restart_pending: true, restart_not_before: Some(now), active_release: Some(AgentRelease), last_command: None, signed_intent: None })
}
fn unresolved() -> SignedIntent { SignedIntent { status: SignedIntentStatus::RecoveryRequired, digest: "exact-synthetic-intent-digest" } }
#[test]
fn recovery_quarantine_retains_pending_witness_after_eligibility() {
    let now = Instant::now(); let (mut supervisor, mut slot) = setup(now);
    slot.signed_intent = Some(unresolved());
    for advance in [Duration::ZERO, Duration::from_secs(10)] {
        assert_eq!(supervisor.tick_slot(&"agent".to_owned(), &mut slot, now + advance), Ok(()));
        assert_eq!(supervisor.automatic_starts, 0);
        assert!(slot.runtime.is_none()); assert!(slot.restart_pending);
        assert_eq!(slot.restart_not_before, Some(now));
        assert_eq!(slot.signed_intent, Some(unresolved()));
        assert_eq!(slot.active_release, Some(AgentRelease));
        assert_eq!(restart_budget::COMPLETIONS.load(Ordering::SeqCst), 0);
    }
    assert_eq!(supervisor.matrix_ticks, 2);
}
#[test]
fn quarantined_missing_previous_command_does_not_enter_startup() {
    let now = Instant::now(); let (mut supervisor, mut slot) = setup(now);
    slot.signed_intent = Some(unresolved()); slot.active_release = None;
    assert_eq!(supervisor.tick_slot(&"agent".to_owned(), &mut slot, now), Ok(()));
    assert!(slot.restart_pending); assert_eq!(supervisor.automatic_starts, 0);
    assert_eq!(restart_budget::COMPLETIONS.load(Ordering::SeqCst), 0);
}
#[test]
fn normal_pending_restart_runs_once() {
    let now = Instant::now(); let (mut supervisor, mut slot) = setup(now);
    assert_eq!(supervisor.tick_slot(&"agent".to_owned(), &mut slot, now), Ok(()));
    assert_eq!(supervisor.tick_slot(&"agent".to_owned(), &mut slot, now), Ok(()));
    assert_eq!(supervisor.automatic_starts, 1); assert!(!slot.restart_pending);
    assert_eq!(restart_budget::COMPLETIONS.load(Ordering::SeqCst), 0);
}
#[test]
fn terminal_signed_outcome_allows_existing_normal_restart() {
    for status in [SignedIntentStatus::Committed, SignedIntentStatus::RolledBack] {
        let now = Instant::now(); let (mut supervisor, mut slot) = setup(now);
        slot.signed_intent = Some(SignedIntent { status, digest: "synthetic-terminal-digest" });
        assert_eq!(supervisor.tick_slot(&"agent".to_owned(), &mut slot, now), Ok(()));
        assert_eq!(supervisor.automatic_starts, 1); assert!(!slot.restart_pending);
    }
}
#[test]
fn future_eligibility_keeps_existing_backoff() {
    let now = Instant::now(); let (mut supervisor, mut slot) = setup(now);
    slot.restart_not_before = Some(now + Duration::from_secs(1));
    assert_eq!(supervisor.tick_slot(&"agent".to_owned(), &mut slot, now), Ok(()));
    assert_eq!(supervisor.automatic_starts, 0); assert!(slot.restart_pending);
    assert_eq!(slot.restart_not_before, Some(now + Duration::from_secs(1)));
}
#[test]
fn admitted_target_and_rollback_continuation_remain_before_guard() {
    for change in [ReleaseChange::Upgrade, ReleaseChange::Rollback] {
        let now = Instant::now(); let (mut supervisor, mut slot) = setup(now);
        slot.runtime = Some(Runtime { marker: PhantomData }); slot.release_change = Some(change); slot.restart_pending = false;
        slot.signed_intent = Some(SignedIntent { status: SignedIntentStatus::Queued, digest: "synthetic-admitted-grant" }); supervisor.exit = true;
        assert_eq!(supervisor.tick_slot(&"agent".to_owned(), &mut slot, now), Ok(()));
        assert_eq!((supervisor.release_starts, supervisor.automatic_starts), (1, 0)); assert!(slot.runtime.is_some());
    }
}
#[test]
fn startup_failure_retains_existing_cleanup_and_error() {
    let now = Instant::now(); let (mut supervisor, mut slot) = setup(now); supervisor.fail_start = true;
    assert_eq!(supervisor.tick_slot(&"agent".to_owned(), &mut slot, now), Err(SupervisorError::StartFailure));
    assert!(!slot.restart_pending); assert!(slot.restart_not_before.is_none());
    assert_eq!(restart_budget::COMPLETIONS.load(Ordering::SeqCst), 1);
}
#[test]
fn poll_failure_keeps_existing_runtime_handle() {
    let now = Instant::now(); let (mut supervisor, mut slot) = setup(now); supervisor.fail_poll = true;
    slot.runtime = Some(Runtime { marker: PhantomData });
    assert_eq!(supervisor.tick_slot(&"agent".to_owned(), &mut slot, now), Err(SupervisorError::PollFailure));
    assert!(slot.runtime.is_some()); assert!(slot.restart_pending); assert_eq!(supervisor.automatic_starts, 0);
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--rustc', default='rustc')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    runs = []
    with tempfile.TemporaryDirectory(prefix='hcsn-tick-quarantine-') as temp:
        work = Path(temp)
        for label, tree in [('original', args.original), ('candidate', args.candidate)]:
            path = tree/'codex-rs/hepta-supervisor/src/tick.rs'
            text = path.read_text()
            outcome = text[text.index('enum RuntimeTickOutcome {'):text.index('impl<D: ProcessDriver> Supervisor<D> {')]
            method = text[text.index('    pub(crate) fn tick_slot('):text.index('    fn queue_automatic_restart_before_exit(')]
            generated = STUBS + outcome + '\nimpl<D: ProcessDriver> Supervisor<D> {\n' + method + '}\n' + TESTS
            source = work/f'{label}.rs'; binary = work/label
            source.write_text(generated)
            command = [args.rustc, '--edition=2024', '--test', str(source), '-o', str(binary)]
            compiled = subprocess.run(command, capture_output=True, text=True)
            assert compiled.returncode == 0, compiled.stderr
            executed = subprocess.run([str(binary), '--test-threads=1'], capture_output=True, text=True)
            runs.append({'variant': label, 'tick_source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'method_sha256': hashlib.sha256(method.encode()).hexdigest(), 'generated_sha256': hashlib.sha256(generated.encode()).hexdigest(), 'compile_command': command, 'compile_exit_code': compiled.returncode, 'compile_stderr': compiled.stderr, 'run_command': [str(binary), '--test-threads=1'], 'run_exit_code': executed.returncode, 'stdout': executed.stdout, 'stderr': executed.stderr})
    assert runs[0]['run_exit_code'] != 0 and '6 passed; 2 failed' in runs[0]['stdout'], runs[0]
    assert runs[1]['run_exit_code'] == 0 and '8 passed; 0 failed' in runs[1]['stdout'], runs[1]
    result = {'schema': 1, 'scope': 'Entire unchanged/exact-extracted tick_slot control flow; explicit synthetic process/storage/registry/release helper boundaries. Not full native integration or actual authorized release validation.', 'original_expected_failures': 2, 'candidate_expected_passes': 8, 'runs': runs}
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'original': '6 passed, 2 failed', 'candidate': '8 passed, 0 failed', 'scope': result['scope']}))


if __name__ == '__main__':
    main()
