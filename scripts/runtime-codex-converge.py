#!/usr/bin/env python3
'''One-shot, idempotent runtime.codex convergence source migration.

This script is intentionally branch-scoped. It applies the cross-owner
pre-effect-abort protocol and its durable local two-phase journal changes.
It fails closed if an expected source anchor drifts.
'''

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one source anchor, found {count}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


def regex_once(path: str, pattern: str, replacement: str) -> None:
    text = read(path)
    if replacement in text:
        return
    next_text, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"{path}: regex anchor did not match exactly once: {pattern[:120]!r}")
    write(path, next_text)


def append_once(path: str, marker: str, addition: str) -> None:
    text = read(path)
    if marker in text:
        return
    if not text.endswith("\n"):
        text += "\n"
    write(path, text + addition)


def patch_lane_runtime() -> None:
    path = "codex-rs/hepta-agentd/src/lane_b_runtime.rs"
    replace_once(
        path,
        "use codex_hepta_learning_ledger::RunStartRecordV1;\n",
        "use codex_hepta_learning_ledger::RunStartRecordV1;\n"
        "use codex_hepta_types::Digest32;\n",
    )
    replace_once(
        path,
        '''    pub dispatch_binding_digest: Option<String>,
    /// Durable proof identity accepted by Agentd for a definitely-unsent
    /// dispatch. This is deliberately not a provider terminal observation.
    pub pre_effect_abort_proof_digest: Option<String>,
''',
        '''    pub dispatch_binding_digest: Option<String>,
    /// Commitment to the live worker's non-serializable abort nonce. Agentd
    /// records it at the same transition that records Dispatched.
    pub pre_effect_abort_commitment_digest: Option<String>,
    /// Durable proof identity accepted by Agentd for a definitely-unsent
    /// dispatch. This is deliberately not a provider terminal observation.
    pub pre_effect_abort_proof_digest: Option<String>,
''',
    )
    replace_once(
        path,
        '''    dispatch_binding_digest: Option<String>,
    pre_effect_abort_proof_digest: Option<String>,
''',
        '''    dispatch_binding_digest: Option<String>,
    pre_effect_abort_commitment_digest: Option<String>,
    pre_effect_abort_proof_digest: Option<String>,
''',
    )
    text = read(path)
    text = text.replace(
        "            dispatch_binding_digest: None,\n            pre_effect_abort_proof_digest: None,\n",
        "            dispatch_binding_digest: None,\n"
        "            pre_effect_abort_commitment_digest: None,\n"
        "            pre_effect_abort_proof_digest: None,\n",
    )
    write(path, text)

    regex_once(
        path,
        r'''    /// Legacy dispatch transition\..*?    pub fn cancel_run\(''',
        '''    /// Legacy dispatch transition. It remains for compatibility, but because it
    /// carries no exact external binding it cannot later prove a pre-effect
    /// abort across the owner boundary.
    pub fn mark_dispatched(
        &mut self,
        now_ms: u64,
        run_id: &str,
        expected_revision: u64,
    ) -> Result<RunReceipt, AgentRunError> {
        self.mark_dispatched_inner(now_ms, run_id, expected_revision, None, None)
    }

    /// Commit the exact runtime.codex dispatch identity and the live worker's
    /// nonce commitment at the Agentd owner.
    pub fn mark_dispatched_bound(
        &mut self,
        now_ms: u64,
        run_id: &str,
        expected_revision: u64,
        dispatch_binding_digest: String,
        pre_effect_abort_commitment_digest: String,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_digest(&dispatch_binding_digest, "dispatch binding")?;
        validate_digest(
            &pre_effect_abort_commitment_digest,
            "pre-effect abort commitment",
        )?;
        self.mark_dispatched_inner(
            now_ms,
            run_id,
            expected_revision,
            Some(dispatch_binding_digest),
            Some(pre_effect_abort_commitment_digest),
        )
    }

    fn mark_dispatched_inner(
        &mut self,
        now_ms: u64,
        run_id: &str,
        expected_revision: u64,
        dispatch_binding_digest: Option<String>,
        pre_effect_abort_commitment_digest: Option<String>,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_identity(run_id, "run")?;
        if dispatch_binding_digest.is_some() != pre_effect_abort_commitment_digest.is_some() {
            return Err(AgentRunError::InvalidTransition);
        }
        let record = self
            .runs
            .get_mut(run_id)
            .ok_or(AgentRunError::RunNotFound)?;
        if record.phase == RunPhase::Dispatched {
            return if record.dispatch_binding_digest == dispatch_binding_digest
                && record.pre_effect_abort_commitment_digest
                    == pre_effect_abort_commitment_digest
            {
                Ok(receipt(record, /*idempotent*/ true))
            } else {
                Err(AgentRunError::Conflict)
            };
        }
        require_revision(record, expected_revision)?;
        require_live_deadline(record, now_ms)?;
        if record.phase == RunPhase::Indeterminate {
            return Err(AgentRunError::InvalidTransition);
        }
        if record.phase != RunPhase::ContextAttached {
            return Err(AgentRunError::ContextRequired);
        }
        record.dispatch_binding_digest = dispatch_binding_digest;
        record.pre_effect_abort_commitment_digest = pre_effect_abort_commitment_digest;
        record.phase = RunPhase::Dispatched;
        advance_revision(record)?;
        Ok(receipt(record, /*idempotent*/ false))
    }

    /// Close a bound dispatch as definitely unsent without inventing a
    /// provider terminal observation. The nonce opens the commitment stored by
    /// mark_dispatched_bound, and the proof additionally binds the reason.
    pub fn abort_before_effect(
        &mut self,
        run_id: &str,
        expected_revision: u64,
        dispatch_binding_digest: &str,
        abort_nonce_hex: &str,
        proof_digest: &str,
        reason: &str,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_identity(run_id, "run")?;
        validate_digest(dispatch_binding_digest, "dispatch binding")?;
        validate_digest(proof_digest, "pre-effect abort proof")?;
        validate_cancel_reason(reason)?;
        let nonce = decode_abort_nonce_hex(abort_nonce_hex)?;
        let expected_commitment =
            pre_effect_abort_commitment(run_id, dispatch_binding_digest, &nonce);
        let expected_proof =
            pre_effect_abort_proof(run_id, dispatch_binding_digest, &nonce, reason);
        if expected_proof != proof_digest {
            return Err(AgentRunError::Conflict);
        }

        let record = self
            .runs
            .get_mut(run_id)
            .ok_or(AgentRunError::RunNotFound)?;
        if record.phase == RunPhase::AbortedBeforeEffect {
            let same = record.dispatch_binding_digest.as_deref() == Some(dispatch_binding_digest)
                && record.pre_effect_abort_commitment_digest.as_deref()
                    == Some(expected_commitment.as_str())
                && record.pre_effect_abort_proof_digest.as_deref() == Some(proof_digest)
                && record.cancel_reason.as_deref() == Some(reason);
            return if same {
                Ok(receipt(record, /*idempotent*/ true))
            } else {
                Err(AgentRunError::Conflict)
            };
        }
        require_revision(record, expected_revision)?;
        if record.phase != RunPhase::Dispatched {
            return Err(AgentRunError::InvalidTransition);
        }
        if record.dispatch_binding_digest.as_deref() != Some(dispatch_binding_digest)
            || record.pre_effect_abort_commitment_digest.as_deref()
                != Some(expected_commitment.as_str())
        {
            return Err(AgentRunError::Conflict);
        }
        record.phase = RunPhase::AbortedBeforeEffect;
        record.pre_effect_abort_proof_digest = Some(proof_digest.to_string());
        record.cancel_reason = Some(reason.to_string());
        record.cancel_ack_deadline_ms = None;
        advance_revision(record)?;
        Ok(receipt(record, /*idempotent*/ false))
    }

    pub fn cancel_run(''',
    )
    replace_once(
        path,
        '''        dispatch_binding_digest: record.dispatch_binding_digest.clone(),
        pre_effect_abort_proof_digest: record.pre_effect_abort_proof_digest.clone(),
''',
        '''        dispatch_binding_digest: record.dispatch_binding_digest.clone(),
        pre_effect_abort_commitment_digest: record
            .pre_effect_abort_commitment_digest
            .clone(),
        pre_effect_abort_proof_digest: record.pre_effect_abort_proof_digest.clone(),
''',
    )
    replace_once(
        path,
        '''#[cfg(test)]
#[path = "lane_b_runtime_tests.rs"]
mod tests;
''',
        '''const PRE_EFFECT_ABORT_COMMITMENT_DOMAIN: &[u8] =
    b"hepta.runtime.codex.pre-effect-abort.commitment.v1";
const PRE_EFFECT_ABORT_PROOF_DOMAIN: &[u8] =
    b"hepta.runtime.codex.pre-effect-abort.proof.v1";

fn pre_effect_abort_commitment(
    run_id: &str,
    dispatch_binding_digest: &str,
    nonce: &[u8; 32],
) -> String {
    framed_abort_digest(
        PRE_EFFECT_ABORT_COMMITMENT_DOMAIN,
        run_id,
        dispatch_binding_digest,
        nonce,
        None,
    )
}

fn pre_effect_abort_proof(
    run_id: &str,
    dispatch_binding_digest: &str,
    nonce: &[u8; 32],
    reason: &str,
) -> String {
    framed_abort_digest(
        PRE_EFFECT_ABORT_PROOF_DOMAIN,
        run_id,
        dispatch_binding_digest,
        nonce,
        Some(reason),
    )
}

fn framed_abort_digest(
    domain: &[u8],
    run_id: &str,
    dispatch_binding_digest: &str,
    nonce: &[u8; 32],
    reason: Option<&str>,
) -> String {
    let mut bytes = Vec::new();
    push_abort_part(&mut bytes, domain);
    push_abort_part(&mut bytes, run_id.as_bytes());
    push_abort_part(&mut bytes, dispatch_binding_digest.as_bytes());
    push_abort_part(&mut bytes, nonce);
    if let Some(reason) = reason {
        push_abort_part(&mut bytes, reason.as_bytes());
    }
    Digest32::of_bytes(&bytes).to_string()
}

fn push_abort_part(output: &mut Vec<u8>, value: &[u8]) {
    let length = u64::try_from(value.len()).expect("bounded runtime.codex abort field");
    output.extend_from_slice(&length.to_be_bytes());
    output.extend_from_slice(value);
}

fn decode_abort_nonce_hex(value: &str) -> Result<[u8; 32], AgentRunError> {
    if value.len() != 64 {
        return Err(AgentRunError::InvalidDigest("pre-effect abort nonce"));
    }
    let mut nonce = [0_u8; 32];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        let high = abort_hex_nibble(pair[0])
            .ok_or(AgentRunError::InvalidDigest("pre-effect abort nonce"))?;
        let low = abort_hex_nibble(pair[1])
            .ok_or(AgentRunError::InvalidDigest("pre-effect abort nonce"))?;
        nonce[index] = (high << 4) | low;
    }
    Ok(nonce)
}

fn abort_hex_nibble(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        _ => None,
    }
}

#[cfg(test)]
#[path = "lane_b_runtime_tests.rs"]
mod tests;
''',
    )


