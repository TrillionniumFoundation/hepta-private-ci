#!/usr/bin/env python3
"""Apply runtime.codex product-caller convergence after phase 1.

This migration is idempotent and fails closed on source drift. It wires the
nonce-bound Agentd transition into the real App Server caller and makes
AbortPending recovery non-sendable.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, value: str) -> None:
    (ROOT / path).write_text(value, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one anchor, found {count}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


def regex_once(path: str, pattern: str, replacement: str) -> None:
    text = read(path)
    if replacement in text:
        return
    next_text, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"{path}: regex anchor did not match once: {pattern[:100]!r}")
    write(path, next_text)


def append_once(path: str, marker: str, addition: str) -> None:
    text = read(path)
    if marker in text:
        return
    write(path, text.rstrip() + "\n" + addition)


def run_phase1() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/runtime-codex-converge.py")],
        cwd=ROOT,
        check=True,
    )


def patch_native_run_control() -> None:
    path = "codex-rs/hepta-infer-worker-host/src/native_run_control.rs"
    replace_once(
        path,
        "use codex_hepta_infer_core::durable_control::native::NativeRequest;\n",
        "use codex_hepta_infer_core::durable_control::native::NativeRequest;\n"
        "use codex_hepta_infer_core::durable_control::native::NativeRunRecord;\n",
    )
    replace_once(
        path,
        "use codex_hepta_infer_core::durable_control::native::NativeReservationState;\n",
        "use codex_hepta_infer_core::durable_control::native::NativeReservationState;\n"
        "use codex_hepta_agentd::AgentRunPhase;\n"
        "use codex_hepta_agentd::AgentdClient;\n",
    )
    replace_once(
        path,
        '''        if record.state != NativeReservationState::Reserved {
            if let Some(output) = record
''',
        '''        if record.state == NativeReservationState::AbortPending {
            self.reconcile_pre_effect_abort(control, &record).await?;
            return Err("request was durably aborted before the provider effect boundary".into());
        }
        if record.state != NativeReservationState::Reserved {
            if let Some(output) = record
''',
    )
    replace_once(
        path,
        '''    }
}

fn native_source_payload_digest(
''',
        r'''    }

    /// Complete an AbortPending saga before any generic App Server recovery.
    /// This path can only close the exact stored proof; it cannot thread/read,
    /// enter a final-use token, or send a new turn/start.
    async fn reconcile_pre_effect_abort(
        &self,
        control: &mut DurableInferenceControl,
        record: &NativeRunRecord,
    ) -> Result<()> {
        let abort = record
            .pre_effect_abort
            .as_ref()
            .ok_or("AbortPending record omitted its exact owner proof")?;
        let owner = AgentdClient::new(
            self.config.agentd_socket.clone(),
            self.config.agent_id.clone(),
            self.config.generation,
        )?;
        let receipt = match owner
            .run_abort_before_effect(
                abort.owner_run_id.clone(),
                abort.owner_dispatch_revision,
                abort.dispatch_binding_digest.clone(),
                abort.abort_nonce_hex.clone(),
                abort.proof_digest.clone(),
                abort.reason.clone(),
            )
            .await
        {
            Ok(receipt) => receipt,
            Err(error) => owner
                .run_status(abort.owner_run_id.clone())
                .await?
                .ok_or_else(|| {
                    format!(
                        "Agentd abort acknowledgement unknown and run disappeared: {error}"
                    )
                })?,
        };
        if receipt.phase != AgentRunPhase::AbortedBeforeEffect
            || receipt.terminal_observed
            || receipt.dispatch_binding_digest.as_deref()
                != Some(abort.dispatch_binding_digest.as_str())
            || receipt.pre_effect_abort_commitment_digest.as_deref()
                != Some(abort.commitment_digest.as_str())
            || receipt.pre_effect_abort_proof_digest.as_deref()
                != Some(abort.proof_digest.as_str())
            || receipt.cancel_reason.as_deref() != Some(abort.reason.as_str())
        {
            return Err("Agentd pre-effect abort reconciliation conflicted".into());
        }
        control.confirm_native_abort_before_effect(
            &record.request.request_id,
            &abort.proof_digest,
        )?;
        Ok(())
    }
}

fn native_source_payload_digest(
''',
    )


def patch_native_app_server() -> None:
    path = "codex-rs/hepta-infer-worker-host/src/native_app_server.rs"
    replace_once(
        path,
        "use codex_hepta_infer_core::durable_control::native::NativeDispatchRejectionStatus;\n",
        "use codex_hepta_infer_core::durable_control::native::NativeDispatchRejectionStatus;\n"
        "use codex_hepta_infer_core::durable_control::native::NativePreEffectAbortRecord;\n"
        "use codex_hepta_infer_core::durable_control::native::NativePreEffectAbortToken;\n",
    )
    replace_once(
        path,
        '''        let request_receipt = adapt_request(adapted_at_ms, adapter_intent.clone())?;
        let authority_binding = final_use_binding(
''',
        '''        let request_receipt = adapt_request(adapted_at_ms, adapter_intent.clone())?;
        let dispatch_binding_digest = request_receipt.request_digest.to_string();
        let authority_binding = final_use_binding(
''',
    )
    replace_once(
        path,
        '''        let (_, pre_effect_abort) = control.dispatch_native_with_pre_effect_abort(
''',
        '''        let (_, pre_effect_abort_token) = control.dispatch_native_with_pre_effect_abort(
''',
    )
    regex_once(
        path,
        r'''        if let Some\(binding\) = intelligence \{\n            let dispatched = match owner.*?            intelligence_revision = Some\(dispatched\.revision\);\n        \}\n''',
        r'''        let mut prepared_effect = PreparedEffectEntry {
            token: pre_effect_abort_token,
            dispatch_binding_digest: dispatch_binding_digest.clone(),
            owner_dispatch_revision: None,
        };
        if let Some(binding) = intelligence {
            let commitment = prepared_effect
                .token
                .commitment_digest(&binding.run_id, &dispatch_binding_digest)?;
            let dispatched = match owner
                .run_mark_dispatched_bound(
                    binding.run_id.clone(),
                    binding.expected_revision,
                    dispatch_binding_digest.clone(),
                    commitment.clone(),
                )
                .await
            {
                Ok(receipt) => receipt,
                Err(error) => {
                    let status = owner.run_status(binding.run_id.clone()).await;
                    match status {
                        Ok(Some(receipt))
                            if owner_dispatch_matches(
                                &receipt,
                                binding,
                                self.config.generation,
                                &dispatch_binding_digest,
                                &commitment,
                            ) =>
                        {
                            receipt
                        }
                        Ok(Some(receipt))
                            if receipt.phase == AgentRunPhase::ContextAttached
                                && receipt.revision == binding.expected_revision =>
                        {
                            let reason = format!(
                                "Agentd rejected bound dispatch before state change: {error}"
                            );
                            control.abort_native_before_effect(
                                prepared_effect.token,
                                reason.clone(),
                            )?;
                            cleanup_pre_effect_thread(
                                &mut client,
                                &started.thread.id,
                            )
                            .await;
                            return Err(reason.into());
                        }
                        _ => {
                            // The owner may have committed the exact dispatch,
                            // but no authenticated acknowledgement is available.
                            // Drop the live-only token and leave the local slot
                            // reconcile-only; never send or claim definitely unsent.
                            cleanup_pre_effect_thread(
                                &mut client,
                                &started.thread.id,
                            )
                            .await;
                            return Err(format!(
                                "Agentd bound dispatch acknowledgement unknown; operation held without replay: {error}"
                            )
                            .into());
                        }
                    }
                }
            };
            if !owner_dispatch_matches(
                &dispatched,
                binding,
                self.config.generation,
                &dispatch_binding_digest,
                &commitment,
            ) {
                let reason =
                    "Agentd did not commit this exact bound intelligence dispatch".to_string();
                prepared_effect
                    .abort(
                        control,
                        &owner,
                        intelligence,
                        Some(dispatched.revision),
                        reason.clone(),
                    )
                    .await?;
                cleanup_pre_effect_thread(&mut client, &started.thread.id).await;
                return Err(reason.into());
            }
            prepared_effect.owner_dispatch_revision = Some(dispatched.revision);
            intelligence_revision = Some(dispatched.revision);
        }
''',
    )

    # Common post-owner failure branches become the two-phase abort saga.
    text = read(path)
    text = text.replace(
        '''                control.abort_native_before_effect(pre_effect_abort, reason.clone())?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(reason.into());
''',
        '''                prepared_effect
                    .abort(
                        control,
                        &owner,
                        intelligence,
                        prepared_effect.owner_dispatch_revision,
                        reason.clone(),
                    )
                    .await?;
                cleanup_pre_effect_thread(&mut client, &started.thread.id).await;
                return Err(reason.into());
''',
    )
    text = text.replace(
        '''            control.abort_native_before_effect(pre_effect_abort, reason.clone())?;
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err(reason.into());
''',
        '''            prepared_effect
                .abort(
                    control,
                    &owner,
                    intelligence,
                    prepared_effect.owner_dispatch_revision,
                    reason.clone(),
                )
                .await?;
            cleanup_pre_effect_thread(&mut client, &started.thread.id).await;
            return Err(reason.into());
''',
    )
    text = text.replace(
        '''                    let stopped = control.abort_native_before_effect(pre_effect_abort, reason);
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                    stopped?;
                    return Err(error.into());
''',
        '''                    prepared_effect
                        .abort(
                            control,
                            &owner,
                            intelligence,
                            prepared_effect.owner_dispatch_revision,
                            reason,
                        )
                        .await?;
                    cleanup_pre_effect_thread(&mut client, &started.thread.id).await;
                    return Err(error.into());
''',
    )
    text = text.replace(
        '''                let stopped = control.abort_native_before_effect(
                    pre_effect_abort,
                    "cognitive final-use revalidation returned a mismatched receipt".to_string(),
                );
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                stopped?;
''',
        '''                prepared_effect
                    .abort(
                        control,
                        &owner,
                        intelligence,
                        prepared_effect.owner_dispatch_revision,
                        "cognitive final-use revalidation returned a mismatched receipt".to_string(),
                    )
                    .await?;
                cleanup_pre_effect_thread(&mut client, &started.thread.id).await;
''',
    )
    text = text.replace(
        '''            let stopped = control.abort_native_before_effect(
                pre_effect_abort,
                "cancelled before model dispatch".to_string(),
            );
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            stopped?;
''',
        '''            prepared_effect
                .abort(
                    control,
                    &owner,
                    intelligence,
                    prepared_effect.owner_dispatch_revision,
                    "cancelled before model dispatch".to_string(),
                )
                .await?;
            cleanup_pre_effect_thread(&mut client, &started.thread.id).await;
''',
    )
    text = text.replace(
        '''                control.abort_native_before_effect(pre_effect_abort, reason.clone())?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(reason.into());
''',
        '''                prepared_effect
                    .abort(
                        control,
                        &owner,
                        intelligence,
                        prepared_effect.owner_dispatch_revision,
                        reason.clone(),
                    )
                    .await?;
                cleanup_pre_effect_thread(&mut client, &started.thread.id).await;
                return Err(reason.into());
''',
    )
    text = text.replace(
        '''        // From here on, a missing acknowledgement is reconcile-only. Recovery
        // cannot recreate the local pre-effect proof that is deliberately lost.
        drop(pre_effect_abort);
''',
        '''        // Typestate transition: only an EnteredEffect can reach the physical
        // App Server request. Consuming PreparedEffectEntry destroys the abort path.
        let entered_effect = prepared_effect.enter(entered_use);
        // From here on, a missing acknowledgement is reconcile-only.
''',
    )
    text = text.replace(
        "send_authorized_turn_start(&mut client, entered_use, turn_params)",
        "send_authorized_turn_start(&mut client, entered_effect, turn_params)",
    )
    if "pre_effect_abort" in text and "pre_effect_abort_token" not in text:
        raise RuntimeError("native_app_server: unexpected stale pre-effect token spelling")
    write(path, text)

    replace_once(
        path,
        '''async fn send_authorized_turn_start(
    client: &mut RemoteAppServerClient,
    _entered: EnteredUseToken,
    params: TurnStartParams,
''',
        '''async fn send_authorized_turn_start(
    client: &mut RemoteAppServerClient,
    _entered: EnteredEffect,
    params: TurnStartParams,
''',
    )
    replace_once(
        path,
        '''fn final_use_binding(
''',
        r'''struct PreparedEffectEntry {
    token: NativePreEffectAbortToken,
    dispatch_binding_digest: String,
    owner_dispatch_revision: Option<u64>,
}

struct EnteredEffect {
    _token: EnteredUseToken,
}

impl PreparedEffectEntry {
    async fn abort(
        self,
        control: &mut DurableInferenceControl,
        owner: &AgentdClient,
        intelligence: Option<&NativeIntelligenceRunBinding>,
        owner_dispatch_revision: Option<u64>,
        reason: String,
    ) -> Result<()> {
        let Some(binding) = intelligence else {
            control.abort_native_before_effect(self.token, reason)?;
            return Ok(());
        };
        let owner_dispatch_revision = owner_dispatch_revision
            .ok_or("bound pre-effect abort omitted the Agentd dispatch revision")?;
        let pending = control.prepare_native_abort_before_effect(
            self.token,
            binding.run_id.clone(),
            owner_dispatch_revision,
            self.dispatch_binding_digest.clone(),
            reason,
        )?;
        let abort = pending
            .pre_effect_abort
            .as_ref()
            .ok_or("durable AbortPending transition omitted its proof")?
            .clone();
        let receipt = reconcile_owner_abort(owner, &abort).await?;
        if !owner_abort_matches(&receipt, &abort) {
            return Err("Agentd accepted a mismatched pre-effect abort".into());
        }
        control.confirm_native_abort_before_effect(
            &pending.request.request_id,
            &abort.proof_digest,
        )?;
        Ok(())
    }

    fn enter(self, entered: EnteredUseToken) -> EnteredEffect {
        drop(self.token);
        EnteredEffect { _token: entered }
    }
}

async fn reconcile_owner_abort(
    owner: &AgentdClient,
    abort: &NativePreEffectAbortRecord,
) -> Result<codex_hepta_agentd::AgentRunReceipt> {
    match owner
        .run_abort_before_effect(
            abort.owner_run_id.clone(),
            abort.owner_dispatch_revision,
            abort.dispatch_binding_digest.clone(),
            abort.abort_nonce_hex.clone(),
            abort.proof_digest.clone(),
            abort.reason.clone(),
        )
        .await
    {
        Ok(receipt) => Ok(receipt),
        Err(first_error) => {
            if let Some(receipt) = owner.run_status(abort.owner_run_id.clone()).await?
                && owner_abort_matches(&receipt, abort)
            {
                return Ok(receipt);
            }
            owner
                .run_abort_before_effect(
                    abort.owner_run_id.clone(),
                    abort.owner_dispatch_revision,
                    abort.dispatch_binding_digest.clone(),
                    abort.abort_nonce_hex.clone(),
                    abort.proof_digest.clone(),
                    abort.reason.clone(),
                )
                .await
                .map_err(|retry_error| {
                    format!(
                        "Agentd pre-effect abort acknowledgement unresolved: {first_error}; retry: {retry_error}"
                    )
                    .into()
                })
        }
    }
}

fn owner_dispatch_matches(
    receipt: &codex_hepta_agentd::AgentRunReceipt,
    binding: &NativeIntelligenceRunBinding,
    generation: u64,
    dispatch_binding_digest: &str,
    commitment: &str,
) -> bool {
    receipt.phase == AgentRunPhase::Dispatched
        && receipt.generation == generation
        && !receipt.terminal_observed
        && receipt.context_digest.as_deref() == Some(binding.context_digest.as_str())
        && receipt.compilation_receipt_digest.as_deref()
            == Some(binding.envelope_digest.as_str())
        && receipt.dispatch_binding_digest.as_deref() == Some(dispatch_binding_digest)
        && receipt.pre_effect_abort_commitment_digest.as_deref() == Some(commitment)
        && receipt.pre_effect_abort_proof_digest.is_none()
}

fn owner_abort_matches(
    receipt: &codex_hepta_agentd::AgentRunReceipt,
    abort: &NativePreEffectAbortRecord,
) -> bool {
    receipt.phase == AgentRunPhase::AbortedBeforeEffect
        && !receipt.terminal_observed
        && receipt.dispatch_binding_digest.as_deref()
            == Some(abort.dispatch_binding_digest.as_str())
        && receipt.pre_effect_abort_commitment_digest.as_deref()
            == Some(abort.commitment_digest.as_str())
        && receipt.pre_effect_abort_proof_digest.as_deref()
            == Some(abort.proof_digest.as_str())
        && receipt.cancel_reason.as_deref() == Some(abort.reason.as_str())
}

async fn cleanup_pre_effect_thread(
    client: &mut RemoteAppServerClient,
    thread_id: &str,
) {
    let _ = timeout(
        RPC_TIMEOUT,
        client.request(ClientRequest::ThreadUnsubscribe {
            request_id: RequestId::Integer(90),
            params: ThreadUnsubscribeParams {
                thread_id: thread_id.to_string(),
            },
        }),
    )
    .await;
    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
}

fn final_use_binding(
''',
    )

    # Explicitly clean up the already-created ephemeral thread on early
    # model/cancellation/handoff failures that precede durable dispatch.
    replace_once(
        path,
        '''        if started.model != self.config.model {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("provider substituted the requested model".into());
        }
''',
        '''        if started.model != self.config.model {
            cleanup_pre_effect_thread(&mut client, &started.thread.id).await;
            return Err("provider substituted the requested model".into());
        }
''',
    )
    replace_once(
        path,
        '''        if cancellation.is_cancelled() {
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err("cancelled before model dispatch".into());
        }
        if let Some(binding) = intelligence {
''',
        '''        if cancellation.is_cancelled() {
            cleanup_pre_effect_thread(&mut client, &started.thread.id).await;
            return Err("cancelled before model dispatch".into());
        }
        if let Some(binding) = intelligence {
''',
    )
    replace_once(
        path,
        '''            if Some(current_revision) != intelligence_revision {
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err("intelligence handoff revision changed before dispatch".into());
            }
''',
        '''            if Some(current_revision) != intelligence_revision {
                cleanup_pre_effect_thread(&mut client, &started.thread.id).await;
                return Err("intelligence handoff revision changed before dispatch".into());
            }
''',
    )


def patch_source_order_test() -> None:
    path = "codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs"
    append_once(
        path,
        "fn bound_abort_saga_precedes_effect_entry_and_recovery_never_sends()",
        r'''

#[test]
fn bound_abort_saga_precedes_effect_entry_and_recovery_never_sends() {
    let source = include_str!("native_app_server.rs");
    let local_dispatch = source
        .find("dispatch_native_with_pre_effect_abort(")
        .expect("local durable dispatch");
    let owner_mark = source
        .find("run_mark_dispatched_bound(")
        .expect("bound owner dispatch");
    let abort_prepare = source
        .find("prepare_native_abort_before_effect(")
        .expect("durable AbortPending");
    let owner_abort = source
        .find("run_abort_before_effect(")
        .expect("owner abort");
    let abort_confirm = source
        .find("confirm_native_abort_before_effect(")
        .expect("local abort confirmation");
    let effect_entry = source
        .find("verified_use.enter(&authority_binding)")
        .expect("final-use entry");
    let physical_send = source
        .find("send_authorized_turn_start(&mut client, entered_effect")
        .expect("typed physical send");
    assert!(local_dispatch < owner_mark);
    assert!(owner_mark < effect_entry);
    assert!(abort_prepare < effect_entry);
    assert!(owner_abort < effect_entry);
    assert!(abort_confirm < effect_entry);
    assert!(effect_entry < physical_send);

    let recovery = include_str!("native_run_control.rs");
    let abort_branch = recovery
        .find("record.state == NativeReservationState::AbortPending")
        .expect("AbortPending recovery branch");
    let generic_reconcile = recovery
        .find("self.reconcile_existing(&record, &prompt)")
        .expect("generic App Server recovery");
    assert!(abort_branch < generic_reconcile);
}
''',
    )


def main() -> None:
    run_phase1()
    patch_native_run_control()
    patch_native_app_server()
    patch_source_order_test()


if __name__ == "__main__":
    main()
