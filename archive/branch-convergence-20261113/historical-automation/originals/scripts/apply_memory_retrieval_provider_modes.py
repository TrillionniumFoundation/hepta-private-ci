#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def replace_once(rel: str, old: str, new: str) -> None:
    text = read(rel)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{rel}: expected one occurrence, found {count}: {old[:120]!r}")
    write(rel, text.replace(old, new, 1))


def regex_once(rel: str, pattern: str, replacement: str) -> None:
    text = read(rel)
    rendered, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{rel}: regex matched {count}: {pattern[:120]!r}")
    write(rel, rendered)


# ---------------------------------------------------------------------------
# Product-owned, lease-bound current-context provider.
# ---------------------------------------------------------------------------
write(
    "codex-rs/hepta-agentd/src/cognitive_retrieval_context.rs",
    r'''//! Product-owned current retrieval-context provider.
//!
//! The provider owns no model execution or memory store. It holds one verified,
//! generation-bound retrieval context behind an expiring lease. Rotation,
//! revocation and restart recovery are optimistic-revision operations; stale
//! writers cannot replace a newer context. Agentd still requires the provider to
//! be supplied explicitly by protected host configuration.

use std::sync::RwLock;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_memory::RetrievalExecutionContextV1;
use codex_hepta_types::Digest32;

const GENERATION_IDENTITY_DOMAIN: &[u8] = b"hepta.agentd.retrieval-generation-identity.v1";
const PROVIDER_SNAPSHOT_DOMAIN: &[u8] = b"hepta.agentd.retrieval-provider-snapshot.v1";

pub trait CurrentMemoryRetrievalContext: Send + Sync {
    fn current(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<RetrievalExecutionContextV1, String>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryRetrievalContextSnapshotV1 {
    pub owner: AgentId,
    pub body_generation: u64,
    pub revision: u64,
    pub issued_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
    pub revoked: bool,
    pub context: RetrievalExecutionContextV1,
    pub context_binding_digest: Digest32,
    pub generation_identity_digest: Digest32,
    pub snapshot_digest: Digest32,
}

impl MemoryRetrievalContextSnapshotV1 {
    fn new(
        owner: AgentId,
        body_generation: u64,
        revision: u64,
        issued_at_unix_ms: u64,
        expires_at_unix_ms: u64,
        revoked: bool,
        context: RetrievalExecutionContextV1,
    ) -> Result<Self, String> {
        let mut value = Self {
            owner,
            body_generation,
            revision,
            issued_at_unix_ms,
            expires_at_unix_ms,
            revoked,
            context_binding_digest: context.binding_digest(),
            generation_identity_digest: generation_identity_digest(&context),
            context,
            snapshot_digest: Digest32::ZERO,
        };
        value.snapshot_digest = value.compute_snapshot_digest();
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.body_generation == 0 {
            return Err("retrieval provider body generation must be non-zero".to_string());
        }
        if self.revision == 0 {
            return Err("retrieval provider revision must be non-zero".to_string());
        }
        if self.issued_at_unix_ms >= self.expires_at_unix_ms {
            return Err("retrieval provider lease interval is empty".to_string());
        }
        self.context
            .validate()
            .map_err(|error| format!("invalid retrieval execution context: {error}"))?;
        if self.context_binding_digest != self.context.binding_digest() {
            return Err("retrieval provider context binding digest mismatch".to_string());
        }
        if self.generation_identity_digest != generation_identity_digest(&self.context) {
            return Err("retrieval provider generation identity mismatch".to_string());
        }
        if self.snapshot_digest != self.compute_snapshot_digest() {
            return Err("retrieval provider snapshot digest mismatch".to_string());
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_snapshot_digest(&self) -> Digest32 {
        let mut bytes = PROVIDER_SNAPSHOT_DOMAIN.to_vec();
        push_bytes(&mut bytes, self.owner.as_str().as_bytes());
        bytes.extend_from_slice(&self.body_generation.to_be_bytes());
        bytes.extend_from_slice(&self.revision.to_be_bytes());
        bytes.extend_from_slice(&self.issued_at_unix_ms.to_be_bytes());
        bytes.extend_from_slice(&self.expires_at_unix_ms.to_be_bytes());
        bytes.push(u8::from(self.revoked));
        bytes.extend_from_slice(self.context_binding_digest.as_array());
        bytes.extend_from_slice(self.generation_identity_digest.as_array());
        Digest32::of_bytes(&bytes)
    }
}

pub struct ProductMemoryRetrievalContextV1 {
    state: RwLock<MemoryRetrievalContextSnapshotV1>,
}

impl ProductMemoryRetrievalContextV1 {
    pub fn new(
        owner: AgentId,
        body_generation: u64,
        context: RetrievalExecutionContextV1,
        issued_at_unix_ms: u64,
        expires_at_unix_ms: u64,
    ) -> Result<Self, String> {
        Ok(Self {
            state: RwLock::new(MemoryRetrievalContextSnapshotV1::new(
                owner,
                body_generation,
                1,
                issued_at_unix_ms,
                expires_at_unix_ms,
                false,
                context,
            )?),
        })
    }

    pub fn recover(snapshot: MemoryRetrievalContextSnapshotV1) -> Result<Self, String> {
        snapshot.validate()?;
        Ok(Self {
            state: RwLock::new(snapshot),
        })
    }

    pub fn snapshot(&self) -> Result<MemoryRetrievalContextSnapshotV1, String> {
        self.state
            .read()
            .map_err(|_| "retrieval provider read lock poisoned".to_string())
            .map(|state| state.clone())
    }

    pub fn rotate(
        &self,
        expected_revision: u64,
        context: RetrievalExecutionContextV1,
        issued_at_unix_ms: u64,
        expires_at_unix_ms: u64,
    ) -> Result<MemoryRetrievalContextSnapshotV1, String> {
        let mut state = self
            .state
            .write()
            .map_err(|_| "retrieval provider write lock poisoned".to_string())?;
        if state.revision != expected_revision {
            return Err(format!(
                "retrieval provider revision conflict: expected {expected_revision}, current {}",
                state.revision
            ));
        }
        let revision = state
            .revision
            .checked_add(1)
            .ok_or_else(|| "retrieval provider revision overflow".to_string())?;
        let next = MemoryRetrievalContextSnapshotV1::new(
            state.owner.clone(),
            state.body_generation,
            revision,
            issued_at_unix_ms,
            expires_at_unix_ms,
            false,
            context,
        )?;
        *state = next.clone();
        Ok(next)
    }

    pub fn revoke(
        &self,
        expected_revision: u64,
    ) -> Result<MemoryRetrievalContextSnapshotV1, String> {
        let mut state = self
            .state
            .write()
            .map_err(|_| "retrieval provider write lock poisoned".to_string())?;
        if state.revision != expected_revision {
            return Err(format!(
                "retrieval provider revision conflict: expected {expected_revision}, current {}",
                state.revision
            ));
        }
        let revision = state
            .revision
            .checked_add(1)
            .ok_or_else(|| "retrieval provider revision overflow".to_string())?;
        let next = MemoryRetrievalContextSnapshotV1::new(
            state.owner.clone(),
            state.body_generation,
            revision,
            state.issued_at_unix_ms,
            state.expires_at_unix_ms,
            true,
            state.context.clone(),
        )?;
        *state = next.clone();
        Ok(next)
    }
}

impl CurrentMemoryRetrievalContext for ProductMemoryRetrievalContextV1 {
    fn current(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<RetrievalExecutionContextV1, String> {
        let state = self.snapshot()?;
        state.validate()?;
        if &state.owner != owner || state.body_generation != body_generation {
            return Err("retrieval provider identity or generation mismatch".to_string());
        }
        if state.revoked {
            return Err("retrieval provider context is revoked".to_string());
        }
        let now = now_unix_ms()?;
        if now < state.issued_at_unix_ms || now >= state.expires_at_unix_ms {
            return Err("retrieval provider lease is not current".to_string());
        }
        Ok(state.context)
    }
}

fn generation_identity_digest(context: &RetrievalExecutionContextV1) -> Digest32 {
    let vector = &context.generation_vector;
    let mut bytes = GENERATION_IDENTITY_DOMAIN.to_vec();
    bytes.extend_from_slice(vector.digest().as_array());
    bytes.extend_from_slice(vector.retrieval_profile_digest.as_array());
    bytes.extend_from_slice(vector.encoder_preprocessor_digest.as_array());
    bytes.extend_from_slice(vector.model_digest.as_array());
    bytes.extend_from_slice(vector.tokenizer_digest.as_array());
    bytes.extend_from_slice(vector.template_digest.as_array());
    bytes.extend_from_slice(vector.tool_schema_digest.as_array());
    bytes.extend_from_slice(context.retrieval_policy.digest().as_array());
    bytes.extend_from_slice(context.engram_snapshot.snapshot_digest.as_array());
    bytes.extend_from_slice(context.dynamics_policy.digest().as_array());
    Digest32::of_bytes(&bytes)
}

fn now_unix_ms() -> Result<u64, String> {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|error| format!("system clock before Unix epoch: {error}"))?
            .as_millis(),
    )
    .map_err(|error| format!("system clock milliseconds overflow: {error}"))
}

fn push_bytes(bytes: &mut Vec<u8>, value: &[u8]) {
    bytes.extend_from_slice(&u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(value);
}

#[cfg(test)]
#[path = "cognitive_retrieval_context_tests.rs"]
mod tests;
''',
)

