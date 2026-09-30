//! Bind publication evidence without turning a historical plan into a lease.
//!
//! The response schema stays unchanged. Its opaque read digest additionally
//! covers the publisher's owner/generation and every planning field. The
//! publication plan is audit evidence; physical use evaluates a NEW plan over
//! newly verified owner observations and checks that new plan's deadline.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_control_plane::ObservedContextV1;
use codex_hepta_control_plane::plan_observed_context;
use codex_hepta_memory::CognitiveStoreError;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CognitiveContextPlan;
use crate::CognitiveContextSnapshot;
use crate::MAX_COGNITIVE_CONTEXT_BYTES;

const PLAN_WINDOW_MICROS: u64 = 1_000_000;
const PLAN_BOUND_READ_DOMAIN: &[u8] = b"hepta.agentd.cognitive-context-plan-bound-read.v2";

/// Request-local evaluation, never serialized or retained as future authority.
pub(super) struct FreshContextPlan {
    pub(super) plan: CognitiveContextPlan,
    observed_at_micros: u64,
    expires_at_micros: u64,
}

impl FreshContextPlan {
    pub(super) fn ensure_current(&self, now_micros: u64) -> Result<(), CognitiveStoreError> {
        if now_micros < self.observed_at_micros || now_micros >= self.expires_at_micros {
            return Err(CognitiveStoreError::Conflict(
                "fresh cognitive planning observation expired or clock regressed".to_string(),
            ));
        }
        Ok(())
    }
}

pub(super) fn now_micros() -> Result<u64, CognitiveStoreError> {
    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?;
    u64::try_from(elapsed.as_micros())
        .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))
}

pub(super) fn evaluate(
    owner: &AgentId,
    body_generation: u64,
    unplanned: &CognitiveContextSnapshot,
    observed_at_micros: u64,
) -> Result<FreshContextPlan, CognitiveStoreError> {
    if unplanned.plan.is_some() || unplanned.items.len() > 4 {
        return Err(CognitiveStoreError::Invalid(
            "planning requires a bounded pre-plan context".to_string(),
        ));
    }
    let encoded = serde_json::to_vec(unplanned)
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
    if encoded.len() > MAX_COGNITIVE_CONTEXT_BYTES {
        return Err(CognitiveStoreError::Invalid(
            "pre-plan context exceeds the product byte budget".to_string(),
        ));
    }
    let expires_at_micros = observed_at_micros
        .checked_add(PLAN_WINDOW_MICROS)
        .ok_or_else(|| CognitiveStoreError::Invalid("context plan expiry overflow".to_string()))?;
    let observed = plan_observed_context(ObservedContextV1 {
        owner_id: StableId::new(owner.as_str())
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        body_generation: Generation::new(body_generation)
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        source_snapshot_digest: parse_digest(&unplanned.snapshot_digest)?,
        read_digest: parse_digest(&unplanned.read_digest)?,
        verified_item_count: unplanned.items.len() as u32,
        encoded_context: &encoded,
        maximum_context_bytes: MAX_COGNITIVE_CONTEXT_BYTES as u32,
        observed_at_micros,
        expires_at_micros,
    })
    .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?;
    Ok(FreshContextPlan {
        plan: CognitiveContextPlan {
            evaluated_context_digest: observed.context_digest.to_string(),
            plan_receipt_digest: observed.evaluation.plan.receipt_digest().to_string(),
            read_allowed: observed.read_allowed,
        },
        observed_at_micros,
        expires_at_micros,
    })
}

/// Integrity binding, NOT a signature or an authorization grant. Authentication
/// and currentness still come from the existing Agentd/SQLite owners.
pub(super) fn bind(
    owner: &AgentId,
    body_generation: u64,
    owner_read_digest: Digest32,
    plan: &CognitiveContextPlan,
) -> Result<Digest32, CognitiveStoreError> {
    Generation::new(body_generation)
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
    let context = parse_digest(&plan.evaluated_context_digest)?;
    let receipt = parse_digest(&plan.plan_receipt_digest)?;
    if context.is_zero() || receipt.is_zero() {
        return Err(CognitiveStoreError::Invalid(
            "empty cognitive planning evidence".to_string(),
        ));
    }
    let mut bytes = PLAN_BOUND_READ_DOMAIN.to_vec();
    bytes.extend_from_slice(&(owner.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(owner.as_str().as_bytes());
    bytes.extend_from_slice(&body_generation.to_be_bytes());
    bytes.extend_from_slice(owner_read_digest.as_array());
    bytes.extend_from_slice(context.as_array());
    bytes.extend_from_slice(receipt.as_array());
    bytes.push(u8::from(plan.read_allowed));
    Ok(Digest32::of_bytes(&bytes))
}

pub(super) fn verify_publication(
    owner: &AgentId,
    body_generation: u64,
    owner_read_digest: Digest32,
    response: &CognitiveContextSnapshot,
) -> Result<CognitiveContextSnapshot, CognitiveStoreError> {
    let plan = response.plan.as_ref().ok_or_else(|| {
        CognitiveStoreError::Invalid("cognitive final use requires planning evidence".to_string())
    })?;
    if bind(owner, body_generation, owner_read_digest, plan)?
        != parse_digest(&response.read_digest)?
    {
        return Err(CognitiveStoreError::Conflict(
            "cognitive publication owner, generation or plan receipt changed".to_string(),
        ));
    }
    let mut unplanned = response.clone();
    unplanned.read_digest = owner_read_digest.to_string();
    unplanned.plan = None;
    let encoded = serde_json::to_vec(&unplanned)
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
    if encoded.len() > MAX_COGNITIVE_CONTEXT_BYTES
        || Digest32::of_bytes(&encoded) != parse_digest(&plan.evaluated_context_digest)?
    {
        return Err(CognitiveStoreError::Conflict(
            "cognitive ordered pre-plan payload changed".to_string(),
        ));
    }
    Ok(unplanned)
}

fn parse_digest(value: &str) -> Result<Digest32, CognitiveStoreError> {
    value.parse().map_err(|error| {
        CognitiveStoreError::Invalid(format!("invalid cognitive planning digest: {error}"))
    })
}

#[cfg(test)]
#[path = "cognitive_context_plan_tests.rs"]
mod tests;
