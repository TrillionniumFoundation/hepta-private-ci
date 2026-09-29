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

#[derive(Debug)]
pub enum AgentdNeuronControlErrorV2 {
    Runtime(NeuronRuntimeV2Error),
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
}

impl fmt::Display for AgentdNeuronControlErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for AgentdNeuronControlErrorV2 {}

impl From<NeuronRuntimeV2Error> for AgentdNeuronControlErrorV2 {
    fn from(error: NeuronRuntimeV2Error) -> Self {
        Self::Runtime(error)
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