write(
    "codex-rs/hepta-agentd/src/cognitive_retrieval_context_tests.rs",
    r'''use super::*;

use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_memory::sqlite_owner_cue_profile_digest;
use codex_hepta_memory::sqlite_owner_retrieval_policy_v1;
use codex_hepta_memory_retrieval::EngramDynamicsPolicyV1;
use codex_hepta_memory_retrieval::EngramSnapshotV1;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn owner() -> AgentId {
    AgentId::parse("00000000-0000-4000-8000-000000000321").expect("owner")
}

fn context(suffix: &str) -> RetrievalExecutionContextV1 {
    let policy = sqlite_owner_retrieval_policy_v1().expect("policy");
    let external = digest(&format!("provider-external-{suffix}"));
    let generation_vector = LaneCGenerationVectorV1 {
        scope_id: StableId::new(format!("scope:provider:{suffix}")).expect("scope"),
        purpose_id: StableId::new("purpose:provider-recall").expect("purpose"),
        memory_ledger_frontier: 1,
        knowledge_fact_frontier: 1,
        tombstone_frontier: 1,
        source_ledger_frontier: 1,
        knowledge_graph_generation: Generation::new(1).expect("kg generation"),
        compact_checkpoint_generation: Generation::new(1).expect("compact generation"),
        prompt_registry_revision: Revision::new(1).expect("prompt revision"),
        retrieval_profile_digest: policy.digest(),
        encoder_preprocessor_digest: external,
        authority_epoch: 1,
        model_digest: external,
        tokenizer_digest: external,
        template_digest: external,
        tool_schema_digest: external,
    };
    let vector_digest = generation_vector.digest();
    let context = RetrievalExecutionContextV1 {
        generation_vector,
        objective_digest: digest(&format!("objective-{suffix}")),
        approved_context_digest: digest(&format!("approved-{suffix}")),
        cue_profile_digest: sqlite_owner_cue_profile_digest(),
        retrieval_policy: policy,
        engram_snapshot: EngramSnapshotV1::new(
            vector_digest,
            digest(&format!("engram-{suffix}")),
            Vec::new(),
            Vec::new(),
        )
        .expect("engram"),
        dynamics_policy: EngramDynamicsPolicyV1::product_default().expect("dynamics"),
    };
    context.validate().expect("context");
    context
}

fn lease_window() -> (u64, u64) {
    let now = now_unix_ms().expect("clock");
    (now.saturating_sub(1_000), now.saturating_add(60_000))
}

#[test]
fn provider_binds_common_generation_identity_and_current_lease() {
    let (issued, expires) = lease_window();
    let provider = ProductMemoryRetrievalContextV1::new(
        owner(),
        7,
        context("initial"),
        issued,
        expires,
    )
    .expect("provider");
    let current = provider.current(&owner(), 7).expect("current");
    let snapshot = provider.snapshot().expect("snapshot");
    assert_eq!(current.binding_digest(), snapshot.context_binding_digest);
    assert_eq!(
        generation_identity_digest(&current),
        snapshot.generation_identity_digest
    );
    assert!(!snapshot.snapshot_digest.is_zero());
}

#[test]
fn rotation_is_revision_fenced_and_recovery_preserves_current_state() {
    let (issued, expires) = lease_window();
    let provider = ProductMemoryRetrievalContextV1::new(
        owner(),
        7,
        context("initial"),
        issued,
        expires,
    )
    .expect("provider");
    let rotated = provider
        .rotate(1, context("rotated"), issued, expires)
        .expect("rotate");
    assert_eq!(rotated.revision, 2);
    assert!(provider.rotate(1, context("stale"), issued, expires).is_err());
    let recovered = ProductMemoryRetrievalContextV1::recover(rotated.clone()).expect("recover");
    assert_eq!(recovered.snapshot().expect("snapshot"), rotated);
    assert_eq!(
        recovered.current(&owner(), 7).expect("current").objective_digest,
        context("rotated").objective_digest
    );
}

#[test]
fn revocation_and_expiry_fail_closed_across_recovery() {
    let (issued, expires) = lease_window();
    let provider = ProductMemoryRetrievalContextV1::new(
        owner(),
        7,
        context("revoked"),
        issued,
        expires,
    )
    .expect("provider");
    let revoked = provider.revoke(1).expect("revoke");
    assert!(provider.current(&owner(), 7).is_err());
    let recovered = ProductMemoryRetrievalContextV1::recover(revoked).expect("recover");
    assert!(recovered.current(&owner(), 7).is_err());

    let expired = ProductMemoryRetrievalContextV1::new(
        owner(),
        7,
        context("expired"),
        1,
        2,
    )
    .expect("expired provider");
    assert!(expired.current(&owner(), 7).is_err());
}

#[test]
fn identity_generation_and_snapshot_tampering_are_rejected() {
    let (issued, expires) = lease_window();
    let provider = ProductMemoryRetrievalContextV1::new(
        owner(),
        7,
        context("identity"),
        issued,
        expires,
    )
    .expect("provider");
    let other = AgentId::parse("00000000-0000-4000-8000-000000000322").expect("other");
    assert!(provider.current(&other, 7).is_err());
    assert!(provider.current(&owner(), 8).is_err());

    let mut tampered = provider.snapshot().expect("snapshot");
    tampered.context.objective_digest = digest("tampered-objective");
    tampered.snapshot_digest = tampered.compute_snapshot_digest();
    assert!(ProductMemoryRetrievalContextV1::recover(tampered).is_err());
}
''',
)