def patch_lane_tests() -> None:
    path = "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs"
    append_once(
        path,
        "fn bound_pre_effect_abort_is_nonce_verified_and_nonterminal()",
        r'''
#[test]
fn bound_pre_effect_abort_is_nonce_verified_and_nonterminal() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    coordinator.start_run(100, snapshot()).expect("admit");
    coordinator
        .attach_context(200, 1, attachment())
        .expect("attach");

    let binding = digest('a');
    let nonce = [42_u8; 32];
    let nonce_hex = nonce
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    let commitment = pre_effect_abort_commitment("run.1", &binding, &nonce);
    let reason = "final-use fence changed";
    let proof = pre_effect_abort_proof("run.1", &binding, &nonce, reason);

    let dispatched = coordinator
        .mark_dispatched_bound(
            300,
            "run.1",
            2,
            binding.clone(),
            commitment.clone(),
        )
        .expect("bound dispatch");
    assert_eq!(dispatched.phase, RunPhase::Dispatched);
    assert_eq!(
        dispatched.dispatch_binding_digest.as_deref(),
        Some(binding.as_str())
    );
    assert_eq!(
        dispatched.pre_effect_abort_commitment_digest.as_deref(),
        Some(commitment.as_str())
    );

    assert_eq!(
        coordinator.abort_before_effect(
            "run.1",
            dispatched.revision,
            &binding,
            &"00".repeat(32),
            &proof,
            reason,
        ),
        Err(AgentRunError::Conflict)
    );

    let aborted = coordinator
        .abort_before_effect(
            "run.1",
            dispatched.revision,
            &binding,
            &nonce_hex,
            &proof,
            reason,
        )
        .expect("abort");
    assert_eq!(aborted.phase, RunPhase::AbortedBeforeEffect);
    assert!(!aborted.terminal_observed);
    assert_eq!(
        aborted.pre_effect_abort_proof_digest.as_deref(),
        Some(proof.as_str())
    );
    assert_eq!(coordinator.active_run_count(), 0);
    assert_eq!(coordinator.unresolved_run_count(), 0);

    let repeated = coordinator
        .abort_before_effect(
            "run.1",
            dispatched.revision,
            &binding,
            &nonce_hex,
            &proof,
            reason,
        )
        .expect("idempotent abort");
    assert!(repeated.idempotent);
    assert_eq!(
        coordinator.observe_terminal(
            "run.1",
            aborted.revision,
            RunPhase::Succeeded,
            /*terminal_observed*/ true,
        ),
        Err(AgentRunError::InvalidTransition)
    );
}
''',
    )


