#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum AgentdNeuronLifecycleStateV2 {
    Starting,
    Serving,
    Quiescing,
    Sealed,
    Reloading,
    Stopped,
    Failed,
}

/// Stable retry classification for logs, metrics, CLI output and operator
/// automation. This is advice only; it never grants execution or result-use
/// authority.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AgentdNeuronRetryClassV2 {
    NeverBusinessRetry,
    BoundedBackoff,
    ExactIdentityRecovery,
    ReconstructOwner,
    ReconstructController,
    RepairControlState,
}

impl AgentdNeuronRetryClassV2 {
    #[must_use]
    pub const fn stable_code(self) -> &'static str {
        match self {
            Self::NeverBusinessRetry => "never_business_retry",
            Self::BoundedBackoff => "bounded_backoff",
            Self::ExactIdentityRecovery => "exact_identity_recovery",
            Self::ReconstructOwner => "reconstruct_owner",
            Self::ReconstructController => "reconstruct_controller",
            Self::RepairControlState => "repair_control_state",
        }
    }
}

#[derive(Debug)]
pub enum AgentdNeuronControlErrorV2 {
    Runtime(NeuronRuntimeV2Error),
    ControlState(AgentdNeuronControlStateErrorV2),
    OwnerBusy,
    OwnerPoisoned,
    ControllerBusy,
    ControllerPoisoned,
    NotServing,
    InvalidTransition,
    GenerationConflict,
    PendingRecovery,
    UnknownGeneration,
}

impl AgentdNeuronControlErrorV2 {
    #[must_use]
    pub fn stable_code(&self) -> &'static str {
        match self {
            Self::Runtime(error) => error.stable_code(),
            Self::ControlState(error) => error.stable_code(),
            Self::OwnerBusy => "owner_busy",
            Self::OwnerPoisoned => "owner_poisoned",
            Self::ControllerBusy => "controller_busy",
            Self::ControllerPoisoned => "controller_poisoned",
            Self::NotServing => "not_serving",
            Self::InvalidTransition => "invalid_lifecycle_transition",
            Self::GenerationConflict => "generation_conflict",
            Self::PendingRecovery => "pending_recovery",
            Self::UnknownGeneration => "unknown_generation",
        }
    }

    #[must_use]
    pub const fn retry_class(&self) -> AgentdNeuronRetryClassV2 {
        match self {
            Self::Runtime(_) | Self::PendingRecovery => {
                AgentdNeuronRetryClassV2::ExactIdentityRecovery
            }
            Self::ControlState(AgentdNeuronControlStateErrorV2::Io(_))
            | Self::OwnerBusy
            | Self::ControllerBusy => AgentdNeuronRetryClassV2::BoundedBackoff,
            Self::ControlState(
                AgentdNeuronControlStateErrorV2::Invalid
                | AgentdNeuronControlStateErrorV2::Corrupt,
            ) => AgentdNeuronRetryClassV2::RepairControlState,
            Self::OwnerPoisoned => AgentdNeuronRetryClassV2::ReconstructOwner,
            Self::ControllerPoisoned => AgentdNeuronRetryClassV2::ReconstructController,
            Self::NotServing
            | Self::InvalidTransition
            | Self::GenerationConflict
            | Self::UnknownGeneration => AgentdNeuronRetryClassV2::NeverBusinessRetry,
        }
    }

    #[must_use]
    pub const fn operator_action(&self) -> &'static str {
        match self {
            Self::Runtime(_) => "inspect_exact_operation_and_reconcile",
            Self::ControlState(AgentdNeuronControlStateErrorV2::Invalid) => {
                "repair_control_state_namespace"
            }
            Self::ControlState(AgentdNeuronControlStateErrorV2::Corrupt) => {
                "retain_corrupt_bytes_and_reconstruct_topology"
            }
            Self::ControlState(AgentdNeuronControlStateErrorV2::Io(_)) => {
                "restore_control_state_storage_and_retry"
            }
            Self::OwnerBusy => "retry_control_observation_with_bounded_backoff",
            Self::OwnerPoisoned => "stop_serving_and_reconstruct_owner",
            Self::ControllerBusy => "keep_admission_closed_and_retry_after_drain",
            Self::ControllerPoisoned => "stop_serving_and_reconstruct_controller",
            Self::NotServing => "use_documented_lifecycle_transition",
            Self::InvalidTransition => "correct_lifecycle_transition_order",
            Self::GenerationConflict => "correct_generation_handoff_plan",
            Self::PendingRecovery => "reconcile_exact_provider_or_witness_identity",
            Self::UnknownGeneration => "restore_retained_generation_topology",
        }
    }

    /// Whether repeating the same control call without changing state is
    /// terminally invalid. This does not classify a model/business outcome.
    #[must_use]
    pub const fn is_terminal(&self) -> bool {
        matches!(
            self,
            Self::NotServing
                | Self::InvalidTransition
                | Self::GenerationConflict
                | Self::UnknownGeneration
        )
    }

    #[must_use]
    pub const fn is_reconstruction_required(&self) -> bool {
        matches!(self, Self::OwnerPoisoned | Self::ControllerPoisoned)
    }
}