# ---------------------------------------------------------------------------
# Four explicit product modes and deterministic canary selection.
# ---------------------------------------------------------------------------
CONFIG = "codex-rs/hepta-agentd/src/config.rs"
replace_once(
    CONFIG,
    """#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CognitiveRetrievalMode {
    Compatibility,
    HnmfRequired,
}

impl CognitiveRetrievalMode {
    #[must_use]
    pub const fn requires_current_context(self) -> bool {
        matches!(self, Self::HnmfRequired)
    }
}""",
    """#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CognitiveRetrievalMode {
    Compatibility,
    Shadow,
    Canary,
    HnmfRequired,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum CognitiveRetrievalApplication {
    Compatibility,
    ObserveOnly,
    Apply,
}

pub const COGNITIVE_RETRIEVAL_CANARY_DENOMINATOR: u64 = 16;

impl CognitiveRetrievalMode {
    #[must_use]
    pub const fn requires_current_context(self) -> bool {
        !matches!(self, Self::Compatibility)
    }

    #[must_use]
    pub const fn application(self, request_id: u64) -> CognitiveRetrievalApplication {
        match self {
            Self::Compatibility => CognitiveRetrievalApplication::Compatibility,
            Self::Shadow => CognitiveRetrievalApplication::ObserveOnly,
            Self::Canary => {
                if request_id % COGNITIVE_RETRIEVAL_CANARY_DENOMINATOR == 0 {
                    CognitiveRetrievalApplication::Apply
                } else {
                    CognitiveRetrievalApplication::ObserveOnly
                }
            }
            Self::HnmfRequired => CognitiveRetrievalApplication::Apply,
        }
    }
}

impl CognitiveRetrievalApplication {
    #[must_use]
    pub const fn applies_selection(self) -> bool {
        matches!(self, Self::Apply)
    }
}""",
)
replace_once(
    CONFIG,
    """    match value.as_str() {
        "compatibility" => Ok(CognitiveRetrievalMode::Compatibility),
        "hnmf-required" => Ok(CognitiveRetrievalMode::HnmfRequired),
        _ => Err(AgentdError::Invalid(format!(
            "{HEPTA_COGNITIVE_RETRIEVAL_MODE_ENV} must be compatibility or hnmf-required"
        ))),
    }""",
    """    match value.as_str() {
        "compatibility" => Ok(CognitiveRetrievalMode::Compatibility),
        "shadow" => Ok(CognitiveRetrievalMode::Shadow),
        "canary" => Ok(CognitiveRetrievalMode::Canary),
        "required" | "hnmf-required" => Ok(CognitiveRetrievalMode::HnmfRequired),
        _ => Err(AgentdError::Invalid(format!(
            "{HEPTA_COGNITIVE_RETRIEVAL_MODE_ENV} must be compatibility, shadow, canary, required or hnmf-required"
        ))),
    }""",
)
replace_once(
    CONFIG,
    """    /// Select the retrieval product profile explicitly. Compatibility preserves
    /// the legacy owner-ranked path. HnmfRequired forbids startup without a
    /// current authenticated retrieval context and never silently falls back.""",
    """    /// Select the retrieval product profile explicitly. Compatibility preserves
    /// the owner-ranked path. Shadow evaluates HNMF without changing delivery,
    /// Canary applies it to a deterministic bounded request sample, and
    /// HnmfRequired applies it to every request. Every non-compatibility mode
    /// requires a current authenticated retrieval context and never falls back.""",
)

