// Native composition of the same original lifecycle/storage implementation.
include!("state_core.rs");

pub(crate) type AgentdState<P = NativeCpuRuntimeOwners> = AgentdStateCore<P>;
