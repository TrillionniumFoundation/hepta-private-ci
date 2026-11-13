from __future__ import annotations

import json
from pathlib import Path

ROOT = Path.cwd()


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one replacement, found {count}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


def insert_before(path: str, marker: str, addition: str) -> None:
    text = read(path)
    count = text.count(marker)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one insertion marker, found {count}: {marker[:100]!r}")
    write(path, text.replace(marker, addition + marker, 1))


def append_once(path: str, marker: str, addition: str) -> None:
    text = read(path)
    if marker in text:
        return
    if not text.endswith("\n"):
        text += "\n"
    write(path, text + addition)


# ---------------------------------------------------------------------------
# Agentd owner state: store the opaque permit only in process memory. Effect
# entry consumes it and increments the revision. Abort and enter race on the
# same exact revision; only one can win.
# ---------------------------------------------------------------------------
replace_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "    cancel_reason: Option<String>,\n    cancel_ack_deadline_ms: Option<u64>,\n}\n",
    "    cancel_reason: Option<String>,\n    cancel_ack_deadline_ms: Option<u64>,\n    pre_effect_abort_digest: Option<String>,\n    entered_effect_digest: Option<String>,\n}\n",
)
text = read("codex-rs/hepta-agentd/src/lane_b_runtime.rs")
old_tail = "            cancel_reason: None,\n            cancel_ack_deadline_ms: None,\n        };"
if text.count(old_tail) != 1:
    raise RuntimeError(f"lane_b_runtime start initializer count={text.count(old_tail)}")
text = text.replace(
    old_tail,
    "            cancel_reason: None,\n            cancel_ack_deadline_ms: None,\n            pre_effect_abort_digest: None,\n            entered_effect_digest: None,\n        };",
    1,
)
old_recovery_tail = "            cancel_reason: recovery.cancel_reason,\n            cancel_ack_deadline_ms: None,\n        };"
if text.count(old_recovery_tail) != 1:
    raise RuntimeError("lane_b_runtime recovery initializer missing")
text = text.replace(
    old_recovery_tail,
    "            cancel_reason: recovery.cancel_reason,\n            cancel_ack_deadline_ms: None,\n            pre_effect_abort_digest: None,\n            entered_effect_digest: None,\n        };",
    1,
)
write("codex-rs/hepta-agentd/src/lane_b_runtime.rs", text)

