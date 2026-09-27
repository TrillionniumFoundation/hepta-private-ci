#!/usr/bin/env python3
"""Apply the bounded runtime.codex full-convergence repair.

The script is intentionally fail-closed: every source replacement must match
exactly once, and every appended test is guarded by a unique marker. It is run
inside GitHub Actions against one exact candidate, followed by Rust formatting,
focused tests, product E2E, and strict Clippy.
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, value: str) -> None:
    (ROOT / path).write_text(value, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    value = read(path)
    count = value.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one exact occurrence, found {count}: {old[:120]!r}")
    write(path, value.replace(old, new, 1))


def replace_all(path: str, old: str, new: str, expected: int) -> None:
    value = read(path)
    count = value.count(old)
    if count != expected:
        raise SystemExit(f"{path}: expected {expected} occurrences, found {count}: {old[:120]!r}")
    write(path, value.replace(old, new))


def sub_once(path: str, pattern: str, replacement: str) -> None:
    value = read(path)
    updated, count = re.subn(pattern, replacement, value, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"{path}: expected one regex occurrence, found {count}: {pattern[:120]!r}")
    write(path, updated)


def append_once(path: str, marker: str, addition: str) -> None:
    value = read(path)
    if marker in value:
        return
    if not value.endswith("\n"):
        value += "\n"
    write(path, value + "\n" + textwrap.dedent(addition).lstrip("\n"))


# ---------------------------------------------------------------------------
# hepta-infer-core: persist exact effect entry without serializing authority.
# ---------------------------------------------------------------------------
CORE = "codex-rs/hepta-infer-core/src/native_control.rs"

replace_once(
    CORE,
    """impl std::fmt::Debug for NativePreEffectAbortToken {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(\"NativePreEffectAbortToken([LOCAL ONLY])\")
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativePreEffectAbortRecord {
""",
    """impl std::fmt::Debug for NativePreEffectAbortToken {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(\"NativePreEffectAbortToken([LOCAL ONLY])\")
    }
}

/// Non-cloneable proof material for the irreversible effect-entry choice.
///
/// It consumes the pre-effect abort token. The caller may use it to obtain an
/// exact Agentd entry receipt and must then durably confirm that same proof in
/// the local journal before writing the App Server socket.
pub struct NativeEffectEntryClaim {
    request_id: String,
    dispatch_revision: u64,
    owner_run_id: String,
    owner_dispatch_revision: u64,
    dispatch_binding_digest: String,
    commitment_digest: String,
    effect_nonce_hex: String,
    proof_digest: String,
}

impl std::fmt::Debug for NativeEffectEntryClaim {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(\"NativeEffectEntryClaim([ONE SHOT])\")
    }
}

impl NativeEffectEntryClaim {
    pub fn owner_run_id(&self) -> &str {
        &self.owner_run_id
    }

    pub fn owner_dispatch_revision(&self) -> u64 {
        self.owner_dispatch_revision
    }

    pub fn dispatch_binding_digest(&self) -> &str {
        &self.dispatch_binding_digest
    }

    pub fn commitment_digest(&self) -> &str {
        &self.commitment_digest
    }

    pub fn effect_nonce_hex(&self) -> &str {
        &self.effect_nonce_hex
    }

    pub fn proof_digest(&self) -> &str {
        &self.proof_digest
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeEffectEntryRecord {
    pub owner_run_id: String,
    pub owner_dispatch_revision: u64,
    pub owner_effect_revision: u64,
    pub dispatch_binding_digest: String,
    pub commitment_digest: String,
    pub effect_nonce_hex: String,
    pub proof_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativePreEffectAbortRecord {
""",
)

replace_once(
    CORE,
    """    fn proof_record(
""",
    """    pub fn into_effect_entry_claim(
        self,
        owner_run_id: String,
        owner_dispatch_revision: u64,
        dispatch_binding_digest: String,
    ) -> Result<NativeEffectEntryClaim, Error> {
        validate_identity(&owner_run_id, \"native effect-entry owner run\")?;
        validate_digest(
            &dispatch_binding_digest,
            \"native effect-entry dispatch binding\",
        )?;
        if owner_dispatch_revision == 0 {
            return Err(Error::InvalidIdentity(
                \"native effect-entry owner revision\",
            ));
        }
        let commitment_digest =
            self.commitment_digest(&owner_run_id, &dispatch_binding_digest)?;
        let proof_digest = pre_effect_entry_digest(
            &owner_run_id,
            &dispatch_binding_digest,
            owner_dispatch_revision,
            &self.abort_nonce,
        );
        Ok(NativeEffectEntryClaim {
            request_id: self.request_id,
            dispatch_revision: self.dispatch_revision,
            owner_run_id,
            owner_dispatch_revision,
            dispatch_binding_digest,
            commitment_digest,
            effect_nonce_hex: encode_abort_nonce(&self.abort_nonce),
            proof_digest,
        })
    }

    fn proof_record(
""",
)

replace_once(
    CORE,
    """    #[serde(default)]
    pub pre_effect_abort: Option<NativePreEffectAbortRecord>,
    #[serde(default)]
    pub dispatch_rejection: Option<NativeDispatchRejection>,
""",
    """    #[serde(default)]
    pub pre_effect_abort: Option<NativePreEffectAbortRecord>,
    #[serde(default)]
    pub effect_entry: Option<NativeEffectEntryRecord>,
    #[serde(default)]
    pub dispatch_rejection: Option<NativeDispatchRejection>,
""",
)

replace_once(
    CORE,
    """    Started {
        request_id: String,
        turn_id: String,
    },
""",
    """    EnterEffect {
        request_id: String,
        entry: NativeEffectEntryRecord,
    },
    Started {
        request_id: String,
        turn_id: String,
    },
""",
)

replace_all(
    CORE,
    """            || record.cancel_requested
        {
""",
    """            || record.cancel_requested
            || record.effect_entry.is_some()
        {
""",
    2,
)

replace_once(
    CORE,
    """    pub fn native_started(
""",
    """    pub fn confirm_native_effect_entry(
        &mut self,
        claim: NativeEffectEntryClaim,
        owner_effect_revision: u64,
    ) -> Result<NativeRunRecord, Error> {
        if owner_effect_revision < claim.owner_dispatch_revision {
            return Err(Error::InvalidTransition);
        }
        let record = self
            .native
            .records
            .get(&claim.request_id)
            .ok_or(Error::RequestNotFound)?;
        if record.state != NativeReservationState::Dispatching
            || record.revision != claim.dispatch_revision
            || record.turn_id.is_some()
            || record.observation.is_some()
            || record.dispatch_rejection.is_some()
            || record.cancel_requested
            || record.pre_effect_abort.is_some()
            || record.effect_entry.is_some()
            || record
                .dispatch
                .as_ref()
                .and_then(|dispatch| dispatch.codex_request_digest.as_deref())
                != Some(claim.dispatch_binding_digest.as_str())
        {
            return Err(Error::InvalidTransition);
        }
        let request_id = claim.request_id.clone();
        let entry = NativeEffectEntryRecord {
            owner_run_id: claim.owner_run_id,
            owner_dispatch_revision: claim.owner_dispatch_revision,
            owner_effect_revision,
            dispatch_binding_digest: claim.dispatch_binding_digest,
            commitment_digest: claim.commitment_digest,
            effect_nonce_hex: claim.effect_nonce_hex,
            proof_digest: claim.proof_digest,
        };
        self.commit_native(
            &request_id,
            Event::EnterEffect {
                request_id: request_id.clone(),
                entry,
            },
        )
    }

    pub fn native_started(
""",
)

replace_once(
    CORE,
    """                    pre_effect_abort: None,
                    dispatch_rejection: None,
""",
    """                    pre_effect_abort: None,
                    effect_entry: None,
                    dispatch_rejection: None,
""",
)

replace_once(
    CORE,
    """            | Event::Started { request_id, .. }
""",
    """            | Event::EnterEffect { request_id, .. }
            | Event::Started { request_id, .. }
""",
)

replace_once(
    CORE,
    """            Event::Started { turn_id, .. } => {
""",
    """            Event::EnterEffect { entry, .. } => {
                if record.state != NativeReservationState::Dispatching
                    || record.turn_id.is_some()
                    || record.observation.is_some()
                    || record.dispatch_rejection.is_some()
                    || record.cancel_requested
                    || record.pre_effect_abort.is_some()
                    || record.effect_entry.is_some()
                {
                    return Err(Error::InvalidTransition);
                }
                validate_identity(&entry.owner_run_id, \"native effect-entry owner run\")?;
                validate_digest(
                    &entry.dispatch_binding_digest,
                    \"native effect-entry dispatch binding\",
                )?;
                validate_digest(&entry.commitment_digest, \"native effect-entry commitment\")?;
                validate_digest(&entry.proof_digest, \"native effect-entry proof\")?;
                if entry.owner_dispatch_revision == 0
                    || entry.owner_effect_revision < entry.owner_dispatch_revision
                {
                    return Err(Error::InvalidIdentity(
                        \"native effect-entry owner revision\",
                    ));
                }
                let nonce = decode_abort_nonce(&entry.effect_nonce_hex)?;
                if pre_effect_abort_digest(
                    b\"hepta.runtime.codex.pre-effect-abort.commitment.v1\",
                    &entry.owner_run_id,
                    &entry.dispatch_binding_digest,
                    &nonce,
                    None,
                ) != entry.commitment_digest
                    || pre_effect_entry_digest(
                        &entry.owner_run_id,
                        &entry.dispatch_binding_digest,
                        entry.owner_dispatch_revision,
                        &nonce,
                    ) != entry.proof_digest
                    || record
                        .dispatch
                        .as_ref()
                        .and_then(|dispatch| dispatch.codex_request_digest.as_deref())
                        != Some(entry.dispatch_binding_digest.as_str())
                {
                    return Err(Error::Conflict);
                }
                record.effect_entry = Some(entry);
            }
            Event::Started { turn_id, .. } => {
""",
)

replace_once(
    CORE,
    """                if record.state != NativeReservationState::Dispatching
                    || record.dispatch_rejection.is_some()
                {
""",
    """                let requires_effect_entry = record
                    .dispatch
                    .as_ref()
                    .and_then(|dispatch| dispatch.codex_request_digest.as_ref())
                    .is_some();
                if record.state != NativeReservationState::Dispatching
                    || record.dispatch_rejection.is_some()
                    || (requires_effect_entry && record.effect_entry.is_none())
                {
""",
)

replace_once(
    CORE,
    """                if record.state != NativeReservationState::Dispatching
                    || record.turn_id.is_some()
                    || record.observation.is_some()
                    || rejection.reason.is_empty()
""",
    """                let requires_effect_entry = record
                    .dispatch
                    .as_ref()
                    .and_then(|dispatch| dispatch.codex_request_digest.as_ref())
                    .is_some();
                if record.state != NativeReservationState::Dispatching
                    || record.turn_id.is_some()
                    || record.observation.is_some()
                    || (requires_effect_entry && record.effect_entry.is_none())
                    || rejection.reason.is_empty()
""",
)

replace_all(
    CORE,
    """                    || record.pre_effect_abort.is_some()
""",
    """                    || record.pre_effect_abort.is_some()
                    || record.effect_entry.is_some()
""",
    2,
)

replace_once(
    CORE,
    """fn push_abort_part(output: &mut Vec<u8>, value: &[u8]) {
""",
    """fn pre_effect_entry_digest(
    owner_run_id: &str,
    dispatch_binding_digest: &str,
    owner_dispatch_revision: u64,
    nonce: &[u8; 32],
) -> String {
    let mut bytes = Vec::new();
    push_abort_part(
        &mut bytes,
        b\"hepta.runtime.codex.pre-effect-entry.proof.v1\",
    );
    push_abort_part(&mut bytes, owner_run_id.as_bytes());
    push_abort_part(&mut bytes, dispatch_binding_digest.as_bytes());
    push_abort_part(&mut bytes, &owner_dispatch_revision.to_be_bytes());
    push_abort_part(&mut bytes, nonce);
    Digest32::of_bytes(&bytes).to_string()
}

fn push_abort_part(output: &mut Vec<u8>, value: &[u8]) {
""",
)

append_once(
    "codex-rs/hepta-infer-core/src/native_control_tests.rs",
    "effect_entry_is_durable_and_gates_modern_turn_start",
    r'''
#[test]
fn effect_entry_is_durable_and_gates_modern_turn_start() {
    let path = path("effect-entry");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native(request("effect.1"), 1).unwrap();
    let (_, token) = control
        .dispatch_native_with_pre_effect_abort("effect.1", dispatch())
        .unwrap();
    assert_eq!(
        control.native_started("effect.1", "turn-before-entry".to_string()),
        Err(Error::InvalidTransition)
    );
    let claim = token
        .into_effect_entry_claim("run.effect.1".to_string(), 3, "c".repeat(64))
        .unwrap();
    let proof = claim.proof_digest().to_string();
    let entered = control.confirm_native_effect_entry(claim, 4).unwrap();
    assert_eq!(
        entered.effect_entry.as_ref().map(|entry| entry.proof_digest.as_str()),
        Some(proof.as_str())
    );
    control
        .native_started("effect.1", "turn-after-entry".to_string())
        .unwrap();
    drop(control);

    let reopened = DurableInferenceControl::open(&path, 8).unwrap();
    let record = reopened.native_record("effect.1").unwrap();
    assert_eq!(record.state, NativeReservationState::Running);
    assert_eq!(
        record.effect_entry.as_ref().map(|entry| entry.proof_digest.as_str()),
        Some(proof.as_str())
    );
    drop(reopened);
    let _ = std::fs::remove_file(path);
}
''',
)

# ---------------------------------------------------------------------------
# Agentd: server-owned irreversible effect-entry marker on the exact dispatch.
# ---------------------------------------------------------------------------
AGENT = "codex-rs/hepta-agentd/src/lane_b_runtime.rs"

replace_once(
    AGENT,
    """    pub pre_effect_abort_proof_digest: Option<String>,
    pub terminal_observed: bool,
""",
    """    pub pre_effect_abort_proof_digest: Option<String>,
    /// Exact proof that the worker consumed the pre-effect abort choice and
    /// entered the effectful path. Phase remains Dispatched for wire
    /// compatibility, but abort is permanently fenced once this is present.
    pub pre_effect_entry_proof_digest: Option<String>,
    pub terminal_observed: bool,
""",
)

replace_once(
    AGENT,
    """    pre_effect_abort_proof_digest: Option<String>,
    cancel_reason: Option<String>,
""",
    """    pre_effect_abort_proof_digest: Option<String>,
    pre_effect_entry_proof_digest: Option<String>,
    cancel_reason: Option<String>,
""",
)

replace_all(
    AGENT,
    """            pre_effect_abort_proof_digest: None,
""",
    """            pre_effect_abort_proof_digest: None,
            pre_effect_entry_proof_digest: None,
""",
    2,
)

replace_once(
    AGENT,
    """    /// Close a bound dispatch as definitely unsent without inventing a
""",
    """    /// Atomically choose the effect-entry branch for the exact dispatch.
    /// The nonce opens the same commitment used by abort-before-effect, while
    /// the proof additionally binds the Agentd dispatch revision. Once this
    /// marker is present, abort-before-effect is impossible.
    pub fn enter_effect(
        &mut self,
        run_id: &str,
        expected_revision: u64,
        dispatch_binding_digest: &str,
        effect_nonce_hex: &str,
        proof_digest: &str,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_identity(run_id, \"run\")?;
        validate_digest(dispatch_binding_digest, \"dispatch binding\")?;
        validate_digest(proof_digest, \"pre-effect entry proof\")?;
        let nonce = decode_abort_nonce_hex(effect_nonce_hex)?;
        let expected_commitment =
            pre_effect_abort_commitment(run_id, dispatch_binding_digest, &nonce);
        let expected_proof = pre_effect_entry_proof(
            run_id,
            dispatch_binding_digest,
            expected_revision,
            &nonce,
        );
        if expected_proof != proof_digest {
            return Err(AgentRunError::Conflict);
        }

        let record = self
            .runs
            .get_mut(run_id)
            .ok_or(AgentRunError::RunNotFound)?;
        if record.pre_effect_entry_proof_digest.is_some() {
            let same = record.phase == RunPhase::Dispatched
                && record.dispatch_binding_digest.as_deref() == Some(dispatch_binding_digest)
                && record.pre_effect_abort_commitment_digest.as_deref()
                    == Some(expected_commitment.as_str())
                && record.pre_effect_entry_proof_digest.as_deref() == Some(proof_digest);
            return if same {
                Ok(receipt(record, /*idempotent*/ true))
            } else {
                Err(AgentRunError::Conflict)
            };
        }
        require_revision(record, expected_revision)?;
        if record.phase != RunPhase::Dispatched
            || record.pre_effect_abort_proof_digest.is_some()
            || record.dispatch_binding_digest.as_deref() != Some(dispatch_binding_digest)
            || record.pre_effect_abort_commitment_digest.as_deref()
                != Some(expected_commitment.as_str())
        {
            return Err(AgentRunError::InvalidTransition);
        }
        record.pre_effect_entry_proof_digest = Some(proof_digest.to_string());
        advance_revision(record)?;
        Ok(receipt(record, /*idempotent*/ false))
    }

    /// Close a bound dispatch as definitely unsent without inventing a
""",
)

replace_once(
    AGENT,
    """        if record.phase != RunPhase::Dispatched {
            return Err(AgentRunError::InvalidTransition);
        }
""",
    """        if record.phase != RunPhase::Dispatched
            || record.pre_effect_entry_proof_digest.is_some()
        {
            return Err(AgentRunError::InvalidTransition);
        }
""",
)

replace_once(
    AGENT,
    """        pre_effect_abort_proof_digest: record.pre_effect_abort_proof_digest.clone(),
        terminal_observed: record.phase.terminal_observed(),
""",
    """        pre_effect_abort_proof_digest: record.pre_effect_abort_proof_digest.clone(),
        pre_effect_entry_proof_digest: record.pre_effect_entry_proof_digest.clone(),
        terminal_observed: record.phase.terminal_observed(),
""",
)

replace_once(
    AGENT,
    """const PRE_EFFECT_ABORT_PROOF_DOMAIN: &[u8] = b\"hepta.runtime.codex.pre-effect-abort.proof.v1\";
""",
    """const PRE_EFFECT_ABORT_PROOF_DOMAIN: &[u8] = b\"hepta.runtime.codex.pre-effect-abort.proof.v1\";
const PRE_EFFECT_ENTRY_PROOF_DOMAIN: &[u8] =
    b\"hepta.runtime.codex.pre-effect-entry.proof.v1\";
""",
)

replace_once(
    AGENT,
    """fn framed_abort_digest(
""",
    """fn pre_effect_entry_proof(
    run_id: &str,
    dispatch_binding_digest: &str,
    owner_dispatch_revision: u64,
    nonce: &[u8; 32],
) -> String {
    let mut bytes = Vec::new();
    push_abort_part(&mut bytes, PRE_EFFECT_ENTRY_PROOF_DOMAIN);
    push_abort_part(&mut bytes, run_id.as_bytes());
    push_abort_part(&mut bytes, dispatch_binding_digest.as_bytes());
    push_abort_part(&mut bytes, &owner_dispatch_revision.to_be_bytes());
    push_abort_part(&mut bytes, nonce);
    Digest32::of_bytes(&bytes).to_string()
}

fn framed_abort_digest(
""",
)

append_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs",
    "effect_entry_and_abort_are_mutually_exclusive",
    r'''
#[test]
fn effect_entry_and_abort_are_mutually_exclusive() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition()).expect("compose");
    coordinator.start_run(100, snapshot()).expect("admit");
    coordinator
        .attach_context(200, 1, attachment())
        .expect("attach");

    let binding = digest('a');
    let nonce = [77_u8; 32];
    let nonce_hex = nonce
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    let commitment = pre_effect_abort_commitment("run.1", &binding, &nonce);
    let dispatched = coordinator
        .mark_dispatched_bound(300, "run.1", 2, binding.clone(), commitment)
        .expect("dispatch");
    let proof = pre_effect_entry_proof("run.1", &binding, dispatched.revision, &nonce);
    let entered = coordinator
        .enter_effect(
            "run.1",
            dispatched.revision,
            &binding,
            &nonce_hex,
            &proof,
        )
        .expect("enter effect");
    assert_eq!(entered.phase, RunPhase::Dispatched);
    assert_eq!(
        entered.pre_effect_entry_proof_digest.as_deref(),
        Some(proof.as_str())
    );
    assert_eq!(coordinator.unresolved_run_count(), 1);

    let repeated = coordinator
        .enter_effect(
            "run.1",
            dispatched.revision,
            &binding,
            &nonce_hex,
            &proof,
        )
        .expect("idempotent effect entry");
    assert!(repeated.idempotent);

    let abort_reason = "must not roll back effect entry";
    let abort_proof = pre_effect_abort_proof("run.1", &binding, &nonce, abort_reason);
    assert_eq!(
        coordinator.abort_before_effect(
            "run.1",
            entered.revision,
            &binding,
            &nonce_hex,
            &abort_proof,
            abort_reason,
        ),
        Err(AgentRunError::InvalidTransition)
    );
}
''',
)

# ---------------------------------------------------------------------------
# Wire protocol, client, and state-control handler for exact effect entry.
# ---------------------------------------------------------------------------
PROTO = "codex-rs/hepta-agent-protocol/src/lib.rs"
replace_once(
    PROTO,
    "pub const AGENTD_RUN_LIFECYCLE_CAPABILITY_MINOR: u16 = 2;",
    "pub const AGENTD_RUN_LIFECYCLE_CAPABILITY_MINOR: u16 = 3;",
)
replace_once(
    PROTO,
    """    pub pre_effect_abort_proof_digest: Option<String>,
    pub cancel_reason: Option<String>,
""",
    """    pub pre_effect_abort_proof_digest: Option<String>,
    #[serde(default, skip_serializing_if = \"Option::is_none\")]
    pub pre_effect_entry_proof_digest: Option<String>,
    pub cancel_reason: Option<String>,
""",
)
replace_once(
    PROTO,
    """    pub fn run_abort_before_effect(
""",
    """    pub fn run_enter_effect(
        request_id: u64,
        spawn_generation: u64,
        run_id: String,
        expected_revision: u64,
        dispatch_binding_digest: String,
        effect_nonce_hex: String,
        proof_digest: String,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::RunEnterEffect {
                run_id,
                expected_revision,
                dispatch_binding_digest,
                effect_nonce_hex,
                proof_digest,
            },
        }
    }

    pub fn run_abort_before_effect(
""",
)
replace_once(
    PROTO,
    """    RunAbortBeforeEffect {
""",
    """    RunEnterEffect {
        run_id: String,
        expected_revision: u64,
        dispatch_binding_digest: String,
        effect_nonce_hex: String,
        proof_digest: String,
    },
    RunAbortBeforeEffect {
""",
)

CLIENT = "codex-rs/hepta-agentd/src/client.rs"
replace_once(
    CLIENT,
    """    pub async fn run_abort_before_effect(
""",
    """    pub async fn run_enter_effect(
        &self,
        run_id: String,
        expected_revision: u64,
        dispatch_binding_digest: String,
        effect_nonce_hex: String,
        proof_digest: String,
    ) -> Result<AgentRunReceipt, AgentdError> {
        match self
            .send(AgentdRequest::run_enter_effect(
                self.request_id(),
                self.spawn_generation,
                run_id,
                expected_revision,
                dispatch_binding_digest,
                effect_nonce_hex,
                proof_digest,
            ))
            .await?
            .payload
        {
            AgentdPayload::RunReceipt(receipt) => Ok(receipt),
            payload => unexpected(payload),
        }
    }

    pub async fn run_abort_before_effect(
""",
)

STATE = "codex-rs/hepta-agentd/src/state_control.rs"
replace_once(
    STATE,
    """            crate::AgentdMethod::RunAbortBeforeEffect {
""",
    """            crate::AgentdMethod::RunEnterEffect {
                run_id,
                expected_revision,
                dispatch_binding_digest,
                effect_nonce_hex,
                proof_digest,
            } => {
                require_run_reconciliation_ready(lifecycle, fenced)?;
                let receipt = self
                    .runs
                    .lock()
                    .map_err(poisoned_state)?
                    .enter_effect(
                        &run_id,
                        expected_revision,
                        &dispatch_binding_digest,
                        &effect_nonce_hex,
                        &proof_digest,
                    )
                    .map_err(run_error)?;
                AgentdPayload::RunReceipt(wire_run_receipt(receipt))
            }
            crate::AgentdMethod::RunAbortBeforeEffect {
""",
)
replace_once(
    STATE,
    """        pre_effect_abort_proof_digest: value.pre_effect_abort_proof_digest,
        cancel_reason: value.cancel_reason,
""",
    """        pre_effect_abort_proof_digest: value.pre_effect_abort_proof_digest,
        pre_effect_entry_proof_digest: value.pre_effect_entry_proof_digest,
        cancel_reason: value.cancel_reason,
""",
)

# ---------------------------------------------------------------------------
# Worker: retain typestate/deadline/thread guard, adapt it to the newer owners.
# ---------------------------------------------------------------------------
APP = "codex-rs/hepta-infer-worker-host/src/native_app_server.rs"
replace_once(
    APP,
    "use codex_hepta_infer_core::durable_control::native::NativeOwnerDispatchBinding;\n",
    "",
)

sub_once(
    APP,
    r"async fn abort_pre_effect_consistently\(.*?\nfn final_use_binding\(",
    textwrap.dedent(
        r'''
async fn abort_pre_effect_consistently(
    control: &mut DurableInferenceControl,
    owner: &AgentdClient,
    intelligence: Option<&NativeIntelligenceRunBinding>,
    token: NativePreEffectAbortToken,
    dispatch_digest: Digest32,
    reason: String,
) -> Result<()> {
    let reason: String = reason.chars().take(512).collect();
    let Some(binding) = intelligence else {
        control.abort_native_before_effect(token, reason)?;
        return Ok(());
    };

    let dispatch_digest = dispatch_digest.to_string();
    let commitment = token.commitment_digest(&binding.run_id, &dispatch_digest)?;
    let status = owner
        .run_status(binding.run_id.clone())
        .await?
        .ok_or("Agentd run disappeared while reconciling pre-effect abort")?;

    if status.phase == AgentRunPhase::ContextAttached
        && status.revision == binding.expected_revision
        && status.dispatch_binding_digest.is_none()
    {
        let cancelled = owner
            .run_cancel(
                binding.run_id.clone(),
                status.revision,
                reason.clone(),
            )
            .await?;
        if cancelled.receipt.phase != AgentRunPhase::Cancelled {
            return Err("Agentd did not close the pre-dispatch run".into());
        }
        control.abort_native_before_effect(token, reason)?;
        return Ok(());
    }

    if status.phase != AgentRunPhase::Dispatched
        || status.dispatch_binding_digest.as_deref() != Some(dispatch_digest.as_str())
        || status.pre_effect_abort_commitment_digest.as_deref() != Some(commitment.as_str())
        || status.pre_effect_entry_proof_digest.is_some()
    {
        return Err(
            "Agentd dispatch/effect-entry state does not permit a pre-effect abort".into(),
        );
    }

    let prepared = control.prepare_native_abort_before_effect(
        token,
        binding.run_id.clone(),
        status.revision,
        dispatch_digest.clone(),
        reason.clone(),
    )?;
    let abort = prepared
        .pre_effect_abort
        .as_ref()
        .ok_or("prepared native abort omitted its proof")?
        .clone();
    let receipt = match owner
        .run_abort_before_effect(
            binding.run_id.clone(),
            status.revision,
            dispatch_digest.clone(),
            abort.abort_nonce_hex.clone(),
            abort.proof_digest.clone(),
            reason,
        )
        .await
    {
        Ok(receipt) => receipt,
        Err(error) => {
            let reconciled = owner
                .run_status(binding.run_id.clone())
                .await?
                .ok_or_else(|| {
                    format!("Agentd abort acknowledgement unknown and run disappeared: {error}")
                })?;
            if reconciled.phase != AgentRunPhase::AbortedBeforeEffect
                || reconciled.dispatch_binding_digest.as_deref()
                    != Some(dispatch_digest.as_str())
                || reconciled.pre_effect_abort_proof_digest.as_deref()
                    != Some(abort.proof_digest.as_str())
            {
                return Err(format!(
                    "Agentd abort acknowledgement remains unresolved: {error}"
                )
                .into());
            }
            reconciled
        }
    };
    if receipt.phase != AgentRunPhase::AbortedBeforeEffect
        || receipt.dispatch_binding_digest.as_deref() != Some(dispatch_digest.as_str())
        || receipt.pre_effect_abort_proof_digest.as_deref()
            != Some(abort.proof_digest.as_str())
    {
        return Err("Agentd did not acknowledge the exact pre-effect abort".into());
    }
    control.confirm_native_abort_before_effect(
        &prepared.request.request_id,
        &abort.proof_digest,
    )?;
    Ok(())
}

async fn enter_effect_consistently(
    control: &mut DurableInferenceControl,
    owner: &AgentdClient,
    intelligence: Option<&NativeIntelligenceRunBinding>,
    token: NativePreEffectAbortToken,
    request_id: &str,
    prepared_revision: u64,
    owner_dispatch_revision: Option<u64>,
    dispatch_digest: Digest32,
) -> Result<u64> {
    let dispatch_digest = dispatch_digest.to_string();
    let (owner_run_id, dispatch_revision) = match (intelligence, owner_dispatch_revision) {
        (Some(binding), Some(revision)) => (binding.run_id.clone(), revision),
        (None, None) => (
            format!("local:{}", Digest32::of_bytes(request_id.as_bytes())),
            prepared_revision,
        ),
        _ => return Err("runtime.codex owner dispatch revision is inconsistent".into()),
    };
    let claim = token.into_effect_entry_claim(
        owner_run_id.clone(),
        dispatch_revision,
        dispatch_digest.clone(),
    )?;
    let proof_digest = claim.proof_digest().to_string();

    let owner_effect_revision = if intelligence.is_some() {
        let receipt = match owner
            .run_enter_effect(
                owner_run_id.clone(),
                dispatch_revision,
                dispatch_digest.clone(),
                claim.effect_nonce_hex().to_string(),
                proof_digest.clone(),
            )
            .await
        {
            Ok(receipt) => receipt,
            Err(error) => {
                let reconciled = owner
                    .run_status(owner_run_id.clone())
                    .await?
                    .ok_or_else(|| {
                        format!("Agentd effect-entry acknowledgement unknown and run disappeared: {error}")
                    })?;
                if reconciled.phase != AgentRunPhase::Dispatched
                    || reconciled.dispatch_binding_digest.as_deref()
                        != Some(dispatch_digest.as_str())
                    || reconciled.pre_effect_entry_proof_digest.as_deref()
                        != Some(proof_digest.as_str())
                {
                    return Err(format!(
                        "Agentd effect-entry acknowledgement remains unresolved: {error}"
                    )
                    .into());
                }
                reconciled
            }
        };
        if receipt.phase != AgentRunPhase::Dispatched
            || receipt.dispatch_binding_digest.as_deref() != Some(dispatch_digest.as_str())
            || receipt.pre_effect_entry_proof_digest.as_deref()
                != Some(proof_digest.as_str())
        {
            return Err("Agentd effect-entry receipt lost the exact dispatch binding".into());
        }
        receipt.revision
    } else {
        prepared_revision
    };

    control.confirm_native_effect_entry(claim, owner_effect_revision)?;
    Ok(owner_effect_revision)
}

impl AppServerModelDriver {
    pub(super) async fn reconcile_pending_pre_effect_abort(
        &self,
        control: &mut DurableInferenceControl,
        record: &NativeRunRecord,
    ) -> Result<()> {
        let abort = record
            .pre_effect_abort
            .as_ref()
            .ok_or("pending pre-effect abort omitted its proof")?
            .clone();
        let owner = AgentdClient::new(
            self.config.agentd_socket.clone(),
            self.config.agent_id.clone(),
            self.config.generation,
        )?;
        let status = owner
            .run_status(abort.owner_run_id.clone())
            .await?
            .ok_or("Agentd run disappeared while recovering pre-effect abort")?;
        let receipt = if status.phase == AgentRunPhase::AbortedBeforeEffect {
            status
        } else if status.phase == AgentRunPhase::Dispatched
            && status.revision == abort.owner_dispatch_revision
            && status.dispatch_binding_digest.as_deref()
                == Some(abort.dispatch_binding_digest.as_str())
            && status.pre_effect_abort_commitment_digest.as_deref()
                == Some(abort.commitment_digest.as_str())
            && status.pre_effect_entry_proof_digest.is_none()
        {
            owner
                .run_abort_before_effect(
                    abort.owner_run_id.clone(),
                    abort.owner_dispatch_revision,
                    abort.dispatch_binding_digest.clone(),
                    abort.abort_nonce_hex.clone(),
                    abort.proof_digest.clone(),
                    abort.reason.clone(),
                )
                .await?
        } else {
            return Err("Agentd state cannot reconcile the pending pre-effect abort".into());
        };
        if receipt.phase != AgentRunPhase::AbortedBeforeEffect
            || receipt.dispatch_binding_digest.as_deref()
                != Some(abort.dispatch_binding_digest.as_str())
            || receipt.pre_effect_abort_proof_digest.as_deref()
                != Some(abort.proof_digest.as_str())
        {
            return Err("Agentd pending abort acknowledgement mismatched".into());
        }
        control.confirm_native_abort_before_effect(
            &record.request.request_id,
            &abort.proof_digest,
        )?;
        Ok(())
    }
}

fn final_use_binding(
'''
    ).lstrip("\n"),
)

RUN = "codex-rs/hepta-infer-worker-host/src/native_run_control.rs"
replace_once(
    RUN,
    """        let record = control.reserve_native(request, admission.maximum_in_flight)?;
        if let Some(reason) = &record.pre_dispatch_stop {
""",
    """        let mut record = control.reserve_native(request, admission.maximum_in_flight)?;
        if record.state == NativeReservationState::AbortPending {
            self.reconcile_pending_pre_effect_abort(control, &record)
                .await?;
            record = control
                .native_record(&record.request.request_id)
                .ok_or("native record disappeared after abort reconciliation")?
                .clone();
        }
        if let Some(reason) = &record.pre_dispatch_stop {
""",
)

EXEC = "codex-rs/hepta-infer-worker-host/src/native_execution.rs"
replace_once(
    EXEC,
    """        let owner_dispatch = intelligence.map(|binding| NativeOwnerDispatchBinding {
            run_id: binding.run_id.clone(),
            pre_dispatch_revision: binding.expected_revision,
            dispatch_digest: request_receipt.request_digest.to_string(),
        });
""",
    "",
)
replace_once(
    EXEC,
    """        let (_, pre_effect_abort) = match owner_dispatch {
            Some(binding) => control
                .dispatch_native_with_pre_effect_abort_bound(request_id, dispatch, binding)?,
            None => control.dispatch_native_with_pre_effect_abort(request_id, dispatch)?,
        };
""",
    """        let (_, pre_effect_abort) =
            control.dispatch_native_with_pre_effect_abort(request_id, dispatch)?;
        let abort_commitment = intelligence
            .map(|binding| {
                pre_effect_abort.commitment_digest(&binding.run_id, &dispatch_digest)
            })
            .transpose()?;
""",
)
replace_once(
    EXEC,
    """        let mut owner_abort_required = intelligence.is_some();
        let preparation: Result<(EnteredUseToken, Duration)> = async {
""",
    """        let preparation: Result<EnteredUseToken> = async {
""",
)

sub_once(
    EXEC,
    r"            if let Some\(binding\) = intelligence \{.*?\n            let post_health = owner\.health\(\)\.await\?;",
    textwrap.dedent(
        r'''
            if let Some(binding) = intelligence {
                let commitment = abort_commitment
                    .clone()
                    .ok_or("missing runtime.codex abort commitment")?;
                let dispatched = owner
                    .run_mark_dispatched_bound(
                        binding.run_id.clone(),
                        binding.expected_revision,
                        dispatch_digest.clone(),
                        commitment.clone(),
                    )
                    .await?;
                if dispatched.phase != AgentRunPhase::Dispatched
                    || dispatched.dispatch_binding_digest.as_deref()
                        != Some(dispatch_digest.as_str())
                    || dispatched.pre_effect_abort_commitment_digest.as_deref()
                        != Some(commitment.as_str())
                    || dispatched.pre_effect_entry_proof_digest.is_some()
                    || dispatched.generation != self.config.generation
                    || dispatched.terminal_observed
                    || dispatched.context_digest.as_deref()
                        != Some(binding.context_digest.as_str())
                    || dispatched.compilation_receipt_digest.as_deref()
                        != Some(binding.envelope_digest.as_str())
                {
                    return Err(
                        "Agentd did not commit this exact runtime.codex dispatch".into(),
                    );
                }
                intelligence_revision = Some(dispatched.revision);
            }
            let post_health = owner.health().await?;
'''
    ).lstrip("\n").rstrip("\n"),
)

replace_once(
    EXEC,
    """            let send_budget = execution_clock.remaining(unix_time_ms()?)?.min(RPC_TIMEOUT);
            let entered_use = verified_use.enter(&authority_binding)?;
""",
    """            let entered_use = verified_use.enter(&authority_binding)?;
""",
)
replace_once(EXEC, "            Ok((entered_use, send_budget))\n", "            Ok(entered_use)\n")

sub_once(
    EXEC,
    r"        let \(entered_use, send_budget\) = match preparation \{.*?\n        \};\n        // From here on, a missing acknowledgement is reconcile-only\..*?\n        let response = timeout\(",
    textwrap.dedent(
        r'''
        let entered_use = match preparation {
            Ok(value) => value,
            Err(error) => {
                let reason: String = error.to_string().chars().take(512).collect();
                let stopped = abort_pre_effect_consistently(
                    control,
                    &owner,
                    intelligence,
                    pre_effect_abort,
                    request_receipt.request_digest,
                    reason,
                )
                .await;
                thread_guard.cleanup().await;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                stopped?;
                return Err(error);
            }
        };

        let owner_dispatch_revision = intelligence_revision;
        let attempt = attempt
            .prepare_durable(request_receipt.request_digest)?
            .commit_owner(
                owner_dispatch_revision.unwrap_or(prepared_revision),
                request_receipt.request_digest,
            )?;
        let effect_revision = match enter_effect_consistently(
            control,
            &owner,
            intelligence,
            pre_effect_abort,
            request_id,
            prepared_revision,
            owner_dispatch_revision,
            request_receipt.request_digest,
        )
        .await
        {
            Ok(revision) => revision,
            Err(error) => {
                thread_guard.cleanup().await;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Ok(indeterminate_start_output(
                    started,
                    format!(
                        "runtime.codex effect-entry acknowledgement unknown ({error}); no turn/start was issued; reconcile the same operation"
                    ),
                ));
            }
        };
        if intelligence.is_some() {
            intelligence_revision = Some(effect_revision);
        }
        let send_budget = match execution_clock.remaining(unix_time_ms()) {
            Ok(remaining) => remaining.min(RPC_TIMEOUT),
            Err(error) => {
                thread_guard.cleanup().await;
                let _ = timeout(RPC_TIMEOUT, client.shutdown()).await;
                return Ok(indeterminate_start_output(
                    started,
                    format!(
                        "runtime.codex deadline elapsed after durable effect entry ({error}); no turn/start was issued; reconcile the same operation"
                    ),
                ));
            }
        };
        thread_guard.effect_entered();
        let attempt = attempt.enter_effect();
        let response = timeout(
'''
    ).lstrip("\n"),
)

# The split-source ordering test must inspect the actual execution file.
replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs",
    """    let source = include_str!(\"native_app_server.rs\");
""",
    """    let source = include_str!(\"native_execution.rs\");
""",
)

# ---------------------------------------------------------------------------
# Sanity checks: stale APIs are forbidden after the repair.
# ---------------------------------------------------------------------------
for path, forbidden in [
    (EXEC, "NativeOwnerDispatchBinding"),
    (EXEC, "dispatch_native_with_pre_effect_abort_bound"),
    (EXEC, "run_mark_dispatched_exact"),
    (APP, "complete_native_abort_before_effect"),
    (APP, "pre_effect_abort_pending"),
]:
    if forbidden in read(path):
        raise SystemExit(f"{path}: stale API remains: {forbidden}")

print("runtime.codex full-convergence source repair applied")
