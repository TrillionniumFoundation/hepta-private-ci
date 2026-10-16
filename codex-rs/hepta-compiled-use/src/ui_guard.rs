//! Bind a typed UI action proposal to a prior exact observed UI state.
//!
//! Pure SHADOW_ONLY data checks. Neither caller-supplied readback nor a digest
//! proves a trusted OS observation; external readback owner and per-effect
//! authority/revocation checks remain mandatory. This file does not execute.

use crate::{
    propose_compiled_use_v1, verify_compiled_use_proposal_v1, ActionErrorV1,
    ActionFrameV1, ActionVerifierV1, CompiledUseProposalV1,
};
use codex_hepta_types::{AuthorityPosture, Digest32};
use std::error::Error as StdError;
use std::fmt;

const MAX_OBSERVATION_AGE_MS: u64 = 5_000;

/// External observer **claim**; the crate cannot authenticate its origin.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct UiReadbackV1 {
    pub principal_scope_digest: Digest32,
    pub observer_digest: Digest32,
    pub tree_digest: Digest32,
    pub generation: u64,
    pub observed_at_ms: u64,
    pub max_age_ms: u64,
}

/// Fixed entire observed state and bounded typed actions. No executable bytes.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UiGuardedPlanV1 {
    pub required_readback: UiReadbackV1,
    pub actions: Vec<ActionFrameV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UiGuardedShadowProposalV1 {
    pub required_readback: UiReadbackV1,
    pub proposed_actions: CompiledUseProposalV1,
    pub guarded_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum UiGuardErrorV1 {
    EmptyIdentity,
    InvalidObservationWindow,
    WrongGeneration,
    ChangedObservation,
    ObservationFromFuture,
    StaleObservation,
    ChangedGuardedDigest,
    Action(ActionErrorV1),
}

impl fmt::Display for UiGuardErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for UiGuardErrorV1 {}
impl From<ActionErrorV1> for UiGuardErrorV1 {
    fn from(value: ActionErrorV1) -> Self {
        Self::Action(value)
    }
}

/// Build an immutable *proposal*, not permission to click/type/scroll.
///
/// `observed` MUST come from an independently trusted runtime owner in an
/// eventual effect adapter. Both this value and `now_ms` are caller-provided
/// assertions here; passing them does not certify original host provenance.
/// Final-use MUST re-read the current UI state and validate a distinct,
/// scoped, expiring effect token immediately before the actual OS call.
pub fn propose_ui_guarded_shadow_v1(
    verifier: ActionVerifierV1,
    plan: &UiGuardedPlanV1,
    observed: &UiReadbackV1,
    now_ms: u64,
) -> Result<UiGuardedShadowProposalV1, UiGuardErrorV1> {
    let required = plan.required_readback;
    if required.principal_scope_digest.is_zero()
        || required.observer_digest.is_zero()
        || required.tree_digest.is_zero()
    {
        return Err(UiGuardErrorV1::EmptyIdentity);
    }
    if required.observed_at_ms == 0
        || required.max_age_ms == 0
        || required.max_age_ms > MAX_OBSERVATION_AGE_MS
    {
        return Err(UiGuardErrorV1::InvalidObservationWindow);
    }
    if required.generation != verifier.generation || required.generation == 0 {
        return Err(UiGuardErrorV1::WrongGeneration);
    }
    if observed != &required {
        return Err(UiGuardErrorV1::ChangedObservation);
    }
    if now_ms < observed.observed_at_ms {
        return Err(UiGuardErrorV1::ObservationFromFuture);
    }
    if now_ms - observed.observed_at_ms > required.max_age_ms {
        return Err(UiGuardErrorV1::StaleObservation);
    }
    let base = propose_compiled_use_v1(verifier, plan.actions.clone())?;
    let guarded_digest = Digest32::of_parts(&[
        b"hepta.compiled-use.ui-guarded-shadow.v1\0",
        required.principal_scope_digest.as_array(),
        required.observer_digest.as_array(),
        required.tree_digest.as_array(),
        &required.generation.to_be_bytes(),
        &required.observed_at_ms.to_be_bytes(),
        &required.max_age_ms.to_be_bytes(),
        base.proposal_digest.as_array(),
    ]);
    Ok(UiGuardedShadowProposalV1 {
        required_readback: required,
        proposed_actions: base,
        guarded_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

/// Rebuild exact source binding, including all action bytes. No OS effects.
pub fn verify_ui_guarded_shadow_v1(
    verifier: ActionVerifierV1,
    proposal: &UiGuardedShadowProposalV1,
    observed: &UiReadbackV1,
    now_ms: u64,
) -> Result<(), UiGuardErrorV1> {
    if proposal.authority.grants_any() {
        return Err(UiGuardErrorV1::ChangedGuardedDigest);
    }
    verify_compiled_use_proposal_v1(verifier, &proposal.proposed_actions)?;
    let rebuilt = propose_ui_guarded_shadow_v1(
        verifier,
        &UiGuardedPlanV1 {
            required_readback: proposal.required_readback,
            actions: proposal.proposed_actions.actions.clone(),
        },
        observed,
        now_ms,
    )?;
    if rebuilt != *proposal {
        return Err(UiGuardErrorV1::ChangedGuardedDigest);
    }
    Ok(())
}

#[cfg(test)]
#[path = "ui_guard_tests.rs"]
mod tests;
