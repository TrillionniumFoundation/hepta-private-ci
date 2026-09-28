// Retain the reviewed Agentd crate root and add only the canonical product-loop
// contract introduced by the existing intelligence ingress owner.
include!("lib_base.rs");

pub use intelligence_ingress::AgentdIntelligenceProductContinuationFuture;
pub use intelligence_ingress::AgentdIntelligenceProductContinuationV1;
pub use intelligence_ingress::AgentdIntelligenceProductLoopDispositionV1;
pub use intelligence_ingress::AgentdIntelligenceProductLoopReceiptV1;
