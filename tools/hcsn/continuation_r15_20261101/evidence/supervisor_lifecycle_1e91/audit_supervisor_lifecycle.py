#!/usr/bin/env python3
"""Compile source-extracted lifecycle fragments with explicit synthetic boundaries.

This is not the repository native suite: durable restart storage, protocol wire
encoding, and process/registry I/O are replaced by named synthetic inputs. The
unchanged Rust method, actual fixture response construction, and production
drain validation tail are compiled and executed for before/after comparison.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


STUBS = r'''
use std::cell::RefCell;
use std::marker::PhantomData;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};
type AgentId = String;
#[derive(Debug, Eq, PartialEq)]
enum SupervisorError { RestartBudgetExhausted(AgentId), Invalid(String) }
#[derive(Clone, Debug, Eq, PartialEq)]
enum SupervisorEventKind { RestartQueued, AutomaticRestartQueued { attempt: u32 }, AutomaticRestartBudgetExhausted { attempts: u32 } }
trait ProcessDriver { type Process; }
struct Driver;
impl ProcessDriver for Driver { type Process = (); }
struct Config { restart_max_attempts: u32, restart_window: Duration, restart_backoff_base: Duration }
struct Supervisor<D: ProcessDriver> { config: Config, marker: PhantomData<D> }
struct AgentSlot<P> { restart_attempt: u32, restart_not_before: Option<Instant>, restart_pending: bool, events: Vec<(u64, SupervisorEventKind)>, marker: PhantomData<P> }
impl<P> AgentSlot<P> { fn event(&mut self, generation: u64, event: SupervisorEventKind) { self.events.push((generation, event)); } }
struct Layout;
impl Layout { fn run_root(&self) -> &Path { Path::new("synthetic-run-root") } }
struct Record { layout: Layout, lifecycle: AgentLifecycleState }
impl<D: ProcessDriver> Supervisor<D> { fn record(&self, _: &AgentId) -> Result<Record, SupervisorError> { Ok(Record { layout: Layout, lifecycle: AgentLifecycleState { lifecycle: AgentLifecycle::Running, generation: 7 } }) } }
mod restart_budget {
    use super::*;
    pub struct Claim { pub attempt: u32, pub backoff: Duration }
    #[derive(Debug)]
    pub enum RestartBudgetError { Exhausted, Invalid }
    impl std::fmt::Display for RestartBudgetError { fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result { write!(f, "{self:?}") } }
    thread_local! { pub static NEXT: RefCell<Option<Result<Claim, RestartBudgetError>>> = const { RefCell::new(None) }; }
    // Explicit injected storage boundary; this does not exercise durable claims.
    pub fn claim_restart(_: &Path, _: u32, _: Duration, _: Duration) -> Result<Claim, RestartBudgetError> { NEXT.with(|next| next.borrow_mut().take().expect("injected claim")) }
}
use restart_budget::RestartBudgetError;
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum AgentLifecycle { Starting, Running, Draining, Failed, Stopped }
struct AgentLifecycleState { lifecycle: AgentLifecycle, generation: u64 }
#[derive(Clone, Copy, Eq, PartialEq)]
enum AgentdMethod { Health, Drain }
struct AgentdRequest { request_id: u64, method: AgentdMethod }
#[derive(Debug)]
struct DrainSnapshot { admission_closed: bool, running_turns: u32, drained: bool, lifecycle: AgentLifecycle, fenced: bool }
#[derive(Debug)]
struct HealthSnapshot { promotion_ready: bool, ready: bool, fenced: bool, lifecycle: AgentLifecycle, process_id: u32, workspace: PathBuf, home_root: PathBuf, run_root: PathBuf }
#[derive(Debug)]
enum AgentdPayload { Drain(DrainSnapshot), Health(HealthSnapshot) }
struct AgentdResponse { schema_version: u32, request_id: u64, agent_id: AgentId, spawn_generation: u64, current_generation: u64, payload: AgentdPayload }
struct AgentHealthProbeIdentity { agent_id: AgentId, spawn_generation: u64 }
#[derive(Debug)]
struct ProcessDriverError(String);
impl ProcessDriverError { fn new(message: &str) -> Self { Self(message.to_owned()) } }
const AGENTD_CONTROL_SCHEMA_VERSION: u32 = 1;
'''

TESTS = r'''
fn setup() -> (Supervisor<Driver>, AgentSlot<()>) {
    (Supervisor { config: Config { restart_max_attempts: 3, restart_window: Duration::from_secs(300), restart_backoff_base: Duration::from_millis(250) }, marker: PhantomData }, AgentSlot { restart_attempt: 0, restart_not_before: None, restart_pending: false, events: Vec::new(), marker: PhantomData })
}
#[test]
fn exact_attempt_events_follow_successful_claims() {
    for attempt in 1..=3 {
        let (supervisor, mut slot) = setup();
        let backoff = Duration::from_millis(250_u64 << (attempt - 1));
        restart_budget::NEXT.with(|next| next.replace(Some(Ok(restart_budget::Claim { attempt, backoff }))));
        let now = Instant::now();
        assert_eq!(supervisor.queue_automatic_restart_before_exit(&"agent".to_owned(), &mut slot, now), None);
        assert_eq!((slot.restart_attempt, slot.restart_not_before, slot.restart_pending), (attempt, Some(now + backoff), true));
        assert_eq!(slot.events, vec![(7, SupervisorEventKind::RestartQueued), (7, SupervisorEventKind::AutomaticRestartQueued { attempt })]);
    }
}
#[test]
fn exhaustion_reports_event_and_preserves_error() {
    let (supervisor, mut slot) = setup();
    slot.restart_attempt = 3; slot.restart_pending = true; slot.restart_not_before = Some(Instant::now());
    restart_budget::NEXT.with(|next| next.replace(Some(Err(RestartBudgetError::Exhausted))));
    assert_eq!(supervisor.queue_automatic_restart_before_exit(&"agent".to_owned(), &mut slot, Instant::now()), Some(SupervisorError::RestartBudgetExhausted("agent".to_owned())));
    assert_eq!((slot.restart_attempt, slot.restart_not_before, slot.restart_pending), (3, None, false));
    assert_eq!(slot.events, vec![(7, SupervisorEventKind::AutomaticRestartBudgetExhausted { attempts: 3 })]);
}
#[test]
fn storage_error_does_not_publish_attempt_or_exhaustion() {
    let (supervisor, mut slot) = setup();
    restart_budget::NEXT.with(|next| next.replace(Some(Err(RestartBudgetError::Invalid))));
    assert_eq!(supervisor.queue_automatic_restart_before_exit(&"agent".to_owned(), &mut slot, Instant::now()), Some(SupervisorError::Invalid("Invalid".to_owned())));
    assert!(slot.events.is_empty()); assert!(!slot.restart_pending); assert!(slot.restart_not_before.is_none());
}
fn response(method: AgentdMethod, state: AgentLifecycle, generation: u64) -> AgentdResponse {
    fixture_response(AgentdRequest { request_id: 11, method }, "agent".to_owned(), 5, AgentLifecycleState { lifecycle: state, generation })
}
#[test]
fn draining_fixture_passes_existing_production_guard() {
    let identity = AgentHealthProbeIdentity { agent_id: "agent".to_owned(), spawn_generation: 5 };
    assert_eq!(validate_response(&identity, 11, response(AgentdMethod::Drain, AgentLifecycle::Draining, 7)).ok(), Some(true));
}
#[test]
fn non_draining_or_stale_generation_never_acknowledges() {
    let identity = AgentHealthProbeIdentity { agent_id: "agent".to_owned(), spawn_generation: 5 };
    for state in [AgentLifecycle::Starting, AgentLifecycle::Running, AgentLifecycle::Failed, AgentLifecycle::Stopped] {
        assert!(validate_response(&identity, 11, response(AgentdMethod::Drain, state, 7)).is_err());
    }
    assert!(validate_response(&identity, 11, response(AgentdMethod::Drain, AgentLifecycle::Draining, 8)).is_err());
    assert!(validate_response(&identity, 12, response(AgentdMethod::Drain, AgentLifecycle::Draining, 7)).is_err());
}
#[test]
fn health_fixture_retains_ready_state_and_payload_kind() {
    for state in [AgentLifecycle::Starting, AgentLifecycle::Running, AgentLifecycle::Draining, AgentLifecycle::Failed, AgentLifecycle::Stopped] {
        let AgentdPayload::Health(snapshot) = response(AgentdMethod::Health, state, 7).payload else { panic!("health payload changed"); };
        assert_eq!(snapshot.ready, state == AgentLifecycle::Running);
        assert!(snapshot.promotion_ready); assert!(!snapshot.fenced); assert_eq!(snapshot.lifecycle, state);
    }
}
'''


def between(source, start, end):
    assert source.count(start) == 1 and source.count(end) == 1
    return source[source.index(start):source.index(end)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--rustc", default="rustc")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    relative = Path("codex-rs/hepta-supervisor")
    runtime = (args.original / relative / "src/runtime.rs").read_text()
    deadline = between(runtime, "pub(crate) fn deadline(", "pub(crate) fn bounded_message(")
    unix = (args.original / relative / "src/unix.rs").read_text()
    drain_function = between(unix, "fn query_agent_drain_once(", "fn query_matrix_health_once(")
    guard = drain_function[drain_function.index("    let exact_envelope = response.schema_version"):]
    rows = []
    with tempfile.TemporaryDirectory(prefix="hcsn-supervisor-fragments-") as temp:
        work = Path(temp)
        for label, tree in (("original", args.original), ("candidate", args.candidate)):
            tick = (tree / relative / "src/tick.rs").read_text()
            method = between(tick, "    fn queue_automatic_restart_before_exit(", "    fn tick_runtime(")
            paired = (tree / relative / "tests/paired_process_product.rs").read_text()
            child = between(paired, "fn run_agent_child()", "fn latest_lifecycle(")
            response = between(child, "        let running = lifecycle.lifecycle", "        let mut stream = reader.into_inner();")
            source = STUBS + deadline + "\nimpl<D: ProcessDriver> Supervisor<D> {\n" + method + "}\n"
            source += "fn fixture_response(request: AgentdRequest, agent_id: AgentId, spawn_generation: u64, lifecycle: AgentLifecycleState) -> AgentdResponse {\nlet (workspace, home_root, run_root) = (PathBuf::from(\"workspace\"), PathBuf::from(\"home\"), PathBuf::from(\"run\"));\n" + response + "response\n}\n"
            source += "fn validate_response(identity: &AgentHealthProbeIdentity, request_id: u64, response: AgentdResponse) -> Result<bool, ProcessDriverError> {\n" + guard + TESTS
            rust_file = work / f"{label}.rs"
            rust_file.write_text(source)
            binary = work / label
            command = [args.rustc, "--edition=2024", "--test", str(rust_file), "-o", str(binary)]
            compiled = subprocess.run(command, text=True, capture_output=True)
            assert compiled.returncode == 0, compiled.stderr
            executed = subprocess.run([str(binary), "--test-threads=1"], text=True, capture_output=True)
            rows.append({"variant": label, "source_sha256": hashlib.sha256(source.encode()).hexdigest(), "compile_command": command, "compile_exit_code": compiled.returncode, "compile_stderr": compiled.stderr, "run_command": [str(binary), "--test-threads=1"], "run_exit_code": executed.returncode, "stdout": executed.stdout, "stderr": executed.stderr})
    assert rows[0]["run_exit_code"] != 0 and "3 passed; 3 failed" in rows[0]["stdout"], rows[0]
    assert rows[1]["run_exit_code"] == 0 and "6 passed; 0 failed" in rows[1]["stdout"], rows[1]
    result = {"schema": 1, "scope": "source-extracted Rust fragments with synthetic storage/registry/types; no native suite or wire/process I/O claim", "production_drain_guard_unchanged": True, "before_after_expected": True, "runs": rows}
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"original": "3 passed, 3 failed", "candidate": "6 passed, 0 failed", "scope": result["scope"]}))


if __name__ == "__main__":
    main()
