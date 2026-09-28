// Keep the reviewed owner adapters, signed evaluation and runner composition at
// the original module depth. The nested authority reader is selected explicitly
// by the product runner and closes path replacement, unbounded read and signed
// manifest rollback without introducing another authority owner.
include!("intelligence_product_base.rs");

#[path = "intelligence_authority_current.rs"]
mod secure_authority;