# ---------------------------------------------------------------------------
# Runtime/state composition retains the exact mode selected at startup.
# ---------------------------------------------------------------------------
STATE = "codex-rs/hepta-agentd/src/state.rs"
replace_once(STATE, "use std::sync::Mutex;", "use std::sync::Mutex;\nuse std::sync::RwLock;")
replace_once(
    STATE,
    """    pub(crate) cognitive_retrieval_learning:
        std::sync::OnceLock<Arc<crate::CognitiveRetrievalLearningSink>>,""",
    """    pub(crate) cognitive_retrieval_learning:
        std::sync::OnceLock<Arc<crate::CognitiveRetrievalLearningSink>>,
    cognitive_retrieval_mode: RwLock<crate::CognitiveRetrievalMode>,""",
)
replace_once(
    STATE,
    """            cognitive_retrieval_context: std::sync::OnceLock::new(),
            cognitive_retrieval_learning: std::sync::OnceLock::new(),""",
    """            cognitive_retrieval_context: std::sync::OnceLock::new(),
            cognitive_retrieval_learning: std::sync::OnceLock::new(),
            cognitive_retrieval_mode: RwLock::new(crate::CognitiveRetrievalMode::Compatibility),""",
)
replace_once(
    STATE,
    """    pub(crate) fn attach_plasticity_runtime(
        &self,""",
    """    pub(crate) fn set_cognitive_retrieval_mode(
        &self,
        mode: crate::CognitiveRetrievalMode,
    ) -> Result<(), AgentdError> {
        *self
            .cognitive_retrieval_mode
            .write()
            .map_err(|_| AgentdError::Protocol("retrieval mode lock poisoned".to_string()))? = mode;
        Ok(())
    }

    pub(crate) fn cognitive_retrieval_mode(
        &self,
    ) -> Result<crate::CognitiveRetrievalMode, AgentdError> {
        self.cognitive_retrieval_mode
            .read()
            .map(|mode| *mode)
            .map_err(|_| AgentdError::Protocol("retrieval mode lock poisoned".to_string()))
    }

    pub(crate) fn attach_plasticity_runtime(
        &self,""",
)