def patch_protocol() -> None:
    path = "codex-rs/hepta-agent-protocol/src/lib.rs"
    replace_once(
        path,
        "pub const AGENTD_RUN_LIFECYCLE_CAPABILITY_MINOR: u16 = 1;",
        "pub const AGENTD_RUN_LIFECYCLE_CAPABILITY_MINOR: u16 = 2;",
    )
    replace_once(
        path,
        '''    ContextAttached,
    Dispatched,
    Cancelling,
''',
        '''    ContextAttached,
    Dispatched,
    AbortedBeforeEffect,
    Cancelling,
''',
    )
    replace_once(
        path,
        '''    pub deadline_ms: u64,
    pub cancel_reason: Option<String>,
''',
        '''    pub deadline_ms: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub dispatch_binding_digest: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pre_effect_abort_commitment_digest: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pre_effect_abort_proof_digest: Option<String>,
    pub cancel_reason: Option<String>,
''',
    )
    replace_once(
        path,
        '''    pub fn run_cancel(
        request_id: u64,
''',
        '''    pub fn run_mark_dispatched_bound(
        request_id: u64,
        spawn_generation: u64,
        run_id: String,
        expected_revision: u64,
        dispatch_binding_digest: String,
        pre_effect_abort_commitment_digest: String,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::RunMarkDispatchedBound {
                run_id,
                expected_revision,
                dispatch_binding_digest,
                pre_effect_abort_commitment_digest,
            },
        }
    }

    pub fn run_abort_before_effect(
        request_id: u64,
        spawn_generation: u64,
        run_id: String,
        expected_revision: u64,
        dispatch_binding_digest: String,
        abort_nonce_hex: String,
        proof_digest: String,
        reason: String,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::RunAbortBeforeEffect {
                run_id,
                expected_revision,
                dispatch_binding_digest,
                abort_nonce_hex,
                proof_digest,
                reason,
            },
        }
    }

    pub fn run_cancel(
        request_id: u64,
''',
    )
    replace_once(
        path,
        '''    RunMarkDispatched {
        run_id: String,
        expected_revision: u64,
    },
    RunCancel {
''',
        '''    RunMarkDispatched {
        run_id: String,
        expected_revision: u64,
    },
    RunMarkDispatchedBound {
        run_id: String,
        expected_revision: u64,
        dispatch_binding_digest: String,
        pre_effect_abort_commitment_digest: String,
    },
    RunAbortBeforeEffect {
        run_id: String,
        expected_revision: u64,
        dispatch_binding_digest: String,
        abort_nonce_hex: String,
        proof_digest: String,
        reason: String,
    },
    RunCancel {
''',
    )
    replace_once(
        path,
        '''    #[test]
    fn host_turn_authority_binding_is_strict_and_fail_closed() {
''',
        r'''    #[test]
    fn bound_dispatch_and_pre_effect_abort_wire_are_strict_and_bounded() {
        let binding = "a".repeat(64);
        let commitment = "b".repeat(64);
        let proof = "c".repeat(64);
        let mark = AgentdRequest::run_mark_dispatched_bound(
            17,
            4,
            "run.1".to_string(),
            2,
            binding.clone(),
            commitment,
        );
        let mark_bytes = serde_json::to_vec(&mark).expect("serialize bound mark");
        assert!(mark_bytes.len() as u64 <= MAX_CONTROL_FRAME_BYTES);
        assert_eq!(
            serde_json::from_slice::<AgentdRequest>(&mark_bytes).expect("parse bound mark"),
            mark
        );

        let abort = AgentdRequest::run_abort_before_effect(
            18,
            4,
            "run.1".to_string(),
            3,
            binding,
            "11".repeat(32),
            proof,
            "final-use fence changed".to_string(),
        );
        let abort_bytes = serde_json::to_vec(&abort).expect("serialize pre-effect abort");
        assert!(abort_bytes.len() as u64 <= MAX_CONTROL_FRAME_BYTES);
        assert_eq!(
            serde_json::from_slice::<AgentdRequest>(&abort_bytes)
                .expect("parse pre-effect abort"),
            abort
        );
    }

    #[test]
    fn host_turn_authority_binding_is_strict_and_fail_closed() {
''',
    )


