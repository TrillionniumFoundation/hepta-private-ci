// Native typed lifecycle router over the original control transport.
include!("control_core.rs");

pub(crate) type AgentdControlServer<S = crate::state::NativeCpuRuntimeOwners> =
    AgentdControlServerCore<S>;
