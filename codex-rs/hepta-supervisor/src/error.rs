use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::FleetRegistryError;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

use crate::control_intent::DurableControlIntentError;

#[derive(Clone, Debug, Eq, Error, PartialEq)]
#[error("{message}")]
pub struct ProcessDriverError {
    message: String,
}

impl ProcessDriverError {
    pub fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl From<std::io::Error> for ProcessDriverError {
    fn from(error: std::io::Error) -> Self {
        Self::new(error.to_string())
    }
}

impl From<serde_json::Error> for ProcessDriverError {
    fn from(error: serde_json::Error) -> Self {
        Self::new(error.to_string())
    }
}

/// Last durable boundary known to the caller when a control operation failed.
/// The classification never grants retry authority; it tells the caller which
/// observation or recovery ceremony must happen next.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ControlEffectBoundary {
    Preflight,
    IntentPrepared,
    EffectAttempted,
    ResultCommit,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ControlFailureClass {
    NotStarted,
    TargetIdentityStale,
    AlreadyCompleted,
    PersistenceIndeterminate,
    RecoveryRequired,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ControlFailureAction {
    CorrectRequest,
    RefreshTarget,
    TreatAsCompleted,
    InspectDurableState,
    RunRecovery,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ControlFailureDisposition {
    pub class: ControlFailureClass,
    pub next_action: ControlFailureAction,
}

impl ControlFailureDisposition {
    fn new(class: ControlFailureClass, next_action: ControlFailureAction) -> Self {
        Self { class, next_action }
    }
}

#[derive(Debug, Error)]
pub enum SupervisorError {
    #[error("invalid supervisor value: {0}")]
    Invalid(String),
    #[error("unknown fleet agent {0}")]
    UnknownAgent(AgentId),
    #[error("agent {0} already has an active child")]
    AlreadyActive(AgentId),
    #[error("agent {0} has no previous child command")]
    NoPreviousCommand(AgentId),
    #[error("agent {0} has no previous healthy release to roll back")]
    NoPreviousRelease(AgentId),
    #[error("agent {0} already has a release change in progress")]
    ReleaseChangePending(AgentId),
    #[error("agent {0} exhausted its restart budget")]
    RestartBudgetExhausted(AgentId),
    #[error("agent {0} already runs the selected release")]
    TargetReleaseUnchanged(AgentId),
    #[error("agent {0} has an unresolved process lease")]
    UnresolvedLease(AgentId),
    #[error("corrupt supervisor process lease: {0}")]
    CorruptLease(String),
    #[error("process driver failed for agent {agent_id}: {message}")]
    Driver { agent_id: AgentId, message: String },
    #[error("generation fence rejected agent {agent_id}: runtime {runtime}, registry {registry}")]
    GenerationFence {
        agent_id: AgentId,
        runtime: u64,
        registry: u64,
    },
    #[error(transparent)]
    Registry(#[from] FleetRegistryError),
    #[error("durable control persistence outcome is indeterminate: {0}")]
    ControlPersistenceIndeterminate(String),
    #[error("durable control state requires recovery: {0}")]
    ControlRecoveryRequired(String),
    #[error("signed production authority rejected: {0}")]
    ProductionAuthority(String),
    #[error("signed production authority feature is disabled in this build")]
    ProductionAuthorityFeatureDisabled,
    #[error("agent {0} has an unresolved signed supervisor intent after recovery")]
    SignedIntentRecoveryRequired(AgentId),
    #[error(
        "signed mutation for agent {0} crossed its durable effect boundary and is indeterminate"
    )]
    SignedMutationIndeterminate(AgentId),
    #[error(transparent)]
    Io(#[from] std::io::Error),
}

impl SupervisorError {
    pub fn control_failure_disposition(
        &self,
        boundary: ControlEffectBoundary,
    ) -> ControlFailureDisposition {
        use ControlFailureAction as Action;
        use ControlFailureClass as Class;

        match self {
            Self::GenerationFence { .. }
            | Self::Registry(FleetRegistryError::StaleGeneration { .. })
            | Self::Registry(FleetRegistryError::StaleReleaseGeneration { .. }) => {
                ControlFailureDisposition::new(Class::TargetIdentityStale, Action::RefreshTarget)
            }
            Self::AlreadyActive(_) | Self::TargetReleaseUnchanged(_) => {
                ControlFailureDisposition::new(Class::AlreadyCompleted, Action::TreatAsCompleted)
            }
            Self::ControlRecoveryRequired(_)
            | Self::SignedIntentRecoveryRequired(_)
            | Self::UnresolvedLease(_)
            | Self::CorruptLease(_) => {
                ControlFailureDisposition::new(Class::RecoveryRequired, Action::RunRecovery)
            }
            Self::ControlPersistenceIndeterminate(_) | Self::SignedMutationIndeterminate(_) => {
                ControlFailureDisposition::new(
                    Class::PersistenceIndeterminate,
                    Action::InspectDurableState,
                )
            }
            Self::Io(_) | Self::Driver { .. } | Self::Registry(_) | Self::Invalid(_)
                if boundary >= ControlEffectBoundary::IntentPrepared =>
            {
                ControlFailureDisposition::new(
                    Class::PersistenceIndeterminate,
                    Action::InspectDurableState,
                )
            }
            _ => ControlFailureDisposition::new(Class::NotStarted, Action::CorrectRequest),
        }
    }
}

impl From<DurableControlIntentError> for SupervisorError {
    fn from(error: DurableControlIntentError) -> Self {
        match error {
            DurableControlIntentError::Io(error) => {
                Self::ControlPersistenceIndeterminate(error.to_string())
            }
            DurableControlIntentError::Invalid(message) => Self::ControlRecoveryRequired(message),
            DurableControlIntentError::DigestMismatch => {
                Self::ControlRecoveryRequired("control intent digest mismatch".to_string())
            }
            DurableControlIntentError::Unresolved => {
                Self::ControlRecoveryRequired("another control intent is unresolved".to_string())
            }
            DurableControlIntentError::Serialization(error) => {
                Self::ControlRecoveryRequired(error.to_string())
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn agent() -> AgentId {
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent")
    }

    #[test]
    fn target_fence_requires_refresh_in_every_phase() {
        let error = SupervisorError::GenerationFence {
            agent_id: agent(),
            runtime: 7,
            registry: 8,
        };
        for boundary in [
            ControlEffectBoundary::Preflight,
            ControlEffectBoundary::IntentPrepared,
            ControlEffectBoundary::EffectAttempted,
            ControlEffectBoundary::ResultCommit,
        ] {
            assert_eq!(
                error.control_failure_disposition(boundary),
                ControlFailureDisposition {
                    class: ControlFailureClass::TargetIdentityStale,
                    next_action: ControlFailureAction::RefreshTarget,
                }
            );
        }
    }

    #[test]
    fn io_is_clean_before_intent_and_indeterminate_after_intent() {
        let clean = SupervisorError::Io(std::io::Error::other("offline"));
        assert_eq!(
            clean
                .control_failure_disposition(ControlEffectBoundary::Preflight)
                .class,
            ControlFailureClass::NotStarted
        );
        let uncertain = SupervisorError::Io(std::io::Error::other("offline"));
        assert_eq!(
            uncertain
                .control_failure_disposition(ControlEffectBoundary::IntentPrepared)
                .class,
            ControlFailureClass::PersistenceIndeterminate
        );
    }

    #[test]
    fn durable_corruption_never_becomes_an_immediate_retry() {
        let error = SupervisorError::ControlRecoveryRequired("digest".to_string());
        assert_eq!(
            error.control_failure_disposition(ControlEffectBoundary::Preflight),
            ControlFailureDisposition {
                class: ControlFailureClass::RecoveryRequired,
                next_action: ControlFailureAction::RunRecovery,
            }
        );
    }
}
