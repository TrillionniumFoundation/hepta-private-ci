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
# runtime.codex critical effect typestate. Owner and local abort are committed
# in that order. Owner effect-entry consumes the same permit before the first
# App Server effectful await.
# ---------------------------------------------------------------------------
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "use codex_hepta_infer_core::durable_control::native::NativeDispatchRejectionStatus;\n",
    "use codex_hepta_infer_core::durable_control::native::NativeDispatchRejectionStatus;\nuse codex_hepta_infer_core::durable_control::native::NativePreEffectAbortToken;\n",
)
insert_before(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "impl AppServerModelDriver {\n",
    r'''#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum RuntimeCodexEffectStage {
    DurablePrepared,
    OwnerDispatched,
    EffectEntered,
    Aborted,
}

/// Process-local typestate for the final effect boundary. The abort token and
/// its nonce never enter durable state. Agentd stores only the opaque digest.
struct RuntimeCodexPreEffect {
    abort_token: Option<NativePreEffectAbortToken>,
    abort_digest: String,
    intelligence: Option<NativeIntelligenceRunBinding>,
    intelligence_revision: Option<u64>,
    stage: RuntimeCodexEffectStage,
}

impl RuntimeCodexPreEffect {
    fn new(
        abort_token: NativePreEffectAbortToken,
        abort_digest: String,
        intelligence: Option<NativeIntelligenceRunBinding>,
        intelligence_revision: Option<u64>,
    ) -> Self {
        Self {
            abort_token: Some(abort_token),
            abort_digest,
            intelligence,
            intelligence_revision,
            stage: RuntimeCodexEffectStage::DurablePrepared,
        }
    }

    fn intelligence_revision(&self) -> Option<u64> {
        self.intelligence_revision
    }

    async fn commit_owner_dispatch(
        &mut self,
        owner: &AgentdClient,
        generation: u64,
    ) -> Result<()> {
        if let Some(binding) = self.intelligence.as_ref() {
            let dispatched = owner
                .run_mark_dispatched_with_abort(
                    binding.run_id.clone(),
                    binding.expected_revision,
                    self.abort_digest.clone(),
                )
                .await
                .map_err(|error| {
                    format!(
                        "Agentd dispatch acknowledgement unknown before physical send: {error}"
                    )
                })?;
            if dispatched.phase != AgentRunPhase::Dispatched
                || dispatched.idempotent
                || dispatched.generation != generation
                || dispatched.terminal_observed
                || dispatched.context_digest.as_deref() != Some(binding.context_digest.as_str())
                || dispatched.compilation_receipt_digest.as_deref()
                    != Some(binding.envelope_digest.as_str())
            {
                return Err("Agentd did not newly commit this exact intelligence dispatch".into());
            }
            self.intelligence_revision = Some(dispatched.revision);
        }
        self.stage = RuntimeCodexEffectStage::OwnerDispatched;
        Ok(())
    }

    async fn abort_before_effect(
        &mut self,
        owner: &AgentdClient,
        control: &mut DurableInferenceControl,
        request_id: &str,
        reason: String,
        generation: u64,
    ) -> Result<()> {
        if self.stage == RuntimeCodexEffectStage::EffectEntered {
            return Err("runtime.codex effect entry already consumed the abort permit".into());
        }
        if let Some(binding) = self.intelligence.as_ref() {
            let revision = self
                .intelligence_revision
                .ok_or("missing Agentd dispatch revision for pre-effect abort")?;
            let receipt = owner
                .run_abort_before_effect(
                    binding.run_id.clone(),
                    revision,
                    self.abort_digest.clone(),
                    reason.clone(),
                )
                .await?;
            if receipt.phase != AgentRunPhase::Cancelled
                || receipt.generation != generation
                || !receipt.terminal_observed
                || receipt.context_digest.as_deref() != Some(binding.context_digest.as_str())
                || receipt.compilation_receipt_digest.as_deref()
                    != Some(binding.envelope_digest.as_str())
            {
                return Err("Agentd returned a mismatched pre-effect abort receipt".into());
            }
            self.intelligence_revision = Some(receipt.revision);
        }
        let token = self
            .abort_token
            .take()
            .ok_or("runtime.codex pre-effect abort token was already consumed")?;
        control.abort_native_before_effect(token, reason)?;
        self.stage = RuntimeCodexEffectStage::Aborted;
        Ok(())
    }

    async fn enter_effect(&mut self, owner: &AgentdClient, generation: u64) -> Result<()> {
        if let Some(binding) = self.intelligence.as_ref() {
            let revision = self
                .intelligence_revision
                .ok_or("missing Agentd dispatch revision for effect entry")?;
            let receipt = owner
                .run_enter_effect(
                    binding.run_id.clone(),
                    revision,
                    self.abort_digest.clone(),
                )
                .await?;
            if receipt.phase != AgentRunPhase::Dispatched
                || receipt.idempotent
                || receipt.generation != generation
                || receipt.terminal_observed
                || receipt.context_digest.as_deref() != Some(binding.context_digest.as_str())
                || receipt.compilation_receipt_digest.as_deref()
                    != Some(binding.envelope_digest.as_str())
            {
                return Err("Agentd did not newly commit this exact effect entry".into());
            }
            self.intelligence_revision = Some(receipt.revision);
        }
        drop(
            self.abort_token
                .take()
                .ok_or("runtime.codex pre-effect token was already consumed")?,
        );
        self.stage = RuntimeCodexEffectStage::EffectEntered;
        Ok(())
    }
}

''',
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "        let (_, pre_effect_abort) = control.dispatch_native_with_pre_effect_abort(\n",
    "        let (prepared_dispatch, pre_effect_abort) = control.dispatch_native_with_pre_effect_abort(\n",
)
old_owner_block = r'''
        if let Some(binding) = intelligence {
            let dispatched = match owner
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
                    control.abort_native_before_effect(pre_effect_abort, reason.clone())?;
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                    return Err(reason.into());
                }
            };
            // Idempotent acknowledgement is reconciliation, not a second
            // physical-send permit. A competing worker must not redispatch.
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
                control.abort_native_before_effect(pre_effect_abort, reason.clone())?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(reason.into());
            }
            intelligence_revision = Some(dispatched.revision);
        }
'''
new_owner_block = r'''
        let abort_binding = serde_json::to_vec(&(
            "hepta.runtime.codex.pre-effect-abort.v1",
            request_id,
            prepared_dispatch.revision,
            request_receipt.request_digest.to_string(),
            payload_digest.to_string(),
            authority_witness.as_str(),
            intelligence.map(|binding| {
                (
                    binding.run_id.as_str(),
                    binding.expected_revision,
                    binding.context_digest.as_str(),
                    binding.envelope_digest.as_str(),
                )
            }),
        ))?;
        let pre_effect_abort_digest =
            Digest32::from_array(pre_effect_abort.witness_sha256(&abort_binding)).to_string();
        let mut pre_effect = RuntimeCodexPreEffect::new(
            pre_effect_abort,
            pre_effect_abort_digest,
            intelligence.cloned(),
            intelligence_revision,
        );
        if let Err(error) = pre_effect
            .commit_owner_dispatch(&owner, self.config.generation)
            .await
        {
            let reason: String = error.to_string().chars().take(1024).collect();
            // An unknown owner acknowledgement is not a local proof of absence.
            // Keep the durable slot and reconcile; never send or locally release.
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err(reason.into());
        }
        intelligence_revision = pre_effect.intelligence_revision();
'''
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    old_owner_block,
    new_owner_block,
)

