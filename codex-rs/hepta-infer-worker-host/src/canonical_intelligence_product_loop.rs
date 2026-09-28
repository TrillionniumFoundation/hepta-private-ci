// Preserve the reviewed real product-loop implementation and add the bounded
// owner supervisor as an additive product constructor. No second executor,
// journal, learning writer, or authority issuer is introduced.
include!("canonical_intelligence_product_loop_base.rs");

#[path = "canonical_intelligence_owner_supervisor.rs"]
mod owner_supervisor;

pub use owner_supervisor::CanonicalIntelligenceOwnerSupervisorPolicyV1;
pub use owner_supervisor::SupervisedCanonicalIntelligenceProductLoopOwnerV1;