def patch_client() -> None:
    path = "codex-rs/hepta-agentd/src/client.rs"
    replace_once(
        path,
        '''    pub async fn run_cancel(
        &self,
''',
        '''    pub async fn run_mark_dispatched_bound(
        &self,
        run_id: String,
        expected_revision: u64,
        dispatch_binding_digest: String,
        pre_effect_abort_commitment_digest: String,
    ) -> Result<AgentRunReceipt, AgentdError> {
        match self
            .send(AgentdRequest::run_mark_dispatched_bound(
                self.request_id(),
                self.spawn_generation,
                run_id,
                expected_revision,
                dispatch_binding_digest,
                pre_effect_abort_commitment_digest,
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
        dispatch_binding_digest: String,
        abort_nonce_hex: String,
        proof_digest: String,
        reason: String,
    ) -> Result<AgentRunReceipt, AgentdError> {
        match self
            .send(AgentdRequest::run_abort_before_effect(
                self.request_id(),
                self.spawn_generation,
                run_id,
                expected_revision,
                dispatch_binding_digest,
                abort_nonce_hex,
                proof_digest,
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
        &self,
''',
    )


def patch_state_control() -> None:
    path = "codex-rs/hepta-agentd/src/state_control.rs"
    replace_once(
        path,
        '''            crate::AgentdMethod::RunCancel {
                run_id,
''',
        '''            crate::AgentdMethod::RunMarkDispatchedBound {
                run_id,
                expected_revision,
                dispatch_binding_digest,
                pre_effect_abort_commitment_digest,
            } => {
                require_run_admission_ready(lifecycle, app_server_ready, fenced)?;
                let receipt = self
                    .runs
                    .lock()
                    .map_err(poisoned_state)?
                    .mark_dispatched_bound(
                        now_ms()?,
                        &run_id,
                        expected_revision,
                        dispatch_binding_digest,
                        pre_effect_abort_commitment_digest,
                    )
                    .map_err(run_error)?;
                AgentdPayload::RunReceipt(wire_run_receipt(receipt))
            }
            crate::AgentdMethod::RunAbortBeforeEffect {
                run_id,
                expected_revision,
                dispatch_binding_digest,
                abort_nonce_hex,
                proof_digest,
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
                        &dispatch_binding_digest,
                        &abort_nonce_hex,
                        &proof_digest,
                        &reason,
                    )
                    .map_err(run_error)?;
                AgentdPayload::RunReceipt(wire_run_receipt(receipt))
            }
            crate::AgentdMethod::RunCancel {
                run_id,
''',
    )
    replace_once(
        path,
        '''        crate::AgentRunPhase::Dispatched => crate::RunPhase::Dispatched,
        crate::AgentRunPhase::Cancelling => crate::RunPhase::Cancelling,
''',
        '''        crate::AgentRunPhase::Dispatched => crate::RunPhase::Dispatched,
        crate::AgentRunPhase::AbortedBeforeEffect => crate::RunPhase::AbortedBeforeEffect,
        crate::AgentRunPhase::Cancelling => crate::RunPhase::Cancelling,
''',
    )
    replace_once(
        path,
        '''        crate::RunPhase::Dispatched => crate::AgentRunPhase::Dispatched,
        crate::RunPhase::Cancelling => crate::AgentRunPhase::Cancelling,
''',
        '''        crate::RunPhase::Dispatched => crate::AgentRunPhase::Dispatched,
        crate::RunPhase::AbortedBeforeEffect => crate::AgentRunPhase::AbortedBeforeEffect,
        crate::RunPhase::Cancelling => crate::AgentRunPhase::Cancelling,
''',
    )
    replace_once(
        path,
        '''        deadline_ms: value.deadline_ms,
        cancel_reason: value.cancel_reason,
''',
        '''        deadline_ms: value.deadline_ms,
        dispatch_binding_digest: value.dispatch_binding_digest,
        pre_effect_abort_commitment_digest: value.pre_effect_abort_commitment_digest,
        pre_effect_abort_proof_digest: value.pre_effect_abort_proof_digest,
        cancel_reason: value.cancel_reason,
''',
    )