replacements = [
(
'''                control.abort_native_before_effect(pre_effect_abort, reason.clone())?;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Err(reason.into());''',
'''                let stopped = pre_effect
                    .abort_before_effect(
                        &owner,
                        control,
                        request_id,
                        reason.clone(),
                        self.config.generation,
                    )
                    .await;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                stopped?;
                return Err(reason.into());'''
),
(
'''            control.abort_native_before_effect(pre_effect_abort, reason.clone())?;
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            return Err(reason.into());''',
'''            let stopped = pre_effect
                .abort_before_effect(
                    &owner,
                    control,
                    request_id,
                    reason.clone(),
                    self.config.generation,
                )
                .await;
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            stopped?;
            return Err(reason.into());'''
),
(
'''                    let stopped = control.abort_native_before_effect(pre_effect_abort, reason);
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                    stopped?;
                    return Err(error.into());''',
'''                    let stopped = pre_effect
                        .abort_before_effect(
                            &owner,
                            control,
                            request_id,
                            reason,
                            self.config.generation,
                        )
                        .await;
                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                    stopped?;
                    return Err(error.into());'''
),
(
'''                let stopped = control.abort_native_before_effect(
                    pre_effect_abort,
                    "cognitive final-use revalidation returned a mismatched receipt".to_string(),
                );
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                stopped?;''',
'''                let stopped = pre_effect
                    .abort_before_effect(
                        &owner,
                        control,
                        request_id,
                        "cognitive final-use revalidation returned a mismatched receipt"
                            .to_string(),
                        self.config.generation,
                    )
                    .await;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                stopped?;'''
),
(
'''            let stopped = control.abort_native_before_effect(
                pre_effect_abort,
                "cancelled before model dispatch".to_string(),
            );
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            stopped?;''',
'''            let stopped = pre_effect
                .abort_before_effect(
                    &owner,
                    control,
                    request_id,
                    "cancelled before model dispatch".to_string(),
                    self.config.generation,
                )
                .await;
            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
            stopped?;'''
),
]
path = "codex-rs/hepta-infer-worker-host/src/native_app_server.rs"
text = read(path)
for old, new in replacements:
    count = text.count(old)
    if count < 1:
        raise RuntimeError(f"native_app_server missing abort replacement: {old[:80]!r}")
    text = text.replace(old, new)
