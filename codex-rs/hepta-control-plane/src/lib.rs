//! Revision- and authority-epoch-fenced runtime control state.
//!
//! Actions update desired control state only. They do not execute effects,
//! operate hardware, deploy, merge, promote or release.

#![forbid(unsafe_code)]

mod organ_graph;

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
