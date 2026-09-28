// Retain the reviewed Agentd crate root and add only canonical intelligence
// product composition contracts at the existing module boundary.
include!("lib_base.rs");

#[path = "intelligence_authority_rollback.rs"]
mod intelligence_authority_rollback;
#[path = "intelligence_files.rs"]
mod intelligence_files;
#[path = "intelligence_product_profile.rs"]
mod intelligence_product_profile;

pub use intelligence_authority_rollback::IntelligenceAuthorityRollbackErrorV1;
pub use intelligence_authority_rollback::IntelligenceAuthorityRollbackGuardV1;
pub use intelligence_ingress::AgentdIntelligenceProductContinuationFuture;
pub use intelligence_ingress::AgentdIntelligenceProductContinuationV1;
pub use intelligence_ingress::AgentdIntelligenceProductLoopDispositionV1;
pub use intelligence_ingress::AgentdIntelligenceProductLoopReceiptV1;
pub use intelligence_ingress::SupervisedHostOwnedAgentdIntelligenceInvocationProviderV1;
pub use intelligence_product::AgentdIntelligencePhysicalPromptV1;
pub use intelligence_product::intelligence_authority_manifest_digest_v1;
pub use intelligence_product_profile::compose_canonical_intelligence_product_profile;

#[cfg(test)]
#[path = "intelligence_control_internal/intelligence_acceptance_tests.rs"]
mod intelligence_acceptance_tests;
