#!/usr/bin/env python3
"""Add two-stage, cross-owner settlement for typed pre-admission rejections.

The preceding effect-fence transformer verifies and rewrites its exact source
blobs first.  This transformer additionally verifies the untouched local-journal
blobs and then requires the post-fence semantic markers before editing the
product path.  It is removed by the bootstrap workflow after one use.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_UNTOUCHED = {
    "codex-rs/hepta-infer-core/src/native_control.rs": "0ce236c272c957fee1fcbf5df6cfaef37c70a074",
    "codex-rs/hepta-infer-core/src/native_control_tests.rs": "ab99b772f7cbba2b93ad727a34d8c0c6ca179ef2",
    "codex-rs/hepta-infer-worker-host/src/native_run_control.rs": "5e9fd06cefe29abe6ccf5648cafdc5e535bce3ed",
}


def path(name: str) -> Path:
    return ROOT / name


def read(name: str) -> str:
    return path(name).read_text(encoding="utf-8")


def write(name: str, text: str) -> None:
    path(name).write_text(text, encoding="utf-8")


def verify_blob(name: str, expected: str) -> None:
    actual = subprocess.check_output(
        ["git", "hash-object", "--", name], cwd=ROOT, text=True
    ).strip()
    if actual != expected:
        raise SystemExit(f"{name}: expected blob {expected}, got {actual}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    first = text.find(start)
    if first < 0 or text.find(start, first + 1) >= 0:
        raise SystemExit(f"{label}: missing or ambiguous start marker")
    stop = text.find(end, first + len(start))
    if stop < 0:
        raise SystemExit(f"{label}: end marker not found")
    return text[:first] + replacement + text[stop:]


def patch_local_journal() -> None:
    name = "codex-rs/hepta-infer-core/src/native_control.rs"
    text = read(name)
    text = replace_once(
        text,
        """    #[serde(default)]
    pub pre_effect_abort_local_only: bool,
    #[serde(default)]
    pub dispatch_rejection: Option<NativeDispatchRejection>,""",
        """    #[serde(default)]
    pub pre_effect_abort_local_only: bool,
    /// A typed App Server non-admission fact has been durably prepared locally,
    /// but the external Agentd owner has not yet been confirmed terminal.
    #[serde(default)]
    pub pre_admission_rejection_pending: bool,
    #[serde(default)]
    pub dispatch_rejection: Option<NativeDispatchRejection>,""",
        "pending rejection record field",
    )
    text = replace_once(
        text,
        """    RejectBeforeStart {
        request_id: String,
        rejection: NativeDispatchRejection,
    },""",
        """    PrepareRejectBeforeStart {
        request_id: String,
        rejection: NativeDispatchRejection,
    },
    CompleteRejectBeforeStart {
        request_id: String,
    },
    /// Legacy one-event spelling retained for journal replay.
    #[allow(dead_code)]
    RejectBeforeStart {
        request_id: String,
        rejection: NativeDispatchRejection,
    },""",
        "two-stage rejection events",
    )

    start = """    /// A typed JSON-RPC error is evidence that the App Server returned a
    /// rejection rather than a lost acknowledgement. This transition is legal
    /// only after Dispatch and before any turn identity was observed.
    pub fn reject_native_before_start("""
    end = """    /// This records intent only: an interrupt acknowledgement never frees a slot."""
    replacement = """    /// Durably retain an exact typed App Server non-admission response while
    /// keeping local capacity owned. The external owner must be settled before
    /// `complete_native_rejection_before_start` releases the slot.
    pub fn prepare_native_rejection_before_start(
        &mut self,
        request_id: &str,
        rejection: NativeDispatchRejection,
    ) -> Result<NativeRunRecord, Error> {
        if self.poisoned {
            return Err(Error::WriterUnavailable);
        }
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        if record.pre_admission_rejection_pending
            && record.dispatch_rejection.as_ref() == Some(&rejection)
        {
            return Ok(record.clone());
        }
        if record.dispatch_rejection.is_some() {
            return Err(Error::Conflict);
        }
        self.commit_native(
            request_id,
            Event::PrepareRejectBeforeStart {
                request_id: request_id.to_string(),
                rejection,
            },
        )
    }

    /// Release local capacity only after Agentd terminally acknowledges the
    /// exact dispatched run. A crash between prepare and complete reopens in a
    /// durable pending state and must reconcile the owner first.
    pub fn complete_native_rejection_before_start(
        &mut self,
        request_id: &str,
    ) -> Result<NativeRunRecord, Error> {
        if self.poisoned {
            return Err(Error::WriterUnavailable);
        }
        let record = self
            .native
            .records
            .get(request_id)
            .ok_or(Error::RequestNotFound)?;
        if record.state == NativeReservationState::Released
            && !record.pre_admission_rejection_pending
            && record.dispatch_rejection.is_some()
        {
            return Ok(record.clone());
        }
        self.commit_native(
            request_id,
            Event::CompleteRejectBeforeStart {
                request_id: request_id.to_string(),
            },
        )
    }

    /// Compatibility helper for callers without an external owner. Product
    /// runtime.codex callers use the explicit prepare/owner/complete sequence.
    pub fn reject_native_before_start(
        &mut self,
        request_id: &str,
        rejection: NativeDispatchRejection,
    ) -> Result<NativeRunRecord, Error> {
        self.prepare_native_rejection_before_start(request_id, rejection)?;
        self.complete_native_rejection_before_start(request_id)
    }

""" + end
    text = replace_between(text, start, end, replacement, "rejection API replacement")

    text = replace_once(
        text,
        """                    pre_effect_abort_pending: false,
                    pre_effect_abort_local_only: false,
                    dispatch_rejection: None,""",
        """                    pre_effect_abort_pending: false,
                    pre_effect_abort_local_only: false,
                    pre_admission_rejection_pending: false,
                    dispatch_rejection: None,""",
        "reserve initializes rejection state",
    )
    text = replace_once(
        text,
        """            | Event::Started { request_id, .. }
            | Event::RejectBeforeStart { request_id, .. }
            | Event::Cancel { request_id }""",
        """            | Event::Started { request_id, .. }
            | Event::PrepareRejectBeforeStart { request_id, .. }
            | Event::CompleteRejectBeforeStart { request_id }
            | Event::RejectBeforeStart { request_id, .. }
            | Event::Cancel { request_id }""",
        "event identity dispatch",
    )
    text = replace_once(
        text,
        """                if record.state != NativeReservationState::Dispatching
                    || record.pre_effect_abort_pending
                    || record.dispatch_rejection.is_some()""",
        """                if record.state != NativeReservationState::Dispatching
                    || record.pre_effect_abort_pending
                    || record.pre_admission_rejection_pending
                    || record.dispatch_rejection.is_some()""",
        "started rejects pending rejection",
    )

    old_apply = """            Event::RejectBeforeStart { rejection, .. } => {
                if record.state != NativeReservationState::Dispatching
                    || record.pre_effect_abort_pending
                    || record.turn_id.is_some()
                    || record.observation.is_some()
                    || rejection.reason.is_empty()
                    || rejection.reason.len() > 4096
                {
                    return Err(Error::InvalidTransition);
                }
                validate_digest(&rejection.response_digest, "native dispatch rejection")?;
                if rejection.retry_safe_before_admission
                    && !matches!(
                        rejection.status,
                        NativeDispatchRejectionStatus::Overloaded
                            | NativeDispatchRejectionStatus::Unavailable
                    )
                {
                    return Err(Error::InvalidTransition);
                }
                let safe_before_admission = rejection.retry_safe_before_admission;
                record.dispatch_rejection = Some(rejection);
                record.state = if safe_before_admission {
                    NativeReservationState::Released
                } else {
                    NativeReservationState::Indeterminate
                };
            }
"""
    new_apply = """            Event::PrepareRejectBeforeStart { rejection, .. } => {
                if record.state != NativeReservationState::Dispatching
                    || record.pre_effect_abort_pending
                    || record.pre_admission_rejection_pending
                    || record.dispatch_rejection.is_some()
                    || record.turn_id.is_some()
                    || record.observation.is_some()
                    || rejection.reason.is_empty()
                    || rejection.reason.len() > 4096
                {
                    return Err(Error::InvalidTransition);
                }
                validate_dispatch_rejection(&rejection)?;
                record.dispatch_rejection = Some(rejection);
                record.pre_admission_rejection_pending = true;
            }
            Event::CompleteRejectBeforeStart { .. } => {
                if record.state != NativeReservationState::Dispatching
                    || !record.pre_admission_rejection_pending
                    || record.dispatch_rejection.is_none()
                    || record.turn_id.is_some()
                    || record.observation.is_some()
                    || record.cancel_requested
                {
                    return Err(Error::InvalidTransition);
                }
                record.pre_admission_rejection_pending = false;
                // Both explicit overload and deterministic JSON-RPC request
                // rejection prove non-admission. `retry_safe_before_admission`
                // controls retry policy, not ownership/capacity closure.
                record.state = NativeReservationState::Released;
            }
            Event::RejectBeforeStart { rejection, .. } => {
                // Historical one-event journals retain their old interpretation.
                if record.state != NativeReservationState::Dispatching
                    || record.pre_effect_abort_pending
                    || record.pre_admission_rejection_pending
                    || record.turn_id.is_some()
                    || record.observation.is_some()
                {
                    return Err(Error::InvalidTransition);
                }
                validate_dispatch_rejection(&rejection)?;
                let safe_before_admission = rejection.retry_safe_before_admission;
                record.dispatch_rejection = Some(rejection);
                record.state = if safe_before_admission {
                    NativeReservationState::Released
                } else {
                    NativeReservationState::Indeterminate
                };
            }
"""
    text = replace_once(text, old_apply, new_apply, "two-stage rejection apply")
    text = replace_once(
        text,
        """            Event::Cancel { .. } => {
                if record.pre_effect_abort_pending
                    || record.state == NativeReservationState::Released""",
        """            Event::Cancel { .. } => {
                if record.pre_effect_abort_pending
                    || record.pre_admission_rejection_pending
                    || record.state == NativeReservationState::Released""",
        "cancel rejects pending rejection",
    )
    text = replace_once(
        text,
        """fn apply_observation(
    record: &mut NativeRunRecord,
    mut output: NativeRunOutput,
) -> Result<(), Error> {
    if record.pre_effect_abort_pending {""",
        """fn validate_dispatch_rejection(rejection: &NativeDispatchRejection) -> Result<(), Error> {
    if rejection.reason.is_empty() || rejection.reason.len() > 4096 {
        return Err(Error::InvalidTransition);
    }
    validate_digest(&rejection.response_digest, "native dispatch rejection")?;
    if rejection.retry_safe_before_admission
        && !matches!(
            rejection.status,
            NativeDispatchRejectionStatus::Overloaded
                | NativeDispatchRejectionStatus::Unavailable
        )
    {
        return Err(Error::InvalidTransition);
    }
    Ok(())
}

fn apply_observation(
    record: &mut NativeRunRecord,
    mut output: NativeRunOutput,
) -> Result<(), Error> {
    if record.pre_effect_abort_pending || record.pre_admission_rejection_pending {""",
        "rejection validation helper",
    )
    write(name, text)


def patch_local_tests() -> None:
    name = "codex-rs/hepta-infer-core/src/native_control_tests.rs"
    text = read(name)
    start = """#[test]
fn explicit_dispatch_rejection_releases_without_claiming_provider_terminal() {"""
    end = """#[test]
fn codex_bound_terminal_requires_adapter_correlation_witness() {"""
    replacement = """#[test]
fn typed_pre_admission_rejection_is_durable_and_holds_capacity_until_owner_ack() {
    let path = path("dispatch-rejected-two-stage");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native(request("r1"), 1).unwrap();
    control.dispatch_native("r1", dispatch()).unwrap();
    let rejection = NativeDispatchRejection {
        status: NativeDispatchRejectionStatus::Overloaded,
        reason: "Server overloaded before admission.".to_string(),
        response_digest: "e".repeat(64),
        retry_safe_before_admission: true,
    };
    let prepared = control
        .prepare_native_rejection_before_start("r1", rejection.clone())
        .unwrap();
    assert_eq!(prepared.state, NativeReservationState::Dispatching);
    assert!(prepared.pre_admission_rejection_pending);
    assert_eq!(prepared.dispatch_rejection, Some(rejection.clone()));
    assert_eq!(
        control.reserve_native(request("r2"), 1),
        Err(Error::CapacityExceeded)
    );
    drop(control);

    let mut reopened = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(reopened.native_record("r1"), Some(&prepared));
    let released = reopened
        .complete_native_rejection_before_start("r1")
        .unwrap();
    assert_eq!(released.state, NativeReservationState::Released);
    assert!(!released.pre_admission_rejection_pending);
    assert_eq!(released.dispatch_rejection, Some(rejection));
    assert_eq!(
        reopened
            .complete_native_rejection_before_start("r1")
            .unwrap(),
        released
    );
    reopened.reserve_native(request("r2"), 1).unwrap();
    drop(reopened);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn deterministic_request_rejection_closes_capacity_but_never_becomes_retry_safe() {
    let path = path("dispatch-invalid-request-two-stage");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native(request("r1"), 1).unwrap();
    control.dispatch_native("r1", dispatch()).unwrap();
    let rejection = NativeDispatchRejection {
        status: NativeDispatchRejectionStatus::Rejected,
        reason: "invalid params before handler admission".to_string(),
        response_digest: "f".repeat(64),
        retry_safe_before_admission: false,
    };
    control
        .prepare_native_rejection_before_start("r1", rejection.clone())
        .unwrap();
    let released = control
        .complete_native_rejection_before_start("r1")
        .unwrap();
    assert_eq!(released.state, NativeReservationState::Released);
    assert_eq!(released.dispatch_rejection, Some(rejection));
    assert!(
        !released
            .dispatch_rejection
            .as_ref()
            .unwrap()
            .retry_safe_before_admission
    );
    drop(control);
    std::fs::remove_file(path).unwrap();
}

""" + end
    text = replace_between(text, start, end, replacement, "rejection journal tests")
    write(name, text)


def patch_recovery() -> None:
    name = "codex-rs/hepta-infer-worker-host/src/native_run_control.rs"
    text = read(name)
    text = replace_once(
        text,
        """use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeRequest;""",
        """use codex_hepta_agentd::AgentRunPhase;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeRequest;""",
        "owner imports for rejection recovery",
    )
    text = replace_once(
        text,
        """        if let Some(reason) = &record.pre_dispatch_stop {
            return Err(format!("request stopped before dispatch: {reason}").into());
        }
        if let Some(rejection) = &record.dispatch_rejection {""",
        """        if let Some(reason) = &record.pre_dispatch_stop {
            return Err(format!("request stopped before dispatch: {reason}").into());
        }
        if record.pre_admission_rejection_pending {
            self.reconcile_pending_pre_admission_rejection(control, &record)
                .await?;
            let rejection = record
                .dispatch_rejection
                .as_ref()
                .ok_or("pending pre-admission rejection omitted its durable evidence")?;
            return Err(format!(
                "turn/start was explicitly rejected before admission ({:?}): {}",
                rejection.status, rejection.reason
            )
            .into());
        }
        if let Some(rejection) = &record.dispatch_rejection {""",
        "pending rejection recovery entry",
    )
    method_anchor = """    async fn run_bound(
        &self,
        control: &mut DurableInferenceControl,"""
    method = """    pub(super) async fn reconcile_pending_pre_admission_rejection(
        &self,
        control: &mut DurableInferenceControl,
        record: &codex_hepta_infer_core::durable_control::native::NativeRunRecord,
    ) -> Result<()> {
        if !record.pre_admission_rejection_pending || record.dispatch_rejection.is_none() {
            return Err("runtime.codex rejection recovery requires durable pending evidence".into());
        }
        let binding = record
            .owner_dispatch
            .as_ref()
            .ok_or("pending runtime.codex rejection omitted its Agentd owner binding")?;
        let owner = AgentdClient::new(
            self.config.agentd_socket.clone(),
            self.config.agent_id.clone(),
            self.config.generation,
        )?;
        let expected_dispatched_revision = binding
            .pre_dispatch_revision
            .checked_add(1)
            .ok_or("Agentd dispatch revision overflow")?;
        let mut owner_record = owner
            .run_status(binding.run_id.clone())
            .await?
            .ok_or("Agentd lost the run for a pending pre-admission rejection")?;
        let exact_binding = owner_record.generation == self.config.generation
            && owner_record.dispatch_digest.as_deref()
                == Some(binding.dispatch_digest.as_str());
        if owner_record.phase == AgentRunPhase::Dispatched
            && owner_record.revision == expected_dispatched_revision
            && exact_binding
        {
            owner_record = owner
                .run_observe_terminal(
                    binding.run_id.clone(),
                    owner_record.revision,
                    AgentRunPhase::Cancelled,
                    /*terminal_observed*/ true,
                )
                .await
                .or_else(|first_error| async {
                    owner
                        .run_status(binding.run_id.clone())
                        .await?
                        .ok_or(first_error)
                }
                .await?;
        }
        if owner_record.phase != AgentRunPhase::Cancelled
            || !owner_record.terminal_observed
            || owner_record.generation != self.config.generation
            || owner_record.dispatch_digest.as_deref()
                != Some(binding.dispatch_digest.as_str())
        {
            return Err(
                "Agentd did not terminally acknowledge the exact pre-admission rejection"
                    .into(),
            );
        }
        control.complete_native_rejection_before_start(&record.request.request_id)?;
        Ok(())
    }

""" + method_anchor
    text = replace_once(text, method_anchor, method, "rejection recovery method")
    # Rust futures cannot be returned from Result::or_else; replace the concise
    # source above with an explicit match while the marker is still unique.
    text = replace_once(
        text,
        """            owner_record = owner
                .run_observe_terminal(
                    binding.run_id.clone(),
                    owner_record.revision,
                    AgentRunPhase::Cancelled,
                    /*terminal_observed*/ true,
                )
                .await
                .or_else(|first_error| async {
                    owner
                        .run_status(binding.run_id.clone())
                        .await?
                        .ok_or(first_error)
                }
                .await?;""",
        """            owner_record = match owner
                .run_observe_terminal(
                    binding.run_id.clone(),
                    owner_record.revision,
                    AgentRunPhase::Cancelled,
                    /*terminal_observed*/ true,
                )
                .await
            {
                Ok(receipt) => receipt,
                Err(first_error) => owner
                    .run_status(binding.run_id.clone())
                    .await?
                    .ok_or(first_error)?,
            };""",
        "explicit owner acknowledgement reconciliation",
    )
    write(name, text)


def patch_product() -> None:
    name = "codex-rs/hepta-infer-worker-host/src/native_execution.rs"
    text = read(name)
    required = [
        "effect_entry_fence_started",
        "Agentd effect-entry fence was already committed; reconcile only",
        ".run_mark_dispatched_exact(",
    ]
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise SystemExit(f"native execution is not the reviewed post-fence source: {missing}")
    old = """                        control.reject_native_before_start(
                            request_id,
                            NativeDispatchRejection {
                                status,
                                reason: reason.clone(),
                                response_digest: response_digest.to_string(),
                                retry_safe_before_admission,
                            },
                        )?;
                        thread_guard.cleanup().await;"""
    new = """                        let prepared_rejection = control
                            .prepare_native_rejection_before_start(
                                request_id,
                                NativeDispatchRejection {
                                    status,
                                    reason: reason.clone(),
                                    response_digest: response_digest.to_string(),
                                    retry_safe_before_admission,
                                },
                            )?;
                        if intelligence.is_some() {
                            if let Err(error) = self
                                .reconcile_pending_pre_admission_rejection(
                                    control,
                                    &prepared_rejection,
                                )
                                .await
                            {
                                thread_guard.cleanup().await;
                                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                                return Err(format!(
                                    "Agentd pre-admission rejection settlement requires reconciliation; local slot retained: {error}"
                                )
                                .into());
                            }
                        } else {
                            control.complete_native_rejection_before_start(request_id)?;
                        }
                        thread_guard.cleanup().await;"""
    text = replace_once(text, old, new, "owner-first product rejection settlement")
    write(name, text)


def patch_product_tests() -> None:
    name = "codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs"
    text = read(name)
    addition = r'''

#[test]
fn typed_pre_admission_rejection_is_prepared_before_owner_terminal_and_local_release() {
    let execution = include_str!("native_execution.rs");
    let control = include_str!("native_run_control.rs");
    let prepare = execution
        .find(".prepare_native_rejection_before_start(")
        .expect("durable rejection prepare");
    let reconcile = execution
        .find(".reconcile_pending_pre_admission_rejection(")
        .expect("Agentd rejection settlement");
    let local_complete = control
        .find("control.complete_native_rejection_before_start(")
        .expect("local rejection completion");
    let owner_terminal = control
        .find(".run_observe_terminal(")
        .expect("Agentd terminal transition");
    assert!(prepare < reconcile);
    assert!(owner_terminal < local_complete);
    assert!(control.contains("pending pre-admission rejection"));
    assert!(execution.contains("local slot retained"));
}
'''
    if "fn typed_pre_admission_rejection_is_prepared_before_owner_terminal_and_local_release" in text:
        raise SystemExit("product rejection settlement test already exists")
    text += addition
    write(name, text)


def patch_fault_matrix() -> None:
    name = "docs/modules/runtime.codex/FAULT_MATRIX.md"
    text = read(name)
    text = replace_once(
        text,
        """| Exact App Server overload `-32001` before handler admission | `AdapterStatus::Overloaded` | `SafeBeforeAdmission` | durable rejection may release the slot |
| Invalid request / method-not-found / invalid params (`-32600/-32601/-32602`) | `AdapterStatus::Rejected` | `Never` | durable rejection; do not reinterpret as execution |""",
        """| Exact App Server overload `-32001` before handler admission | `AdapterStatus::Overloaded` | `SafeBeforeAdmission` | prepare exact local response evidence; terminally settle the exact Agentd dispatch; only then release local capacity |
| Invalid request / method-not-found / invalid params (`-32600/-32601/-32602`) | `AdapterStatus::Rejected` | `Never` | prepare exact local response evidence; terminally settle the exact Agentd dispatch; release capacity without authorizing retry |
| Agentd acknowledgement is lost while settling a typed pre-admission rejection | owner state reconciliation | never resend the original operation | retain the local slot and durable response evidence until exact Agentd terminal state is observed |""",
        "fault matrix rejection settlement",
    )
    write(name, text)


def main() -> None:
    for name, expected in EXPECTED_UNTOUCHED.items():
        verify_blob(name, expected)
    patch_local_journal()
    patch_local_tests()
    patch_recovery()
    patch_product()
    patch_product_tests()
    patch_fault_matrix()
    Path(__file__).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
