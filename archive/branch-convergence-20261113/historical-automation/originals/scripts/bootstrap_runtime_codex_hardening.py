#!/usr/bin/env python3
"""Apply the runtime.codex exact pre-effect compensation change set.

This file is intentionally temporary.  The branch bootstrap workflow removes it
only after formatting and focused tests pass, so a failed bootstrap remains
inspectable and rerunnable without partially publishing source changes.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, value: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    value = read(path)
    count = value.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement, found {count}: {old[:120]!r}")
    write(path, value.replace(old, new, 1))


def replace_all(path: str, old: str, new: str, expected: int) -> None:
    value = read(path)
    count = value.count(old)
    if count != expected:
        raise RuntimeError(f"{path}: expected {expected} replacements, found {count}: {old[:120]!r}")
    write(path, value.replace(old, new))


# ---------------------------------------------------------------------------
# Durable local proof: generate a one-shot nonce before dispatch, commit only
# its digest with the dispatch, and persist the opening only after the same
# live process durably proves that no effect entry occurred.
# ---------------------------------------------------------------------------
replace_once(
    "codex-rs/hepta-infer-core/Cargo.toml",
    "codex-hepta-types = { path = \"../hepta-types\" }\nserde = { workspace = true, features = [\"derive\"] }\nserde_json = { workspace = true }\n",
    "codex-hepta-types = { path = \"../hepta-types\" }\nrand = { workspace = true }\nserde = { workspace = true, features = [\"derive\"] }\nserde_json = { workspace = true }\nsha2 = { workspace = true }\n",
)

replace_once(
    "codex-rs/hepta-infer-core/src/native_control.rs",
    "use serde::Deserialize;\nuse serde::Serialize;\n",
    "use rand::RngCore;\nuse serde::Deserialize;\nuse serde::Serialize;\nuse sha2::Digest;\nuse sha2::Sha256;\n",
)
replace_once(
    "codex-rs/hepta-infer-core/src/native_control.rs",
    "pub(super) const JOURNAL_PREFIX: &str = \"native-v1|\";\n",
    "pub(super) const JOURNAL_PREFIX: &str = \"native-v1|\";\nconst PRE_EFFECT_ABORT_COMMITMENT_DOMAIN: &[u8] =\n    b\"hepta.runtime.codex.pre-effect-abort.commitment.v1\";\nconst PRE_EFFECT_ABORT_PROOF_DOMAIN: &[u8] =\n    b\"hepta.runtime.codex.pre-effect-abort.proof.v1\";\n",
)
replace_once(
    "codex-rs/hepta-infer-core/src/native_control.rs",
    "    /// Digest of the independently signed final-use grant + exact claim-time\n    /// revocation head witness claimed for this dispatch before physical turn/start.\n    #[serde(default)]\n    pub codex_authority_witness_sha256: Option<String>,\n}\n\n/// In-memory proof that this live process has durably prepared one dispatch but\n",
    "    /// Digest of the independently signed final-use grant + exact claim-time\n    /// revocation head witness claimed for this dispatch before physical turn/start.\n    #[serde(default)]\n    pub codex_authority_witness_sha256: Option<String>,\n    /// Commitment to the non-serializable abort nonce created by the same live\n    /// process that durably publishes this dispatch.  The nonce is disclosed\n    /// only after a local pre-effect abort is durably committed.\n    #[serde(default)]\n    pub pre_effect_abort_commitment_sha256: Option<String>,\n}\n\n#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]\n#[serde(deny_unknown_fields)]\npub struct NativePreEffectAbortBinding {\n    pub effect_request_digest: String,\n    pub native_dispatch_revision: u64,\n    pub local_abort_revision: u64,\n    pub abort_commitment_sha256: String,\n}\n\n#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]\n#[serde(deny_unknown_fields)]\npub struct NativePreEffectAbortProof {\n    pub effect_request_digest: String,\n    pub native_dispatch_revision: u64,\n    pub local_abort_revision: u64,\n    pub nonce: [u8; 32],\n}\n\nimpl NativePreEffectAbortProof {\n    pub fn proof_sha256(&self) -> String {\n        pre_effect_abort_proof_sha256(self)\n    }\n}\n\n/// In-memory proof that this live process has durably prepared one dispatch but\n",
)
replace_once(
    "codex-rs/hepta-infer-core/src/native_control.rs",
    "pub struct NativePreEffectAbortToken {\n    request_id: String,\n    dispatch_revision: u64,\n}\n\nimpl std::fmt::Debug for NativePreEffectAbortToken {\n",
    "pub struct NativePreEffectAbortToken {\n    request_id: String,\n    binding: NativePreEffectAbortBinding,\n    nonce: [u8; 32],\n}\n\nimpl NativePreEffectAbortToken {\n    pub fn binding(&self) -> &NativePreEffectAbortBinding {\n        &self.binding\n    }\n}\n\nimpl std::fmt::Debug for NativePreEffectAbortToken {\n",
)
replace_once(
    "codex-rs/hepta-infer-core/src/native_control.rs",
    "    pub pre_dispatch_stop: Option<String>,\n    #[serde(default)]\n    pub dispatch_rejection: Option<NativeDispatchRejection>,\n",
    "    pub pre_dispatch_stop: Option<String>,\n    /// Opening of the dispatch commitment.  It is absent while a physical send\n    /// is still possible and survives restart only after the local journal has\n    /// durably established a definitely-unsent outcome.\n    #[serde(default)]\n    pub pre_effect_abort_proof: Option<NativePreEffectAbortProof>,\n    #[serde(default)]\n    pub dispatch_rejection: Option<NativeDispatchRejection>,\n",
)
replace_once(
    "codex-rs/hepta-infer-core/src/native_control.rs",
    "    AbortBeforeEffect {\n        request_id: String,\n        reason: String,\n    },\n",
    "    AbortBeforeEffect {\n        request_id: String,\n        reason: String,\n        proof: NativePreEffectAbortProof,\n    },\n",
)
replace_once(
    "codex-rs/hepta-infer-core/src/native_control.rs",
    "    pub fn dispatch_native_with_pre_effect_abort(\n        &mut self,\n        request_id: &str,\n        dispatch: NativeDispatch,\n    ) -> Result<(NativeRunRecord, NativePreEffectAbortToken), Error> {\n        let record = self.dispatch_native(request_id, dispatch)?;\n        Ok((\n            record.clone(),\n            NativePreEffectAbortToken {\n                request_id: request_id.to_string(),\n                dispatch_revision: record.revision,\n            },\n        ))\n    }\n\n    /// Release a prepared dispatch only while the same live process still owns\n    /// the exact one-shot pre-effect proof. If the process died, this proof is\n    /// gone and recovery must reconcile instead of declaring the effect unsent.\n    pub fn abort_native_before_effect(\n        &mut self,\n        token: NativePreEffectAbortToken,\n        reason: String,\n    ) -> Result<NativeRunRecord, Error> {\n        let record = self\n            .native\n            .records\n            .get(&token.request_id)\n            .ok_or(Error::RequestNotFound)?;\n        if record.state != NativeReservationState::Dispatching\n            || record.revision != token.dispatch_revision\n            || record.turn_id.is_some()\n            || record.observation.is_some()\n            || record.dispatch_rejection.is_some()\n            || record.cancel_requested\n        {\n            return Err(Error::InvalidTransition);\n        }\n        self.commit_native(\n            &token.request_id,\n            Event::AbortBeforeEffect {\n                request_id: token.request_id.clone(),\n                reason,\n            },\n        )\n    }\n",
    "    pub fn dispatch_native_with_pre_effect_abort(\n        &mut self,\n        request_id: &str,\n        mut dispatch: NativeDispatch,\n    ) -> Result<(NativeRunRecord, NativePreEffectAbortToken), Error> {\n        let current = self\n            .native\n            .records\n            .get(request_id)\n            .ok_or(Error::RequestNotFound)?;\n        if current.state != NativeReservationState::Reserved {\n            return Err(Error::InvalidTransition);\n        }\n        let native_dispatch_revision = current\n            .revision\n            .checked_add(1)\n            .ok_or(Error::ArithmeticOverflow)?;\n        let local_abort_revision = native_dispatch_revision\n            .checked_add(1)\n            .ok_or(Error::ArithmeticOverflow)?;\n        let effect_request_digest = dispatch\n            .codex_request_digest\n            .clone()\n            .ok_or(Error::InvalidIdentity(\"native pre-effect request digest\"))?;\n        validate_digest(&effect_request_digest, \"native pre-effect request\")?;\n        let mut nonce = [0_u8; 32];\n        rand::rng().fill_bytes(&mut nonce);\n        let abort_commitment_sha256 = pre_effect_abort_commitment_sha256(\n            &effect_request_digest,\n            native_dispatch_revision,\n            local_abort_revision,\n            &nonce,\n        );\n        dispatch.pre_effect_abort_commitment_sha256 = Some(abort_commitment_sha256.clone());\n        let binding = NativePreEffectAbortBinding {\n            effect_request_digest,\n            native_dispatch_revision,\n            local_abort_revision,\n            abort_commitment_sha256,\n        };\n        let record = self.dispatch_native(request_id, dispatch)?;\n        if record.revision != native_dispatch_revision {\n            return Err(Error::Conflict);\n        }\n        Ok((\n            record,\n            NativePreEffectAbortToken {\n                request_id: request_id.to_string(),\n                binding,\n                nonce,\n            },\n        ))\n    }\n\n    /// Release a prepared dispatch only while the same live process still owns\n    /// the exact one-shot pre-effect proof. If the process died, this proof is\n    /// gone and recovery must reconcile instead of declaring the effect unsent.\n    pub fn abort_native_before_effect_with_proof(\n        &mut self,\n        token: NativePreEffectAbortToken,\n        reason: String,\n    ) -> Result<(NativeRunRecord, NativePreEffectAbortProof), Error> {\n        let record = self\n            .native\n            .records\n            .get(&token.request_id)\n            .ok_or(Error::RequestNotFound)?;\n        if record.state != NativeReservationState::Dispatching\n            || record.revision != token.binding.native_dispatch_revision\n            || record.turn_id.is_some()\n            || record.observation.is_some()\n            || record.dispatch_rejection.is_some()\n            || record.cancel_requested\n            || record.pre_effect_abort_proof.is_some()\n        {\n            return Err(Error::InvalidTransition);\n        }\n        let proof = NativePreEffectAbortProof {\n            effect_request_digest: token.binding.effect_request_digest.clone(),\n            native_dispatch_revision: token.binding.native_dispatch_revision,\n            local_abort_revision: token.binding.local_abort_revision,\n            nonce: token.nonce,\n        };\n        let committed = self.commit_native(\n            &token.request_id,\n            Event::AbortBeforeEffect {\n                request_id: token.request_id.clone(),\n                reason,\n                proof: proof.clone(),\n            },\n        )?;\n        if committed.revision != proof.local_abort_revision {\n            return Err(Error::Conflict);\n        }\n        Ok((committed, proof))\n    }\n\n    pub fn abort_native_before_effect(\n        &mut self,\n        token: NativePreEffectAbortToken,\n        reason: String,\n    ) -> Result<NativeRunRecord, Error> {\n        self.abort_native_before_effect_with_proof(token, reason)\n            .map(|(record, _proof)| record)\n    }\n",
)
replace_once(
    "codex-rs/hepta-infer-core/src/native_control.rs",
    "                    pre_dispatch_stop: None,\n                    dispatch_rejection: None,\n",
    "                    pre_dispatch_stop: None,\n                    pre_effect_abort_proof: None,\n                    dispatch_rejection: None,\n",
)
replace_once(
    "codex-rs/hepta-infer-core/src/native_control.rs",
    "                if let Some(digest) = &dispatch.codex_authority_witness_sha256 {\n                    validate_digest(digest, \"native codex authority witness\")?;\n                }\n                record.dispatch = Some(dispatch);\n",
    "                if let Some(digest) = &dispatch.codex_authority_witness_sha256 {\n                    validate_digest(digest, \"native codex authority witness\")?;\n                }\n                if let Some(digest) = &dispatch.pre_effect_abort_commitment_sha256 {\n                    validate_digest(digest, \"native pre-effect abort commitment\")?;\n                    if dispatch.codex_request_digest.is_none() {\n                        return Err(Error::InvalidIdentity(\n                            \"native pre-effect commitment without codex request\",\n                        ));\n                    }\n                }\n                record.dispatch = Some(dispatch);\n",
)
replace_once(
    "codex-rs/hepta-infer-core/src/native_control.rs",
    "            Event::AbortBeforeEffect { reason, .. } => {\n                if record.state != NativeReservationState::Dispatching\n                    || record.turn_id.is_some()\n                    || record.observation.is_some()\n                    || record.dispatch_rejection.is_some()\n                    || record.cancel_requested\n                    || reason.is_empty()\n                    || reason.len() > 4096\n                {\n                    return Err(Error::InvalidTransition);\n                }\n                record.pre_dispatch_stop = Some(reason);\n                record.state = NativeReservationState::Released;\n            }\n            Event::Observe { output, .. } => {\n                if record.dispatch_rejection.is_some() {\n",
    "            Event::AbortBeforeEffect { reason, proof, .. } => {\n                if record.state != NativeReservationState::Dispatching\n                    || record.turn_id.is_some()\n                    || record.observation.is_some()\n                    || record.dispatch_rejection.is_some()\n                    || record.cancel_requested\n                    || record.pre_effect_abort_proof.is_some()\n                    || reason.is_empty()\n                    || reason.len() > 4096\n                {\n                    return Err(Error::InvalidTransition);\n                }\n                validate_pre_effect_abort_proof(record, &proof)?;\n                record.pre_dispatch_stop = Some(reason);\n                record.pre_effect_abort_proof = Some(proof);\n                record.state = NativeReservationState::Released;\n            }\n            Event::Observe { output, .. } => {\n                if record.dispatch_rejection.is_some() || record.pre_effect_abort_proof.is_some() {\n",
)
replace_once(
    "codex-rs/hepta-infer-core/src/native_control.rs",
    "fn apply_observation(\n",
    "fn pre_effect_abort_commitment_sha256(\n    effect_request_digest: &str,\n    native_dispatch_revision: u64,\n    local_abort_revision: u64,\n    nonce: &[u8; 32],\n) -> String {\n    let mut hasher = Sha256::new();\n    hasher.update(PRE_EFFECT_ABORT_COMMITMENT_DOMAIN);\n    hasher.update(effect_request_digest.as_bytes());\n    hasher.update(native_dispatch_revision.to_be_bytes());\n    hasher.update(local_abort_revision.to_be_bytes());\n    hasher.update(nonce);\n    format!(\"{:x}\", hasher.finalize())\n}\n\nfn pre_effect_abort_proof_sha256(proof: &NativePreEffectAbortProof) -> String {\n    let mut hasher = Sha256::new();\n    hasher.update(PRE_EFFECT_ABORT_PROOF_DOMAIN);\n    hasher.update(proof.effect_request_digest.as_bytes());\n    hasher.update(proof.native_dispatch_revision.to_be_bytes());\n    hasher.update(proof.local_abort_revision.to_be_bytes());\n    hasher.update(proof.nonce);\n    format!(\"{:x}\", hasher.finalize())\n}\n\nfn validate_pre_effect_abort_proof(\n    record: &NativeRunRecord,\n    proof: &NativePreEffectAbortProof,\n) -> Result<(), Error> {\n    validate_digest(\n        &proof.effect_request_digest,\n        \"native pre-effect proof request\",\n    )?;\n    let dispatch = record.dispatch.as_ref().ok_or(Error::AssignmentMismatch)?;\n    let expected_request = dispatch\n        .codex_request_digest\n        .as_deref()\n        .ok_or(Error::AssignmentMismatch)?;\n    let expected_commitment = dispatch\n        .pre_effect_abort_commitment_sha256\n        .as_deref()\n        .ok_or(Error::AssignmentMismatch)?;\n    let expected_abort_revision = record\n        .revision\n        .checked_add(1)\n        .ok_or(Error::ArithmeticOverflow)?;\n    if proof.effect_request_digest != expected_request\n        || proof.native_dispatch_revision != record.revision\n        || proof.local_abort_revision != expected_abort_revision\n        || pre_effect_abort_commitment_sha256(\n            &proof.effect_request_digest,\n            proof.native_dispatch_revision,\n            proof.local_abort_revision,\n            &proof.nonce,\n        ) != expected_commitment\n    {\n        return Err(Error::Conflict);\n    }\n    Ok(())\n}\n\nfn apply_observation(\n",
)

# Struct literals outside the proof-producing path explicitly state that they
# do not carry a local proof commitment.
replace_once(
    "codex-rs/hepta-infer-core/src/native_control_tests.rs",
    "        codex_authority_witness_sha256: Some(\"2\".repeat(64)),\n    }\n",
    "        codex_authority_witness_sha256: Some(\"2\".repeat(64)),\n        pre_effect_abort_commitment_sha256: None,\n    }\n",
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs",
    "                codex_authority_witness_sha256: Some(\"f\".repeat(64)),\n            },\n",
    "                codex_authority_witness_sha256: Some(\"f\".repeat(64)),\n                pre_effect_abort_commitment_sha256: None,\n            },\n",
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "                codex_authority_witness_sha256: Some(authority_witness.clone()),\n            },\n",
    "                codex_authority_witness_sha256: Some(authority_witness.clone()),\n                pre_effect_abort_commitment_sha256: None,\n            },\n",
)

# ---------------------------------------------------------------------------
# Wire contract: an exact prepare binding and an exact abort opening.  Ordinary
# cancellation remains deliberately separate and cannot claim definitely-unsent.
# ---------------------------------------------------------------------------
replace_once(
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    "pub const AGENTD_CONTROL_SCHEMA_VERSION: u32 = 2;\n",
    "pub const AGENTD_CONTROL_SCHEMA_VERSION: u32 = 3;\n",
)
replace_once(
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    "pub const AGENTD_RUN_LIFECYCLE_CAPABILITY_MINOR: u16 = 1;\n",
    "pub const AGENTD_RUN_LIFECYCLE_CAPABILITY_MINOR: u16 = 2;\n",
)
replace_once(
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    "#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]\n#[serde(rename_all = \"snake_case\")]\npub enum AgentCancellationDisposition {\n",
    "#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]\n#[serde(deny_unknown_fields)]\npub struct AgentPreEffectBinding {\n    pub effect_request_digest: String,\n    pub native_dispatch_revision: u64,\n    pub local_abort_revision: u64,\n    pub abort_commitment_sha256: String,\n}\n\n#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]\n#[serde(deny_unknown_fields)]\npub struct AgentPreEffectAbortProof {\n    pub effect_request_digest: String,\n    pub native_dispatch_revision: u64,\n    pub local_abort_revision: u64,\n    pub nonce: [u8; 32],\n}\n\n#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]\n#[serde(rename_all = \"snake_case\")]\npub enum AgentCancellationDisposition {\n",
)
replace_once(
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    "    pub terminal_observed: bool,\n    pub idempotent: bool,\n}\n",
    "    pub terminal_observed: bool,\n    #[serde(default, skip_serializing_if = \"Option::is_none\")]\n    pub pre_effect_binding: Option<AgentPreEffectBinding>,\n    #[serde(default, skip_serializing_if = \"Option::is_none\")]\n    pub pre_effect_abort_proof_sha256: Option<String>,\n    #[serde(default)]\n    pub pre_effect_aborted: bool,\n    pub idempotent: bool,\n}\n",
)
replace_once(
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    "    pub fn run_cancel(\n",
    "    pub fn run_mark_effect_prepared(\n        request_id: u64,\n        spawn_generation: u64,\n        run_id: String,\n        expected_revision: u64,\n        binding: AgentPreEffectBinding,\n    ) -> Self {\n        Self {\n            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,\n            request_id,\n            spawn_generation,\n            method: AgentdMethod::RunMarkEffectPrepared {\n                run_id,\n                expected_revision,\n                binding,\n            },\n        }\n    }\n\n    pub fn run_abort_before_effect(\n        request_id: u64,\n        spawn_generation: u64,\n        run_id: String,\n        expected_revision: u64,\n        proof: AgentPreEffectAbortProof,\n        reason: String,\n    ) -> Self {\n        Self {\n            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,\n            request_id,\n            spawn_generation,\n            method: AgentdMethod::RunAbortBeforeEffect {\n                run_id,\n                expected_revision,\n                proof,\n                reason,\n            },\n        }\n    }\n\n    pub fn run_cancel(\n",
)
replace_once(
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    "    RunCancel {\n        run_id: String,\n        expected_revision: u64,\n        reason: String,\n    },\n",
    "    RunMarkEffectPrepared {\n        run_id: String,\n        expected_revision: u64,\n        binding: AgentPreEffectBinding,\n    },\n    RunAbortBeforeEffect {\n        run_id: String,\n        expected_revision: u64,\n        proof: AgentPreEffectAbortProof,\n        reason: String,\n    },\n    RunCancel {\n        run_id: String,\n        expected_revision: u64,\n        reason: String,\n    },\n",
)

# ---------------------------------------------------------------------------
# Agentd owner state: the prepare commitment is frozen at the Dispatched cut;
# only its exact opening may transition directly to Cancelled-before-effect.
# ---------------------------------------------------------------------------
replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    "pub use codex_hepta_agent_protocol::AgentContextAttachment;\n",
    "pub use codex_hepta_agent_protocol::AgentContextAttachment;\npub use codex_hepta_agent_protocol::AgentPreEffectAbortProof;\npub use codex_hepta_agent_protocol::AgentPreEffectBinding;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "use codex_hepta_learning_ledger::RunStartRecordV1;\n",
    "use codex_hepta_learning_ledger::RunStartRecordV1;\nuse sha2::Digest;\nuse sha2::Sha256;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "const DEADLINE_CANCEL_REASON: &str = \"deadline_elapsed\";\n",
    "const DEADLINE_CANCEL_REASON: &str = \"deadline_elapsed\";\nconst PRE_EFFECT_ABORT_COMMITMENT_DOMAIN: &[u8] =\n    b\"hepta.runtime.codex.pre-effect-abort.commitment.v1\";\nconst PRE_EFFECT_ABORT_PROOF_DOMAIN: &[u8] =\n    b\"hepta.runtime.codex.pre-effect-abort.proof.v1\";\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "    pub terminal_observed: bool,\n    pub idempotent: bool,\n}\n",
    "    pub terminal_observed: bool,\n    pub pre_effect_binding: Option<crate::AgentPreEffectBinding>,\n    pub pre_effect_abort_proof_sha256: Option<String>,\n    pub pre_effect_aborted: bool,\n    pub idempotent: bool,\n}\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "    cancel_reason: Option<String>,\n    cancel_ack_deadline_ms: Option<u64>,\n}\n",
    "    cancel_reason: Option<String>,\n    cancel_ack_deadline_ms: Option<u64>,\n    pre_effect_binding: Option<crate::AgentPreEffectBinding>,\n    pre_effect_abort_proof_sha256: Option<String>,\n    pre_effect_aborted: bool,\n}\n",
)
replace_all(
    "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "            cancel_reason: None,\n            cancel_ack_deadline_ms: None,\n",
    "            cancel_reason: None,\n            cancel_ack_deadline_ms: None,\n            pre_effect_binding: None,\n            pre_effect_abort_proof_sha256: None,\n            pre_effect_aborted: false,\n",
    1,
)
replace_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "            cancel_reason: recovery.cancel_reason,\n            cancel_ack_deadline_ms: None,\n",
    "            cancel_reason: recovery.cancel_reason,\n            cancel_ack_deadline_ms: None,\n            pre_effect_binding: None,\n            pre_effect_abort_proof_sha256: None,\n            pre_effect_aborted: false,\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "    pub fn cancel_run(\n",
    "    pub fn mark_effect_prepared(\n        &mut self,\n        now_ms: u64,\n        run_id: &str,\n        expected_revision: u64,\n        binding: crate::AgentPreEffectBinding,\n    ) -> Result<RunReceipt, AgentRunError> {\n        validate_identity(run_id, \"run\")?;\n        validate_pre_effect_binding(&binding)?;\n        let record = self\n            .runs\n            .get_mut(run_id)\n            .ok_or(AgentRunError::RunNotFound)?;\n        if record.phase == RunPhase::Dispatched {\n            if record.pre_effect_binding.as_ref() == Some(&binding) {\n                return Ok(receipt(record, /*idempotent*/ true));\n            }\n            return Err(AgentRunError::Conflict);\n        }\n        require_revision(record, expected_revision)?;\n        require_live_deadline(record, now_ms)?;\n        if record.phase != RunPhase::ContextAttached {\n            return Err(AgentRunError::ContextRequired);\n        }\n        record.pre_effect_binding = Some(binding);\n        record.phase = RunPhase::Dispatched;\n        advance_revision(record)?;\n        Ok(receipt(record, /*idempotent*/ false))\n    }\n\n    pub fn abort_before_effect(\n        &mut self,\n        run_id: &str,\n        expected_revision: u64,\n        proof: crate::AgentPreEffectAbortProof,\n        reason: &str,\n    ) -> Result<RunReceipt, AgentRunError> {\n        validate_identity(run_id, \"run\")?;\n        validate_cancel_reason(reason)?;\n        validate_pre_effect_abort_proof(&proof)?;\n        let proof_sha256 = pre_effect_abort_proof_sha256(&proof);\n        let record = self\n            .runs\n            .get_mut(run_id)\n            .ok_or(AgentRunError::RunNotFound)?;\n        if record.pre_effect_aborted {\n            if record.pre_effect_abort_proof_sha256.as_deref() == Some(proof_sha256.as_str())\n                && record.cancel_reason.as_deref() == Some(reason)\n            {\n                return Ok(receipt(record, /*idempotent*/ true));\n            }\n            return Err(AgentRunError::Conflict);\n        }\n        require_revision(record, expected_revision)?;\n        if record.phase != RunPhase::Dispatched {\n            return Err(AgentRunError::InvalidTransition);\n        }\n        let binding = record\n            .pre_effect_binding\n            .as_ref()\n            .ok_or(AgentRunError::InvalidTransition)?;\n        let expected_commitment = pre_effect_abort_commitment_sha256(\n            &proof.effect_request_digest,\n            proof.native_dispatch_revision,\n            proof.local_abort_revision,\n            &proof.nonce,\n        );\n        if proof.effect_request_digest != binding.effect_request_digest\n            || proof.native_dispatch_revision != binding.native_dispatch_revision\n            || proof.local_abort_revision != binding.local_abort_revision\n            || expected_commitment != binding.abort_commitment_sha256\n        {\n            return Err(AgentRunError::Conflict);\n        }\n        record.phase = RunPhase::Cancelled;\n        record.cancel_reason = Some(reason.to_string());\n        record.cancel_ack_deadline_ms = None;\n        record.pre_effect_abort_proof_sha256 = Some(proof_sha256);\n        record.pre_effect_aborted = true;\n        advance_revision(record)?;\n        Ok(receipt(record, /*idempotent*/ false))\n    }\n\n    pub fn cancel_run(\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "fn validate_recovery(value: &RunRecovery) -> Result<(), AgentRunError> {\n",
    "fn validate_pre_effect_binding(\n    value: &crate::AgentPreEffectBinding,\n) -> Result<(), AgentRunError> {\n    validate_digest(&value.effect_request_digest, \"pre-effect request\")?;\n    validate_digest(&value.abort_commitment_sha256, \"pre-effect commitment\")?;\n    if value.native_dispatch_revision == 0\n        || value.local_abort_revision\n            != value\n                .native_dispatch_revision\n                .checked_add(1)\n                .ok_or(AgentRunError::ArithmeticOverflow)?\n    {\n        return Err(AgentRunError::InvalidTransition);\n    }\n    Ok(())\n}\n\nfn validate_pre_effect_abort_proof(\n    value: &crate::AgentPreEffectAbortProof,\n) -> Result<(), AgentRunError> {\n    validate_digest(&value.effect_request_digest, \"pre-effect proof request\")?;\n    if value.native_dispatch_revision == 0\n        || value.local_abort_revision\n            != value\n                .native_dispatch_revision\n                .checked_add(1)\n                .ok_or(AgentRunError::ArithmeticOverflow)?\n    {\n        return Err(AgentRunError::InvalidTransition);\n    }\n    Ok(())\n}\n\nfn pre_effect_abort_commitment_sha256(\n    effect_request_digest: &str,\n    native_dispatch_revision: u64,\n    local_abort_revision: u64,\n    nonce: &[u8; 32],\n) -> String {\n    let mut hasher = Sha256::new();\n    hasher.update(PRE_EFFECT_ABORT_COMMITMENT_DOMAIN);\n    hasher.update(effect_request_digest.as_bytes());\n    hasher.update(native_dispatch_revision.to_be_bytes());\n    hasher.update(local_abort_revision.to_be_bytes());\n    hasher.update(nonce);\n    format!(\"{:x}\", hasher.finalize())\n}\n\nfn pre_effect_abort_proof_sha256(value: &crate::AgentPreEffectAbortProof) -> String {\n    let mut hasher = Sha256::new();\n    hasher.update(PRE_EFFECT_ABORT_PROOF_DOMAIN);\n    hasher.update(value.effect_request_digest.as_bytes());\n    hasher.update(value.native_dispatch_revision.to_be_bytes());\n    hasher.update(value.local_abort_revision.to_be_bytes());\n    hasher.update(value.nonce);\n    format!(\"{:x}\", hasher.finalize())\n}\n\nfn validate_recovery(value: &RunRecovery) -> Result<(), AgentRunError> {\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "        terminal_observed: record.phase.terminal_observed(),\n        idempotent,\n",
    "        terminal_observed: record.phase.terminal_observed(),\n        pre_effect_binding: record.pre_effect_binding.clone(),\n        pre_effect_abort_proof_sha256: record.pre_effect_abort_proof_sha256.clone(),\n        pre_effect_aborted: record.pre_effect_aborted,\n        idempotent,\n",
)

# State-control handlers and wire projection.
replace_once(
    "codex-rs/hepta-agentd/src/state_control.rs",
    "            crate::AgentdMethod::RunCancel {\n",
    "            crate::AgentdMethod::RunMarkEffectPrepared {\n                run_id,\n                expected_revision,\n                binding,\n            } => {\n                require_run_admission_ready(lifecycle, app_server_ready, fenced)?;\n                let receipt = self\n                    .runs\n                    .lock()\n                    .map_err(poisoned_state)?\n                    .mark_effect_prepared(now_ms()?, &run_id, expected_revision, binding)\n                    .map_err(run_error)?;\n                AgentdPayload::RunReceipt(wire_run_receipt(receipt))\n            }\n            crate::AgentdMethod::RunAbortBeforeEffect {\n                run_id,\n                expected_revision,\n                proof,\n                reason,\n            } => {\n                require_run_reconciliation_ready(lifecycle, fenced)?;\n                let receipt = self\n                    .runs\n                    .lock()\n                    .map_err(poisoned_state)?\n                    .abort_before_effect(&run_id, expected_revision, proof, &reason)\n                    .map_err(run_error)?;\n                AgentdPayload::RunReceipt(wire_run_receipt(receipt))\n            }\n            crate::AgentdMethod::RunCancel {\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/state_control.rs",
    "        terminal_observed: value.terminal_observed,\n        idempotent: value.idempotent,\n",
    "        terminal_observed: value.terminal_observed,\n        pre_effect_binding: value.pre_effect_binding,\n        pre_effect_abort_proof_sha256: value.pre_effect_abort_proof_sha256,\n        pre_effect_aborted: value.pre_effect_aborted,\n        idempotent: value.idempotent,\n",
)

# Client methods expose the two transitions without widening ordinary cancel.
replace_once(
    "codex-rs/hepta-agentd/src/client.rs",
    "use crate::AgentContextAttachment;\n",
    "use crate::AgentContextAttachment;\nuse crate::AgentPreEffectAbortProof;\nuse crate::AgentPreEffectBinding;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/client.rs",
    "    pub async fn run_cancel(\n",
    "    pub async fn run_mark_effect_prepared(\n        &self,\n        run_id: String,\n        expected_revision: u64,\n        binding: AgentPreEffectBinding,\n    ) -> Result<AgentRunReceipt, AgentdError> {\n        match self\n            .send(AgentdRequest::run_mark_effect_prepared(\n                self.request_id(),\n                self.spawn_generation,\n                run_id,\n                expected_revision,\n                binding,\n            ))\n            .await?\n            .payload\n        {\n            AgentdPayload::RunReceipt(receipt) => Ok(receipt),\n            payload => unexpected(payload),\n        }\n    }\n\n    pub async fn run_abort_before_effect(\n        &self,\n        run_id: String,\n        expected_revision: u64,\n        proof: AgentPreEffectAbortProof,\n        reason: String,\n    ) -> Result<AgentRunReceipt, AgentdError> {\n        match self\n            .send(AgentdRequest::run_abort_before_effect(\n                self.request_id(),\n                self.spawn_generation,\n                run_id,\n                expected_revision,\n                proof,\n                reason,\n            ))\n            .await?\n            .payload\n        {\n            AgentdPayload::RunReceipt(receipt) => Ok(receipt),\n            payload => unexpected(payload),\n        }\n    }\n\n    pub async fn run_cancel(\n",
)

# ---------------------------------------------------------------------------
# Product caller: publish the owner commitment with Dispatched, then on every
# pre-effect failure commit the local opening first and reconcile the owner to a
# directly terminal Cancelled state.  Restart replays only this compensation.
# ---------------------------------------------------------------------------
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "use codex_hepta_agentd::AgentRunPhase;\n",
    "use codex_hepta_agentd::AgentPreEffectAbortProof;\nuse codex_hepta_agentd::AgentPreEffectBinding;\nuse codex_hepta_agentd::AgentRunPhase;\n",
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;\n",
    "use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;\nuse codex_hepta_infer_core::durable_control::native::NativePreEffectAbortBinding;\nuse codex_hepta_infer_core::durable_control::native::NativePreEffectAbortProof;\nuse codex_hepta_infer_core::durable_control::native::NativePreEffectAbortToken;\n",
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "            let dispatched = match owner\n                .run_mark_dispatched(binding.run_id.clone(), binding.expected_revision)\n",
    "            let dispatched = match owner\n                .run_mark_effect_prepared(\n                    binding.run_id.clone(),\n                    binding.expected_revision,\n                    agent_pre_effect_binding(pre_effect_abort.binding()),\n                )\n",
)
replace_all(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "control.abort_native_before_effect(pre_effect_abort, reason.clone())?;",
    "abort_pre_effect_and_reconcile(\n                        control,\n                        &owner,\n                        request_id,\n                        pre_effect_abort,\n                        intelligence,\n                        reason.clone(),\n                    )\n                    .await?;",
    6,
)
# Two branches use a temporary `stopped` result instead of the direct spelling.
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "                    let stopped = control.abort_native_before_effect(pre_effect_abort, reason);\n                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;\n                    stopped?;\n                    return Err(error.into());\n",
    "                    abort_pre_effect_and_reconcile(\n                        control,\n                        &owner,\n                        request_id,\n                        pre_effect_abort,\n                        intelligence,\n                        reason,\n                    )\n                    .await?;\n                    let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;\n                    return Err(error.into());\n",
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "                let stopped = control.abort_native_before_effect(\n                    pre_effect_abort,\n                    \"cognitive final-use revalidation returned a mismatched receipt\".to_string(),\n                );\n                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;\n                stopped?;\n",
    "                abort_pre_effect_and_reconcile(\n                    control,\n                    &owner,\n                    request_id,\n                    pre_effect_abort,\n                    intelligence,\n                    \"cognitive final-use revalidation returned a mismatched receipt\".to_string(),\n                )\n                .await?;\n                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;\n",
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "            let stopped = control.abort_native_before_effect(\n                pre_effect_abort,\n                \"cancelled before model dispatch\".to_string(),\n            );\n            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;\n            stopped?;\n",
    "            abort_pre_effect_and_reconcile(\n                control,\n                &owner,\n                request_id,\n                pre_effect_abort,\n                intelligence,\n                \"cancelled before model dispatch\".to_string(),\n            )\n            .await?;\n            let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;\n",
)

# Insert exact mapping/reconciliation helpers before final-use binding.
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "fn final_use_binding(\n",
    "fn agent_pre_effect_binding(value: &NativePreEffectAbortBinding) -> AgentPreEffectBinding {\n    AgentPreEffectBinding {\n        effect_request_digest: value.effect_request_digest.clone(),\n        native_dispatch_revision: value.native_dispatch_revision,\n        local_abort_revision: value.local_abort_revision,\n        abort_commitment_sha256: value.abort_commitment_sha256.clone(),\n    }\n}\n\nfn agent_pre_effect_abort_proof(value: &NativePreEffectAbortProof) -> AgentPreEffectAbortProof {\n    AgentPreEffectAbortProof {\n        effect_request_digest: value.effect_request_digest.clone(),\n        native_dispatch_revision: value.native_dispatch_revision,\n        local_abort_revision: value.local_abort_revision,\n        nonce: value.nonce,\n    }\n}\n\nfn agentd_abort_receipt_matches(\n    receipt: &codex_hepta_agentd::AgentRunReceipt,\n    binding: &NativeIntelligenceRunBinding,\n    proof: &NativePreEffectAbortProof,\n    reason: &str,\n) -> bool {\n    receipt.phase == AgentRunPhase::Cancelled\n        && receipt.terminal_observed\n        && receipt.pre_effect_aborted\n        && receipt.generation != 0\n        && receipt.context_digest.as_deref() == Some(binding.context_digest.as_str())\n        && receipt.compilation_receipt_digest.as_deref()\n            == Some(binding.envelope_digest.as_str())\n        && receipt.cancel_reason.as_deref() == Some(reason)\n        && receipt.pre_effect_abort_proof_sha256.as_deref()\n            == Some(proof.proof_sha256().as_str())\n}\n\npub(super) async fn reconcile_agentd_pre_effect_abort(\n    owner: &AgentdClient,\n    binding: &NativeIntelligenceRunBinding,\n    proof: &NativePreEffectAbortProof,\n    reason: &str,\n) -> Result<()> {\n    let prepared_revision = binding\n        .expected_revision\n        .checked_add(1)\n        .ok_or(\"Agentd pre-effect revision overflow\")?;\n    let wire_proof = agent_pre_effect_abort_proof(proof);\n    match owner\n        .run_abort_before_effect(\n            binding.run_id.clone(),\n            prepared_revision,\n            wire_proof.clone(),\n            reason.to_string(),\n        )\n        .await\n    {\n        Ok(receipt) if agentd_abort_receipt_matches(&receipt, binding, proof, reason) => {\n            return Ok(());\n        }\n        Ok(_) => return Err(\"Agentd returned a mismatched pre-effect abort receipt\".into()),\n        Err(_direct_error) => {}\n    }\n\n    if let Some(status) = owner.run_status(binding.run_id.clone()).await?\n        && agentd_abort_receipt_matches(&status, binding, proof, reason)\n    {\n        return Ok(());\n    }\n\n    let prepared = owner\n        .run_mark_effect_prepared(\n            binding.run_id.clone(),\n            binding.expected_revision,\n            AgentPreEffectBinding {\n                effect_request_digest: proof.effect_request_digest.clone(),\n                native_dispatch_revision: proof.native_dispatch_revision,\n                local_abort_revision: proof.local_abort_revision,\n                abort_commitment_sha256: {\n                    let status = owner\n                        .run_status(binding.run_id.clone())\n                        .await?\n                        .ok_or(\"Agentd run disappeared during pre-effect compensation\")?;\n                    status\n                        .pre_effect_binding\n                        .map(|value| value.abort_commitment_sha256)\n                        .ok_or(\"Agentd has no pre-effect binding after ambiguous prepare\")?\n                },\n            },\n        )\n        .await?;\n    if prepared.phase != AgentRunPhase::Dispatched\n        || prepared.generation == 0\n        || prepared.context_digest.as_deref() != Some(binding.context_digest.as_str())\n        || prepared.compilation_receipt_digest.as_deref()\n            != Some(binding.envelope_digest.as_str())\n    {\n        return Err(\"Agentd did not retain the exact pre-effect prepare binding\".into());\n    }\n    let aborted = owner\n        .run_abort_before_effect(\n            binding.run_id.clone(),\n            prepared.revision,\n            wire_proof,\n            reason.to_string(),\n        )\n        .await?;\n    if !agentd_abort_receipt_matches(&aborted, binding, proof, reason) {\n        return Err(\"Agentd pre-effect compensation did not close the owner run\".into());\n    }\n    Ok(())\n}\n\nasync fn abort_pre_effect_and_reconcile(\n    control: &mut DurableInferenceControl,\n    owner: &AgentdClient,\n    request_id: &str,\n    token: NativePreEffectAbortToken,\n    intelligence: Option<&NativeIntelligenceRunBinding>,\n    reason: String,\n) -> Result<()> {\n    let (_record, proof) =\n        control.abort_native_before_effect_with_proof(token, reason.clone())?;\n    if let Some(binding) = intelligence {\n        reconcile_agentd_pre_effect_abort(owner, binding, &proof, &reason).await?;\n    }\n    let persisted = control\n        .native_record(request_id)\n        .ok_or(\"runtime.codex pre-effect abort record disappeared\")?;\n    if persisted.pre_effect_abort_proof.as_ref() != Some(&proof) {\n        return Err(\"runtime.codex pre-effect abort proof was not durably retained\".into());\n    }\n    Ok(())\n}\n\nfn final_use_binding(\n",
)

# The compensation helper above must be able to retry from the original exact
# commitment after a lost prepare/abort acknowledgement.  Pass that commitment
# explicitly instead of attempting to discover it from mutable owner state.
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "pub(super) async fn reconcile_agentd_pre_effect_abort(\n    owner: &AgentdClient,\n    binding: &NativeIntelligenceRunBinding,\n    proof: &NativePreEffectAbortProof,\n    reason: &str,\n) -> Result<()> {\n",
    "pub(super) async fn reconcile_agentd_pre_effect_abort(\n    owner: &AgentdClient,\n    binding: &NativeIntelligenceRunBinding,\n    local_binding: &NativePreEffectAbortBinding,\n    proof: &NativePreEffectAbortProof,\n    reason: &str,\n) -> Result<()> {\n",
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "            AgentPreEffectBinding {\n                effect_request_digest: proof.effect_request_digest.clone(),\n                native_dispatch_revision: proof.native_dispatch_revision,\n                local_abort_revision: proof.local_abort_revision,\n                abort_commitment_sha256: {\n                    let status = owner\n                        .run_status(binding.run_id.clone())\n                        .await?\n                        .ok_or(\"Agentd run disappeared during pre-effect compensation\")?;\n                    status\n                        .pre_effect_binding\n                        .map(|value| value.abort_commitment_sha256)\n                        .ok_or(\"Agentd has no pre-effect binding after ambiguous prepare\")?\n                },\n            },\n",
    "            agent_pre_effect_binding(local_binding),\n",
)
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "    let (_record, proof) =\n        control.abort_native_before_effect_with_proof(token, reason.clone())?;\n    if let Some(binding) = intelligence {\n        reconcile_agentd_pre_effect_abort(owner, binding, &proof, &reason).await?;\n",
    "    let local_binding = token.binding().clone();\n    let (_record, proof) =\n        control.abort_native_before_effect_with_proof(token, reason.clone())?;\n    if let Some(binding) = intelligence {\n        reconcile_agentd_pre_effect_abort(\n            owner,\n            binding,\n            &local_binding,\n            &proof,\n            &reason,\n        )\n        .await?;\n",
)

# Reopen retries only the exact compensation opening; it never recreates a turn.
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_run_control.rs",
    "        if let Some(reason) = &record.pre_dispatch_stop {\n            return Err(format!(\"request stopped before dispatch: {reason}\").into());\n        }\n",
    "        if let Some(reason) = &record.pre_dispatch_stop {\n            if let (Some(binding), Some(proof), Some(dispatch)) = (\n                intelligence,\n                record.pre_effect_abort_proof.as_ref(),\n                record.dispatch.as_ref(),\n            ) {\n                let commitment = dispatch\n                    .pre_effect_abort_commitment_sha256\n                    .clone()\n                    .ok_or(\"pre-effect abort record omitted its commitment\")?;\n                let owner = codex_hepta_agentd::AgentdClient::new(\n                    self.config.agentd_socket.clone(),\n                    self.config.agent_id.clone(),\n                    self.config.generation,\n                )?;\n                super::reconcile_agentd_pre_effect_abort(\n                    &owner,\n                    binding,\n                    &codex_hepta_infer_core::durable_control::native::NativePreEffectAbortBinding {\n                        effect_request_digest: proof.effect_request_digest.clone(),\n                        native_dispatch_revision: proof.native_dispatch_revision,\n                        local_abort_revision: proof.local_abort_revision,\n                        abort_commitment_sha256: commitment,\n                    },\n                    proof,\n                    reason,\n                )\n                .await?;\n            }\n            return Err(format!(\"request stopped before dispatch: {reason}\").into());\n        }\n",
)

# ---------------------------------------------------------------------------
# Focused tests: exact proof opening, tamper rejection, idempotence, and direct
# closed-state capacity release rather than Cancelling/Indeterminate drift.
# ---------------------------------------------------------------------------
replace_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs",
    "#[test]\nfn operation_identity_is_idempotent_only_for_equal_semantics() {\n",
    "#[test]\nfn exact_pre_effect_abort_closes_dispatched_owner_without_uncertainty() {\n    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect(\"compose\");\n    coordinator.start_run(100, snapshot()).expect(\"admit\");\n    coordinator\n        .attach_context(200, 1, attachment())\n        .expect(\"attach\");\n    let nonce = [7_u8; 32];\n    let effect_request_digest = digest('a');\n    let binding = crate::AgentPreEffectBinding {\n        effect_request_digest: effect_request_digest.clone(),\n        native_dispatch_revision: 2,\n        local_abort_revision: 3,\n        abort_commitment_sha256: pre_effect_abort_commitment_sha256(\n            &effect_request_digest,\n            2,\n            3,\n            &nonce,\n        ),\n    };\n    let prepared = coordinator\n        .mark_effect_prepared(300, \"run.1\", 2, binding.clone())\n        .expect(\"prepare effect\");\n    assert_eq!(prepared.phase, RunPhase::Dispatched);\n    assert_eq!(prepared.revision, 3);\n    assert_eq!(prepared.pre_effect_binding, Some(binding));\n\n    let proof = crate::AgentPreEffectAbortProof {\n        effect_request_digest,\n        native_dispatch_revision: 2,\n        local_abort_revision: 3,\n        nonce,\n    };\n    let aborted = coordinator\n        .abort_before_effect(\"run.1\", 3, proof.clone(), \"owner_final_fence_failed\")\n        .expect(\"abort before effect\");\n    assert_eq!(aborted.phase, RunPhase::Cancelled);\n    assert!(aborted.terminal_observed);\n    assert!(aborted.pre_effect_aborted);\n    assert_eq!(aborted.cancel_ack_deadline_ms, None);\n    assert_eq!(coordinator.unresolved_run_count(), 0);\n    assert_eq!(coordinator.active_run_count(), 0);\n\n    let repeated = coordinator\n        .abort_before_effect(\"run.1\", 3, proof.clone(), \"owner_final_fence_failed\")\n        .expect(\"idempotent abort\");\n    assert!(repeated.idempotent);\n    let mut forged = proof;\n    forged.nonce[0] ^= 1;\n    assert_eq!(\n        coordinator.abort_before_effect(\n            \"run.1\",\n            3,\n            forged,\n            \"owner_final_fence_failed\",\n        ),\n        Err(AgentRunError::Conflict),\n    );\n}\n\n#[test]\nfn operation_identity_is_idempotent_only_for_equal_semantics() {\n",
)
replace_once(
    "codex-rs/hepta-infer-core/src/native_control_tests.rs",
    "    assert_eq!(stopped.observation, None);\n    control.reserve_native(request(\"r2\"), 1).unwrap();\n",
    "    assert_eq!(stopped.observation, None);\n    let proof = stopped\n        .pre_effect_abort_proof\n        .as_ref()\n        .expect(\"durable abort proof\");\n    assert_eq!(proof.local_abort_revision, stopped.revision);\n    assert_eq!(proof.native_dispatch_revision + 1, proof.local_abort_revision);\n    assert_eq!(proof.proof_sha256().len(), 64);\n    assert!(\n        stopped\n            .dispatch\n            .as_ref()\n            .and_then(|dispatch| dispatch.pre_effect_abort_commitment_sha256.as_ref())\n            .is_some_and(|digest| digest.len() == 64)\n    );\n    control.reserve_native(request(\"r2\"), 1).unwrap();\n",
)
replace_once(
    "codex-rs/hepta-infer-core/src/native_control_tests.rs",
    "    assert_eq!(\n        reopened.native_record(\"r1\").unwrap().state,\n        NativeReservationState::Dispatching\n    );\n",
    "    assert_eq!(\n        reopened.native_record(\"r1\").unwrap().state,\n        NativeReservationState::Dispatching\n    );\n    assert_eq!(\n        reopened\n            .native_record(\"r1\")\n            .unwrap()\n            .pre_effect_abort_proof,\n        None\n    );\n",
)

# Documentation of the corrected invariant is shipped with the implementation.
write(
    "docs/modules/runtime.codex/PRE_EFFECT_COMPENSATION.md",
    """# runtime.codex exact pre-effect compensation\n\nThe native caller now closes the local journal and the Agentd run owner with one\nshared, exact proof rather than translating a definitely-unsent operation into\nordinary post-dispatch cancellation.\n\n1. The local journal creates a random, non-serializable nonce and stores only a\n   domain-separated commitment in the durable dispatch.\n2. Agentd freezes that same commitment in `RunMarkEffectPrepared` when the run\n   enters `Dispatched`.\n3. Before `EnteredUseToken` is consumed, any final-fence failure consumes the\n   live local token and durably writes the nonce opening.\n4. Only that exact opening may invoke `RunAbortBeforeEffect`; Agentd then moves\n   directly from `Dispatched` to terminal `Cancelled`, without `Cancelling`, an\n   acknowledgement timeout, or an invented provider observation.\n5. If either Agentd RPC acknowledgement is lost, reopening the local journal may\n   replay only the exact compensation proof.  It cannot recreate a token or a\n   `turn/start`.\n\nA process crash before the local opening is committed deliberately destroys the\nnonce.  Such a dispatch remains accepted-or-unknown and reconcile-only.  This\npreserves the original no-blind-replay rule.\n""",
)

print("runtime.codex pre-effect compensation patch applied")
