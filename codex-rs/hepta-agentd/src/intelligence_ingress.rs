// Preserve the reviewed ingress implementation at the same module depth while
// adding the panic-safe product provider selected by the atomic profile composer.
// Generated-source anchors retained here:
// - AgentdIntelligenceRunIdentityV1
// - objective_run_fence_digest_v1
// - impl<F> AgentdIntelligenceInvocationProviderV1
include!("intelligence_ingress_base.rs");

#[path = "intelligence_invocation_supervisor.rs"]
mod supervised_invocation;

pub use supervised_invocation::SupervisedHostOwnedAgentdIntelligenceInvocationProviderV1;
