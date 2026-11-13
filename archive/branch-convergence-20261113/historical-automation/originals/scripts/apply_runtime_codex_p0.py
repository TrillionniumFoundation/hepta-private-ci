#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def append_once(path: str, marker: str, addition: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if marker in text:
        return
    target.write_text(text.rstrip() + "\n\n" + addition.strip() + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# inference.control: durable two-phase pre-effect abort + exact Agentd binding
# ---------------------------------------------------------------------------
path = "codex-rs/hepta-infer-core/src/native_control.rs"
replace_once(
    path,
    "pub struct NativePreEffectAbortToken {\n    request_id: String,\n    dispatch_revision: u64,\n}\n",
    "pub struct NativePreEffectAbortToken {\n    request_id: String,\n    dispatch_revision: u64,\n}\n\n#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]\n#[serde(deny_unknown_fields)]\npub struct NativeOwnerDispatchBinding {\n    pub run_id: String,\n    pub pre_dispatch_revision: u64,\n    pub dispatch_digest: String,\n}\n",
)
replace_once(
    path,
    "    pub dispatch: Option<NativeDispatch>,\n    pub turn_id: Option<String>,\n",
    "    pub dispatch: Option<NativeDispatch>,\n    #[serde(default)]\n    pub owner_dispatch: Option<NativeOwnerDispatchBinding>,\n    pub turn_id: Option<String>,\n",
)
replace_once(
    path,
    "    pub pre_dispatch_stop: Option<String>,\n    #[serde(default)]\n    pub dispatch_rejection: Option<NativeDispatchRejection>,\n",
    "    pub pre_dispatch_stop: Option<String>,\n    #[serde(default)]\n    pub pre_effect_abort_pending: bool,\n    #[serde(default)]\n    pub dispatch_rejection: Option<NativeDispatchRejection>,\n",
)
replace_once(
    path,
    "    Dispatch {\n        request_id: String,\n        dispatch: NativeDispatch,\n    },\n",
    "    Dispatch {\n        request_id: String,\n        dispatch: NativeDispatch,\n        #[serde(default)]\n        owner_dispatch: Option<NativeOwnerDispatchBinding>,\n    },\n",
)
replace_once(
    path,
    "    AbortBeforeEffect {\n        request_id: String,\n        reason: String,\n    },\n",
    "    PrepareAbortBeforeEffect {\n        request_id: String,\n        reason: String,\n    },\n    CompleteAbortBeforeEffect {\n        request_id: String,\n    },\n    /// Legacy one-event spelling retained for journal replay.\n    AbortBeforeEffect {\n        request_id: String,\n        reason: String,\n    },\n",
)
replace_once(
    path,
    "            Event::Dispatch {\n                request_id: request_id.to_string(),\n                dispatch,\n            },\n",
    "            Event::Dispatch {\n                request_id: request_id.to_string(),\n                dispatch,\n                owner_dispatch: None,\n            },\n",
)
replace_once(
    path,
    "    /// Commit the write-ahead dispatch while issuing a one-shot local proof\n    /// that this exact process can still prove the external effect was not sent.\n    pub fn dispatch_native_with_pre_effect_abort(\n",
    "    /// Commit the write-ahead dispatch and the exact external owner binding\n    /// before any owner RPC or App Server effect entry.\n    pub fn dispatch_native_with_pre_effect_abort_bound(\n        &mut self,\n        request_id: &str,\n        dispatch: NativeDispatch,\n        owner_dispatch: NativeOwnerDispatchBinding,\n    ) -> Result<(NativeRunRecord, NativePreEffectAbortToken), Error> {\n        self.ensure_native_dispatch_space()?;\n        let record = self.commit_native(\n            request_id,\n            Event::Dispatch {\n                request_id: request_id.to_string(),\n                dispatch,\n                owner_dispatch: Some(owner_dispatch),\n            },\n        )?;\n        Ok((\n            record.clone(),\n            NativePreEffectAbortToken {\n                request_id: request_id.to_string(),\n                dispatch_revision: record.revision,\n            },\n        ))\n    }\n\n    /// Commit the write-ahead dispatch while issuing a one-shot local proof\n    /// that this exact process can still prove the external effect was not sent.\n    pub fn dispatch_native_with_pre_effect_abort(\n",
)
replace_once(
    path,
    "    /// Release a prepared dispatch only while the same live process still owns\n    /// the exact one-shot pre-effect proof. If the process died, this proof is\n    /// gone and recovery must reconcile instead of declaring the effect unsent.\n    pub fn abort_native_before_effect(\n        &mut self,\n        token: NativePreEffectAbortToken,\n        reason: String,\n    ) -> Result<NativeRunRecord, Error> {\n        let record = self\n            .native\n            .records\n            .get(&token.request_id)\n            .ok_or(Error::RequestNotFound)?;\n        if record.state != NativeReservationState::Dispatching\n            || record.revision != token.dispatch_revision\n            || record.turn_id.is_some()\n            || record.observation.is_some()\n            || record.dispatch_rejection.is_some()\n            || record.cancel_requested\n        {\n            return Err(Error::InvalidTransition);\n        }\n        self.commit_native(\n            &token.request_id,\n            Event::AbortBeforeEffect {\n                request_id: token.request_id.clone(),\n                reason,\n            },\n        )\n    }\n",
    "    /// Consume the live pre-effect proof and durably enter an abort-pending\n    /// state before contacting Agentd. Recovery may finish this one-way abort,\n    /// but no path may enter the external effect after this event.\n    pub fn prepare_native_abort_before_effect(\n        &mut self,\n        token: NativePreEffectAbortToken,\n        reason: String,\n    ) -> Result<NativeRunRecord, Error> {\n        let record = self\n            .native\n            .records\n            .get(&token.request_id)\n            .ok_or(Error::RequestNotFound)?;\n        if record.state != NativeReservationState::Dispatching\n            || record.revision != token.dispatch_revision\n            || record.turn_id.is_some()\n            || record.observation.is_some()\n            || record.dispatch_rejection.is_some()\n            || record.cancel_requested\n            || record.pre_effect_abort_pending\n        {\n            return Err(Error::InvalidTransition);\n        }\n        self.commit_native(\n            &token.request_id,\n            Event::PrepareAbortBeforeEffect {\n                request_id: token.request_id.clone(),\n                reason,\n            },\n        )\n    }\n\n    /// Release local capacity only after the external owner has acknowledged the\n    /// exact abort. The pending record is replayable and idempotently finishable.\n    pub fn complete_native_abort_before_effect(\n        &mut self,\n        request_id: &str,\n    ) -> Result<NativeRunRecord, Error> {\n        self.commit_native(\n            request_id,\n            Event::CompleteAbortBeforeEffect {\n                request_id: request_id.to_string(),\n            },\n        )\n    }\n\n    /// Compatibility helper for callers without an external owner transition.\n    pub fn abort_native_before_effect(\n        &mut self,\n        token: NativePreEffectAbortToken,\n        reason: String,\n    ) -> Result<NativeRunRecord, Error> {\n        let request_id = token.request_id.clone();\n        self.prepare_native_abort_before_effect(token, reason)?;\n        self.complete_native_abort_before_effect(&request_id)\n    }\n",
)
replace_once(
    path,
    "                    dispatch: None,\n                    turn_id: None,\n                    cancel_requested: false,\n                    pre_dispatch_stop: None,\n                    dispatch_rejection: None,\n",
    "                    dispatch: None,\n                    owner_dispatch: None,\n                    turn_id: None,\n                    cancel_requested: false,\n                    pre_dispatch_stop: None,\n                    pre_effect_abort_pending: false,\n                    dispatch_rejection: None,\n",
)
replace_once(
    path,
    "            Event::Dispatch { request_id, .. }\n            | Event::Started { request_id, .. }\n            | Event::RejectBeforeStart { request_id, .. }\n            | Event::Cancel { request_id }\n            | Event::Stop { request_id, .. }\n            | Event::AbortBeforeEffect { request_id, .. }\n            | Event::Observe { request_id, .. } => request_id,\n",
    "            Event::Dispatch { request_id, .. }\n            | Event::Started { request_id, .. }\n            | Event::RejectBeforeStart { request_id, .. }\n            | Event::Cancel { request_id }\n            | Event::Stop { request_id, .. }\n            | Event::PrepareAbortBeforeEffect { request_id, .. }\n            | Event::CompleteAbortBeforeEffect { request_id }\n            | Event::AbortBeforeEffect { request_id, .. }\n            | Event::Observe { request_id, .. } => request_id,\n",
)
replace_once(
    path,
    "            Event::Dispatch { dispatch, .. } => {\n",
    "            Event::Dispatch {\n                dispatch,\n                owner_dispatch,\n                ..\n            } => {\n",
)
replace_once(
    path,
    "                record.dispatch = Some(dispatch);\n                record.state = NativeReservationState::Dispatching;\n",
    "                if let Some(binding) = &owner_dispatch {\n                    validate_identity(&binding.run_id, \"native owner run\")?;\n                    if binding.pre_dispatch_revision == 0 {\n                        return Err(Error::InvalidIdentity(\"native owner dispatch revision\"));\n                    }\n                    validate_digest(&binding.dispatch_digest, \"native owner dispatch\")?;\n                }\n                record.dispatch = Some(dispatch);\n                record.owner_dispatch = owner_dispatch;\n                record.state = NativeReservationState::Dispatching;\n",
)
replace_once(
    path,
    "                if record.state != NativeReservationState::Dispatching\n                    || record.dispatch_rejection.is_some()\n",
    "                if record.state != NativeReservationState::Dispatching\n                    || record.pre_effect_abort_pending\n                    || record.dispatch_rejection.is_some()\n",
)
replace_once(
    path,
    "                if record.state != NativeReservationState::Dispatching\n                    || record.turn_id.is_some()\n                    || record.observation.is_some()\n                    || rejection.reason.is_empty()\n",
    "                if record.state != NativeReservationState::Dispatching\n                    || record.pre_effect_abort_pending\n                    || record.turn_id.is_some()\n                    || record.observation.is_some()\n                    || rejection.reason.is_empty()\n",
)
replace_once(
    path,
    "            Event::Cancel { .. } => {\n                if record.state == NativeReservationState::Released\n                    || record.state == NativeReservationState::Reserved\n",
    "            Event::Cancel { .. } => {\n                if record.pre_effect_abort_pending\n                    || record.state == NativeReservationState::Released\n                    || record.state == NativeReservationState::Reserved\n",
)
replace_once(
    path,
    "            Event::AbortBeforeEffect { reason, .. } => {\n                if record.state != NativeReservationState::Dispatching\n                    || record.turn_id.is_some()\n                    || record.observation.is_some()\n                    || record.dispatch_rejection.is_some()\n                    || record.cancel_requested\n                    || reason.is_empty()\n                    || reason.len() > 4096\n                {\n                    return Err(Error::InvalidTransition);\n                }\n                record.pre_dispatch_stop = Some(reason);\n                record.state = NativeReservationState::Released;\n            }\n",
    "            Event::PrepareAbortBeforeEffect { reason, .. } => {\n                if record.state != NativeReservationState::Dispatching\n                    || record.pre_effect_abort_pending\n                    || record.turn_id.is_some()\n                    || record.observation.is_some()\n                    || record.dispatch_rejection.is_some()\n                    || record.cancel_requested\n                    || reason.is_empty()\n                    || reason.len() > 4096\n                {\n                    return Err(Error::InvalidTransition);\n                }\n                record.pre_dispatch_stop = Some(reason);\n                record.pre_effect_abort_pending = true;\n            }\n            Event::CompleteAbortBeforeEffect { .. } => {\n                if record.state != NativeReservationState::Dispatching\n                    || !record.pre_effect_abort_pending\n                    || record.turn_id.is_some()\n                    || record.observation.is_some()\n                    || record.dispatch_rejection.is_some()\n                    || record.cancel_requested\n                {\n                    return Err(Error::InvalidTransition);\n                }\n                record.pre_effect_abort_pending = false;\n                record.state = NativeReservationState::Released;\n            }\n            Event::AbortBeforeEffect { reason, .. } => {\n                if record.state != NativeReservationState::Dispatching\n                    || record.turn_id.is_some()\n                    || record.observation.is_some()\n                    || record.dispatch_rejection.is_some()\n                    || record.cancel_requested\n                    || reason.is_empty()\n                    || reason.len() > 4096\n                {\n                    return Err(Error::InvalidTransition);\n                }\n                record.pre_dispatch_stop = Some(reason);\n                record.pre_effect_abort_pending = false;\n                record.state = NativeReservationState::Released;\n            }\n",
)
replace_once(
    path,
    "    let dispatch = record.dispatch.as_ref().ok_or(Error::AssignmentMismatch)?;\n",
    "    if record.pre_effect_abort_pending {\n        return Err(Error::InvalidTransition);\n    }\n    let dispatch = record.dispatch.as_ref().ok_or(Error::AssignmentMismatch)?;\n",
)

# ---------------------------------------------------------------------------
# Agentd exact dispatch/abort transition
# ---------------------------------------------------------------------------
path = "codex-rs/hepta-agentd/src/lane_b_runtime.rs"
replace_once(path, "    pub cancel_reason: Option<String>,\n}\n\n#[derive(Clone, Debug, Eq, PartialEq)]\npub struct RunReceipt", "    pub cancel_reason: Option<String>,\n    pub dispatch_digest: Option<String>,\n}\n\n#[derive(Clone, Debug, Eq, PartialEq)]\npub struct RunReceipt")
replace_once(path, "    pub compilation_receipt_digest: Option<String>,\n    pub terminal_observed: bool,", "    pub compilation_receipt_digest: Option<String>,\n    pub dispatch_digest: Option<String>,\n    pub terminal_observed: bool,")
replace_once(path, "    compilation_receipt_digest: Option<String>,\n    cancel_reason: Option<String>,", "    compilation_receipt_digest: Option<String>,\n    dispatch_digest: Option<String>,\n    cancel_reason: Option<String>,")
replace_once(path, "            compilation_receipt_digest: None,\n            cancel_reason: None,", "            compilation_receipt_digest: None,\n            dispatch_digest: None,\n            cancel_reason: None,")
old_mark = '''    pub fn mark_dispatched(
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
new_mark = '''    pub fn mark_dispatched(
        &mut self,
        now_ms: u64,
        run_id: &str,
        expected_revision: u64,
    ) -> Result<RunReceipt, AgentRunError> {
        self.mark_dispatched_inner(now_ms, run_id, expected_revision, None)
    }

    pub fn mark_dispatched_exact(
        &mut self,
        now_ms: u64,
        run_id: &str,
        expected_revision: u64,
        dispatch_digest: &str,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_digest(dispatch_digest, "dispatch")?;
        self.mark_dispatched_inner(
            now_ms,
            run_id,
            expected_revision,
            Some(dispatch_digest),
        )
    }

    fn mark_dispatched_inner(
        &mut self,
        now_ms: u64,
        run_id: &str,
        expected_revision: u64,
        dispatch_digest: Option<&str>,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_identity(run_id, "run")?;
        let record = self
            .runs
            .get_mut(run_id)
            .ok_or(AgentRunError::RunNotFound)?;
        if record.phase == RunPhase::Dispatched {
            if record.dispatch_digest.as_deref() == dispatch_digest {
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
        record.dispatch_digest = dispatch_digest.map(str::to_string);
        record.phase = RunPhase::Dispatched;
        advance_revision(record)?;
        Ok(receipt(record, /*idempotent*/ false))
    }

    pub fn abort_before_effect(
        &mut self,
        run_id: &str,
        expected_revision: u64,
        dispatch_digest: &str,
        reason: &str,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_identity(run_id, "run")?;
        validate_digest(dispatch_digest, "dispatch")?;
        validate_cancel_reason(reason)?;
        let record = self
            .runs
            .get_mut(run_id)
            .ok_or(AgentRunError::RunNotFound)?;
        if record.phase == RunPhase::Cancelled
            && record.dispatch_digest.as_deref() == Some(dispatch_digest)
            && record.cancel_reason.as_deref() == Some(reason)
        {
            return Ok(receipt(record, /*idempotent*/ true));
        }
        require_revision(record, expected_revision)?;
        if record.phase != RunPhase::Dispatched
            || record.dispatch_digest.as_deref() != Some(dispatch_digest)
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
replace_once(path, old_mark, new_mark)
replace_once(path, "            compilation_receipt_digest: Some(recovery.compilation_receipt_digest),\n            cancel_reason: recovery.cancel_reason,", "            compilation_receipt_digest: Some(recovery.compilation_receipt_digest),\n            dispatch_digest: recovery.dispatch_digest,\n            cancel_reason: recovery.cancel_reason,")
replace_once(path, "    validate_digest(&value.compilation_receipt_digest, \"compilation receipt\")?;\n    if let Some(reason)", "    validate_digest(&value.compilation_receipt_digest, \"compilation receipt\")?;\n    if let Some(dispatch_digest) = value.dispatch_digest.as_deref() {\n        validate_digest(dispatch_digest, \"dispatch\")?;\n    }\n    if let Some(reason)")
replace_once(path, "        compilation_receipt_digest: record.compilation_receipt_digest.clone(),\n        terminal_observed:", "        compilation_receipt_digest: record.compilation_receipt_digest.clone(),\n        dispatch_digest: record.dispatch_digest.clone(),\n        terminal_observed:")

# Protocol additions.
path = "codex-rs/hepta-agent-protocol/src/lib.rs"
replace_once(path, "pub const AGENTD_RUN_LIFECYCLE_CAPABILITY_MINOR: u16 = 1;", "pub const AGENTD_RUN_LIFECYCLE_CAPABILITY_MINOR: u16 = 2;")
replace_once(path, "    pub compilation_receipt_digest: Option<String>,\n    pub authority_epoch:", "    pub compilation_receipt_digest: Option<String>,\n    #[serde(default, skip_serializing_if = \"Option::is_none\")]\n    pub dispatch_digest: Option<String>,\n    pub authority_epoch:")
replace_once(path, "    pub fn run_cancel(\n", '''    pub fn run_mark_dispatched_exact(
        request_id: u64,
        spawn_generation: u64,
        run_id: String,
        expected_revision: u64,
        dispatch_digest: String,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::RunMarkDispatchedExact {
                run_id,
                expected_revision,
                dispatch_digest,
            },
        }
    }

    pub fn run_abort_before_effect(
        request_id: u64,
        spawn_generation: u64,
        run_id: String,
        expected_revision: u64,
        dispatch_digest: String,
        reason: String,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::RunAbortBeforeEffect {
                run_id,
                expected_revision,
                dispatch_digest,
                reason,
            },
        }
    }

    pub fn run_cancel(
''')
replace_once(path, "    RunCancel {\n", '''    RunMarkDispatchedExact {
        run_id: String,
        expected_revision: u64,
        dispatch_digest: String,
    },
    RunAbortBeforeEffect {
        run_id: String,
        expected_revision: u64,
        dispatch_digest: String,
        reason: String,
    },
    RunCancel {
''')

# Agentd dispatch and client methods.
path = "codex-rs/hepta-agentd/src/state_control.rs"
replace_once(path, "            crate::AgentdMethod::RunCancel {\n", '''            crate::AgentdMethod::RunMarkDispatchedExact {
                run_id,
                expected_revision,
                dispatch_digest,
            } => {
                require_run_admission_ready(lifecycle, app_server_ready, fenced)?;
                let receipt = self
                    .runs
                    .lock()
                    .map_err(poisoned_state)?
                    .mark_dispatched_exact(
                        now_ms()?,
                        &run_id,
                        expected_revision,
                        &dispatch_digest,
                    )
                    .map_err(run_error)?;
                AgentdPayload::RunReceipt(wire_run_receipt(receipt))
            }
            crate::AgentdMethod::RunAbortBeforeEffect {
                run_id,
                expected_revision,
                dispatch_digest,
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
                        &dispatch_digest,
                        &reason,
                    )
                    .map_err(run_error)?;
                AgentdPayload::RunReceipt(wire_run_receipt(receipt))
            }
            crate::AgentdMethod::RunCancel {
''')
replace_once(path, "        compilation_receipt_digest: value.compilation_receipt_digest,\n        authority_epoch:", "        compilation_receipt_digest: value.compilation_receipt_digest,\n        dispatch_digest: value.dispatch_digest,\n        authority_epoch:")

path = "codex-rs/hepta-agentd/src/client.rs"
replace_once(path, "    pub async fn run_cancel(\n", '''    pub async fn run_mark_dispatched_exact(
        &self,
        run_id: String,
        expected_revision: u64,
        dispatch_digest: String,
    ) -> Result<AgentRunReceipt, AgentdError> {
        match self
            .send(AgentdRequest::run_mark_dispatched_exact(
                self.request_id(),
                self.spawn_generation,
                run_id,
                expected_revision,
                dispatch_digest,
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
        dispatch_digest: String,
        reason: String,
    ) -> Result<AgentRunReceipt, AgentdError> {
        match self
            .send(AgentdRequest::run_abort_before_effect(
                self.request_id(),
                self.spawn_generation,
                run_id,
                expected_revision,
                dispatch_digest,
                reason,
            ))
            .await?
            .payload
        {
            AgentdPayload::RunReceipt(receipt) => Ok(receipt),
            payload => unexpected(payload),
        }
    }

    pub async fn run_cancel(
''')

# Worker recovery sees and finishes a durable pending abort before generic stop handling.
path = "codex-rs/hepta-infer-worker-host/src/native_run_control.rs"
replace_once(path, "        if let Some(reason) = &record.pre_dispatch_stop {\n", '''        if record.pre_effect_abort_pending {
            self.reconcile_pending_pre_effect_abort(control, &record).await?;
            let reason = record
                .pre_dispatch_stop
                .as_deref()
                .unwrap_or("pre-effect abort pending");
            return Err(format!("request stopped before effect entry: {reason}").into());
        }
        if let Some(reason) = &record.pre_dispatch_stop {
''')

# Worker uses exact Agentd dispatch digest and two-phase abort helper.
path = "codex-rs/hepta-infer-worker-host/src/native_app_server.rs"
replace_once(path, "use codex_hepta_infer_core::durable_control::native::NativeRunRecord;\n", "use codex_hepta_infer_core::durable_control::native::NativeOwnerDispatchBinding;\nuse codex_hepta_infer_core::durable_control::native::NativePreEffectAbortToken;\nuse codex_hepta_infer_core::durable_control::native::NativeRunRecord;\n")
replace_once(path, "        let (_, pre_effect_abort) = control.dispatch_native_with_pre_effect_abort(\n            request_id,\n            NativeDispatch {", "        let owner_dispatch = intelligence.map(|binding| NativeOwnerDispatchBinding {\n            run_id: binding.run_id.clone(),\n            pre_dispatch_revision: binding.expected_revision,\n            dispatch_digest: request_receipt.request_digest.to_string(),\n        });\n        let (_, pre_effect_abort) = match owner_dispatch {\n            Some(owner_dispatch) => control.dispatch_native_with_pre_effect_abort_bound(\n                request_id,\n                NativeDispatch {")
replace_once(path, "                codex_authority_witness_sha256: Some(authority_witness.clone()),\n            },\n        )?;\n        verify_persisted_dispatch_binding(", "                codex_authority_witness_sha256: Some(authority_witness.clone()),\n                },\n                owner_dispatch,\n            )?,\n            None => control.dispatch_native_with_pre_effect_abort(\n                request_id,\n                NativeDispatch {\n                    thread_id: started.thread.id.clone(),\n                    model_provider: started.model_provider.clone(),\n                    context_digest: control::digest(&serde_json::to_vec(\n                        &turn_params.additional_context,\n                    )?),\n                    owner_context_digest,\n                    codex_payload_digest: Some(payload_digest.to_string()),\n                    codex_request_digest: Some(request_receipt.request_digest.to_string()),\n                    app_server_version: Some(app_server_version.clone()),\n                    protocol_id: Some(APP_SERVER_V2_PROTOCOL_ID.to_string()),\n                    codex_source_admission_digest: Some(source_admission_digest.to_string()),\n                    codex_home_digest: Some(codex_home_digest.to_string()),\n                    codex_connection_id: Some(connection_id),\n                    codex_session_id: Some(started.thread.session_id.clone()),\n                    codex_deadline_ms: Some(adapter_intent.deadline_ms),\n                    codex_authority_epoch: Some(authority_epoch),\n                    codex_revocation_revision: Some(revocation_revision),\n                    codex_revocation_head_sha256: Some(revocation_head_digest.clone()),\n                    codex_authority_witness_sha256: Some(authority_witness.clone()),\n                },\n            )?,\n        };\n        verify_persisted_dispatch_binding(")
replace_once(path, ".run_mark_dispatched(binding.run_id.clone(), binding.expected_revision)", ".run_mark_dispatched_exact(\n                    binding.run_id.clone(),\n                    binding.expected_revision,\n                    request_receipt.request_digest.to_string(),\n                )")
replace_once(path, "                || dispatched.generation != self.config.generation\n", "                || dispatched.dispatch_digest.as_deref()\n                    != Some(request_receipt.request_digest.to_string().as_str())\n                || dispatched.generation != self.config.generation\n")
# Exact initial dispatch must still be newly committed; all abort paths are made consistent below.
for old, new in [
    ("                    control.abort_native_before_effect(pre_effect_abort, reason.clone())?;", "                    abort_pre_effect_consistently(\n                        control,\n                        &owner,\n                        intelligence,\n                        pre_effect_abort,\n                        request_receipt.request_digest,\n                        reason.clone(),\n                    )\n                    .await?;"),
    ("                control.abort_native_before_effect(pre_effect_abort, reason.clone())?;", "                abort_pre_effect_consistently(\n                    control,\n                    &owner,\n                    intelligence,\n                    pre_effect_abort,\n                    request_receipt.request_digest,\n                    reason.clone(),\n                )\n                .await?;"),
]:
    # Replace every occurrence with exact indentation, one at a time.
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    while old in text:
        text = text.replace(old, new, 1)
    target.write_text(text, encoding="utf-8")
# Handle non-clone/result-shaped abort call sites.
text = (ROOT / path).read_text(encoding="utf-8")
text = text.replace(
'''                    let stopped = control.abort_native_before_effect(pre_effect_abort, reason);
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                    stopped?;
                    return Err(error.into());''',
'''                    abort_pre_effect_consistently(
                        control,
                        &owner,
                        intelligence,
                        pre_effect_abort,
                        request_receipt.request_digest,
                        reason,
                    )
                    .await?;
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                    return Err(error.into());''')
text = text.replace(
'''                let stopped = control.abort_native_before_effect(
                    pre_effect_abort,
                    "cognitive final-use revalidation returned a mismatched receipt".to_string(),
                );
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                stopped?;''',
'''                abort_pre_effect_consistently(
                    control,
                    &owner,
                    intelligence,
                    pre_effect_abort,
                    request_receipt.request_digest,
                    "cognitive final-use revalidation returned a mismatched receipt".to_string(),
                )
                .await?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;''')
text = text.replace(
'''            let stopped = control.abort_native_before_effect(
                pre_effect_abort,
                "cancelled before model dispatch".to_string(),
            );
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            stopped?;''',
'''            abort_pre_effect_consistently(
                control,
                &owner,
                intelligence,
                pre_effect_abort,
                request_receipt.request_digest,
                "cancelled before model dispatch".to_string(),
            )
            .await?;
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;''')
(ROOT / path).write_text(text, encoding="utf-8")

# Add reconciliation and abort helpers before final_use_binding.
replace_once(path, "fn final_use_binding(\n", '''async fn abort_pre_effect_consistently(
    control: &mut DurableInferenceControl,
    owner: &AgentdClient,
    intelligence: Option<&NativeIntelligenceRunBinding>,
    token: NativePreEffectAbortToken,
    dispatch_digest: Digest32,
    reason: String,
) -> Result<()> {
    let reason: String = reason.chars().take(512).collect();
    let prepared = control.prepare_native_abort_before_effect(token, reason.clone())?;
    if let Some(binding) = intelligence {
        let dispatched = owner
            .run_mark_dispatched_exact(
                binding.run_id.clone(),
                binding.expected_revision,
                dispatch_digest.to_string(),
            )
            .await?;
        if dispatched.phase != AgentRunPhase::Dispatched
            || dispatched.dispatch_digest.as_deref() != Some(dispatch_digest.to_string().as_str())
        {
            return Err("Agentd could not confirm the exact dispatch before abort".into());
        }
        let aborted = owner
            .run_abort_before_effect(
                binding.run_id.clone(),
                dispatched.revision,
                dispatch_digest.to_string(),
                reason,
            )
            .await?;
        if aborted.phase != AgentRunPhase::Cancelled
            || aborted.dispatch_digest.as_deref() != Some(dispatch_digest.to_string().as_str())
        {
            return Err("Agentd did not acknowledge the exact pre-effect abort".into());
        }
    }
    control.complete_native_abort_before_effect(&prepared.request.request_id)?;
    Ok(())
}

impl AppServerModelDriver {
    pub(super) async fn reconcile_pending_pre_effect_abort(
        &self,
        control: &mut DurableInferenceControl,
        record: &NativeRunRecord,
    ) -> Result<()> {
        if !record.pre_effect_abort_pending {
            return Ok(());
        }
        let reason = record
            .pre_dispatch_stop
            .clone()
            .ok_or("pending pre-effect abort omitted its reason")?;
        if let Some(binding) = record.owner_dispatch.as_ref() {
            let owner = AgentdClient::new(
                self.config.agentd_socket.clone(),
                self.config.agent_id.clone(),
                self.config.generation,
            )?;
            let dispatched = owner
                .run_mark_dispatched_exact(
                    binding.run_id.clone(),
                    binding.pre_dispatch_revision,
                    binding.dispatch_digest.clone(),
                )
                .await?;
            if dispatched.phase != AgentRunPhase::Dispatched
                || dispatched.dispatch_digest.as_deref()
                    != Some(binding.dispatch_digest.as_str())
            {
                return Err("Agentd pending abort could not confirm exact dispatch".into());
            }
            let aborted = owner
                .run_abort_before_effect(
                    binding.run_id.clone(),
                    dispatched.revision,
                    binding.dispatch_digest.clone(),
                    reason,
                )
                .await?;
            if aborted.phase != AgentRunPhase::Cancelled
                || aborted.dispatch_digest.as_deref()
                    != Some(binding.dispatch_digest.as_str())
            {
                return Err("Agentd pending abort acknowledgement mismatched".into());
            }
        }
        control.complete_native_abort_before_effect(&record.request.request_id)?;
        Ok(())
    }
}

fn final_use_binding(
''')

# Test fixtures need the new recovery field.
path = "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs"
replace_once(path, "        cancel_reason: Some(\"process_restart\".to_string()),\n", "        cancel_reason: Some(\"process_restart\".to_string()),\n        dispatch_digest: None,\n")
append_once(path, "exact_dispatch_abort_is_digest_bound_and_idempotent", r'''
#[test]
fn exact_dispatch_abort_is_digest_bound_and_idempotent() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    coordinator.start_run(100, snapshot()).expect("start");
    coordinator
        .attach_context(200, 1, attachment())
        .expect("attach");
    let dispatch = coordinator
        .mark_dispatched_exact(300, "run.1", 2, &digest('a'))
        .expect("exact dispatch");
    assert_eq!(dispatch.dispatch_digest, Some(digest('a')));
    assert!(!dispatch.idempotent);
    let repeated = coordinator
        .mark_dispatched_exact(301, "run.1", 2, &digest('a'))
        .expect("idempotent exact dispatch");
    assert!(repeated.idempotent);
    assert_eq!(
        coordinator.mark_dispatched_exact(301, "run.1", 2, &digest('b')),
        Err(AgentRunError::Conflict)
    );
    assert_eq!(
        coordinator.abort_before_effect("run.1", dispatch.revision, &digest('b'), "denied"),
        Err(AgentRunError::InvalidTransition)
    );
    let aborted = coordinator
        .abort_before_effect("run.1", dispatch.revision, &digest('a'), "denied")
        .expect("abort");
    assert_eq!(aborted.phase, RunPhase::Cancelled);
    assert_eq!(aborted.dispatch_digest, Some(digest('a')));
    let repeated_abort = coordinator
        .abort_before_effect("run.1", dispatch.revision, &digest('a'), "denied")
        .expect("repeat abort");
    assert!(repeated_abort.idempotent);
}

#[test]
fn duplicate_owner_stress_never_accepts_two_dispatch_digests() {
    for winner in ['a', 'b'] {
        let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
        coordinator.start_run(100, snapshot()).expect("start");
        coordinator.attach_context(200, 1, attachment()).expect("attach");
        let selected = digest(winner);
        coordinator
            .mark_dispatched_exact(300, "run.1", 2, &selected)
            .expect("winner");
        for candidate in ['a', 'b', 'c', 'd'] {
            let result = coordinator.mark_dispatched_exact(301, "run.1", 2, &digest(candidate));
            if candidate == winner {
                assert!(result.expect("same digest").idempotent);
            } else {
                assert_eq!(result, Err(AgentRunError::Conflict));
            }
        }
    }
}
''')

path = "codex-rs/hepta-infer-core/src/native_control_tests.rs"
append_once(path, "two_phase_pre_effect_abort_survives_reopen", r'''
#[test]
fn two_phase_pre_effect_abort_survives_reopen() {
    let temp = tempfile::tempdir().unwrap();
    let journal = temp.path().join("native-abort-pending.journal");
    let mut control = DurableInferenceControl::open(&journal, 32).unwrap();
    control.reserve_native(request("r-pending"), 4).unwrap();
    let (_, token) = control
        .dispatch_native_with_pre_effect_abort_bound(
            "r-pending",
            dispatch(),
            NativeOwnerDispatchBinding {
                run_id: "run.pending".to_string(),
                pre_dispatch_revision: 2,
                dispatch_digest: digest("owner-dispatch"),
            },
        )
        .unwrap();
    let pending = control
        .prepare_native_abort_before_effect(token, "owner fence drift".to_string())
        .unwrap();
    assert!(pending.pre_effect_abort_pending);
    assert_eq!(pending.state, NativeReservationState::Dispatching);
    drop(control);

    let mut reopened = DurableInferenceControl::open(&journal, 32).unwrap();
    let replayed = reopened.native_record("r-pending").unwrap();
    assert!(replayed.pre_effect_abort_pending);
    assert_eq!(
        replayed.owner_dispatch.as_ref().unwrap().run_id,
        "run.pending"
    );
    let released = reopened
        .complete_native_abort_before_effect("r-pending")
        .unwrap();
    assert_eq!(released.state, NativeReservationState::Released);
    assert!(!released.pre_effect_abort_pending);
}

#[test]
fn pending_abort_forbids_start_cancel_and_observation() {
    let temp = tempfile::tempdir().unwrap();
    let journal = temp.path().join("native-abort-fence.journal");
    let mut control = DurableInferenceControl::open(&journal, 32).unwrap();
    control.reserve_native(request("r-fenced"), 4).unwrap();
    let (_, token) = control
        .dispatch_native_with_pre_effect_abort("r-fenced", dispatch())
        .unwrap();
    control
        .prepare_native_abort_before_effect(token, "final-use denied".to_string())
        .unwrap();
    assert_eq!(
        control.native_started("r-fenced", "turn-fenced".to_string()),
        Err(Error::InvalidTransition)
    );
    assert_eq!(control.cancel_native("r-fenced"), Err(Error::InvalidTransition));
}
''')

print("runtime.codex P0 patch applied")
