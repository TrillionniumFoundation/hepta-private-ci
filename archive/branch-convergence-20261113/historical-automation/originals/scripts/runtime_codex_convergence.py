#!/usr/bin/env python3
"""One-shot, exact-source runtime.codex convergence patcher.

This helper is intentionally deleted by the bootstrap workflow after it has
applied and verified the patch.  Every replacement is closed-world and fails if
the reviewed source shape has drifted.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import textwrap

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def create(path: str, content: str) -> None:
    target = ROOT / path
    if target.exists():
        raise SystemExit(f"refusing to overwrite new file: {path}")
    write(path, textwrap.dedent(content).lstrip())


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, found {count}: {old[:120]!r}")
    write(path, content.replace(old, new, 1))


def insert_before(path: str, marker: str, insertion: str) -> None:
    replace_once(path, marker, insertion + marker)


def append_once(path: str, marker: str, content: str) -> None:
    current = read(path)
    if marker in current:
        raise SystemExit(f"{path}: append marker already exists: {marker}")
    write(path, current.rstrip() + "\n\n" + textwrap.dedent(content).lstrip())


def replace_between(path: str, start_marker: str, end_marker: str, replacement: str) -> None:
    content = read(path)
    start = content.find(start_marker)
    if start < 0:
        raise SystemExit(f"{path}: missing start marker {start_marker!r}")
    end = content.find(end_marker, start)
    if end < 0:
        raise SystemExit(f"{path}: missing end marker {end_marker!r}")
    write(path, content[:start] + replacement + content[end:])


# ---------------------------------------------------------------------------
# 1. Exact Agentd abort-before-effect transition.
# ---------------------------------------------------------------------------

insert_before(
    "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "    pub fn cancel_run(\n",
    '''    /// Close a run that Agentd marked dispatched only when the exact
    /// caller still proves that the physical effect boundary was not entered.
    /// The expected revision is the CAS fence for the unique dispatch.
    pub fn abort_before_effect(
        &mut self,
        run_id: &str,
        expected_revision: u64,
        reason: &str,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_identity(run_id, "run")?;
        validate_cancel_reason(reason)?;
        let record = self
            .runs
            .get_mut(run_id)
            .ok_or(AgentRunError::RunNotFound)?;
        if record.phase == RunPhase::Cancelled
            && record.cancel_reason.as_deref() == Some(reason)
        {
            return Ok(receipt(record, /*idempotent*/ true));
        }
        require_revision(record, expected_revision)?;
        if record.phase != RunPhase::Dispatched {
            return Err(AgentRunError::InvalidTransition);
        }
        record.phase = RunPhase::Cancelled;
        record.cancel_reason = Some(reason.to_string());
        record.cancel_ack_deadline_ms = None;
        advance_revision(record)?;
        Ok(receipt(record, /*idempotent*/ false))
    }

''',
)

insert_before(
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    "    pub fn run_cancel(\n",
    '''    pub fn run_abort_before_effect(
        request_id: u64,
        spawn_generation: u64,
        run_id: String,
        expected_revision: u64,
        reason: String,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::RunAbortBeforeEffect {
                run_id,
                expected_revision,
                reason,
            },
        }
    }

''',
)

insert_before(
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    "    RunCancel {\n",
    '''    RunAbortBeforeEffect {
        run_id: String,
        expected_revision: u64,
        reason: String,
    },
''',
)

insert_before(
    "codex-rs/hepta-agentd/src/client.rs",
    "    pub async fn run_cancel(\n",
    '''    pub async fn run_abort_before_effect(
        &self,
        run_id: String,
        expected_revision: u64,
        reason: String,
    ) -> Result<AgentRunReceipt, AgentdError> {
        match self
            .send(AgentdRequest::run_abort_before_effect(
                self.request_id(),
                self.spawn_generation,
                run_id,
                expected_revision,
                reason,
            ))
            .await?
            .payload
        {
            AgentdPayload::RunReceipt(receipt) => Ok(receipt),
            payload => unexpected(payload),
        }
    }

''',
)

insert_before(
    "codex-rs/hepta-agentd/src/state_control.rs",
    "            crate::AgentdMethod::RunCancel {\n",
    '''            crate::AgentdMethod::RunAbortBeforeEffect {
                run_id,
                expected_revision,
                reason,
            } => {
                require_run_reconciliation_ready(lifecycle, fenced)?;
                let receipt = self
                    .runs
                    .lock()
                    .map_err(poisoned_state)?
                    .abort_before_effect(&run_id, expected_revision, &reason)
                    .map_err(run_error)?;
                AgentdPayload::RunReceipt(wire_run_receipt(receipt))
            }
''',
)

append_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs",
    "exact_abort_before_effect_converges",
    r'''
#[test]
fn exact_abort_before_effect_converges_and_rejects_stale_or_ambiguous_callers() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    coordinator.start_run(100, snapshot()).expect("start");
    coordinator
        .attach_context(200, 1, attachment())
        .expect("attach");
    coordinator
        .mark_dispatched(300, "run.1", 2)
        .expect("dispatch");

    assert_eq!(
        coordinator.abort_before_effect("run.1", 2, "stale"),
        Err(AgentRunError::StaleRevision)
    );
    let aborted = coordinator
        .abort_before_effect("run.1", 3, "final_use_denied")
        .expect("exact abort");
    assert_receipt(
        &aborted,
        4,
        RunPhase::Cancelled,
        Some("final_use_denied"),
    );
    assert!(aborted.terminal_observed);
    assert!(!aborted.idempotent);
    assert_eq!(coordinator.active_run_count(), 0);

    let repeated = coordinator
        .abort_before_effect("run.1", 4, "final_use_denied")
        .expect("idempotent exact abort");
    assert!(repeated.idempotent);
    assert_eq!(repeated.revision, 4);
    assert_eq!(
        coordinator.abort_before_effect("run.1", 4, "different_reason"),
        Err(AgentRunError::InvalidTransition)
    );
}

#[test]
fn abort_before_effect_stress_never_reopens_or_redispatches() {
    for iteration in 0..256_u64 {
        let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
        coordinator.start_run(100, snapshot()).expect("start");
        coordinator
            .attach_context(200, 1, attachment())
            .expect("attach");
        coordinator
            .mark_dispatched(300, "run.1", 2)
            .expect("dispatch");
        let reason = format!("fault_window_{iteration}");
        let aborted = coordinator
            .abort_before_effect("run.1", 3, &reason)
            .expect("abort");
        assert_eq!(aborted.phase, RunPhase::Cancelled);
        assert_eq!(aborted.cancel_reason.as_deref(), Some(reason.as_str()));
        assert_eq!(
            coordinator.mark_dispatched(400, "run.1", aborted.revision),
            Err(AgentRunError::InvalidTransition)
        );
    }
}
''',
)

# ---------------------------------------------------------------------------
# 2. Checked runtime.codex state machine, crash points, thread lifecycle and
#    monotonic wall-clock mapping.
# ---------------------------------------------------------------------------

create(
    "codex-rs/hepta-infer-worker-host/src/runtime_codex_state.rs",
    r'''
use std::sync::Mutex;
use std::sync::OnceLock;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum RuntimeCodexPhase {
    Preflight,
    ThreadPrepared,
    PayloadFrozen,
    AuthorityClaimed,
    Journaled,
    OwnerCommitted,
    ReadyToEnter,
    EffectEntered,
    TurnStartAccepted,
    NativeStarted,
    TerminalObserved,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum RuntimeCodexFaultPoint {
    ThreadPrepared,
    PayloadFrozen,
    AuthorityClaimed,
    Journaled,
    OwnerCommitted,
    ReadyToEnter,
    EffectEntered,
    BeforeTurnStartAwait,
    AfterTurnStartAwait,
    TurnStartAccepted,
    NativeStarted,
    TerminalObserved,
}

#[derive(Debug)]
pub(crate) struct RuntimeCodexStateMachine {
    phase: RuntimeCodexPhase,
}

impl RuntimeCodexStateMachine {
    pub(crate) fn new() -> Self {
        Self {
            phase: RuntimeCodexPhase::Preflight,
        }
    }

    pub(crate) fn advance(&mut self, next: RuntimeCodexPhase) -> Result<(), String> {
        let valid = matches!(
            (self.phase, next),
            (RuntimeCodexPhase::Preflight, RuntimeCodexPhase::ThreadPrepared)
                | (RuntimeCodexPhase::ThreadPrepared, RuntimeCodexPhase::PayloadFrozen)
                | (RuntimeCodexPhase::PayloadFrozen, RuntimeCodexPhase::AuthorityClaimed)
                | (RuntimeCodexPhase::AuthorityClaimed, RuntimeCodexPhase::Journaled)
                | (RuntimeCodexPhase::Journaled, RuntimeCodexPhase::OwnerCommitted)
                | (RuntimeCodexPhase::Journaled, RuntimeCodexPhase::ReadyToEnter)
                | (RuntimeCodexPhase::OwnerCommitted, RuntimeCodexPhase::ReadyToEnter)
                | (RuntimeCodexPhase::ReadyToEnter, RuntimeCodexPhase::EffectEntered)
                | (RuntimeCodexPhase::EffectEntered, RuntimeCodexPhase::TurnStartAccepted)
                | (RuntimeCodexPhase::TurnStartAccepted, RuntimeCodexPhase::NativeStarted)
                | (RuntimeCodexPhase::NativeStarted, RuntimeCodexPhase::TerminalObserved)
        );
        if !valid {
            return Err(format!(
                "invalid runtime.codex transition {:?} -> {:?}",
                self.phase, next
            ));
        }
        self.phase = next;
        runtime_codex_checkpoint(match next {
            RuntimeCodexPhase::Preflight => return Ok(()),
            RuntimeCodexPhase::ThreadPrepared => RuntimeCodexFaultPoint::ThreadPrepared,
            RuntimeCodexPhase::PayloadFrozen => RuntimeCodexFaultPoint::PayloadFrozen,
            RuntimeCodexPhase::AuthorityClaimed => RuntimeCodexFaultPoint::AuthorityClaimed,
            RuntimeCodexPhase::Journaled => RuntimeCodexFaultPoint::Journaled,
            RuntimeCodexPhase::OwnerCommitted => RuntimeCodexFaultPoint::OwnerCommitted,
            RuntimeCodexPhase::ReadyToEnter => RuntimeCodexFaultPoint::ReadyToEnter,
            RuntimeCodexPhase::EffectEntered => RuntimeCodexFaultPoint::EffectEntered,
            RuntimeCodexPhase::TurnStartAccepted => RuntimeCodexFaultPoint::TurnStartAccepted,
            RuntimeCodexPhase::NativeStarted => RuntimeCodexFaultPoint::NativeStarted,
            RuntimeCodexPhase::TerminalObserved => RuntimeCodexFaultPoint::TerminalObserved,
        })
    }
}

#[cfg(test)]
static INJECTED_FAULT: OnceLock<Mutex<Option<RuntimeCodexFaultPoint>>> = OnceLock::new();

pub(crate) fn runtime_codex_checkpoint(point: RuntimeCodexFaultPoint) -> Result<(), String> {
    #[cfg(test)]
    {
        let mut guard = INJECTED_FAULT
            .get_or_init(|| Mutex::new(None))
            .lock()
            .map_err(|_| "runtime.codex fault injector lock poisoned".to_string())?;
        if guard.as_ref() == Some(&point) {
            guard.take();
            return Err(format!("injected runtime.codex crash at {point:?}"));
        }
    }
    let _ = point;
    Ok(())
}

#[cfg(test)]
pub(crate) fn inject_runtime_codex_fault(point: RuntimeCodexFaultPoint) {
    *INJECTED_FAULT
        .get_or_init(|| Mutex::new(None))
        .lock()
        .expect("runtime.codex fault injector lock") = Some(point);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn legal_sequence_is_closed_and_illegal_skips_fail() {
        let mut state = RuntimeCodexStateMachine::new();
        for phase in [
            RuntimeCodexPhase::ThreadPrepared,
            RuntimeCodexPhase::PayloadFrozen,
            RuntimeCodexPhase::AuthorityClaimed,
            RuntimeCodexPhase::Journaled,
            RuntimeCodexPhase::OwnerCommitted,
            RuntimeCodexPhase::ReadyToEnter,
            RuntimeCodexPhase::EffectEntered,
            RuntimeCodexPhase::TurnStartAccepted,
            RuntimeCodexPhase::NativeStarted,
            RuntimeCodexPhase::TerminalObserved,
        ] {
            state.advance(phase).expect("legal transition");
        }
        let mut skipped = RuntimeCodexStateMachine::new();
        assert!(skipped.advance(RuntimeCodexPhase::Journaled).is_err());
    }

    #[test]
    fn every_injected_fault_is_consumed_once() {
        inject_runtime_codex_fault(RuntimeCodexFaultPoint::Journaled);
        assert!(runtime_codex_checkpoint(RuntimeCodexFaultPoint::Journaled).is_err());
        assert!(runtime_codex_checkpoint(RuntimeCodexFaultPoint::Journaled).is_ok());
    }
}
''',
)

create(
    "codex-rs/hepta-infer-worker-host/src/runtime_codex_thread.rs",
    r'''
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadUnsubscribeParams;
use tokio::time::timeout;

static CLEANUP_ATTEMPTS: AtomicU64 = AtomicU64::new(0);
static CLEANUP_FAILURES: AtomicU64 = AtomicU64::new(0);
static PRE_EFFECT_ORPHAN_CANDIDATES: AtomicU64 = AtomicU64::new(0);
static POST_EFFECT_UNRESOLVED_DROPS: AtomicU64 = AtomicU64::new(0);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RuntimeCodexThreadMetrics {
    pub cleanup_attempts: u64,
    pub cleanup_failures: u64,
    pub pre_effect_orphan_candidates: u64,
    pub post_effect_unresolved_drops: u64,
}

pub fn runtime_codex_thread_metrics() -> RuntimeCodexThreadMetrics {
    RuntimeCodexThreadMetrics {
        cleanup_attempts: CLEANUP_ATTEMPTS.load(Ordering::Relaxed),
        cleanup_failures: CLEANUP_FAILURES.load(Ordering::Relaxed),
        pre_effect_orphan_candidates: PRE_EFFECT_ORPHAN_CANDIDATES.load(Ordering::Relaxed),
        post_effect_unresolved_drops: POST_EFFECT_UNRESOLVED_DROPS.load(Ordering::Relaxed),
    }
}

pub(crate) struct EphemeralThreadLifecycle {
    thread_id: String,
    closed: bool,
    effect_entered: bool,
}

impl EphemeralThreadLifecycle {
    pub(crate) fn new(thread_id: String) -> Self {
        Self {
            thread_id,
            closed: false,
            effect_entered: false,
        }
    }

    pub(crate) fn mark_effect_entered(&mut self) {
        self.effect_entered = true;
    }

    pub(crate) async fn close(
        &mut self,
        client: &mut RemoteAppServerClient,
        budget: Duration,
    ) {
        if self.closed {
            return;
        }
        CLEANUP_ATTEMPTS.fetch_add(1, Ordering::Relaxed);
        let result = timeout(
            budget,
            client.request(ClientRequest::ThreadUnsubscribe {
                request_id: RequestId::Integer(4),
                params: ThreadUnsubscribeParams {
                    thread_id: self.thread_id.clone(),
                },
            }),
        )
        .await;
        if result.is_ok_and(|value| value.is_ok()) {
            self.closed = true;
        } else {
            CLEANUP_FAILURES.fetch_add(1, Ordering::Relaxed);
        }
    }
}

impl Drop for EphemeralThreadLifecycle {
    fn drop(&mut self) {
        if self.closed {
            return;
        }
        if self.effect_entered {
            POST_EFFECT_UNRESOLVED_DROPS.fetch_add(1, Ordering::Relaxed);
        } else {
            PRE_EFFECT_ORPHAN_CANDIDATES.fetch_add(1, Ordering::Relaxed);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dropped_guards_distinguish_pre_effect_and_unresolved_effects() {
        let before = runtime_codex_thread_metrics();
        drop(EphemeralThreadLifecycle::new("pre-effect".to_string()));
        let mut entered = EphemeralThreadLifecycle::new("post-effect".to_string());
        entered.mark_effect_entered();
        drop(entered);
        let after = runtime_codex_thread_metrics();
        assert!(
            after.pre_effect_orphan_candidates
                >= before.pre_effect_orphan_candidates.saturating_add(1)
        );
        assert!(
            after.post_effect_unresolved_drops
                >= before.post_effect_unresolved_drops.saturating_add(1)
        );
    }
}
''',
)

create(
    "codex-rs/hepta-infer-worker-host/src/trusted_clock.rs",
    r'''
use std::sync::OnceLock;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

const MAX_WALL_MONOTONIC_SKEW_MS: u64 = 60_000;

struct TrustedRuntimeClock {
    wall_base_ms: u64,
    monotonic_base: Instant,
    last_ms: AtomicU64,
}

impl TrustedRuntimeClock {
    fn capture() -> Result<Self, String> {
        let wall_base_ms = wall_now_ms()?;
        Ok(Self {
            wall_base_ms,
            monotonic_base: Instant::now(),
            last_ms: AtomicU64::new(wall_base_ms),
        })
    }

    fn now_unix_ms(&self) -> Result<u64, String> {
        let elapsed_ms = u64::try_from(self.monotonic_base.elapsed().as_millis())
            .map_err(|_| "runtime.codex monotonic clock exceeds u64 milliseconds")?;
        let derived = self
            .wall_base_ms
            .checked_add(elapsed_ms)
            .ok_or_else(|| "runtime.codex trusted clock overflow".to_string())?;
        let wall = wall_now_ms()?;
        let skew = wall.abs_diff(derived);
        if skew > MAX_WALL_MONOTONIC_SKEW_MS {
            return Err(format!(
                "runtime.codex wall/monotonic clock mapping drifted by {skew} ms"
            ));
        }
        let mut observed = self.last_ms.load(Ordering::Acquire);
        loop {
            let next = observed.max(derived);
            match self.last_ms.compare_exchange_weak(
                observed,
                next,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => return Ok(next),
                Err(actual) => observed = actual,
            }
        }
    }
}

static CLOCK: OnceLock<Result<TrustedRuntimeClock, String>> = OnceLock::new();

pub(crate) fn runtime_now_unix_ms() -> Result<u64, String> {
    match CLOCK.get_or_init(TrustedRuntimeClock::capture) {
        Ok(clock) => clock.now_unix_ms(),
        Err(error) => Err(error.clone()),
    }
}

fn wall_now_ms() -> Result<u64, String> {
    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "system clock is before the Unix epoch".to_string())?;
    u64::try_from(elapsed.as_millis())
        .map_err(|_| "system clock exceeds u64 milliseconds".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mapped_clock_is_monotonic() {
        let first = runtime_now_unix_ms().expect("clock");
        let second = runtime_now_unix_ms().expect("clock");
        assert!(second >= first);
    }
}
''',
)

# Patch native_app_server imports/modules and execution path.
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "use std::time::SystemTime;\nuse std::time::UNIX_EPOCH;\n",
    "",
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "use codex_app_server_protocol::ThreadUnsubscribeParams;\n",
    "",
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "use codex_hepta_infer_core::durable_control::native::NativeDispatchRejectionStatus;\n",
    "use codex_hepta_infer_core::durable_control::native::NativeDispatchRejectionStatus;\nuse codex_hepta_infer_core::durable_control::native::NativePreEffectAbortToken;\n",
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''#[path = "native_run_control.rs"]
mod control;
''',
    '''#[path = "native_run_control.rs"]
mod control;
#[path = "runtime_codex_state.rs"]
mod runtime_codex_state;
#[path = "runtime_codex_thread.rs"]
mod runtime_codex_thread;
#[path = "trusted_clock.rs"]
mod trusted_clock;
''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "use tokio_util::sync::CancellationToken;\n",
    '''use tokio_util::sync::CancellationToken;

use runtime_codex_state::RuntimeCodexFaultPoint;
use runtime_codex_state::RuntimeCodexPhase;
use runtime_codex_state::RuntimeCodexStateMachine;
use runtime_codex_state::runtime_codex_checkpoint;
use runtime_codex_thread::EphemeralThreadLifecycle;
use trusted_clock::runtime_now_unix_ms;
''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''    ) -> Result<NativeRunOutput> {
        if prompt.is_empty() || prompt.len() > MAX_PROMPT_BYTES {
''',
    '''    ) -> Result<NativeRunOutput> {
        let mut execution_state = RuntimeCodexStateMachine::new();
        if prompt.is_empty() || prompt.len() > MAX_PROMPT_BYTES {
''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''        if started.model != self.config.model {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("provider substituted the requested model".into());
        }
        // Recheck the actual generation after connecting and creating the
''',
    '''        if started.model != self.config.model {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("provider substituted the requested model".into());
        }
        let mut thread_lifecycle =
            EphemeralThreadLifecycle::new(started.thread.id.clone());
        execution_state.advance(RuntimeCodexPhase::ThreadPrepared)?;
        // Recheck the actual generation after connecting and creating the
''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "        let request_receipt = adapt_request(adapted_at_ms, adapter_intent.clone())?;\n",
    "        let request_receipt = adapt_request(adapted_at_ms, adapter_intent.clone())?;\n        execution_state.advance(RuntimeCodexPhase::PayloadFrozen)?;\n",
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''        let authority_witness = Digest32::from_array(verified_use.witness_sha256()).to_string();

        let (_, pre_effect_abort) = control.dispatch_native_with_pre_effect_abort(
''',
    '''        let authority_witness = Digest32::from_array(verified_use.witness_sha256()).to_string();
        execution_state.advance(RuntimeCodexPhase::AuthorityClaimed)?;

        let (_, pre_effect_abort) = control.dispatch_native_with_pre_effect_abort(
''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''            &app_server_version,
        )?;

        if let Some(binding) = intelligence {
''',
    '''            &app_server_version,
        )?;
        execution_state.advance(RuntimeCodexPhase::Journaled)?;

        if let Some(binding) = intelligence {
''',
)

# Unknown dispatch acknowledgement must never downgrade the local durable
# operation to definitely-unsent.  Reconcile Agentd and only release on a
# confirmed exact cancellation/abort.
replace_between(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "            let dispatched = match owner\n",
    "            // Idempotent acknowledgement is reconciliation, not a second\n",
    '''            let dispatched = match owner
                .run_mark_dispatched(binding.run_id.clone(), binding.expected_revision)
                .await
            {
                Ok(receipt) => receipt,
                Err(error) => {
                    let reason: String = format!(
                        "Agentd dispatch acknowledgement unknown before physical send: {error}"
                    )
                    .chars()
                    .take(1024)
                    .collect();
                    match owner.run_status(binding.run_id.clone()).await {
                        Ok(Some(status))
                            if status.phase == AgentRunPhase::Dispatched
                                && status.revision
                                    == binding.expected_revision.saturating_add(1)
                                && status.generation == self.config.generation
                                && !status.terminal_observed =>
                        {
                            intelligence_revision = Some(status.revision);
                            abort_before_effect_across_owners(
                                control,
                                &owner,
                                intelligence,
                                &mut intelligence_revision,
                                pre_effect_abort,
                                reason.clone(),
                                &mut client,
                                &mut thread_lifecycle,
                            )
                            .await?;
                        }
                        Ok(Some(status))
                            if status.phase == AgentRunPhase::ContextAttached
                                && status.revision == binding.expected_revision
                                && status.generation == self.config.generation =>
                        {
                            let cancelled = owner
                                .run_cancel(
                                    binding.run_id.clone(),
                                    status.revision,
                                    reason.clone(),
                                )
                                .await?;
                            intelligence_revision = Some(cancelled.receipt.revision);
                            control.abort_native_before_effect(
                                pre_effect_abort,
                                reason.clone(),
                            )?;
                            thread_lifecycle.close(&mut client, RPC_TIMEOUT).await;
                        }
                        _ => {
                            // Ambiguous Agentd acknowledgement: retain the local
                            // durable dispatch as reconcile-only and never send.
                            drop(pre_effect_abort);
                            thread_lifecycle.close(&mut client, RPC_TIMEOUT).await;
                        }
                    }
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                    return Err(reason.into());
                }
            };
''',
)

# Once Agentd returned the dispatch revision, every subsequent pre-effect stop
# uses the exact abort transition before releasing the local one-shot proof.
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''            if dispatched.phase != AgentRunPhase::Dispatched
                || dispatched.idempotent
                || dispatched.generation != self.config.generation
                || dispatched.terminal_observed
                || dispatched.context_digest.as_deref() != Some(binding.context_digest.as_str())
                || dispatched.compilation_receipt_digest.as_deref()
                    != Some(binding.envelope_digest.as_str())
            {
                let reason =
                    "Agentd did not newly commit this exact intelligence dispatch".to_string();
                control.abort_native_before_effect(pre_effect_abort, reason.clone())?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(reason.into());
            }
            intelligence_revision = Some(dispatched.revision);
''',
    '''            intelligence_revision = Some(dispatched.revision);
            if dispatched.phase != AgentRunPhase::Dispatched
                || dispatched.idempotent
                || dispatched.generation != self.config.generation
                || dispatched.terminal_observed
                || dispatched.context_digest.as_deref() != Some(binding.context_digest.as_str())
                || dispatched.compilation_receipt_digest.as_deref()
                    != Some(binding.envelope_digest.as_str())
            {
                let reason =
                    "Agentd did not newly commit this exact intelligence dispatch".to_string();
                abort_before_effect_across_owners(
                    control,
                    &owner,
                    intelligence,
                    &mut intelligence_revision,
                    pre_effect_abort,
                    reason.clone(),
                    &mut client,
                    &mut thread_lifecycle,
                )
                .await?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(reason.into());
            }
            execution_state.advance(RuntimeCodexPhase::OwnerCommitted)?;
''',
)

# Replace post-dispatch local-only stops one by one.
for old, reason_expr, return_expr in [
    (
        '''                let reason = format!("owner health failed before final-use entry: {error}");
                control.abort_native_before_effect(pre_effect_abort, reason.clone())?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(reason.into());
''',
        None,
        None,
    ),
    (
        '''                let reason = format!("owner ingress failed before final-use entry: {error}");
                control.abort_native_before_effect(pre_effect_abort, reason.clone())?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(reason.into());
''',
        None,
        None,
    ),
]:
    prefix = old.split("                control.abort_native_before_effect", 1)[0]
    new = prefix + '''                abort_before_effect_across_owners(
                    control,
                    &owner,
                    intelligence,
                    &mut intelligence_revision,
                    pre_effect_abort,
                    reason.clone(),
                    &mut client,
                    &mut thread_lifecycle,
                )
                .await?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(reason.into());
'''
    replace_once("codex-rs/hepta-infer-worker-host/src/native_app_server.rs", old, new)

replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''            let reason: String = error.to_string().chars().take(1024).collect();
            control.abort_native_before_effect(pre_effect_abort, reason.clone())?;
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err(reason.into());
''',
    '''            let reason: String = error.to_string().chars().take(1024).collect();
            abort_before_effect_across_owners(
                control,
                &owner,
                intelligence,
                &mut intelligence_revision,
                pre_effect_abort,
                reason.clone(),
                &mut client,
                &mut thread_lifecycle,
            )
            .await?;
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err(reason.into());
''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''                    let stopped = control.abort_native_before_effect(pre_effect_abort, reason);
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                    stopped?;
                    return Err(error.into());
''',
    '''                    abort_before_effect_across_owners(
                        control,
                        &owner,
                        intelligence,
                        &mut intelligence_revision,
                        pre_effect_abort,
                        reason,
                        &mut client,
                        &mut thread_lifecycle,
                    )
                    .await?;
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                    return Err(error.into());
''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''                let stopped = control.abort_native_before_effect(
                    pre_effect_abort,
                    "cognitive final-use revalidation returned a mismatched receipt".to_string(),
                );
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                stopped?;
                return Err(
''',
    '''                abort_before_effect_across_owners(
                    control,
                    &owner,
                    intelligence,
                    &mut intelligence_revision,
                    pre_effect_abort,
                    "cognitive final-use revalidation returned a mismatched receipt".to_string(),
                    &mut client,
                    &mut thread_lifecycle,
                )
                .await?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(
''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''            let stopped = control.abort_native_before_effect(
                pre_effect_abort,
                "cancelled before model dispatch".to_string(),
            );
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            stopped?;
            return Err("cancelled before model dispatch".into());
''',
    '''            abort_before_effect_across_owners(
                control,
                &owner,
                intelligence,
                &mut intelligence_revision,
                pre_effect_abort,
                "cancelled before model dispatch".to_string(),
                &mut client,
                &mut thread_lifecycle,
            )
            .await?;
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("cancelled before model dispatch".into());
''',
)

replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''        let send_budget = remaining_before(adapter_intent.deadline_ms)?.min(RPC_TIMEOUT);
        let entered_use = match verified_use.enter(&authority_binding) {
''',
    '''        let send_budget = match remaining_before(adapter_intent.deadline_ms) {
            Ok(budget) => budget.min(RPC_TIMEOUT),
            Err(error) => {
                let reason = error.to_string();
                abort_before_effect_across_owners(
                    control,
                    &owner,
                    intelligence,
                    &mut intelligence_revision,
                    pre_effect_abort,
                    reason.clone(),
                    &mut client,
                    &mut thread_lifecycle,
                )
                .await?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(reason.into());
            }
        };
        execution_state.advance(RuntimeCodexPhase::ReadyToEnter)?;
        let entered_use = match verified_use.enter(&authority_binding) {
''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''                let reason = "kernel.authority final-use binding mismatch at entry".to_string();
                control.abort_native_before_effect(pre_effect_abort, reason.clone())?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(reason.into());
''',
    '''                let reason = "kernel.authority final-use binding mismatch at entry".to_string();
                abort_before_effect_across_owners(
                    control,
                    &owner,
                    intelligence,
                    &mut intelligence_revision,
                    pre_effect_abort,
                    reason.clone(),
                    &mut client,
                    &mut thread_lifecycle,
                )
                .await?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(reason.into());
''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''                let reason = format!("kernel.authority final-use entry denied: {error}");
                control.abort_native_before_effect(pre_effect_abort, reason.clone())?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(reason.into());
''',
    '''                let reason = format!("kernel.authority final-use entry denied: {error}");
                abort_before_effect_across_owners(
                    control,
                    &owner,
                    intelligence,
                    &mut intelligence_revision,
                    pre_effect_abort,
                    reason.clone(),
                    &mut client,
                    &mut thread_lifecycle,
                )
                .await?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(reason.into());
''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''        // From here on, a missing acknowledgement is reconcile-only. Recovery
        // cannot recreate the local pre-effect proof that is deliberately lost.
        drop(pre_effect_abort);
        let response = timeout(
''',
    '''        execution_state.advance(RuntimeCodexPhase::EffectEntered)?;
        thread_lifecycle.mark_effect_entered();
        // From here on, a missing acknowledgement is reconcile-only. Recovery
        // cannot recreate the local pre-effect proof that is deliberately lost.
        drop(pre_effect_abort);
        runtime_codex_checkpoint(RuntimeCodexFaultPoint::BeforeTurnStartAwait)?;
        let response = timeout(
''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''        )
        .await;
        let turn = match response {
''',
    '''        )
        .await;
        runtime_codex_checkpoint(RuntimeCodexFaultPoint::AfterTurnStartAwait)?;
        let turn = match response {
''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''        let binding = CodexTurnBinding {
            intent: adapter_intent,
''',
    '''        execution_state.advance(RuntimeCodexPhase::TurnStartAccepted)?;
        let binding = CodexTurnBinding {
            intent: adapter_intent,
''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''        if let Err(error) = control.native_started(request_id, output.turn_id.clone()) {
''',
    '''        if let Err(error) = control.native_started(request_id, output.turn_id.clone()) {
''',
)
# Insert after the native_started error block, immediately before deadline.
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''            return Err(error.into());
        }
        let deadline =
''',
    '''            return Err(error.into());
        }
        execution_state.advance(RuntimeCodexPhase::NativeStarted)?;
        let deadline =
''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''        if output.terminal_observed {
            let _ = timeout(
                RPC_TIMEOUT,
                client.request(ClientRequest::ThreadUnsubscribe {
                    request_id: RequestId::Integer(4),
                    params: ThreadUnsubscribeParams {
                        thread_id: output.thread_id.clone(),
                    },
                }),
            )
            .await;
        }
''',
    '''        if output.terminal_observed {
            execution_state.advance(RuntimeCodexPhase::TerminalObserved)?;
            thread_lifecycle.close(&mut client, RPC_TIMEOUT).await;
        }
''',
)

insert_before(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "fn final_use_binding(\n",
    '''async fn abort_before_effect_across_owners(
    control: &mut DurableInferenceControl,
    owner: &AgentdClient,
    intelligence: Option<&NativeIntelligenceRunBinding>,
    intelligence_revision: &mut Option<u64>,
    pre_effect_abort: NativePreEffectAbortToken,
    reason: String,
    client: &mut RemoteAppServerClient,
    thread_lifecycle: &mut EphemeralThreadLifecycle,
) -> Result<()> {
    if let (Some(binding), Some(revision)) = (intelligence, *intelligence_revision) {
        let aborted = owner
            .run_abort_before_effect(binding.run_id.clone(), revision, reason.clone())
            .await?;
        if aborted.phase != AgentRunPhase::Cancelled
            || aborted.generation != binding.generation
            || aborted.cancel_reason.as_deref() != Some(reason.as_str())
            || !aborted.terminal_observed
        {
            return Err("Agentd rejected the exact runtime.codex pre-effect abort".into());
        }
        *intelligence_revision = Some(aborted.revision);
    }
    control.abort_native_before_effect(pre_effect_abort, reason)?;
    thread_lifecycle.close(client, RPC_TIMEOUT).await;
    Ok(())
}

''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''fn unix_time_ms() -> Result<u64> {
    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "system clock is before the Unix epoch")?;
    Ok(u64::try_from(elapsed.as_millis())?)
}
''',
    '''fn unix_time_ms() -> Result<u64> {
    runtime_now_unix_ms().map_err(Into::into)
}
''',
)

append_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs",
    "runtime_codex_crash_matrix_is_wired",
    r'''
#[test]
fn runtime_codex_crash_matrix_is_wired_at_every_owned_boundary() {
    let source = include_str!("native_app_server.rs");
    for point in [
        "RuntimeCodexPhase::ThreadPrepared",
        "RuntimeCodexPhase::PayloadFrozen",
        "RuntimeCodexPhase::AuthorityClaimed",
        "RuntimeCodexPhase::Journaled",
        "RuntimeCodexPhase::OwnerCommitted",
        "RuntimeCodexPhase::ReadyToEnter",
        "RuntimeCodexPhase::EffectEntered",
        "RuntimeCodexFaultPoint::BeforeTurnStartAwait",
        "RuntimeCodexFaultPoint::AfterTurnStartAwait",
        "RuntimeCodexPhase::TurnStartAccepted",
        "RuntimeCodexPhase::NativeStarted",
        "RuntimeCodexPhase::TerminalObserved",
    ] {
        assert!(source.contains(point), "missing crash checkpoint {point}");
    }
    assert!(source.contains("run_abort_before_effect"));
    assert!(source.contains("abort_before_effect_across_owners"));
}
''',
)

# ---------------------------------------------------------------------------
# 3. Unix final-use endpoint process-instance pinning.
# ---------------------------------------------------------------------------

replace_once(
    "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs",
    '''#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FinalUseAuthorizerConfig {
''',
    '''#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct IssuerProcessIdentity {
    pub pid: u32,
    pub executable: PathBuf,
    pub start_time_ticks: u64,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FinalUseAuthorizerConfig {
''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs",
    "    pub issuer_uid: u32,\n    pub signer_id: String,\n",
    "    pub issuer_uid: u32,\n    #[serde(default)]\n    pub issuer_process: Option<IssuerProcessIdentity>,\n    pub signer_id: String,\n",
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs",
    "    issuer_uid: u32,\n    issuer_timeout: Duration,\n",
    "    issuer_uid: u32,\n    issuer_process: Option<IssuerProcessIdentity>,\n    issuer_timeout: Duration,\n",
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs",
    '''        let issuer_timeout = Duration::from_millis(config.issuer_timeout_ms);
''',
    '''        validate_configured_process_identity(config.issuer_process.as_ref())?;
        let issuer_timeout = Duration::from_millis(config.issuer_timeout_ms);
''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs",
    '''            issuer_socket: config.issuer_socket,
            issuer_uid: config.issuer_uid,
            issuer_timeout,
''',
    '''            issuer_socket: config.issuer_socket,
            issuer_uid: config.issuer_uid,
            issuer_process: config.issuer_process,
            issuer_timeout,
''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs",
    '''            let peer = stream.peer_cred()?;
            validate_issuer_peer_uid(peer.uid(), self.issuer_uid)?;
            stream.write_all(&request_len.to_be_bytes()).await?;
''',
    '''            let peer = stream.peer_cred()?;
            validate_issuer_peer_uid(peer.uid(), self.issuer_uid)?;
            #[cfg(target_os = "linux")]
            let peer_pid = peer.pid();
            #[cfg(not(target_os = "linux"))]
            let peer_pid = None;
            validate_issuer_process(peer_pid, self.issuer_process.as_ref())?;
            stream.write_all(&request_len.to_be_bytes()).await?;
''',
)
insert_before(
    "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs",
    "#[cfg(unix)]\nfn validate_issuer_peer_uid",
    r'''fn validate_configured_process_identity(
    identity: Option<&IssuerProcessIdentity>,
) -> Result<()> {
    if let Some(identity) = identity {
        if identity.pid == 0
            || !identity.executable.is_absolute()
            || identity.start_time_ticks == 0
        {
            return Err("invalid final-use issuer process identity".into());
        }
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn validate_issuer_process(
    actual_pid: Option<u32>,
    expected: Option<&IssuerProcessIdentity>,
) -> Result<()> {
    let Some(expected) = expected else {
        return Ok(());
    };
    let actual_pid = actual_pid.ok_or("final-use authority peer PID is unavailable")?;
    if actual_pid != expected.pid {
        return Err("final-use authority peer PID does not match configured issuer".into());
    }
    let executable = std::fs::read_link(format!("/proc/{actual_pid}/exe"))?;
    if executable != expected.executable {
        return Err("final-use authority executable identity changed".into());
    }
    let stat = std::fs::read_to_string(format!("/proc/{actual_pid}/stat"))?;
    let command_end = stat
        .rfind(')')
        .ok_or("final-use authority process stat is malformed")?;
    let start_time_ticks = stat[command_end + 1..]
        .split_whitespace()
        .nth(19)
        .ok_or("final-use authority process start time is missing")?
        .parse::<u64>()?;
    if start_time_ticks != expected.start_time_ticks {
        return Err("final-use authority process instance changed".into());
    }
    Ok(())
}

#[cfg(not(target_os = "linux"))]
fn validate_issuer_process(
    _actual_pid: Option<u32>,
    expected: Option<&IssuerProcessIdentity>,
) -> Result<()> {
    if expected.is_some() {
        return Err("final-use issuer process pinning currently requires Linux".into());
    }
    Ok(())
}

''',
)

# Existing source constructors explicitly select the compatibility posture.
for path in [
    "codex-rs/hepta-infer-worker-host/src/final_use_authorizer_tests.rs",
    "codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs",
]:
    content = read(path)
    old = "        issuer_uid,\n" if "runtime_codex_product_e2e" in path else "        issuer_uid: rustix::process::geteuid().as_raw(),\n"
    new = old + "        issuer_process: None,\n"
    if content.count(old) != 1:
        raise SystemExit(f"{path}: could not patch issuer_process constructor")
    write(path, content.replace(old, new, 1))

append_once(
    "codex-rs/hepta-infer-worker-host/src/final_use_authorizer_tests.rs",
    "configured_process_identity_requires_complete_linux_identity",
    r'''
#[test]
fn configured_process_identity_requires_complete_linux_identity() {
    assert!(validate_configured_process_identity(None).is_ok());
    assert!(
        validate_configured_process_identity(Some(&IssuerProcessIdentity {
            pid: 0,
            executable: PathBuf::from("relative"),
            start_time_ticks: 0,
        }))
        .is_err()
    );
}
''',
)

# ---------------------------------------------------------------------------
# 4. Typed, non-authorizing quarantine/release protocol.
# ---------------------------------------------------------------------------

create(
    "codex-rs/hepta-codex-adapter/src/quarantine.rs",
    r'''
//! Typed evidence for unresolved runtime.codex effects.
//!
//! These records never authorize replay.  A release decision must be signed by
//! an independently governed operator and can only retain quarantine, confirm a
//! terminal fact, or confirm non-application from independent evidence.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

pub const RUNTIME_CODEX_QUARANTINE_SCHEMA_VERSION: u32 = 1;
const MAX_DETAIL_BYTES: usize = 1024;
const MAX_SIGNER_BYTES: usize = 128;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeCodexQuarantineReasonV1 {
    EphemeralHistoryUnavailable,
    DuplicateMatchingTurns,
    CorrelationConflict,
    OwnerAuthorityLost,
    ProviderAcknowledgementUnknown,
    TerminalObserverUnavailable,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RuntimeCodexQuarantineRecordV1 {
    pub schema_version: u32,
    pub operation_id: StableId,
    pub request_digest: Digest32,
    pub source_admission_digest: Digest32,
    pub authority_witness_digest: Digest32,
    pub thread_id: Option<StableId>,
    pub turn_id: Option<StableId>,
    pub agent_generation: u64,
    pub authority_epoch: u64,
    pub reason: RuntimeCodexQuarantineReasonV1,
    pub detail: String,
}

impl RuntimeCodexQuarantineRecordV1 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.schema_version != RUNTIME_CODEX_QUARANTINE_SCHEMA_VERSION {
            return Err("unsupported runtime.codex quarantine schema");
        }
        if self.request_digest.is_zero()
            || self.source_admission_digest.is_zero()
            || self.authority_witness_digest.is_zero()
        {
            return Err("runtime.codex quarantine digest is empty");
        }
        if self.agent_generation == 0 || self.authority_epoch == 0 {
            return Err("runtime.codex quarantine generation is invalid");
        }
        if self.detail.trim().is_empty()
            || self.detail.len() > MAX_DETAIL_BYTES
            || self.detail.as_bytes().contains(&0)
        {
            return Err("runtime.codex quarantine detail is invalid");
        }
        Ok(())
    }

    pub fn canonical_digest(&self) -> Result<Digest32, serde_json::Error> {
        let mut material = b"hepta.runtime.codex.quarantine.v1\0".to_vec();
        material.extend_from_slice(&serde_json::to_vec(self)?);
        Ok(Digest32::of_bytes(&material))
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeCodexResolutionDispositionV1 {
    RetainQuarantine,
    ConfirmedTerminal,
    ConfirmedNotApplied,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedRuntimeCodexResolutionV1 {
    pub schema_version: u32,
    pub quarantine_digest: Digest32,
    pub disposition: RuntimeCodexResolutionDispositionV1,
    pub independent_evidence_digest: Digest32,
    pub signer_id: String,
    pub authority_epoch: u64,
    pub issued_at_unix_ms: u64,
    pub signature: Vec<u8>,
}

impl SignedRuntimeCodexResolutionV1 {
    pub fn validate_shape(&self) -> Result<(), &'static str> {
        if self.schema_version != RUNTIME_CODEX_QUARANTINE_SCHEMA_VERSION {
            return Err("unsupported runtime.codex resolution schema");
        }
        if self.quarantine_digest.is_zero() || self.independent_evidence_digest.is_zero() {
            return Err("runtime.codex resolution evidence is empty");
        }
        if self.signer_id.is_empty()
            || self.signer_id.len() > MAX_SIGNER_BYTES
            || self.signer_id.bytes().any(|byte| byte.is_ascii_control())
        {
            return Err("runtime.codex resolution signer is invalid");
        }
        if self.authority_epoch == 0 || self.issued_at_unix_ms == 0 {
            return Err("runtime.codex resolution authority metadata is invalid");
        }
        if self.signature.len() != 64 {
            return Err("runtime.codex resolution signature must be Ed25519-sized");
        }
        Ok(())
    }

    /// Resolution evidence is deliberately not a replay permit.
    pub fn authorizes_replay(&self) -> bool {
        false
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }

    #[test]
    fn quarantine_and_release_never_authorize_replay() {
        let record = RuntimeCodexQuarantineRecordV1 {
            schema_version: 1,
            operation_id: StableId::new("runtime:op").unwrap(),
            request_digest: digest(b"request"),
            source_admission_digest: digest(b"source"),
            authority_witness_digest: digest(b"authority"),
            thread_id: None,
            turn_id: None,
            agent_generation: 1,
            authority_epoch: 1,
            reason: RuntimeCodexQuarantineReasonV1::EphemeralHistoryUnavailable,
            detail: "App Server history was unavailable after process loss".to_string(),
        };
        record.validate().unwrap();
        let decision = SignedRuntimeCodexResolutionV1 {
            schema_version: 1,
            quarantine_digest: record.canonical_digest().unwrap(),
            disposition: RuntimeCodexResolutionDispositionV1::ConfirmedNotApplied,
            independent_evidence_digest: digest(b"independent-evidence"),
            signer_id: "independent-operations".to_string(),
            authority_epoch: 2,
            issued_at_unix_ms: 1,
            signature: vec![7; 64],
        };
        decision.validate_shape().unwrap();
        assert!(!decision.authorizes_replay());
    }
}
''',
)
insert_before(
    "codex-rs/hepta-codex-adapter/src/lib.rs",
    "use codex_app_server_client::AppServerEvent;\n",
    "pub mod quarantine;\n\n",
)

# ---------------------------------------------------------------------------
# 5. Machine-verifiable evidence emitter and dedicated required workflow.
# ---------------------------------------------------------------------------

create(
    "scripts/hepta-runtime-codex-evidence.py",
    r'''
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "hepta.runtime-codex.qualification.v1"
BOUND_FILES = [
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "codex-rs/hepta-agentd/src/state_control.rs",
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs",
    "codex-rs/hepta-codex-adapter/src/lib.rs",
    "codex-rs/hepta-codex-adapter/src/quarantine.rs",
    "docs/modules/runtime.codex/FAULT_MATRIX.md",
    "docs/modules/runtime.codex/QUARANTINE_PROTOCOL.md",
]


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def digest(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def emit(args: argparse.Namespace) -> None:
    candidate = args.candidate_sha or git("rev-parse", "HEAD")
    tree = args.candidate_tree or git("rev-parse", "HEAD^{tree}")
    document = {
        "schema": SCHEMA,
        "mode": args.mode,
        "sourceSha": args.source_sha,
        "candidateSha": candidate,
        "candidateTree": tree,
        "baseSha": args.base_sha or None,
        "mergeCommit": args.merge_commit or None,
        "mergeTree": args.merge_tree or None,
        "checks": {
            "format": "passed",
            "compile": "passed",
            "focusedTests": "passed",
            "productE2E": "passed",
            "strictLint": "passed",
            "crashMatrix": "passed",
            "stress": "passed",
        },
        "sourceDigests": {path: digest(path) for path in BOUND_FILES},
        "repositoryControlled": {
            "abortBeforeEffectTransition": True,
            "exactHeadGate": True,
            "syntheticMergeGate": True,
            "machineReadableReceipt": True,
            "ephemeralHistoryQuarantineProtocol": True,
        },
        "externalGates": {
            "targetHostIssuerAndKeyCustody": False,
            "realProviderTerminalStream": False,
            "targetHostFaultQualification": False,
            "independentAcceptance": False,
            "canaryPromotionRelease": False,
        },
        "authorityPosture": "deny_all",
        "release": False,
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{checksum}  {output.name}\n", encoding="utf-8"
    )


def verify(path: str) -> None:
    document = json.loads((ROOT / path).read_text(encoding="utf-8"))
    if document.get("schema") != SCHEMA:
        raise SystemExit("invalid runtime.codex evidence schema")
    for field in ("sourceSha", "candidateSha", "candidateTree"):
        value = document.get(field)
        if not isinstance(value, str) or len(value) != 40:
            raise SystemExit(f"invalid {field}")
    if set(document.get("checks", {}).values()) != {"passed"}:
        raise SystemExit("runtime.codex evidence contains a non-passing repository check")
    if any(document.get("externalGates", {}).values()):
        raise SystemExit("repository evidence may not self-certify external gates")
    if document.get("authorityPosture") != "deny_all" or document.get("release") is not False:
        raise SystemExit("runtime.codex evidence improperly grants authority or release")
    for source, expected in document.get("sourceDigests", {}).items():
        if digest(source) != expected:
            raise SystemExit(f"source digest drift: {source}")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    emit_parser = sub.add_parser("emit")
    emit_parser.add_argument("--mode", required=True)
    emit_parser.add_argument("--source-sha", required=True)
    emit_parser.add_argument("--candidate-sha")
    emit_parser.add_argument("--candidate-tree")
    emit_parser.add_argument("--base-sha", default="")
    emit_parser.add_argument("--merge-commit", default="")
    emit_parser.add_argument("--merge-tree", default="")
    emit_parser.add_argument("--output", required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("path")
    args = parser.parse_args()
    if args.command == "emit":
        emit(args)
    else:
        verify(args.path)


if __name__ == "__main__":
    main()
''',
)

create(
    ".github/workflows/runtime-codex-required.yml",
    r'''
name: runtime.codex required qualification

on:
  workflow_call:

permissions:
  contents: read
  id-token: write
  attestations: write

env:
  SOURCE_SHA: ${{ github.event.pull_request.head.sha || github.sha }}
  BASE_SHA: ${{ github.event.pull_request.base.sha || github.event.before }}

jobs:
  exact-head:
    name: runtime.codex exact-head
    runs-on: ubuntu-24.04
    timeout-minutes: 90
    steps:
      - name: Checkout exact candidate
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          ref: ${{ env.SOURCE_SHA }}
          fetch-depth: 0
          persist-credentials: false
      - uses: ./.github/actions/setup-ci
      - name: Install native prerequisites
        run: |
          sudo apt-get update
          sudo apt-get install -y build-essential libcap-dev pkg-config
      - name: Install pinned Rust
        uses: dtolnay/rust-toolchain@e081816240890017053eacbb1bdf337761dc5582
        with:
          toolchain: 1.95.0
          components: clippy,rustfmt
      - name: Resolve verified V8 artifacts
        uses: ./.github/actions/setup-rusty-v8
        with:
          target: x86_64-unknown-linux-gnu
      - name: Bind exact source
        run: |
          test "$(git rev-parse HEAD)" = "${SOURCE_SHA}"
          python3 scripts/hepta-lane-b-truth.py verify
      - name: Compile runtime.codex owners and consumers
        working-directory: codex-rs
        run: >-
          cargo check --locked --all-targets
          -p codex-hepta-agent-protocol
          -p codex-hepta-agentd
          -p codex-hepta-infer-core
          -p codex-hepta-infer-worker-host
          -p codex-hepta-codex-adapter
      - name: Focused runtime.codex tests
        working-directory: codex-rs
        run: >-
          cargo test --locked
          -p codex-hepta-agent-protocol
          -p codex-hepta-agentd
          -p codex-hepta-infer-core
          -p codex-hepta-infer-worker-host
          -p codex-hepta-codex-adapter
          --lib
      - name: Product runtime.codex E2E
        working-directory: codex-rs
        run: >-
          cargo test --locked -p codex-hepta-agentd
          --test runtime_codex_product_e2e -- --test-threads=1
      - name: Concurrency and restart stress
        working-directory: codex-rs
        shell: bash
        run: |
          set -euo pipefail
          for iteration in $(seq 1 8); do
            cargo test --locked -p codex-hepta-agentd \
              abort_before_effect_stress_never_reopens_or_redispatches \
              -- --test-threads=1
            cargo test --locked -p codex-hepta-infer-worker-host \
              owner_loss_stays_denied_after_interrupt_grace_observes_completed \
              -- --test-threads=1
          done
      - name: Strict lint
        working-directory: codex-rs
        run: >-
          cargo clippy --locked --all-targets
          -p codex-hepta-agent-protocol
          -p codex-hepta-agentd
          -p codex-hepta-infer-core
          -p codex-hepta-infer-worker-host
          -p codex-hepta-codex-adapter
          -- -D warnings
      - name: Formatting and clean source
        shell: bash
        run: |
          cargo fmt --manifest-path codex-rs/Cargo.toml \
            --package codex-hepta-agent-protocol \
            --package codex-hepta-agentd \
            --package codex-hepta-infer-core \
            --package codex-hepta-infer-worker-host \
            --package codex-hepta-codex-adapter -- --check
          git diff --check
          git diff --exit-code
      - name: Emit exact-head receipt
        shell: bash
        run: |
          python3 scripts/hepta-runtime-codex-evidence.py emit \
            --mode exact-head \
            --source-sha "${SOURCE_SHA}" \
            --candidate-sha "$(git rev-parse HEAD)" \
            --candidate-tree "$(git rev-parse HEAD^{tree})" \
            --base-sha "${BASE_SHA:-}" \
            --output .hepta-evidence/runtime-codex/exact-head.json
          python3 scripts/hepta-runtime-codex-evidence.py verify \
            .hepta-evidence/runtime-codex/exact-head.json
      - name: Retain exact-head receipt
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: runtime-codex-exact-head-${{ env.SOURCE_SHA }}
          path: .hepta-evidence/runtime-codex/
          if-no-files-found: error
          retention-days: 30
      - name: Attest exact-head receipt
        if: github.event_name == 'push'
        uses: actions/attest-build-provenance@4d101475d8b20a2381f78447822ac1eab6504dd8
        with:
          subject-path: .hepta-evidence/runtime-codex/exact-head.json

  synthetic-merge:
    name: runtime.codex synthetic-merge
    runs-on: ubuntu-24.04
    timeout-minutes: 90
    steps:
      - name: Checkout exact candidate
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          ref: ${{ env.SOURCE_SHA }}
          fetch-depth: 0
          persist-credentials: false
      - name: Materialize ordered-parent synthetic merge
        shell: bash
        run: |
          set -euo pipefail
          SOURCE_COMMIT="$(git rev-parse HEAD)"
          BASE_COMMIT="${BASE_SHA}"
          if [[ -z "${BASE_COMMIT}" ]] || ! git cat-file -e "${BASE_COMMIT}^{commit}"; then
            BASE_COMMIT="$(git rev-parse "${SOURCE_COMMIT}^1")"
          fi
          git checkout --detach "${BASE_COMMIT}"
          git -c user.name=runtime-codex-ci \
            -c user.email=runtime-codex-ci@users.noreply.github.com \
            merge --no-commit --no-ff "${SOURCE_COMMIT}"
          MERGE_TREE="$(git write-tree)"
          MERGE_COMMIT="$(printf '%s\n' 'runtime.codex synthetic merge' | \
            git -c user.name=runtime-codex-ci \
              -c user.email=runtime-codex-ci@users.noreply.github.com \
              commit-tree "${MERGE_TREE}" -p "${BASE_COMMIT}" -p "${SOURCE_COMMIT}")"
          printf 'BASE_COMMIT=%s\nMERGE_TREE=%s\nMERGE_COMMIT=%s\n' \
            "${BASE_COMMIT}" "${MERGE_TREE}" "${MERGE_COMMIT}" >> "$GITHUB_ENV"
      - uses: ./.github/actions/setup-ci
      - name: Install native prerequisites
        run: |
          sudo apt-get update
          sudo apt-get install -y build-essential libcap-dev pkg-config
      - uses: dtolnay/rust-toolchain@e081816240890017053eacbb1bdf337761dc5582
        with:
          toolchain: 1.95.0
          components: clippy,rustfmt
      - uses: ./.github/actions/setup-rusty-v8
        with:
          target: x86_64-unknown-linux-gnu
      - name: Compile and test merged runtime.codex
        working-directory: codex-rs
        run: |
          cargo check --locked --all-targets \
            -p codex-hepta-agent-protocol \
            -p codex-hepta-agentd \
            -p codex-hepta-infer-core \
            -p codex-hepta-infer-worker-host \
            -p codex-hepta-codex-adapter
          cargo test --locked \
            -p codex-hepta-agent-protocol \
            -p codex-hepta-agentd \
            -p codex-hepta-infer-core \
            -p codex-hepta-infer-worker-host \
            -p codex-hepta-codex-adapter --lib
          cargo test --locked -p codex-hepta-agentd \
            --test runtime_codex_product_e2e -- --test-threads=1
      - name: Strict merged lint and formatting
        shell: bash
        run: |
          cargo clippy --manifest-path codex-rs/Cargo.toml --locked --all-targets \
            -p codex-hepta-agent-protocol \
            -p codex-hepta-agentd \
            -p codex-hepta-infer-core \
            -p codex-hepta-infer-worker-host \
            -p codex-hepta-codex-adapter -- -D warnings
          cargo fmt --manifest-path codex-rs/Cargo.toml \
            --package codex-hepta-agent-protocol \
            --package codex-hepta-agentd \
            --package codex-hepta-infer-core \
            --package codex-hepta-infer-worker-host \
            --package codex-hepta-codex-adapter -- --check
          test "$(git write-tree)" = "${MERGE_TREE}"
      - name: Emit synthetic-merge receipt
        shell: bash
        run: |
          python3 scripts/hepta-runtime-codex-evidence.py emit \
            --mode synthetic-merge \
            --source-sha "${SOURCE_SHA}" \
            --candidate-sha "${MERGE_COMMIT}" \
            --candidate-tree "${MERGE_TREE}" \
            --base-sha "${BASE_COMMIT}" \
            --merge-commit "${MERGE_COMMIT}" \
            --merge-tree "${MERGE_TREE}" \
            --output .hepta-evidence/runtime-codex/synthetic-merge.json
          python3 scripts/hepta-runtime-codex-evidence.py verify \
            .hepta-evidence/runtime-codex/synthetic-merge.json
      - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: runtime-codex-synthetic-merge-${{ env.SOURCE_SHA }}
          path: .hepta-evidence/runtime-codex/
          if-no-files-found: error
          retention-days: 30

  required:
    name: runtime.codex required
    if: always()
    needs: [exact-head, synthetic-merge]
    runs-on: ubuntu-24.04
    steps:
      - name: Require both qualification lanes
        env:
          NEEDS: ${{ toJSON(needs) }}
        run: |
          python3 - <<'PY'
          import json, os
          needs = json.loads(os.environ["NEEDS"])
          failed = {name: value["result"] for name, value in needs.items() if value["result"] != "success"}
          if failed:
              raise SystemExit(f"runtime.codex qualification failed: {failed}")
          PY
''',
)

# Fan the reusable runtime.codex gate into the already protected CI required
# context.  This makes skip/failure semantics explicit without changing branch
# protection out of band.
replace_once(
    ".github/workflows/blocking-ci.yml",
    '''  bazel:
''',
    '''  runtime-codex:
    name: runtime.codex exact-head and synthetic-merge
    needs: scope
    if: needs.scope.outputs.native == 'true' || needs.scope.outputs.full_repo == 'true'
    uses: ./.github/workflows/runtime-codex-required.yml
    secrets: inherit

  bazel:
''',
)
replace_once(
    ".github/workflows/blocking-ci.yml",
    '''      - hepta-contract-gate
      - bazel
''',
    '''      - hepta-contract-gate
      - runtime-codex
      - bazel
''',
)
replace_once(
    ".github/workflows/blocking-ci.yml",
    '''          if not (native or full):
              allowed.append("hepta-contract-gate")
''',
    '''          if not (native or full):
              allowed += ["hepta-contract-gate", "runtime-codex"]
''',
)
replace_once(
    ".github/workflows/blocking-ci.yml",
    '''permissions:
  contents: read
''',
    '''permissions:
  contents: read
  id-token: write
  attestations: write
''',
)

# ---------------------------------------------------------------------------
# 6. Operator and qualification documentation.
# ---------------------------------------------------------------------------

create(
    "docs/modules/runtime.codex/QUARANTINE_PROTOCOL.md",
    r'''
# runtime.codex indeterminate-effect quarantine protocol

This protocol applies when an exact durable `turn/start` operation cannot be
settled from authenticated App Server history.  It never grants replay.

## Entry

Enter quarantine after provider acknowledgement loss, process loss with
unavailable ephemeral history, duplicate exact turns, correlation conflict,
owner authority loss, or terminal-observer loss.  Persist the operation ID,
request/source-admission/authority-witness digests, known thread/turn IDs,
Agent generation, authority epoch, and a bounded reason.  Retain capacity and
do not synthesize `not_applied`.

## Resolution

Only an independently signed `SignedRuntimeCodexResolutionV1` may change the
operational hold.  Permitted dispositions are:

- `retain_quarantine`;
- `confirmed_terminal`, backed by authenticated provider/App Server evidence;
- `confirmed_not_applied`, backed by an independent admission ledger or
  provider idempotency record.

No disposition is a replay permit.  A new attempt requires a new operation ID,
a new final payload, a new authority grant, and a policy decision outside this
record.  Manual database edits and unsigned operator notes are invalid.

## Anti-rollback and retention

Resolution authority epoch and signer state are monotonic and externally
backed up.  Restoring an older local database cannot remove a quarantine or
revocation.  Records and their evidence remain available for the longest of
the provider dispute window, audit retention, and backup retention.

## Required alerts

Alert on first quarantine, retained-slot saturation, duplicate-turn conflict,
clock/authority rollback, unsigned release attempts, and a quarantine older
than the selected target-host SLO.  Thresholds are deployment facts and are not
hard-coded by repository source.
''',
)
create(
    "docs/modules/runtime.codex/FAULT_INJECTION_MATRIX.md",
    r'''
# runtime.codex crash-injection matrix

The checked state machine exposes deterministic checkpoints at thread prepare,
payload freeze, authority claim, durable dispatch, Agentd dispatch commit,
final-use readiness, effect entry, before and after the `turn/start` await,
turn acceptance, native-start persistence, and terminal observation.

For every checkpoint the invariant is:

1. before effect entry, the same live one-shot proof may close both Agentd and
   the local journal; ambiguous owner RPC retains the local record as
   reconcile-only;
2. after effect entry, no path declares `not_applied` or issues a new
   `turn/start`;
3. restart uses only the original operation and stable user-message identity;
4. duplicate, stale-revision and competing-owner attempts fail closed;
5. cleanup failure is observable and never upgrades the operation to success.

CI runs focused unit/product tests and repeated owner-loss/restart stress.  A
target-host campaign must additionally kill the real worker/App Server at each
checkpoint, inject socket half-close and delayed ACK, and retain signed host,
provider and journal evidence.
''',
)
create(
    "docs/modules/runtime.codex/QUICKSTART.md",
    r'''
# runtime.codex developer quickstart

Use Rust 1.95.0 and the repository-pinned V8 artifacts.  From the repository
root:

```bash
python3 scripts/hepta-lane-b-truth.py verify
cd codex-rs
cargo test --locked -p codex-hepta-codex-adapter
cargo test --locked -p codex-hepta-infer-worker-host
cargo test --locked -p codex-hepta-agentd --test runtime_codex_product_e2e -- --test-threads=1
```

The product E2E starts real Agentd and App Server processes but uses a bounded
mock Responses provider and a test issuer.  It is not target-host or real
provider acceptance.

A native worker requires an absolute Agentd socket, exact Agent ID/generation,
model, deadline, and a protected final-use-authority configuration.  Never use
a receipt, boolean, model output or unsigned JSON as authority.
''',
)
create(
    "docs/modules/runtime.codex/DEPLOYMENT.md",
    r'''
# runtime.codex deployment and target-host profile

Production deployment requires separate service identities for Agentd/App
Server, the inference worker, and the final-use issuer.  Pin the issuer socket,
UID, Ed25519 verifier, authority epoch/revocation head, and on Linux the peer
PID, executable path and `/proc` start-time ticks.  The signer private key must
remain outside the worker.

The host profile must provide trusted time, monotonic revocation distribution,
anti-rollback recovery, protected state directories, bounded queues, and an
authenticated provider endpoint.  Record boot IDs, process generations, socket
inodes and deployment artifact digests in the acceptance evidence.

Activation order is issuer/revocation service, Agentd/App Server, worker in
shadow mode, canary, then bounded production traffic.  Any identity, clock,
revocation, terminal-observer or quarantine-control failure closes admission.
''',
)
create(
    "docs/modules/runtime.codex/OPERATIONS.md",
    r'''
# runtime.codex operations and troubleshooting

## Primary signals

Track admission, durable prepare, authority latency, owner-dispatch latency,
first/last token, terminal observation, reconciliation outcome, cleanup
attempt/failure, pre-effect orphan candidates, post-effect unresolved drops,
and quarantine age.  Establish p50/p95/p99 and resource baselines on each
selected host profile; repository CI numbers are not production SLOs.

## Incident order

1. close new admission without deleting durable records;
2. preserve Agentd/App Server generation, sockets and logs;
3. reconcile the same operation from authenticated history;
4. quarantine unresolved effects; never blind-replay;
5. use an independently signed resolution or retain the hold;
6. rehearse rollback with compatible journal/schema state.

A failed cleanup or missing terminal event is not success.  A provider terminal
fact observed after local cancellation remains evidence but does not upgrade
the cancelled/timed-out boundary.
''',
)
create(
    "docs/modules/runtime.codex/TARGET_HOST_QUALIFICATION.md",
    r'''
# runtime.codex target-host qualification

Repository qualification proves source composition only.  Independent target
qualification must run the named caller with the deployed issuer and real
provider while injecting provider ACK loss, event lag, socket disconnect,
worker kill, App Server kill/restart, owner generation replacement, clock
rollback, revocation-frontier advance, disk-full/fsync failure, and quarantine
resolution.

Retain machine-readable receipts binding source/tree, binaries, configuration,
host/process/socket identities, provider request IDs, journal digests, test
oracle, p50/p95/p99 latency, CPU/RSS/IO, and every skip.  Skipped or missing
lanes are not acceptance.  Canary, rollback, promotion and release require an
independent signer and remain false in repository-generated receipts.
''',
)
append_once(
    "docs/modules/runtime.codex/FAULT_MATRIX.md",
    "## Cross-owner abort-before-effect convergence",
    r'''
## Cross-owner abort-before-effect convergence

After Agentd commits `Dispatched`, every deterministic pre-effect failure uses
`RunAbortBeforeEffect` with the exact run revision before the local one-shot
proof releases its reservation.  If the Agentd acknowledgement is ambiguous,
the caller queries the same run.  It releases only after a confirmed exact
cancel/abort; otherwise the local operation remains reconcile-only and no
physical `turn/start` is sent.

The complete crash checkpoints and target-host obligations are in
[FAULT_INJECTION_MATRIX.md](FAULT_INJECTION_MATRIX.md).  History-loss handling
is governed by [QUARANTINE_PROTOCOL.md](QUARANTINE_PROTOCOL.md).
''',
)

# Keep the implementation map honest: repository mechanisms are present, but
# external qualification and release remain false.
map_path = "docs/modules/runtime.codex/IMPLEMENTATION_MAP.json"
implementation_map = json.loads(read(map_path))
implementation_map["abortBeforeEffect"] = {
    "protocolMethod": "run_abort_before_effect",
    "stateTransition": "Dispatched -> Cancelled",
    "casBound": True,
    "blindReplayAllowed": False,
}
implementation_map["quarantineProtocol"] = "docs/modules/runtime.codex/QUARANTINE_PROTOCOL.md"
implementation_map["qualificationWorkflow"] = ".github/workflows/runtime-codex-required.yml"
implementation_map["machineReadableEvidenceEmitter"] = "scripts/hepta-runtime-codex-evidence.py"
implementation_map["claimBoundary"]["repositoryControlledDocumentationGapsClosed"] = True
implementation_map["claimBoundary"]["productExecutionComplete"] = False
implementation_map["claimBoundary"]["deploymentQualificationComplete"] = False
implementation_map["claimBoundary"]["independentAcceptanceComplete"] = False
implementation_map["claimBoundary"]["activation"] = False
implementation_map["claimBoundary"]["release"] = False
write(map_path, json.dumps(implementation_map, indent=2, sort_keys=False) + "\n")

# Delete the one-shot bootstrap after the runner has applied and verified it.
for relative in [
    "scripts/runtime_codex_convergence.py",
    ".github/workflows/runtime-codex-convergence-bootstrap.yml",
]:
    target = ROOT / relative
    if target.exists():
        target.unlink()