old_mark = r'''    pub fn mark_dispatched(
        &mut self,
        now_ms: u64,
        run_id: &str,
        expected_revision: u64,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_identity(run_id, "run")?;
        let record = self
            .runs
            .get_mut(run_id)
            .ok_or(AgentRunError::RunNotFound)?;
        if record.phase == RunPhase::Dispatched {
            return Ok(receipt(record, /*idempotent*/ true));
        }
        require_revision(record, expected_revision)?;
        require_live_deadline(record, now_ms)?;
        if record.phase == RunPhase::Indeterminate {
            return Err(AgentRunError::InvalidTransition);
        }
        if record.phase != RunPhase::ContextAttached {
            return Err(AgentRunError::ContextRequired);
        }
        record.phase = RunPhase::Dispatched;
        advance_revision(record)?;
        Ok(receipt(record, /*idempotent*/ false))
    }

'''
new_mark = r'''    pub fn mark_dispatched(
        &mut self,
        now_ms: u64,
        run_id: &str,
        expected_revision: u64,
    ) -> Result<RunReceipt, AgentRunError> {
        self.mark_dispatched_internal(now_ms, run_id, expected_revision, None)
    }

    pub fn mark_dispatched_with_abort(
        &mut self,
        now_ms: u64,
        run_id: &str,
        expected_revision: u64,
        pre_effect_abort_digest: &str,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_digest(pre_effect_abort_digest, "pre-effect abort")?;
        self.mark_dispatched_internal(
            now_ms,
            run_id,
            expected_revision,
            Some(pre_effect_abort_digest),
        )
    }

    fn mark_dispatched_internal(
        &mut self,
        now_ms: u64,
        run_id: &str,
        expected_revision: u64,
        pre_effect_abort_digest: Option<&str>,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_identity(run_id, "run")?;
        let record = self
            .runs
            .get_mut(run_id)
            .ok_or(AgentRunError::RunNotFound)?;
        if record.phase == RunPhase::Dispatched {
            if record.pre_effect_abort_digest.as_deref() == pre_effect_abort_digest
                && record.entered_effect_digest.is_none()
            {
                return Ok(receipt(record, /*idempotent*/ true));
            }
            return Err(AgentRunError::Conflict);
        }
        require_revision(record, expected_revision)?;
        require_live_deadline(record, now_ms)?;
        if record.phase == RunPhase::Indeterminate {
            return Err(AgentRunError::InvalidTransition);
        }
        if record.phase != RunPhase::ContextAttached {
            return Err(AgentRunError::ContextRequired);
        }
        record.phase = RunPhase::Dispatched;
        record.pre_effect_abort_digest = pre_effect_abort_digest.map(str::to_string);
        record.entered_effect_digest = None;
        advance_revision(record)?;
        Ok(receipt(record, /*idempotent*/ false))
    }

    /// Atomically consume the owner-side pre-effect permit. A concurrent abort
    /// and effect entry race on `expected_revision`; only one transition wins.
    pub fn enter_effect(
        &mut self,
        run_id: &str,
        expected_revision: u64,
        pre_effect_abort_digest: &str,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_identity(run_id, "run")?;
        validate_digest(pre_effect_abort_digest, "pre-effect abort")?;
        let record = self
            .runs
            .get_mut(run_id)
            .ok_or(AgentRunError::RunNotFound)?;
        if record.phase == RunPhase::Dispatched
            && record.entered_effect_digest.as_deref() == Some(pre_effect_abort_digest)
            && record.pre_effect_abort_digest.is_none()
        {
            return Ok(receipt(record, /*idempotent*/ true));
        }
        require_revision(record, expected_revision)?;
        if record.phase != RunPhase::Dispatched
            || record.pre_effect_abort_digest.as_deref() != Some(pre_effect_abort_digest)
            || record.entered_effect_digest.is_some()
        {
            return Err(AgentRunError::InvalidTransition);
        }
        record.pre_effect_abort_digest = None;
        record.entered_effect_digest = Some(pre_effect_abort_digest.to_string());
        advance_revision(record)?;
        Ok(receipt(record, /*idempotent*/ false))
    }

    /// Close a run as definitely unsent only while the exact process-local
    /// permit is still current. Process loss cannot recreate this digest.
    pub fn abort_before_effect(
        &mut self,
        run_id: &str,
        expected_revision: u64,
        pre_effect_abort_digest: &str,
        reason: &str,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_identity(run_id, "run")?;
        validate_digest(pre_effect_abort_digest, "pre-effect abort")?;
        validate_cancel_reason(reason)?;
        let record = self
            .runs
            .get_mut(run_id)
            .ok_or(AgentRunError::RunNotFound)?;
        if record.phase == RunPhase::Cancelled
            && record.pre_effect_abort_digest.as_deref() == Some(pre_effect_abort_digest)
            && record.entered_effect_digest.is_none()
            && record.cancel_reason.as_deref() == Some(reason)
        {
            return Ok(receipt(record, /*idempotent*/ true));
        }
        require_revision(record, expected_revision)?;
        if record.phase != RunPhase::Dispatched
            || record.pre_effect_abort_digest.as_deref() != Some(pre_effect_abort_digest)
            || record.entered_effect_digest.is_some()
        {
            return Err(AgentRunError::InvalidTransition);
        }
        record.phase = RunPhase::Cancelled;
        record.cancel_reason = Some(reason.to_string());
        record.cancel_ack_deadline_ms = None;
        advance_revision(record)?;
        Ok(receipt(record, /*idempotent*/ false))
    }

'''
replace_once("codex-rs/hepta-agentd/src/lane_b_runtime.rs", old_mark, new_mark)
append_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs",
    "pre_effect_abort_and_effect_entry_are_revision_fenced",
    r'''

#[test]
fn pre_effect_abort_and_effect_entry_are_revision_fenced() {
    let permit = digest('a');

    let mut aborted = AgentRunCoordinator::compose_runtime(composition()).unwrap();
    aborted.start_run(100, snapshot()).unwrap();
    aborted.attach_context(200, 1, attachment()).unwrap();
    let dispatched = aborted
        .mark_dispatched_with_abort(300, "run.1", 2, &permit)
        .unwrap();
    assert_receipt(&dispatched, 3, RunPhase::Dispatched, None);
    let closed = aborted
        .abort_before_effect("run.1", 3, &permit, "final fence changed")
        .unwrap();
    assert_receipt(
        &closed,
        4,
        RunPhase::Cancelled,
        Some("final fence changed"),
    );
    assert_eq!(aborted.active_run_count(), 0);
    assert!(closed.terminal_observed);
    assert!(
        aborted
            .abort_before_effect("run.1", 4, &permit, "final fence changed")
            .unwrap()
            .idempotent
    );

    let mut entered = AgentRunCoordinator::compose_runtime(composition()).unwrap();
    entered.start_run(100, snapshot()).unwrap();
    entered.attach_context(200, 1, attachment()).unwrap();
    entered
        .mark_dispatched_with_abort(300, "run.1", 2, &permit)
        .unwrap();
    let effect = entered.enter_effect("run.1", 3, &permit).unwrap();
    assert_receipt(&effect, 4, RunPhase::Dispatched, None);
    assert!(!effect.idempotent);
    assert_eq!(
        entered.abort_before_effect("run.1", 3, &permit, "too late"),
        Err(AgentRunError::StaleRevision)
    );
    assert_eq!(
        entered.abort_before_effect("run.1", 4, &permit, "too late"),
        Err(AgentRunError::InvalidTransition)
    );
    assert!(entered.enter_effect("run.1", 4, &permit).unwrap().idempotent);
}

#[test]
fn duplicate_owner_and_stale_permit_stress_never_reopen_effect_entry() {
    for iteration in 0..128_u64 {
        let permit = format!("{:064x}", iteration + 1);
        let stale = format!("{:064x}", iteration + 10_000);
        let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).unwrap();
        coordinator.start_run(100, snapshot()).unwrap();
        coordinator.attach_context(200, 1, attachment()).unwrap();
        coordinator
            .mark_dispatched_with_abort(300, "run.1", 2, &permit)
            .unwrap();
        assert_eq!(
            coordinator.enter_effect("run.1", 3, &stale),
            Err(AgentRunError::InvalidTransition)
        );
        coordinator.enter_effect("run.1", 3, &permit).unwrap();
        assert_eq!(
            coordinator.abort_before_effect("run.1", 4, &permit, "late abort"),
            Err(AgentRunError::InvalidTransition)
        );
    }
}
''',
)