RUNTIME = "codex-rs/hepta-agentd/src/runtime.rs"
replace_once(
    RUNTIME,
    """    let state = Arc::new(AgentdState::new(
        identity.clone(),
        registry,
        EVENT_CAPACITY,
    )?);
    let plasticity_runtime =""",
    """    let state = Arc::new(AgentdState::new(
        identity.clone(),
        registry,
        EVENT_CAPACITY,
    )?);
    state.set_cognitive_retrieval_mode(retrieval_mode)?;
    let plasticity_runtime =""",
)
regex_once(
    RUNTIME,
    r"fn require_cognitive_retrieval_context_for_mode\(.*?\n\}\n\n#\[cfg\(feature = \"production-cognitive-write\"\)\]",
    """fn require_cognitive_retrieval_context_for_mode(
    mode: CognitiveRetrievalMode,
    configured: bool,
) -> Result<(), AgentdError> {
    match (mode, configured) {
        (CognitiveRetrievalMode::Compatibility, false)
        | (CognitiveRetrievalMode::Shadow, true)
        | (CognitiveRetrievalMode::Canary, true)
        | (CognitiveRetrievalMode::HnmfRequired, true) => Ok(()),
        (CognitiveRetrievalMode::Compatibility, true) => Err(AgentdError::Invalid(
            "compatibility retrieval profile forbids a current HNMF context; select shadow, canary or required explicitly"
                .to_string(),
        )),
        (CognitiveRetrievalMode::Shadow, false)
        | (CognitiveRetrievalMode::Canary, false)
        | (CognitiveRetrievalMode::HnmfRequired, false) => Err(AgentdError::Invalid(format!(
            "{mode:?} retrieval profile requires a current authenticated retrieval context"
        ))),
    }
}

#[cfg(feature = "production-cognitive-write")]""",
)

