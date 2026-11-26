//! Native-host adapter for cryptographically verified reconciliation evidence.
//!
//! Signed evidence is durably preserved before mapping to the legacy native
//! settlement shape. Administrative retirement remains distinct from provider
//! terminality.

include!("verified_reconciliation/store.rs");
include!("verified_reconciliation/mapping.rs");
include!("verified_reconciliation/tests.rs");
