use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::EvaluatedPlanV1;
use crate::GlobalStateSnapshotV1;
use crate::GrantRequestSetV1;
use crate::NduPlanningError;
use crate::NduPlanningInputV1;
use crate::OwnerSummaryV1;
use crate::PlannerError;
use crate::PlanningRequestV1;
use crate::PreparedPlanInputV1;
use crate::SnapshotRequestV1;
use crate::collect_snapshot;
use crate::evaluate_prepared_plan_with_ndu;
use crate::prepare_plan;
use crate::request_execution_grants;

/// Host-owned authentication/admission boundary for owner summaries.
///
/// Implementations authenticate the producer and exact summary semantics. The
/// returned nonzero digest is folded into the summary support digest before the
/// global snapshot is sealed, so authentication-evidence drift changes every
/// downstream planning receipt.
pub trait OwnerSummaryAuthenticatorV1 {
    fn authenticate_owner(&self, summary: &OwnerSummaryV1) -> Option<Digest32>;
}

#[derive(Clone, Debug)]
pub struct GlobalPlanningInputV1 {
    pub snapshot_request: SnapshotRequestV1,
    pub owner_summaries: Vec<OwnerSummaryV1>,
    pub planning_request: PlanningRequestV1,
    pub ndu_input: NduPlanningInputV1,
    pub now_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GlobalPlanningOutputV1 {
    pub snapshot: GlobalStateSnapshotV1,
    pub prepared: PreparedPlanInputV1,
    pub evaluation: EvaluatedPlanV1,
    pub grant_requests: GrantRequestSetV1,
    pub owner_authentication_set_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GlobalPlanningErrorV1 {
    ClockMismatch,
    OwnerAuthenticationRejected(StableId),
    Planner(PlannerError),
    Ndu(NduPlanningError),
}

impl fmt::Display for GlobalPlanningErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for GlobalPlanningErrorV1 {}

impl From<PlannerError> for GlobalPlanningErrorV1 {
    fn from(error: PlannerError) -> Self {
        Self::Planner(error)
    }
}

impl From<NduPlanningError> for GlobalPlanningErrorV1 {
    fn from(error: NduPlanningError) -> Self {
        Self::Ndu(error)
    }
}

/// Compose authenticated owner admission, coherent snapshotting, resource
/// filtering, the real NDU owner, finalization, and deny-all grant requests.
///
/// This function stops at the authority boundary. GrantRequestSetV1 is not a
/// capability; the product host must submit each request to independent
/// kernel.authority immediately before the corresponding effect.
pub fn evaluate_global_plan_v1<A: OwnerSummaryAuthenticatorV1>(
    authenticator: &A,
    mut input: GlobalPlanningInputV1,
) -> Result<GlobalPlanningOutputV1, GlobalPlanningErrorV1> {
    if input.planning_request.now_micros != input.now_micros {
        return Err(GlobalPlanningErrorV1::ClockMismatch);
    }

    let mut authentication_pairs = Vec::with_capacity(input.owner_summaries.len());
    for summary in &mut input.owner_summaries {
        let authentication_digest = authenticator
            .authenticate_owner(summary)
            .filter(|digest| !digest.is_zero())
            .ok_or_else(|| {
                GlobalPlanningErrorV1::OwnerAuthenticationRejected(summary.owner_id.clone())
            })?;
        let mut support = b"hepta.control.authenticated-owner-support.v1\0".to_vec();
        support.extend_from_slice(summary.support_digest.as_array());
        support.extend_from_slice(authentication_digest.as_array());
        summary.support_digest = Digest32::of_bytes(&support);
        authentication_pairs.push((summary.owner_id.clone(), authentication_digest));
    }
    authentication_pairs.sort_by(|left, right| left.0.cmp(&right.0));
    let owner_authentication_set_digest = digest_authentication_set(&authentication_pairs);

    let snapshot = collect_snapshot(input.snapshot_request, input.owner_summaries)?;
    let prepared = prepare_plan(&snapshot, input.planning_request)?;
    let evaluation =
        evaluate_prepared_plan_with_ndu(&snapshot, &prepared, input.ndu_input, input.now_micros)?;
    let grant_requests =
        request_execution_grants(&snapshot, &prepared, &evaluation.plan, input.now_micros)?;

    Ok(GlobalPlanningOutputV1 {
        snapshot,
        prepared,
        evaluation,
        grant_requests,
        owner_authentication_set_digest,
    })
}

fn digest_authentication_set(pairs: &[(StableId, Digest32)]) -> Digest32 {
    let mut bytes = b"hepta.control.owner-authentication-set.v1\0".to_vec();
    bytes.extend_from_slice(&u32::try_from(pairs.len()).unwrap_or(u32::MAX).to_be_bytes());
    for (owner, authentication_digest) in pairs {
        let raw = owner.as_str().as_bytes();
        bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
        bytes.extend_from_slice(raw);
        bytes.extend_from_slice(authentication_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
#[path = "planner_global_tests.rs"]
mod tests;