# ---------------------------------------------------------------------------
# Execute HNMF in shadow/canary while changing delivery only for Apply.
# ---------------------------------------------------------------------------
CTX = "codex-rs/hepta-agentd/src/cognitive_context.rs"
replace_once(
    CTX,
    "use crate::CognitiveContextItem;",
    "use crate::CognitiveContextItem;\nuse crate::config::CognitiveRetrievalApplication;",
)
# Compatibility wrapper.
replace_once(
    CTX,
    """        None,
        None,
        None,
    )""",
    """        None,
        None,
        None,
        CognitiveRetrievalApplication::Compatibility,
    )""",
)
# Existing context wrapper must retain apply semantics.
replace_once(
    CTX,
    """        current_retrieval,
        None,
        None,
    )""",
    """        current_retrieval,
        None,
        None,
        CognitiveRetrievalApplication::Apply,
    )""",
)
replace_once(
    CTX,
    """    learning_sink: Option<&std::sync::Arc<crate::CognitiveRetrievalLearningSink>>,
    request_id: Option<u64>,
) -> Result<CognitiveContextSnapshot, CognitiveContextError> {""",
    """    learning_sink: Option<&std::sync::Arc<crate::CognitiveRetrievalLearningSink>>,
    request_id: Option<u64>,
    retrieval_application: CognitiveRetrievalApplication,
) -> Result<CognitiveContextSnapshot, CognitiveContextError> {""",
)
replace_once(
    CTX,
    """    if learning_sink.is_some() && retrieval_context.is_none() {
        return Err(CognitiveContextError::RetrievalLearningUnavailable);
    }
    let mut pending_assignment = None;""",
    """    if learning_sink.is_some() && retrieval_context.is_none() {
        return Err(CognitiveContextError::RetrievalLearningUnavailable);
    }
    match (retrieval_application, retrieval_context.is_some()) {
        (CognitiveRetrievalApplication::Compatibility, false)
        | (CognitiveRetrievalApplication::ObserveOnly, true)
        | (CognitiveRetrievalApplication::Apply, true) => {}
        _ => return Err(CognitiveContextError::RetrievalContextUnavailable),
    }
    let mut pending_assignment = None;""",
)
# Replace the selection application and compatibility sort block.
regex_once(
    CTX,
    r"        let selection_order = execution.*?\n    \} else \{\n        observed\.sort_by\(\|left, right\| \{.*?\n        \}\);\n    \}",
    """        pending_assignment = Some(execution.assignment);
        if retrieval_application.applies_selection() {
            let selection_order = execution
                .recall
                .packet
                .selections
                .iter()
                .enumerate()
                .map(|(index, selection)| {
                    (
                        (
                            selection.record_id.as_str().to_string(),
                            selection.record_revision.get(),
                        ),
                        index,
                    )
                })
                .collect::<BTreeMap<_, _>>();
            observed.retain(|candidate| {
                selection_order.contains_key(&(
                    candidate.revalidation.memory.memory_id.as_str().to_string(),
                    candidate.revalidation.memory.revision,
                ))
            });
            observed.sort_by_key(|candidate| {
                selection_order
                    .get(&(
                        candidate.revalidation.memory.memory_id.as_str().to_string(),
                        candidate.revalidation.memory.revision,
                    ))
                    .copied()
                    .unwrap_or(usize::MAX)
            });
        }
    }
    if !retrieval_application.applies_selection() {
        observed.sort_by(|left, right| {
            right
                .reciprocal_rank_score
                .cmp(&left.reciprocal_rank_score)
                .then_with(|| {
                    left.revalidation
                        .memory
                        .memory_id
                        .cmp(&right.revalidation.memory.memory_id)
                })
                .then_with(|| {
                    left.revalidation
                        .memory
                        .revision
                        .cmp(&right.revalidation.memory.revision)
                })
        });
    }""",
)
# Replace durable learning append block so shadow evidence is explicitly not exposure.
regex_once(
    CTX,
    r"    if let Some\(sink\) = learning_sink \{.*?\n    \}\n    Ok\(response\)",
    """    if let Some(sink) = learning_sink {
        let assignment =
            pending_assignment.ok_or(CognitiveContextError::RetrievalLearningUnavailable)?;
        let request_id = request_id.ok_or(CognitiveContextError::RetrievalLearningUnavailable)?;
        let (
            delivered_candidates,
            context_exposed,
            published_context_digest,
            effective_downstream_policy_digest,
            effective_delivery_propensity,
        ) = if retrieval_application.applies_selection() {
            let selected = assignment
                .selected_candidates
                .iter()
                .map(|candidate| {
                    (
                        (
                            candidate.record_id.as_str().to_string(),
                            candidate.record_revision.get(),
                        ),
                        candidate.clone(),
                    )
                })
                .collect::<BTreeMap<_, _>>();
            let delivered_candidates = response
                .items
                .iter()
                .map(|item| {
                    selected
                        .get(&(item.memory_id.clone(), item.revision))
                        .cloned()
                        .ok_or(CognitiveContextError::RetrievalLearningUnavailable)
                })
                .collect::<Result<Vec<RetrievalCandidateIdentityV1>, _>>()?;
            let context_exposed = !delivered_candidates.is_empty();
            let published_context_digest = if context_exposed {
                Some(Digest32::of_bytes(&serde_json::to_vec(&response).map_err(
                    |error| CognitiveStoreError::Invalid(error.to_string()),
                )?))
            } else {
                None
            };
            (
                delivered_candidates,
                context_exposed,
                published_context_digest,
                downstream_policy_digest,
                delivery_propensity,
            )
        } else {
            (
                Vec::new(),
                false,
                None,
                None,
                ProbabilityQ32::ONE,
            )
        };
        let sink = std::sync::Arc::clone(sink);
        let owner = owner.clone();
        tokio::task::spawn_blocking(move || {
            sink.append_with_delivery_policy(
                &owner,
                body_generation,
                request_id,
                &assignment,
                &delivered_candidates,
                context_exposed,
                published_context_digest,
                effective_downstream_policy_digest,
                effective_delivery_propensity,
            )
        })
        .await
        .map_err(|_| CognitiveContextError::RetrievalLearningUnavailable)?
        .map_err(|_| CognitiveContextError::RetrievalLearningUnavailable)?;
    }
    Ok(response)""",
)