write(path, text)

text = read(path)
raw = "control.abort_native_before_effect(pre_effect_abort"
if raw in text:
    raise RuntimeError("native_app_server still contains a raw pre_effect_abort call")

replace_once(
    path,
    "        // From here on, a missing acknowledgement is reconcile-only. Recovery\n        // cannot recreate the local pre-effect proof that is deliberately lost.\n        drop(pre_effect_abort);\n        let response = timeout(\n",
    "        if let Err(error) = pre_effect\n            .enter_effect(&owner, self.config.generation)\n            .await\n        {\n            let reason = format!(\n                \"Agentd effect-entry acknowledgement unknown; turn/start was not sent: {error}\"\n            );\n            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;\n            return Err(reason.into());\n        }\n        intelligence_revision = pre_effect.intelligence_revision();\n        // From here on, a missing acknowledgement is reconcile-only. Both the\n        // process-local and Agentd pre-effect permits have been consumed.\n        let response = timeout(\n",
)
append_once(
    path,
    "runtime_codex_crash_matrix_tests",
    "\n#[cfg(test)]\n#[path = \"runtime_codex_crash_matrix_tests.rs\"]\nmod runtime_codex_crash_matrix_tests;\n",
)
write(
    "codex-rs/hepta-infer-worker-host/src/runtime_codex_crash_matrix_tests.rs",
    r'''use super::*;

#[test]
fn critical_effect_order_is_durable_owner_fenced_and_single_entry() {
    let source = include_str!("native_app_server.rs");
    let durable = source
        .find("dispatch_native_with_pre_effect_abort")
        .expect("durable dispatch");
    let owner_dispatch = source
        .find("commit_owner_dispatch(&owner")
        .expect("owner dispatch");
    let final_fence = source
        .find("validate_post_authority_fence(")
        .expect("final fence");
    let authority_entry = source
        .find("verified_use.enter(&authority_binding)")
        .expect("authority entry");
    let owner_entry = source
        .find(".enter_effect(&owner")
        .expect("owner effect entry");
    let physical_send = source
        .find("send_authorized_turn_start(&mut client")
        .expect("physical send");
    assert!(durable < owner_dispatch);
    assert!(owner_dispatch < final_fence);
    assert!(final_fence < authority_entry);
    assert!(authority_entry < owner_entry);
    assert!(owner_entry < physical_send);
    assert_eq!(
        source.matches("control.abort_native_before_effect(").count(),
        1,
        "all local aborts must be centralized in RuntimeCodexPreEffect",
    );
}

#[test]
fn crash_matrix_never_classifies_post_entry_or_unknown_owner_ack_as_unsent() {
    #[derive(Clone, Copy)]
    enum CrashPoint {
        BeforeDurablePrepare,
        AfterDurablePrepare,
        AfterOwnerDispatch,
        AfterFinalFence,
        AfterAuthorityEntry,
        AfterOwnerEffectEntry,
        AfterSocketWrite,
        AfterStartAck,
    }

    for point in [
        CrashPoint::BeforeDurablePrepare,
        CrashPoint::AfterDurablePrepare,
        CrashPoint::AfterOwnerDispatch,
        CrashPoint::AfterFinalFence,
        CrashPoint::AfterAuthorityEntry,
        CrashPoint::AfterOwnerEffectEntry,
        CrashPoint::AfterSocketWrite,
        CrashPoint::AfterStartAck,
    ] {
        let proven_absent_after_crash = matches!(point, CrashPoint::BeforeDurablePrepare);
        let held_reconcile_only = matches!(
            point,
            CrashPoint::AfterDurablePrepare
                | CrashPoint::AfterOwnerDispatch
                | CrashPoint::AfterFinalFence
                | CrashPoint::AfterAuthorityEntry
                | CrashPoint::AfterOwnerEffectEntry
                | CrashPoint::AfterSocketWrite
                | CrashPoint::AfterStartAck
        );
        assert_ne!(proven_absent_after_crash, held_reconcile_only);
    }
}
''',
)