# ---------------------------------------------------------------------------
# Agentd server and client transport.
# ---------------------------------------------------------------------------
insert_before(
    "codex-rs/hepta-agentd/src/state_control.rs",
    "            crate::AgentdMethod::RunCancel {\n",
    r'''            crate::AgentdMethod::RunMarkDispatchedWithAbort {
                run_id,
                expected_revision,
                pre_effect_abort_digest,
            } => {
                require_run_admission_ready(lifecycle, app_server_ready, fenced)?;
                let receipt = self
                    .runs
                    .lock()
                    .map_err(poisoned_state)?
                    .mark_dispatched_with_abort(
                        now_ms()?,
                        &run_id,
                        expected_revision,
                        &pre_effect_abort_digest,
                    )
                    .map_err(run_error)?;
                AgentdPayload::RunReceipt(wire_run_receipt(receipt))
            }
            crate::AgentdMethod::RunEnterEffect {
                run_id,
                expected_revision,
                pre_effect_abort_digest,
            } => {
                require_run_admission_ready(lifecycle, app_server_ready, fenced)?;
                let receipt = self
                    .runs
                    .lock()
                    .map_err(poisoned_state)?
                    .enter_effect(&run_id, expected_revision, &pre_effect_abort_digest)
                    .map_err(run_error)?;
                AgentdPayload::RunReceipt(wire_run_receipt(receipt))
            }
            crate::AgentdMethod::RunAbortBeforeEffect {
                run_id,
                expected_revision,
                pre_effect_abort_digest,
                reason,
            } => {
                require_run_reconciliation_ready(lifecycle, fenced)?;
                let receipt = self
                    .runs
                    .lock()
                    .map_err(poisoned_state)?
                    .abort_before_effect(
                        &run_id,
                        expected_revision,
                        &pre_effect_abort_digest,
                        &reason,
                    )
                    .map_err(run_error)?;
                AgentdPayload::RunReceipt(wire_run_receipt(receipt))
            }
''',
)
insert_before(
    "codex-rs/hepta-agentd/src/client.rs",
    "    pub async fn run_cancel(\n",
    r'''    pub async fn run_mark_dispatched_with_abort(
        &self,
        run_id: String,
        expected_revision: u64,
        pre_effect_abort_digest: String,
    ) -> Result<AgentRunReceipt, AgentdError> {
        match self
            .send(AgentdRequest::run_mark_dispatched_with_abort(
                self.request_id(),
                self.spawn_generation,
                run_id,
                expected_revision,
                pre_effect_abort_digest,
            ))
            .await?
            .payload
        {
            AgentdPayload::RunReceipt(receipt) => Ok(receipt),
            payload => unexpected(payload),
        }
    }

    pub async fn run_enter_effect(
        &self,
        run_id: String,
        expected_revision: u64,
        pre_effect_abort_digest: String,
    ) -> Result<AgentRunReceipt, AgentdError> {
        match self
            .send(AgentdRequest::run_enter_effect(
                self.request_id(),
                self.spawn_generation,
                run_id,
                expected_revision,
                pre_effect_abort_digest,
            ))
            .await?
            .payload
        {
            AgentdPayload::RunReceipt(receipt) => Ok(receipt),
            payload => unexpected(payload),
        }
    }

    pub async fn run_abort_before_effect(
        &self,
        run_id: String,
        expected_revision: u64,
        pre_effect_abort_digest: String,
        reason: String,
    ) -> Result<AgentRunReceipt, AgentdError> {
        match self
            .send(AgentdRequest::run_abort_before_effect(
                self.request_id(),
                self.spawn_generation,
                run_id,
                expected_revision,
                pre_effect_abort_digest,
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