CONTROL = "codex-rs/hepta-agentd/src/state_control.rs"
replace_once(
    CONTROL,
    """                    self.cognitive_retrieval_learning.get(),
                    Some(request_id),
                )""",
    """                    self.cognitive_retrieval_learning.get(),
                    Some(request_id),
                    self.cognitive_retrieval_mode()?.application(request_id),
                )""",
)

# ---------------------------------------------------------------------------
# Tests for mode parsing, context requirements and delivery isolation.
# ---------------------------------------------------------------------------
CT = "codex-rs/hepta-agentd/src/config_tests.rs"
replace_once(
    CT,
    """    assert_eq!(
        parse_cognitive_retrieval_mode(Some(OsString::from("hnmf-required")))
            .expect("HNMF profile"),
        CognitiveRetrievalMode::HnmfRequired
    );""",
    """    assert_eq!(
        parse_cognitive_retrieval_mode(Some(OsString::from("shadow")))
            .expect("shadow profile"),
        CognitiveRetrievalMode::Shadow
    );
    assert_eq!(
        parse_cognitive_retrieval_mode(Some(OsString::from("canary")))
            .expect("canary profile"),
        CognitiveRetrievalMode::Canary
    );
    for name in ["required", "hnmf-required"] {
        assert_eq!(
            parse_cognitive_retrieval_mode(Some(OsString::from(name)))
                .expect("required profile"),
            CognitiveRetrievalMode::HnmfRequired
        );
    }
    assert_eq!(
        CognitiveRetrievalMode::Shadow.application(16),
        super::CognitiveRetrievalApplication::ObserveOnly
    );
    assert_eq!(
        CognitiveRetrievalMode::Canary.application(15),
        super::CognitiveRetrievalApplication::ObserveOnly
    );
    assert_eq!(
        CognitiveRetrievalMode::Canary.application(16),
        super::CognitiveRetrievalApplication::Apply
    );
    assert_eq!(
        CognitiveRetrievalMode::HnmfRequired.application(1),
        super::CognitiveRetrievalApplication::Apply
    );""",
)
replace_once(
    CT,
    'if message.contains("compatibility or hnmf-required")',
    'if message.contains("compatibility, shadow, canary, required")',
)

