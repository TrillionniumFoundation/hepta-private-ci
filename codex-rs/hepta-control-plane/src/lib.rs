//! Revision- and authority-epoch-fenced runtime control state plus a bounded,
//! snapshot-coherent global planning kernel.
//!
//! Actions update desired control state only. Planning and grant-request
//! construction remain advisory and deny-all: they do not execute effects,
//! operate hardware, issue capabilities, deploy, merge, promote or release.

#![forbid(unsafe_code)]

#[path = "embodiment/cart.rs"]
mod cart;
mod organ_graph;
mod organ_runtime;
mod planner;
mod planner_context;
mod planner_journal;
mod planner_ndu;
#[path = "embodiment/timing.rs"]
mod timing;

pub use cart::CART_Q24_SCALE;
pub use cart::CartCommandV1;
pub use cart::CartControlMode;
pub use cart::CartControllerV1;
pub use cart::CartError;
pub use cart::CartSensorProfileV1;
pub use cart::CartSimulatorV1;
pub use cart::CartStateV1;
pub use cart::SyntheticCartObservationV1;
pub use cart::SyntheticCartPlant;
pub use organ_graph::DataflowTiming;
pub use organ_graph::FailureDomainV1;
pub use organ_graph::FallbackTerminal;
pub use organ_graph::FeedbackProfileV1;
pub use organ_graph::InputPort;
pub use organ_graph::OrganEdge;
pub use organ_graph::OrganGraphError;
pub use organ_graph::OrganGraphsV1;
pub use organ_graph::OrganNodeV1;
pub use organ_graph::OrganRole;
pub use organ_graph::OutputPort;
pub use organ_graph::RuntimeLinkV1;
pub use organ_graph::ValidatedOrganGraphsV1;
pub use organ_runtime::HostedOrganStateV1;
pub use organ_runtime::HostedOrganStatusV1;
pub use organ_runtime::MAX_ORGAN_MESSAGE_BYTES;
pub use organ_runtime::OrganDeliveryV1;
pub use organ_runtime::OrganFaultRecordV1;
pub use organ_runtime::OrganHandlerFaultV1;
pub use organ_runtime::OrganHostV1;
pub use organ_runtime::OrganRuntimeError;
pub use organ_runtime::TrustedReadOnlyOrganV1;
pub use planner::FeasiblePlanReceiptV1;
pub use planner::GlobalStateSnapshotV1;
pub use planner::GrantRequestSetV1;
pub use planner::GrantRequestV1;
pub use planner::NduPlanEvaluationInputV1;
pub use planner::NduPlanEvaluationV1;
pub use planner::OwnerReadinessV1;
pub use planner::OwnerSummaryV1;
pub use planner::PlanCandidateV1;
pub use planner::PlannerAxisValueV1;
pub use planner::PlannerError;
pub use planner::PlanningEvaluationDispositionV1;
pub use planner::PlanningRequestV1;
pub use planner::PreparedPlanInputV1;
pub use planner::ResourceReservationV1;
pub use planner::SearchDisclosureV1;
pub use planner::SnapshotRequestV1;
pub use planner::bind_ndu_plan_evaluation_v1;
pub use planner::collect_snapshot;
pub use planner::finalize_plan;
pub use planner::prepare_plan;
pub use planner::request_execution_grants;
pub use planner_context::ObservedContextPlanV1;
pub use planner_context::ObservedContextV1;
pub use planner_context::plan_observed_context;
pub use planner_journal::PlannerJournalEntryV1;
pub use planner_journal::PlannerJournalError;
pub use planner_journal::PlannerJournalKindV1;
pub use planner_journal::PlannerJournalV1;
pub use planner_ndu::EvaluatedPlanV1;
pub use planner_ndu::NduPlanningError;
pub use planner_ndu::NduPlanningInputV1;
pub use planner_ndu::canonical_ndu_planning_policy_digest;
pub use planner_ndu::evaluate_prepared_plan_with_ndu;
pub use timing::FixedPriorityTaskV1;
pub use timing::TimingError;
pub use timing::fixed_priority_response_times;

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ControlMode {
    Ready,
    Quarantined,
    Recovering,
    RollbackRequested,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ControlState {
    pub revision: Revision,
    pub authority_epoch: u64,
    pub mode: ControlMode,
    pub configuration_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ControlAction {
    Quarantine,
    BeginRecovery,
    RequestRollback,
    MarkReady,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ControlIntent {
    pub operation_id: StableId,
    pub expected_revision: Revision,
    pub expected_authority_epoch: u64,
    pub action: ControlAction,
    pub payload_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ControlReceipt {
    pub operation_id: StableId,
    pub previous_revision: Revision,
    pub next_revision: Revision,
    pub mode: ControlMode,
    pub state_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptyDigest(&'static str),
    ZeroAuthorityEpoch,
    StaleRevision,
    StaleAuthorityEpoch,
    InvalidTransition,
    RevisionOverflow,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub fn apply(
    state: &ControlState,
    intent: ControlIntent,
) -> Result<(ControlState, ControlReceipt), Error> {
    if state.configuration_digest.is_zero() {
        return Err(Error::EmptyDigest("configuration"));
    }
    if intent.payload_digest.is_zero() {
        return Err(Error::EmptyDigest("intent payload"));
    }
    if state.authority_epoch == 0 || intent.expected_authority_epoch == 0 {
        return Err(Error::ZeroAuthorityEpoch);
    }
    if intent.expected_revision != state.revision {
        return Err(Error::StaleRevision);
    }
    if intent.expected_authority_epoch != state.authority_epoch {
        return Err(Error::StaleAuthorityEpoch);
    }
    let next_mode = transition(state.mode, intent.action)?;
    let next_revision = state.revision.next().map_err(|_| Error::RevisionOverflow)?;
    let next = ControlState {
        revision: next_revision,
        authority_epoch: state.authority_epoch,
        mode: next_mode,
        configuration_digest: state.configuration_digest,
    };
    let state_digest = digest_state(&next, &intent);
    let receipt = ControlReceipt {
        operation_id: intent.operation_id,
        previous_revision: state.revision,
        next_revision,
        mode: next_mode,
        state_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    Ok((next, receipt))
}

fn transition(mode: ControlMode, action: ControlAction) -> Result<ControlMode, Error> {
    match (mode, action) {
        (ControlMode::Ready, ControlAction::Quarantine) => Ok(ControlMode::Quarantined),
        (ControlMode::Quarantined, ControlAction::BeginRecovery) => Ok(ControlMode::Recovering),
        (ControlMode::Recovering, ControlAction::MarkReady) => Ok(ControlMode::Ready),
        (ControlMode::Quarantined, ControlAction::RequestRollback)
        | (ControlMode::Recovering, ControlAction::RequestRollback) => {
            Ok(ControlMode::RollbackRequested)
        }
        _ => Err(Error::InvalidTransition),
    }
}

fn digest_state(state: &ControlState, intent: &ControlIntent) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.control.state.v1");
    bytes.extend_from_slice(&state.revision.get().to_be_bytes());
    bytes.extend_from_slice(&state.authority_epoch.to_be_bytes());
    bytes.push(match state.mode {
        ControlMode::Ready => 0,
        ControlMode::Quarantined => 1,
        ControlMode::Recovering => 2,
        ControlMode::RollbackRequested => 3,
    });
    bytes.extend_from_slice(state.configuration_digest.as_array());
    bytes.extend_from_slice(intent.payload_digest.as_array());
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
