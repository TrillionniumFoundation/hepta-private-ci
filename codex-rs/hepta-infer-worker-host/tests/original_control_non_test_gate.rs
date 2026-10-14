//! NON-TEST linked-library qualification for the original CNS production gate.
//!
//! Cargo compiles the library as an ordinary dependency for this integration
//! test. This is deliberately NOT a unit test inside batched_neuron.rs:
//! those unit fixtures may install fake Control frontier and research Metrics.
#![cfg(unix)]

use codex_hepta_infer_worker_host::original_evidence_neuron::OriginalEvidenceWorkerBootstrapErrorV1;
use codex_hepta_infer_worker_host::original_evidence_neuron::require_original_control_v1;

#[test]
fn non_test_library_denies_unverified_original_control_cns_before_worker_bootstrap() {
    assert_eq!(
        require_original_control_v1(),
        Err(OriginalEvidenceWorkerBootstrapErrorV1::UnverifiedOriginalControl)
    );
}