def patch_infer_core() -> None:
    cargo = "codex-rs/hepta-infer-core/Cargo.toml"
    replace_once(
        cargo,
        '''codex-hepta-types = { path = "../hepta-types" }
serde = { workspace = true, features = ["derive"] }
''',
        '''codex-hepta-types = { path = "../hepta-types" }
rand = { workspace = true }
serde = { workspace = true, features = ["derive"] }
''',
    )

    path = "codex-rs/hepta-infer-core/src/native_control.rs"
    replace_once(
        path,
        "use serde::Deserialize;\n",
        "use codex_hepta_types::Digest32;\n"
        "use rand::RngCore;\n"
        "use serde::Deserialize;\n",
    )
    replace_once(
        path,
        '''    Dispatching,
    Running,
''',
        '''    Dispatching,
    AbortPending,
    Running,
''',
    )
    replace_once(
        path,
        '''pub struct NativePreEffectAbortToken {
    request_id: String,
    dispatch_revision: u64,
}
''',
        '''pub struct NativePreEffectAbortToken {
    request_id: String,
    dispatch_revision: u64,
    abort_nonce: [u8; 32],
}
''',
    )
    replace_once(
        path,
        '''#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeDispatchRejectionStatus {
''',
        r'''#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativePreEffectAbortRecord {
    pub owner_run_id: String,
    pub owner_dispatch_revision: u64,
    pub dispatch_binding_digest: String,
    pub commitment_digest: String,
    pub abort_nonce_hex: String,
    pub proof_digest: String,
    pub reason: String,
}

impl NativePreEffectAbortToken {
    pub fn commitment_digest(
        &self,
        owner_run_id: &str,
        dispatch_binding_digest: &str,
    ) -> Result<String, Error> {
        validate_identity(owner_run_id, "native abort owner run")?;
        validate_digest(dispatch_binding_digest, "native abort dispatch binding")?;
        Ok(pre_effect_abort_digest(
            b"hepta.runtime.codex.pre-effect-abort.commitment.v1",
            owner_run_id,
            dispatch_binding_digest,
            &self.abort_nonce,
            None,
        ))
    }

    fn proof_record(
        &self,
        owner_run_id: String,
        owner_dispatch_revision: u64,
        dispatch_binding_digest: String,
        reason: String,
    ) -> Result<NativePreEffectAbortRecord, Error> {
        validate_identity(&owner_run_id, "native abort owner run")?;
        validate_digest(&dispatch_binding_digest, "native abort dispatch binding")?;
        if owner_dispatch_revision == 0
            || reason.trim().is_empty()
            || reason.len() > 512
            || reason.as_bytes().contains(&0)
        {
            return Err(Error::InvalidIdentity("native pre-effect abort"));
        }
        let commitment_digest =
            self.commitment_digest(&owner_run_id, &dispatch_binding_digest)?;
        let proof_digest = pre_effect_abort_digest(
            b"hepta.runtime.codex.pre-effect-abort.proof.v1",
            &owner_run_id,
            &dispatch_binding_digest,
            &self.abort_nonce,
            Some(&reason),
        );
        Ok(NativePreEffectAbortRecord {
            owner_run_id,
            owner_dispatch_revision,
            dispatch_binding_digest,
            commitment_digest,
            abort_nonce_hex: encode_abort_nonce(&self.abort_nonce),
            proof_digest,
            reason,
        })
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeDispatchRejectionStatus {
''',
    )
    replace_once(
        path,
        '''    pub pre_dispatch_stop: Option<String>,
    #[serde(default)]
    pub dispatch_rejection: Option<NativeDispatchRejection>,
''',
        '''    pub pre_dispatch_stop: Option<String>,
    #[serde(default)]
    pub pre_effect_abort: Option<NativePreEffectAbortRecord>,
    #[serde(default)]
    pub dispatch_rejection: Option<NativeDispatchRejection>,
''',
    )
    replace_once(
        path,
        '''    AbortBeforeEffect {
        request_id: String,
        reason: String,
    },
    Observe {
''',
        '''    AbortBeforeEffect {
        request_id: String,
        reason: String,
    },
    PrepareAbortBeforeEffect {
        request_id: String,
        abort: NativePreEffectAbortRecord,
    },
    ConfirmAbortBeforeEffect {
        request_id: String,
        proof_digest: String,
    },
    Observe {
''',
    )
    replace_once(
        path,
        '''        Ok((
            record.clone(),
            NativePreEffectAbortToken {
                request_id: request_id.to_string(),
                dispatch_revision: record.revision,
            },
        ))
''',
        '''        let mut abort_nonce = [0_u8; 32];
        rand::rng().fill_bytes(&mut abort_nonce);
        Ok((
            record.clone(),
            NativePreEffectAbortToken {
                request_id: request_id.to_string(),
                dispatch_revision: record.revision,
                abort_nonce,
            },
        ))
''',
    )
    replace_once(
        path,
        '''    pub fn native_started(
        &mut self,
''',
        r'''    /// Durably commit that this process will not cross the external effect
    /// boundary, while retaining the slot until Agentd acknowledges the same
    /// exact abort proof. Recovery can replay this owner reconciliation safely.
    pub fn prepare_native_abort_before_effect(
        &mut self,
        token: NativePreEffectAbortToken,
        owner_run_id: String,
        owner_dispatch_revision: u64,
        dispatch_binding_digest: String,
        reason: String,
    ) -> Result<NativeRunRecord, Error> {
        let record = self
            .native
            .records
            .get(&token.request_id)
            .ok_or(Error::RequestNotFound)?;
        if record.state != NativeReservationState::Dispatching
            || record.revision != token.dispatch_revision
            || record.turn_id.is_some()
            || record.observation.is_some()
            || record.dispatch_rejection.is_some()
            || record.cancel_requested
            || record.pre_effect_abort.is_some()
        {
            return Err(Error::InvalidTransition);
        }
        let abort = token.proof_record(
            owner_run_id,
            owner_dispatch_revision,
            dispatch_binding_digest,
            reason,
        )?;
        self.commit_native(
            &token.request_id,
            Event::PrepareAbortBeforeEffect {
                request_id: token.request_id.clone(),
                abort,
            },
        )
    }

    pub fn confirm_native_abort_before_effect(
        &mut self,
        request_id: &str,
        proof_digest: &str,
    ) -> Result<NativeRunRecord, Error> {
        validate_digest(proof_digest, "native pre-effect abort proof")?;
        self.commit_native(
            request_id,
            Event::ConfirmAbortBeforeEffect {
                request_id: request_id.to_string(),
                proof_digest: proof_digest.to_string(),
            },
        )
    }

    pub fn native_started(
        &mut self,
''',
    )
    replace_once(
        path,
        '''                    pre_dispatch_stop: None,
                    dispatch_rejection: None,
''',
        '''                    pre_dispatch_stop: None,
                    pre_effect_abort: None,
                    dispatch_rejection: None,
''',
    )
    replace_once(
        path,
        '''            | Event::AbortBeforeEffect { request_id, .. }
            | Event::Observe { request_id, .. } => request_id,
''',
        '''            | Event::AbortBeforeEffect { request_id, .. }
            | Event::PrepareAbortBeforeEffect { request_id, .. }
            | Event::ConfirmAbortBeforeEffect { request_id, .. }
            | Event::Observe { request_id, .. } => request_id,
''',
    )
    replace_once(
        path,
        '''            Event::Observe { output, .. } => {
                if record.dispatch_rejection.is_some() {
                    return Err(Error::InvalidTransition);
                }
                apply_observation(record, output)?;
            }
''',
        r'''            Event::PrepareAbortBeforeEffect { abort, .. } => {
                if record.state != NativeReservationState::Dispatching
                    || record.turn_id.is_some()
                    || record.observation.is_some()
                    || record.dispatch_rejection.is_some()
                    || record.cancel_requested
                    || record.pre_effect_abort.is_some()
                {
                    return Err(Error::InvalidTransition);
                }
                validate_identity(&abort.owner_run_id, "native abort owner run")?;
                validate_digest(
                    &abort.dispatch_binding_digest,
                    "native abort dispatch binding",
                )?;
                validate_digest(&abort.commitment_digest, "native abort commitment")?;
                validate_digest(&abort.proof_digest, "native abort proof")?;
                if abort.owner_dispatch_revision == 0
                    || abort.abort_nonce_hex.len() != 64
                    || !abort
                        .abort_nonce_hex
                        .bytes()
                        .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
                    || abort.reason.trim().is_empty()
                    || abort.reason.len() > 512
                    || abort.reason.as_bytes().contains(&0)
                {
                    return Err(Error::InvalidIdentity("native pre-effect abort"));
                }
                let nonce = decode_abort_nonce(&abort.abort_nonce_hex)?;
                if pre_effect_abort_digest(
                    b"hepta.runtime.codex.pre-effect-abort.commitment.v1",
                    &abort.owner_run_id,
                    &abort.dispatch_binding_digest,
                    &nonce,
                    None,
                ) != abort.commitment_digest
                    || pre_effect_abort_digest(
                        b"hepta.runtime.codex.pre-effect-abort.proof.v1",
                        &abort.owner_run_id,
                        &abort.dispatch_binding_digest,
                        &nonce,
                        Some(&abort.reason),
                    ) != abort.proof_digest
                {
                    return Err(Error::Conflict);
                }
                record.pre_effect_abort = Some(abort);
                record.state = NativeReservationState::AbortPending;
            }
            Event::ConfirmAbortBeforeEffect { proof_digest, .. } => {
                if record.state != NativeReservationState::AbortPending
                    || record
                        .pre_effect_abort
                        .as_ref()
                        .is_none_or(|abort| abort.proof_digest != proof_digest)
                    || record.turn_id.is_some()
                    || record.observation.is_some()
                {
                    return Err(Error::InvalidTransition);
                }
                record.pre_dispatch_stop = record
                    .pre_effect_abort
                    .as_ref()
                    .map(|abort| abort.reason.clone());
                record.state = NativeReservationState::Released;
            }
            Event::Observe { output, .. } => {
                if record.dispatch_rejection.is_some() || record.pre_effect_abort.is_some() {
                    return Err(Error::InvalidTransition);
                }
                apply_observation(record, output)?;
            }
''',
    )
    replace_once(
        path,
        '''                    || record.dispatch_rejection.is_some()
                    || record.cancel_requested
                    || reason.is_empty()
                    || reason.len() > 4096
''',
        '''                    || record.dispatch_rejection.is_some()
                    || record.cancel_requested
                    || record.pre_effect_abort.is_some()
                    || reason.is_empty()
                    || reason.len() > 4096
''',
    )
    replace_once(
        path,
        '''fn apply_observation(
    record: &mut NativeRunRecord,
''',
        r'''fn pre_effect_abort_digest(
    domain: &[u8],
    owner_run_id: &str,
    dispatch_binding_digest: &str,
    nonce: &[u8; 32],
    reason: Option<&str>,
) -> String {
    let mut bytes = Vec::new();
    push_abort_part(&mut bytes, domain);
    push_abort_part(&mut bytes, owner_run_id.as_bytes());
    push_abort_part(&mut bytes, dispatch_binding_digest.as_bytes());
    push_abort_part(&mut bytes, nonce);
    if let Some(reason) = reason {
        push_abort_part(&mut bytes, reason.as_bytes());
    }
    Digest32::of_bytes(&bytes).to_string()
}

fn push_abort_part(output: &mut Vec<u8>, value: &[u8]) {
    let length = u64::try_from(value.len()).expect("bounded native abort part");
    output.extend_from_slice(&length.to_be_bytes());
    output.extend_from_slice(value);
}

fn encode_abort_nonce(nonce: &[u8; 32]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(64);
    for byte in nonce {
        output.push(char::from(HEX[usize::from(byte >> 4)]));
        output.push(char::from(HEX[usize::from(byte & 0x0f)]));
    }
    output
}

fn decode_abort_nonce(value: &str) -> Result<[u8; 32], Error> {
    if value.len() != 64 {
        return Err(Error::InvalidIdentity("native abort nonce"));
    }
    let mut nonce = [0_u8; 32];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        let high = abort_hex_nibble(pair[0])
            .ok_or(Error::InvalidIdentity("native abort nonce"))?;
        let low = abort_hex_nibble(pair[1])
            .ok_or(Error::InvalidIdentity("native abort nonce"))?;
        nonce[index] = (high << 4) | low;
    }
    Ok(nonce)
}

fn abort_hex_nibble(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        _ => None,
    }
}

fn apply_observation(
    record: &mut NativeRunRecord,
''',
    )


