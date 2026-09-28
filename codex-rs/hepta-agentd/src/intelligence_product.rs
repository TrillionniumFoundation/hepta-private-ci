// The active canonical implementation is retained in a single base file so
// product DTOs, owner-backed Prompt delivery and bounded runner types remain at
// their historical module path. No second control plane or executor is added.
include!("intelligence_product_base.rs");
