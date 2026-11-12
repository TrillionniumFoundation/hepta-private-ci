//! Data pins carried only inside original Root-sealed phase descriptors.
//! A decoded value is never a live owner or a grant.

use serde::Deserialize;
use serde::Serialize;

pub(crate) const START_PURPOSE: &str = "hepta.same-actor-q24-phase.start.v1";
pub(crate) const SCOPED_PURPOSE: &str = "hepta.same-actor-q24-phase.scoped.v1";
pub(crate) const CONTROL_SOCKET: &str = "same-actor-q24-phase.sock";

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct OriginalPhaseBootstrap {
    pub(crate) purpose: String,
    pub(crate) phase: String,
    pub(crate) original: crate::same_actor_q24_phase_record::PhaseIdentity,
    pub(crate) control_socket: std::path::PathBuf,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct OriginalScopedPhaseBootstrap {
    pub(crate) purpose: String,
    pub(crate) phase: String,
    pub(crate) original: OriginalPhaseBootstrap,
    pub(crate) learning: crate::HostAuthorityLearningProfileV1,
    pub(crate) claim: crate::same_actor_q24_phase_record::PhaseClaim,
    pub(crate) factory: String,
}