def patch_infer_core_tests() -> None:
    path = "codex-rs/hepta-infer-core/src/native_control_tests.rs"
    append_once(
        path,
        "fn two_phase_pre_effect_abort_survives_reopen_and_holds_capacity_until_owner_ack()",
        r'''
#[test]
fn two_phase_pre_effect_abort_survives_reopen_and_holds_capacity_until_owner_ack() {
    let path = path("abort-saga");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native(request("r1"), 1).unwrap();
    let (_, token) = control
        .dispatch_native_with_pre_effect_abort("r1", dispatch())
        .unwrap();
    let binding = "7".repeat(64);
    let commitment = token
        .commitment_digest("run.1", &binding)
        .expect("commitment");
    let pending = control
        .prepare_native_abort_before_effect(
            token,
            "run.1".to_string(),
            3,
            binding.clone(),
            "final-use fence changed".to_string(),
        )
        .expect("prepare abort");
    assert_eq!(pending.state, NativeReservationState::AbortPending);
    let abort = pending.pre_effect_abort.as_ref().expect("abort record");
    assert_eq!(abort.commitment_digest, commitment);
    assert_eq!(
        control.reserve_native(request("r2"), 1),
        Err(Error::CapacityExceeded)
    );
    let proof = abort.proof_digest.clone();

    drop(control);
    let mut reopened = DurableInferenceControl::open(&path, 8).unwrap();
    let recovered = reopened.native_record("r1").cloned().expect("recovered");
    assert_eq!(recovered, pending);
    assert_eq!(recovered.state, NativeReservationState::AbortPending);
    let confirmed = reopened
        .confirm_native_abort_before_effect("r1", &proof)
        .expect("confirm owner abort");
    assert_eq!(confirmed.state, NativeReservationState::Released);
    assert_eq!(
        confirmed.pre_dispatch_stop.as_deref(),
        Some("final-use fence changed")
    );
    assert_eq!(confirmed.observation, None);
    reopened.reserve_native(request("r2"), 1).unwrap();
    drop(reopened);
    std::fs::remove_file(path).unwrap();
}
''',
    )


def main() -> None:
    patch_lane_runtime()
    patch_lane_tests()
    patch_protocol()
    patch_client()
    patch_state_control()
    patch_infer_core()
    patch_infer_core_tests()


if __name__ == "__main__":
    main()