RT = "codex-rs/hepta-agentd/src/runtime_tests.rs"
regex_once(
    RT,
    r"#\[test\]\nfn compatibility_retrieval_mode_does_not_require_hnmf_context\(\) \{.*?\n\}",
    """#[test]
fn retrieval_modes_require_exact_context_composition() {
    require_cognitive_retrieval_context_for_mode(CognitiveRetrievalMode::Compatibility, false)
        .expect("compatibility mode may run without a context");
    assert!(require_cognitive_retrieval_context_for_mode(
        CognitiveRetrievalMode::Compatibility,
        true,
    )
    .is_err());
    for mode in [
        CognitiveRetrievalMode::Shadow,
        CognitiveRetrievalMode::Canary,
        CognitiveRetrievalMode::HnmfRequired,
    ] {
        assert!(require_cognitive_retrieval_context_for_mode(mode, false).is_err());
        require_cognitive_retrieval_context_for_mode(mode, true)
            .expect("non-compatibility modes require and accept a context");
    }
}""",
)
# Remove the now-redundant legacy required-mode test if present.
text = read(RT)
text = re.sub(
    r"\n#\[test\]\nfn hnmf_required_retrieval_mode_fails_without_current_context\(\) \{.*?\n\}",
    "",
    text,
    count=1,
    flags=re.S,
)
write(RT, text)

HT = "codex-rs/hepta-agentd/src/cognitive_context_hnmf_tests.rs"
replace_once(
    HT,
    "use crate::cognitive_context::read_with_retrieval_context;",
    "use crate::cognitive_context::read_with_retrieval_context;\nuse crate::cognitive_context::read_with_retrieval_context_and_learning;\nuse crate::config::CognitiveRetrievalApplication;",
)
shadow_test = r'''

#[tokio::test]
async fn shadow_context_is_evaluated_without_changing_compatibility_delivery() {
    let (_temp, store, owner, context, compatibility_id) = fixture(134).await;
    let hnmf_id = context.engram_snapshot.nodes[0].support[0]
        .record_id
        .as_str()
        .to_string();
    let provider: Arc<dyn CurrentMemoryRetrievalContext> = Arc::new(SwitchingContext {
        owner: owner.clone(),
        generation: 1,
        first: context.clone(),
        later: context,
        switch_after_first: false,
        calls: Arc::new(AtomicUsize::new(0)),
    });
    let result = read_with_retrieval_context_and_learning(
        &store,
        &owner,
        1,
        "lemon",
        4,
        None,
        Some(&provider),
        None,
        Some(134),
        CognitiveRetrievalApplication::ObserveOnly,
    )
    .await
    .expect("shadow read");
    assert!(result.items.iter().any(|item| item.memory_id == compatibility_id));
    assert!(result.items.iter().any(|item| item.memory_id == hnmf_id));
}
'''
text = read(HT)
if shadow_test.strip() not in text:
    write(HT, text + shadow_test)

# Public provider surfaces.
LIB = "codex-rs/hepta-agentd/src/lib.rs"
replace_once(
    LIB,
    "pub use cognitive_retrieval_context::CurrentMemoryRetrievalContext;",
    "pub use cognitive_retrieval_context::CurrentMemoryRetrievalContext;\npub use cognitive_retrieval_context::MemoryRetrievalContextSnapshotV1;\npub use cognitive_retrieval_context::ProductMemoryRetrievalContextV1;",
)
replace_once(
    LIB,
    "pub use config::CognitiveRetrievalMode;",
    "pub use config::COGNITIVE_RETRIEVAL_CANARY_DENOMINATOR;\npub use config::CognitiveRetrievalMode;",
)

print("memory.retrieval product provider and four-mode patch applied")
