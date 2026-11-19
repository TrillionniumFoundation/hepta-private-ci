//! Read-only history for one retained, signed ObjectiveStart request.
//!
//! These observations never authorize submission, execution, retry or a model
//! turn. A missing record is unknown, including after an owner restart.

use serde::Deserialize;
use serde::Serialize;

use crate::AuthBusObjectiveIngress;

/// An acknowledgement retained through a trusted owner response. A caller must
/// not manufacture this anchor from an untrusted file or a guessed sequence.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ObjectiveJournalAnchor {
    pub sequence: u64,
    pub chain_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ObjectiveAdmissionQuery {
    /// Exact original signed ingress, including its historical spawn generation.
    pub request: AuthBusObjectiveIngress,
    /// When supplied, it must exist and cover the returned publication. Without
    /// it, a positive result is only the current owner's retained observation.
    pub anchor: Option<ObjectiveJournalAnchor>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ObjectiveAdmissionUnknownReason {
    InvalidQuery,
    OwnerUnavailable,
    JournalUnavailable,
    NoMatchingPublication,
    AnchorMissing,
    AnchorMismatch,
    PublicationOutsideAnchor,
}

/// Only the immutable publication disposition, never a current runtime phase
/// or an external-effect outcome. Conflict does not mean the run was admitted.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum ObjectivePublicationOutcome {
    Compiled {
        objective_digest: String,
        hard_constraint_digest: String,
    },
    ExplicitAbstain {
        objective_digest: String,
        hard_constraint_digest: String,
    },
    Conflict {
        conflict_digest: String,
    },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ObjectiveAdmissionPublication {
    pub run_id: String,
    pub original_spawn_generation: u64,
    pub issuer_id: String,
    pub key_epoch: u64,
    pub message_id: String,
    pub message_sequence: u64,
    pub expires_at_ms: u64,
    pub signed_body_digest: String,
    pub profile_digest: String,
    pub publication_sequence: u64,
    pub publication_digest: String,
    pub chain_digest: String,
    pub outcome: ObjectivePublicationOutcome,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum ObjectiveAdmissionOutcome {
    Published {
        publication: Box<ObjectiveAdmissionPublication>,
    },
    Unknown {
        reason: ObjectiveAdmissionUnknownReason,
    },
}
