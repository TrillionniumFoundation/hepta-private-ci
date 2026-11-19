#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement, found {count}: {old[:160]!r}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def replace_count(path: str, old: str, new: str, expected: int) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise RuntimeError(f"{path}: expected {expected} replacements, found {count}: {old[:160]!r}")
    target.write_text(text.replace(old, new), encoding="utf-8")


# Keep legacy journal decode support without producing dead-code lint failures.
replace_once(
    "codex-rs/hepta-infer-core/src/native_control.rs",
    "    /// Legacy one-event spelling retained for journal replay.\n    AbortBeforeEffect {",
    "    /// Legacy one-event spelling retained for journal replay.\n    #[allow(dead_code)]\n    AbortBeforeEffect {",
)

# Recovery equality must bind the exact dispatch identity too.
replace_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "                && current.compilation_receipt_digest.as_deref()\n                    == Some(recovery.compilation_receipt_digest.as_str())\n                && current.cancel_reason == recovery.cancel_reason;",
    "                && current.compilation_receipt_digest.as_deref()\n                    == Some(recovery.compilation_receipt_digest.as_str())\n                && current.dispatch_digest == recovery.dispatch_digest\n                && current.cancel_reason == recovery.cancel_reason;",
)

# A pre-effect abort reconciles both sides of an unknown RunMarkDispatched ACK:
# ContextAttached means the mark did not commit; Dispatched with the exact digest
# means it did. In either case one call closes the owner without guessing.
replace_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    '''    pub fn abort_before_effect(
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
''',
    '''    pub fn abort_before_effect(
        &mut self,
        run_id: &str,
        pre_dispatch_revision: u64,
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
        match record.phase {
            RunPhase::ContextAttached => {
                require_revision(record, pre_dispatch_revision)?;
                if record.dispatch_digest.is_some() {
                    return Err(AgentRunError::Conflict);
                }
                record.dispatch_digest = Some(dispatch_digest.to_string());
            }
            RunPhase::Dispatched => {
                let dispatched_revision = pre_dispatch_revision
                    .checked_add(1)
                    .ok_or(AgentRunError::ArithmeticOverflow)?;
                require_revision(record, dispatched_revision)?;
                if record.dispatch_digest.as_deref() != Some(dispatch_digest) {
                    return Err(AgentRunError::Conflict);
                }
            }
            _ => return Err(AgentRunError::InvalidTransition),
        }
        record.phase = RunPhase::Cancelled;
        record.cancel_reason = Some(reason.to_string());
        record.cancel_ack_deadline_ms = None;
        advance_revision(record)?;
        Ok(receipt(record, /*idempotent*/ false))
    }
''',
)

# Wire vocabulary records that the supplied revision is the predecessor, not an
# assertion about whether the dispatch RPC committed.
replace_once(
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    '''    pub fn run_abort_before_effect(
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
''',
    '''    pub fn run_abort_before_effect(
        request_id: u64,
        spawn_generation: u64,
        run_id: String,
        pre_dispatch_revision: u64,
        dispatch_digest: String,
        reason: String,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::RunAbortBeforeEffect {
                run_id,
                pre_dispatch_revision,
                dispatch_digest,
                reason,
            },
        }
    }
''',
)
replace_once(
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    '''    RunAbortBeforeEffect {
        run_id: String,
        expected_revision: u64,
        dispatch_digest: String,
        reason: String,
    },''',
    '''    RunAbortBeforeEffect {
        run_id: String,
        pre_dispatch_revision: u64,
        dispatch_digest: String,
        reason: String,
    },''',
)
replace_once(
    "codex-rs/hepta-agentd/src/state_control.rs",
    '''            crate::AgentdMethod::RunAbortBeforeEffect {
                run_id,
                expected_revision,
                dispatch_digest,
                reason,
            } => {''',
    '''            crate::AgentdMethod::RunAbortBeforeEffect {
                run_id,
                pre_dispatch_revision,
                dispatch_digest,
                reason,
            } => {''',
)
replace_once(
    "codex-rs/hepta-agentd/src/state_control.rs",
    '''                        &run_id,
                        expected_revision,
                        &dispatch_digest,
                        &reason,
                    )''',
    '''                        &run_id,
                        pre_dispatch_revision,
                        &dispatch_digest,
                        &reason,
                    )''',
)
replace_once(
    "codex-rs/hepta-agentd/src/client.rs",
    '''    pub async fn run_abort_before_effect(
        &self,
        run_id: String,
        expected_revision: u64,
        dispatch_digest: String,
        reason: String,
    ) -> Result<AgentRunReceipt, AgentdError> {''',
    '''    pub async fn run_abort_before_effect(
        &self,
        run_id: String,
        pre_dispatch_revision: u64,
        dispatch_digest: String,
        reason: String,
    ) -> Result<AgentRunReceipt, AgentdError> {''',
)
replace_once(
    "codex-rs/hepta-agentd/src/client.rs",
    '''                run_id,
                expected_revision,
                dispatch_digest,
                reason,
            ))''',
    '''                run_id,
                pre_dispatch_revision,
                dispatch_digest,
                reason,
            ))''',
)

