// Retain the reviewed Agentd crate root and add only canonical intelligence
// product composition contracts at the existing module boundary.
include!("lib_base.rs");

#[path = "intelligence_product_profile.rs"]
mod intelligence_product_profile;

pub use intelligence_ingress::AgentdIntelligenceProductContinuationFuture;
pub use intelligence_ingress::AgentdIntelligenceProductContinuationV1;
pub use intelligence_ingress::AgentdIntelligenceProductLoopDispositionV1;
pub use intelligence_ingress::AgentdIntelligenceProductLoopReceiptV1;
pub use intelligence_ingress::SupervisedHostOwnedAgentdIntelligenceInvocationProviderV1;
pub use intelligence_product_profile::compose_canonical_intelligence_product_profile;
