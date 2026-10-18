#![cfg(feature = "trusted-inprocess-eval")]

// Historical Lane-E test target retained as a thin include so existing
// traceability remains stable. The canonical compatibility fixture is the
// isolated, non-publishable crate under fixtures/trusted-inprocess.
include!("../fixtures/trusted-inprocess/tests/operator_claim.rs");