impl fmt::Display for AgentdNeuronControlErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Runtime(error) => write!(
                formatter,
                "{}: runtime control failure: {error}",
                self.stable_code()
            ),
            Self::ControlState(error) => write!(
                formatter,
                "{}: durable control-state failure: {error}",
                self.stable_code()
            ),
            _ => write!(
                formatter,
                "{}: action={} retry_class={}",
                self.stable_code(),
                self.operator_action(),
                self.retry_class().stable_code()
            ),
        }
    }
}

impl StdError for AgentdNeuronControlErrorV2 {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Runtime(error) => Some(error),
            Self::ControlState(error) => Some(error),
            _ => None,
        }
    }
}

/// Optional exact operation context attached at the logging/CLI boundary. The
/// base control error deliberately does not retain request data; callers that
/// already own an exact durable key may attach it without weakening the typed
/// runtime or duplicating operation state.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AgentdNeuronOperationIdentityV2 {
    pub tick_id: StableId,
    pub input_semantic_digest: Digest32,
}

#[derive(Debug)]
pub struct AgentdNeuronControlFailureV2 {
    error: AgentdNeuronControlErrorV2,
    operation_identity: Option<AgentdNeuronOperationIdentityV2>,
}

impl AgentdNeuronControlFailureV2 {
    #[must_use]
    pub const fn new(error: AgentdNeuronControlErrorV2) -> Self {
        Self {
            error,
            operation_identity: None,
        }
    }

    #[must_use]
    pub fn with_operation(
        error: AgentdNeuronControlErrorV2,
        tick_id: StableId,
        input_semantic_digest: Digest32,
    ) -> Self {
        Self {
            error,
            operation_identity: Some(AgentdNeuronOperationIdentityV2 {
                tick_id,
                input_semantic_digest,
            }),
        }
    }

    #[must_use]
    pub const fn error(&self) -> &AgentdNeuronControlErrorV2 {
        &self.error
    }

    #[must_use]
    pub const fn operation_identity(&self) -> Option<&AgentdNeuronOperationIdentityV2> {
        self.operation_identity.as_ref()
    }

    #[must_use]
    pub fn stable_code(&self) -> &'static str {
        self.error.stable_code()
    }

    #[must_use]
    pub const fn retry_class(&self) -> AgentdNeuronRetryClassV2 {
        self.error.retry_class()
    }

    #[must_use]
    pub const fn operator_action(&self) -> &'static str {
        self.error.operator_action()
    }

    #[must_use]
    pub const fn is_terminal(&self) -> bool {
        self.error.is_terminal()
    }

    #[must_use]
    pub const fn is_reconstruction_required(&self) -> bool {
        self.error.is_reconstruction_required()
    }
}

impl fmt::Display for AgentdNeuronControlFailureV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        if let Some(identity) = &self.operation_identity {
            write!(
                formatter,
                "{} tick_id={} input_digest={}",
                self.error, identity.tick_id, identity.input_semantic_digest
            )
        } else {
            self.error.fmt(formatter)
        }
    }
}

impl StdError for AgentdNeuronControlFailureV2 {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        Some(&self.error)
    }
}

impl From<NeuronRuntimeV2Error> for AgentdNeuronControlErrorV2 {
    fn from(error: NeuronRuntimeV2Error) -> Self {
        Self::Runtime(error)
    }
}

impl From<AgentdNeuronControlErrorV2> for AgentdNeuronControlFailureV2 {
    fn from(error: AgentdNeuronControlErrorV2) -> Self {
        Self::new(error)
    }
}

struct AgentdNeuronGenerationControllerStateV2 {
    lifecycle: AgentdNeuronLifecycleStateV2,
    active: AgentdNeuronHandleV2,
    retained: BTreeMap<u64, AgentdNeuronHandleV2>,
    reload_target_generation: Option<u64>,
    state_path: Option<PathBuf>,
}

/// Explicit daemon lifecycle and generation handoff controller. Historical
/// handles remain queryable but cannot receive new invocations through this
/// controller after handoff.
pub struct AgentdNeuronGenerationControllerV2 {
    state: Mutex<AgentdNeuronGenerationControllerStateV2>,
}