path = "codex-rs/hepta-infer-worker-host/src/native_app_server.rs"
# Reuse a stable string and avoid temporary-owned comparisons under strict Clippy.
replace_once(
    path,
    '''        let owner_dispatch = intelligence.map(|binding| NativeOwnerDispatchBinding {
            run_id: binding.run_id.clone(),
            pre_dispatch_revision: binding.expected_revision,
            dispatch_digest: request_receipt.request_digest.to_string(),
        });''',
    '''        let dispatch_digest = request_receipt.request_digest.to_string();
        let owner_dispatch = intelligence.map(|binding| NativeOwnerDispatchBinding {
            run_id: binding.run_id.clone(),
            pre_dispatch_revision: binding.expected_revision,
            dispatch_digest: dispatch_digest.clone(),
        });''',
)
replace_count(path, "                owner_context_digest,\n", "                owner_context_digest: owner_context_digest.clone(),\n", 2)
replace_once(
    path,
    '''                    request_receipt.request_digest.to_string(),
                )''',
    '''                    dispatch_digest.clone(),
                )''',
)
replace_once(
    path,
    '''                || dispatched.dispatch_digest.as_deref()
                    != Some(request_receipt.request_digest.to_string().as_str())''',
    '''                || dispatched.dispatch_digest.as_deref() != Some(dispatch_digest.as_str())''',
)

# Do not re-mark during abort. The owner transition itself resolves whether the
# unknown mark committed, using the immutable predecessor revision and digest.
replace_once(
    path,
    '''    let reason: String = reason.chars().take(512).collect();
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
    }''',
    '''    let reason: String = reason.chars().take(512).collect();
    let prepared = control.prepare_native_abort_before_effect(token, reason.clone())?;
    if let Some(binding) = intelligence {
        let dispatch_digest = dispatch_digest.to_string();
        let aborted = owner
            .run_abort_before_effect(
                binding.run_id.clone(),
                binding.expected_revision,
                dispatch_digest.clone(),
                reason,
            )
            .await?;
        if aborted.phase != AgentRunPhase::Cancelled
            || aborted.dispatch_digest.as_deref() != Some(dispatch_digest.as_str())
        {
            return Err("Agentd did not acknowledge the exact pre-effect abort".into());
        }
    }''',
)
replace_once(
    path,
    '''            let dispatched = owner
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
                )''',
    '''            let aborted = owner
                .run_abort_before_effect(
                    binding.run_id.clone(),
                    binding.pre_dispatch_revision,
                    binding.dispatch_digest.clone(),
                    reason,
                )''',
)

# Strengthen tests for both possible states after an unknown dispatch ACK.
replace_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs",
    '''    assert_eq!(
        coordinator.abort_before_effect("run.1", dispatch.revision, &digest('b'), "denied"),
        Err(AgentRunError::InvalidTransition)
    );
    let aborted = coordinator
        .abort_before_effect("run.1", dispatch.revision, &digest('a'), "denied")''',
    '''    assert_eq!(
        coordinator.abort_before_effect("run.1", 2, &digest('b'), "denied"),
        Err(AgentRunError::Conflict)
    );
    let aborted = coordinator
        .abort_before_effect("run.1", 2, &digest('a'), "denied")''',
)
replace_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs",
    '''        .abort_before_effect("run.1", dispatch.revision, &digest('a'), "denied")
        .expect("repeat abort");
    assert!(repeated_abort.idempotent);
}''',
    '''        .abort_before_effect("run.1", 2, &digest('a'), "denied")
        .expect("repeat abort");
    assert!(repeated_abort.idempotent);

    let mut before_ack = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    before_ack.start_run(100, snapshot()).expect("start");
    before_ack.attach_context(200, 1, attachment()).expect("attach");
    let direct = before_ack
        .abort_before_effect("run.1", 2, &digest('c'), "dispatch_ack_unknown")
        .expect("abort context-attached predecessor");
    assert_eq!(direct.phase, RunPhase::Cancelled);
    assert_eq!(direct.dispatch_digest, Some(digest('c')));
}''',
)

# Infer-core has no tempfile dependency; use the existing unique path helper.
replace_once(
    "codex-rs/hepta-infer-core/src/native_control_tests.rs",
    '''    let temp = tempfile::tempdir().unwrap();
    let journal = temp.path().join("native-abort-pending.journal");''',
    '''    let journal = path("abort-pending");''',
)
replace_once(
    "codex-rs/hepta-infer-core/src/native_control_tests.rs",
    '''                dispatch_digest: digest("owner-dispatch"),''',
    '''                dispatch_digest: "d".repeat(64),''',
)
replace_once(
    "codex-rs/hepta-infer-core/src/native_control_tests.rs",
    '''    assert!(!released.pre_effect_abort_pending);
}

#[test]
fn pending_abort_forbids_start_cancel_and_observation() {
    let temp = tempfile::tempdir().unwrap();
    let journal = temp.path().join("native-abort-fence.journal");''',
    '''    assert!(!released.pre_effect_abort_pending);
    drop(reopened);
    std::fs::remove_file(journal).unwrap();
}

#[test]
fn pending_abort_forbids_start_cancel_and_observation() {
    let journal = path("abort-fence");''',
)
replace_once(
    "codex-rs/hepta-infer-core/src/native_control_tests.rs",
    '''    assert_eq!(control.cancel_native("r-fenced"), Err(Error::InvalidTransition));
}
''',
    '''    assert_eq!(control.cancel_native("r-fenced"), Err(Error::InvalidTransition));
    drop(control);
    std::fs::remove_file(journal).unwrap();
}
''',
)

print("runtime.codex P0 reconciliation fixes applied")
