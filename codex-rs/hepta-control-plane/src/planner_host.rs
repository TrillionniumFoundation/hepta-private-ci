use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;

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

#[derive(Clone, Debug)]
pub struct AuthenticatedOwnerInputV1<P> {
    pub summary: OwnerSummaryV1,
    pub proof: P,
}

pub trait OwnerSummaryVerifierV1<P> {
    fn verify(&self, summary: &OwnerSummaryV1, proof: &P) -> Result<(), String>;
}

pub trait AuthorityRequestSetVerifierV1 {
    fn admit(&mut self, requests: &GrantRequestSetV1) -> Result<Digest32, String>;
}

#[derive(Clone, Debug)]
pub struct GlobalPlanExecutionV1 {
    pub snapshot: GlobalStateSnapshotV1,
    pub prepared: PreparedPlanInputV1,
    pub evaluation: EvaluatedPlanV1,
    pub grant_requests: GrantRequestSetV1,
    pub authority_admission_receipt_digest: Option<Digest32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GlobalPlanHostError {
    OwnerAuthentication { owner: String, message: String },
    Planner(PlannerError),
    Ndu(NduPlanningError),
    Authority(String),
    EmptyAuthorityReceipt,
}

impl fmt::Display for GlobalPlanHostError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for GlobalPlanHostError {}

impl From<PlannerError> for GlobalPlanHostError {
    fn from(error: PlannerError) -> Self {
        Self::Planner(error)
    }
}

impl From<NduPlanningError> for GlobalPlanHostError {
    fn from(error: NduPlanningError) -> Self {
        Self::Ndu(error)
    }
}

pub fn execute_authenticated_global_plan_v1<P, V, A>(
    snapshot_request: SnapshotRequestV1,
    owners: Vec<AuthenticatedOwnerInputV1<P>>,
    planning_request: PlanningRequestV1,
    ndu_input: NduPlanningInputV1,
    now_micros: u64,
    owner_verifier: &V,
    authority: &mut A,
) -> Result<GlobalPlanExecutionV1, GlobalPlanHostError>
where
    V: OwnerSummaryVerifierV1<P>,
    A: AuthorityRequestSetVerifierV1,
{
    let mut summaries = Vec::with_capacity(owners.len());
    for owner in owners {
        owner_verifier
            .verify(&owner.summary, &owner.proof)
            .map_err(|message| GlobalPlanHostError::OwnerAuthentication {
                owner: owner.summary.owner_id.to_string(),
                message,
            })?;
        summaries.push(owner.summary);
    }
    let snapshot = collect_snapshot(snapshot_request, summaries)?;
    let prepared = prepare_plan(&snapshot, planning_request)?;
    let evaluation =
        evaluate_prepared_plan_with_ndu(&snapshot, &prepared, ndu_input, now_micros)?;
    let grant_requests =
        request_execution_grants(&snapshot, &prepared, &evaluation.plan, now_micros)?;
    let authority_admission_receipt_digest = if grant_requests.requests().is_empty() {
        None
    } else {
        let digest = authority
            .admit(&grant_requests)
            .map_err(GlobalPlanHostError::Authority)?;
        if digest.is_zero() {
            return Err(GlobalPlanHostError::EmptyAuthorityReceipt);
        }
        Some(digest)
    };
    Ok(GlobalPlanExecutionV1 {
        snapshot,
        prepared,
        evaluation,
        grant_requests,
        authority_admission_receipt_digest,
    })
}

#[cfg(test)]
#[path = "planner_host_tests.rs"]
mod tests;
