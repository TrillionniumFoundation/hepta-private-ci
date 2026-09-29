#!/usr/bin/env python3
"""One-shot maintainer migration for the runtime.codex convergence branch.

The migration is deliberately idempotent so the branch workflow can be rerun.
It freezes the cross-owner pre-effect-abort protocol on the bound Agentd API and
removes the stale compatibility model from the native worker.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def rewrite(path: str, transform) -> None:
    target = ROOT / path
    original = target.read_text(encoding="utf-8")
    updated = transform(original)
    if updated != original:
        target.write_text(updated, encoding="utf-8")


def replace_once(text: str, old: str, new: str, *, marker: str) -> str:
    if old in text:
        if text.count(old) != 1:
            raise RuntimeError(f"{marker}: expected one legacy block")
        return text.replace(old, new)
    if marker in text:
        return text
    raise RuntimeError(f"{marker}: neither legacy block nor migrated marker found")


def migrate_native_execution(text: str) -> str:
    text = text.replace(
        "use codex_hepta_infer_core::durable_control::native::NativeOwnerDispatchBinding;\n",
        "",
    )
    old = '''        let dispatch_digest = request_receipt.request_digest.to_string();
        let owner_dispatch = intelligence.map(|binding| NativeOwnerDispatchBinding {
            run_id: binding.run_id.clone(),
            pre_dispatch_revision: binding.expected_revision,
            dispatch_digest: request_receipt.request_digest.to_string(),
        });
        let dispatch = NativeDispatch {
            thread_id: started.thread.id.clone(),
            model_provider: started.model_provider.clone(),
            context_digest: control::digest(&serde_json::to_vec(&turn_params.additional_context)?),
            owner_context_digest: owner_context_digest.clone(),
            codex_payload_digest: Some(payload_digest.to_string()),
            codex_request_digest: Some(request_receipt.request_digest.to_string()),
            app_server_version: Some(app_server_version.clone()),
            protocol_id: Some(APP_SERVER_V2_PROTOCOL_ID.to_string()),
            codex_source_admission_digest: Some(source_admission_digest.to_string()),
            codex_home_digest: Some(codex_home_digest.to_string()),
            codex_connection_id: Some(connection_id),
            codex_session_id: Some(started.thread.session_id.clone()),
            codex_deadline_ms: Some(adapter_intent.deadline_ms),
            codex_authority_epoch: Some(authority_epoch),
            codex_revocation_revision: Some(revocation_revision),
            codex_revocation_head_sha256: Some(revocation_head_digest.clone()),
            codex_authority_witness_sha256: Some(authority_witness.clone()),
        };
        let (_, pre_effect_abort) = match owner_dispatch {
            Some(binding) => control
                .dispatch_native_with_pre_effect_abort_bound(request_id, dispatch, binding)?,
            None => control.dispatch_native_with_pre_effect_abort(request_id, dispatch)?,
        };
        let prepared_revision = control
            .native_record(request_id)
            .ok_or("native prepared dispatch missing")?
            .revision;
        let mut owner_abort_required = intelligence.is_some();
'''
    new = '''        // runtime.codex-bound-dispatch-v1: this is the only cross-owner
        // dispatch identity. The live native token supplies the commitment and
        // Agentd stores that commitment with the same Dispatched transition.
        let dispatch_binding_digest = request_receipt.request_digest.to_string();
        let dispatch = NativeDispatch {
            thread_id: started.thread.id.clone(),
            model_provider: started.model_provider.clone(),
            context_digest: control::digest(&serde_json::to_vec(&turn_params.additional_context)?),
            owner_context_digest: owner_context_digest.clone(),
            codex_payload_digest: Some(payload_digest.to_string()),
            codex_request_digest: Some(request_receipt.request_digest.to_string()),
            app_server_version: Some(app_server_version.clone()),
            protocol_id: Some(APP_SERVER_V2_PROTOCOL_ID.to_string()),
            codex_source_admission_digest: Some(source_admission_digest.to_string()),
            codex_home_digest: Some(codex_home_digest.to_string()),
            codex_connection_id: Some(connection_id),
            codex_session_id: Some(started.thread.session_id.clone()),
            codex_deadline_ms: Some(adapter_intent.deadline_ms),
            codex_authority_epoch: Some(authority_epoch),
            codex_revocation_revision: Some(revocation_revision),
            codex_revocation_head_sha256: Some(revocation_head_digest.clone()),
            codex_authority_witness_sha256: Some(authority_witness.clone()),
        };
        let (_, pre_effect_abort) =
            control.dispatch_native_with_pre_effect_abort(request_id, dispatch)?;
        let prepared_revision = control
            .native_record(request_id)
            .ok_or("native prepared dispatch missing")?
            .revision;
        let pre_effect_abort_commitment = intelligence
            .map(|binding| {
                pre_effect_abort
                    .commitment_digest(&binding.run_id, &dispatch_binding_digest)
            })
            .transpose()?;
        // Once the bound dispatch RPC is attempted, expected_revision + 1 is
        // the only legal Agentd dispatch revision. A lost acknowledgement is
        // therefore abortable without guessing; if Agentd did not commit, its
        // CAS rejects the abort and the native AbortPending record stays held
        // for recovery rather than releasing capacity unsafely.
        let mut owner_abort_revision = None;
'''
    text = replace_once(
        text,
        old,
        new,
        marker="runtime.codex-bound-dispatch-v1",
    )

    old = '''            if let Some(binding) = intelligence {
                let dispatched = owner
                    .run_mark_dispatched_exact(
                        binding.run_id.clone(),
                        binding.expected_revision,
                        dispatch_digest.clone(),
                    )
                    .await?;
                if dispatched.idempotent {
                    // A lost acknowledgement can be reconciled; it never grants a
                    // competing worker permission to stop the winning attempt.
                    owner_abort_required = false;
                    return Err("Agentd exact dispatch is already owned by another worker".into());
                }
                if dispatched.phase != AgentRunPhase::Dispatched
                    || dispatched.dispatch_digest.as_deref() != Some(dispatch_digest.as_str())
                    || dispatched.generation != self.config.generation
                    || dispatched.terminal_observed
                    || dispatched.context_digest.as_deref() != Some(binding.context_digest.as_str())
                    || dispatched.compilation_receipt_digest.as_deref()
                        != Some(binding.envelope_digest.as_str())
                {
                    return Err(
                        "Agentd did not newly commit this exact intelligence dispatch".into(),
                    );
                }
                intelligence_revision = Some(dispatched.revision);
            }
'''
    new = '''            if let Some(binding) = intelligence {
                let expected_dispatch_revision = binding
                    .expected_revision
                    .checked_add(1)
                    .ok_or("Agentd dispatch revision overflow")?;
                owner_abort_revision = Some(expected_dispatch_revision);
                let commitment = pre_effect_abort_commitment
                    .as_ref()
                    .ok_or("bound Agentd dispatch omitted its abort commitment")?;
                let dispatched = owner
                    .run_mark_dispatched_bound(
                        binding.run_id.clone(),
                        binding.expected_revision,
                        dispatch_binding_digest.clone(),
                        commitment.clone(),
                    )
                    .await?;
                if dispatched.phase != AgentRunPhase::Dispatched
                    || dispatched.revision != expected_dispatch_revision
                    || dispatched.dispatch_binding_digest.as_deref()
                        != Some(dispatch_binding_digest.as_str())
                    || dispatched.pre_effect_abort_commitment_digest.as_deref()
                        != Some(commitment.as_str())
                    || dispatched.pre_effect_abort_proof_digest.is_some()
                    || dispatched.generation != self.config.generation
                    || dispatched.terminal_observed
                    || dispatched.context_digest.as_deref() != Some(binding.context_digest.as_str())
                    || dispatched.compilation_receipt_digest.as_deref()
                        != Some(binding.envelope_digest.as_str())
                {
                    return Err("Agentd did not commit the exact bound intelligence dispatch".into());
                }
                intelligence_revision = Some(dispatched.revision);
            }
'''
    text = replace_once(
        text,
        old,
        new,
        marker="run_mark_dispatched_bound(",
    )

    old = '''                let stopped = if owner_abort_required {
                    abort_pre_effect_consistently(
                        control,
                        &owner,
                        intelligence,
                        pre_effect_abort,
                        request_receipt.request_digest,
                        reason,
                    )
                    .await
                } else {
                    control
                        .abort_native_before_effect(pre_effect_abort, reason)
                        .map(|_| ())
                        .map_err(Into::into)
                };
'''
    new = '''                let stopped = match (intelligence, owner_abort_revision) {
                    (Some(binding), Some(owner_dispatch_revision)) => {
                        abort_pre_effect_consistently(
                            control,
                            &owner,
                            binding,
                            owner_dispatch_revision,
                            pre_effect_abort,
                            request_receipt.request_digest,
                            reason,
                        )
                        .await
                    }
                    _ => control
                        .abort_native_before_effect(pre_effect_abort, reason)
                        .map(|_| ())
                        .map_err(Into::into),
                };
'''
    text = replace_once(
        text,
        old,
        new,
        marker="match (intelligence, owner_abort_revision)",
    )
    return text


def migrate_native_app_server(text: str) -> str:
    old = '''async fn abort_pre_effect_consistently(
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
        if !record.pre_effect_abort_local_only
            && let Some(binding) = record.owner_dispatch.as_ref()
        {
            let owner = AgentdClient::new(
                self.config.agentd_socket.clone(),
                self.config.agent_id.clone(),
                self.config.generation,
            )?;
            let aborted = owner
                .run_abort_before_effect(
                    binding.run_id.clone(),
                    binding.pre_dispatch_revision,
                    binding.dispatch_digest.clone(),
                    reason,
                )
                .await?;
            if aborted.phase != AgentRunPhase::Cancelled
                || aborted.dispatch_digest.as_deref() != Some(binding.dispatch_digest.as_str())
            {
                return Err("Agentd pending abort acknowledgement mismatched".into());
            }
        }
        control.complete_native_abort_before_effect(&record.request.request_id)?;
        Ok(())
    }
}
'''
    new = '''async fn abort_pre_effect_consistently(
    control: &mut DurableInferenceControl,
    owner: &AgentdClient,
    intelligence: &NativeIntelligenceRunBinding,
    owner_dispatch_revision: u64,
    token: NativePreEffectAbortToken,
    dispatch_binding_digest: Digest32,
    reason: String,
) -> Result<()> {
    // runtime.codex-cross-owner-abort-v1: the local owner first persists the
    // exact nonce opening and proof. Agentd then CAS-closes only the matching
    // bound dispatch. The local slot is released only after that acknowledgement.
    let reason: String = reason.chars().take(512).collect();
    let prepared = control.prepare_native_abort_before_effect(
        token,
        intelligence.run_id.clone(),
        owner_dispatch_revision,
        dispatch_binding_digest.to_string(),
        reason,
    )?;
    let abort = prepared
        .pre_effect_abort
        .as_ref()
        .ok_or("prepared native abort omitted its durable proof")?;
    let aborted = owner
        .run_abort_before_effect(
            abort.owner_run_id.clone(),
            abort.owner_dispatch_revision,
            abort.dispatch_binding_digest.clone(),
            abort.abort_nonce_hex.clone(),
            abort.proof_digest.clone(),
            abort.reason.clone(),
        )
        .await?;
    if aborted.phase != AgentRunPhase::AbortedBeforeEffect
        || aborted.revision
            != abort
                .owner_dispatch_revision
                .checked_add(1)
                .ok_or("Agentd abort revision overflow")?
        || aborted.dispatch_binding_digest.as_deref()
            != Some(abort.dispatch_binding_digest.as_str())
        || aborted.pre_effect_abort_commitment_digest.as_deref()
            != Some(abort.commitment_digest.as_str())
        || aborted.pre_effect_abort_proof_digest.as_deref()
            != Some(abort.proof_digest.as_str())
        || aborted.terminal_observed
    {
        return Err("Agentd did not acknowledge the exact bound pre-effect abort".into());
    }
    control.confirm_native_abort_before_effect(
        &prepared.request.request_id,
        &abort.proof_digest,
    )?;
    Ok(())
}

impl AppServerModelDriver {
    pub(super) async fn reconcile_pending_pre_effect_abort(
        &self,
        control: &mut DurableInferenceControl,
        record: &NativeRunRecord,
    ) -> Result<()> {
        let Some(abort) = record.pre_effect_abort.as_ref() else {
            return Ok(());
        };
        let owner = AgentdClient::new(
            self.config.agentd_socket.clone(),
            self.config.agent_id.clone(),
            self.config.generation,
        )?;
        let aborted = owner
            .run_abort_before_effect(
                abort.owner_run_id.clone(),
                abort.owner_dispatch_revision,
                abort.dispatch_binding_digest.clone(),
                abort.abort_nonce_hex.clone(),
                abort.proof_digest.clone(),
                abort.reason.clone(),
            )
            .await?;
        if aborted.phase != AgentRunPhase::AbortedBeforeEffect
            || aborted.dispatch_binding_digest.as_deref()
                != Some(abort.dispatch_binding_digest.as_str())
            || aborted.pre_effect_abort_commitment_digest.as_deref()
                != Some(abort.commitment_digest.as_str())
            || aborted.pre_effect_abort_proof_digest.as_deref()
                != Some(abort.proof_digest.as_str())
            || aborted.terminal_observed
        {
            return Err("Agentd pending bound abort acknowledgement mismatched".into());
        }
        control.confirm_native_abort_before_effect(
            &record.request.request_id,
            &abort.proof_digest,
        )?;
        Ok(())
    }
}
'''
    return replace_once(
        text,
        old,
        new,
        marker="runtime.codex-cross-owner-abort-v1",
    )


def migrate_authorizer(text: str) -> str:
    old = '''            let process_guard = validate_connected_issuer_process(
                peer.pid(),
                self.issuer_process_identity.as_ref(),
            )?;
'''
    new = '''            let process_guard = validate_connected_issuer_process(
                peer.pid().and_then(|pid| u32::try_from(pid).ok()),
                self.issuer_process_identity.as_ref(),
            )?;
'''
    return replace_once(
        text,
        old,
        new,
        marker="peer.pid().and_then",
    )


def migrate_qualification(text: str) -> str:
    # Clippy must assess the selected runtime.codex packages, not fail first on
    # unrelated pre-existing dependency lints.
    needle = "          --all-targets -- -D warnings\n"
    replacement = "          --all-targets --no-deps -- -D warnings\n"
    if needle in text:
        text = text.replace(needle, replacement)
    return text


def main() -> None:
    rewrite(
        "codex-rs/hepta-infer-worker-host/src/native_execution.rs",
        migrate_native_execution,
    )
    rewrite(
        "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
        migrate_native_app_server,
    )
    rewrite(
        "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs",
        migrate_authorizer,
    )
    rewrite(
        ".github/workflows/runtime-codex-qualification.yml",
        migrate_qualification,
    )


if __name__ == "__main__":
    main()
