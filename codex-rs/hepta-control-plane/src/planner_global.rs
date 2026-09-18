use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::StableId;

use crate::EvaluatedPlanV1;
use crate::GlobalStateSnapshotV1;
use crate::GrantRequestSetV1;
use crate::NduPlanningError;
use crate::OwnerSummaryV1;
use crate::PlannerError;
use crate::PlanningRequestV1;
use crate::PreparedPlanInputV1;
use crate::SnapshotRequestV1;
use crate::collect_snapshot;
use crate::prepare_plan;
use crate::request_execution_grants;

/// Trusted host boundary for one owner. Implementations authenticate their own
/// producer and scope before returning an owner summary; the planner never
/// accepts an untyped network response as authority.
pub trait AuthenticatedOwnerPortV1 {
    fn owner_id(&self) -> &StableId;

    fn snapshot_summary(
        &self,
        request: &SnapshotRequestV1,
    ) -> Result<OwnerSummaryV1, OwnerPortErrorV1>;
}

/// Independent NDU owner boundary. The implementation computes the evaluation;
/// control.runtime only consumes the returned sealed projection.
pub trait NduPlanningPortV1 {
    fn evaluate(
        &self,
        snapshot: &GlobalStateSnapshotV1,
        prepared: &PreparedPlanInputV1,
        now_micros: u64,
    ) -> Result<EvaluatedPlanV1, NduPlanningError>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OwnerPortErrorV1 {
    Unavailable,
    AuthenticationFailed,
    ScopeMismatch,
    Stale,
}

impl fmt::Display for OwnerPortErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for OwnerPortErrorV1 {}

#[derive(Clone, Debug)]
pub struct GlobalPlanningRequestV1 {
    pub snapshot_request: SnapshotRequestV1,
    pub planning_request: PlanningRequestV1,
    pub now_micros: u64,
}

#[derive(Clone, Debug)]
pub struct GlobalPlanningReceiptV1 {
    pub snapshot: GlobalStateSnapshotV1,
    pub prepared: PreparedPlanInputV1,
    pub evaluation: EvaluatedPlanV1,
    pub grant_requests: GrantRequestSetV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GlobalPlanningErrorV1 {
    DuplicateOwnerPort(StableId),
    MissingOwnerPort(StableId),
    OwnerIdentityMismatch {
        expected: StableId,
        observed: StableId,
    },
    OwnerPort {
        owner: StableId,
        error: OwnerPortErrorV1,
    },
    TimeBindingMismatch,
    Planner(PlannerError),
    Ndu(NduPlanningError),
}

impl fmt::Display for GlobalPlanningErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for GlobalPlanningErrorV1 {}

/// Compose the repository-owned global control plane through the authority-free
/// grant-request boundary. Only required owner ports are sampled; unrelated or
/// optional degraded owners cannot poison a plan accidentally.
pub fn plan_global_v1(
    owner_ports: &[&dyn AuthenticatedOwnerPortV1],
    ndu_port: &dyn NduPlanningPortV1,
    request: GlobalPlanningRequestV1,
) -> Result<GlobalPlanningReceiptV1, GlobalPlanningErrorV1> {
    if request.planning_request.now_micros != request.now_micros
        || request.snapshot_request.collected_at_micros != request.now_micros
    {
        return Err(GlobalPlanningErrorV1::TimeBindingMismatch);
    }

    let mut ports = BTreeMap::new();
    for port in owner_ports {
        let owner_id = port.owner_id().clone();
        if ports.insert(owner_id.clone(), *port).is_some() {
            return Err(GlobalPlanningErrorV1::DuplicateOwnerPort(owner_id));
        }
    }

    let mut required = request.snapshot_request.required_owner_ids.clone();
    required.sort();
    required.dedup();
    let mut summaries = Vec::with_capacity(required.len());
    for owner_id in required {
        let port = ports
            .get(&owner_id)
            .ok_or_else(|| GlobalPlanningErrorV1::MissingOwnerPort(owner_id.clone()))?;
        let summary = port
            .snapshot_summary(&request.snapshot_request)
            .map_err(|error| GlobalPlanningErrorV1::OwnerPort {
                owner: owner_id.clone(),
                error,
            })?;
        if summary.owner_id != owner_id {
            return Err(GlobalPlanningErrorV1::OwnerIdentityMismatch {
                expected: owner_id,
                observed: summary.owner_id,
            });
        }
        summaries.push(summary);
    }

    let snapshot =
        collect_snapshot(request.snapshot_request, summaries).map_err(GlobalPlanningErrorV1::Planner)?;
    let prepared = prepare_plan(&snapshot, request.planning_request)
        .map_err(GlobalPlanningErrorV1::Planner)?;
    let evaluation = ndu_port
        .evaluate(&snapshot, &prepared, request.now_micros)
        .map_err(GlobalPlanningErrorV1::Ndu)?;
    let grant_requests = request_execution_grants(
        &snapshot,
        &prepared,
        &evaluation.plan,
        request.now_micros,
    )
    .map_err(GlobalPlanningErrorV1::Planner)?;

    Ok(GlobalPlanningReceiptV1 {
        snapshot,
        prepared,
        evaluation,
        grant_requests,
    })
}

#[cfg(test)]
#[path = "planner_global_tests.rs"]
mod tests;
