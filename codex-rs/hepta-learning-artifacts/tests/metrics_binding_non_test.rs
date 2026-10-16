//! The ordinary, non-test-linked CAS owner must not back-certify
//! a different Evidence sink. Internal fake metrics fixtures cannot qualify
//! product readiness by themselves.

use std::sync::Arc;

use codex_hepta_learning_artifacts::ArtifactCasOwnerV1;
use codex_hepta_types::PhaseMetricEventV1;
use codex_hepta_types::PhaseMetricSinkErrorV1;
use codex_hepta_types::PhaseMetricSinkV1;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;

#[derive(Debug)]
struct HealthySink;

impl PhaseMetricSinkV1 for HealthySink {
    fn healthy(&self) -> bool {
        true
    }

    fn flush(&self) -> Result<(), PhaseMetricSinkErrorV1> {
        Ok(())
    }

    fn record(&self, _event: PhaseMetricEventV1) -> Result<(), PhaseMetricSinkErrorV1> {
        Ok(())
    }
}

#[test]
fn product_library_rejects_cross_clone_evidence_writer_replacement() {
    let owner = ArtifactCasOwnerV1::new(
        StableId::new("artifact.metrics.external").expect("id"),
        SigningKey::from_bytes(&[41; 32]),
    )
    .expect("owner");
    let before_binding = owner.clone();
    let bound = owner.with_metrics_sink(Arc::new(HealthySink));
    assert!(bound.production_metrics_ready());

    let incompatible = before_binding.with_metrics_sink(Arc::new(HealthySink));
    assert!(!incompatible.production_metrics_ready());
    assert!(!incompatible.flush_production_metrics());
    // Shared poison means no surviving sibling can claim a clean history.
    assert!(!bound.production_metrics_ready());
    assert!(!bound.flush_production_metrics());
}

#[test]
fn product_library_rejects_rebinding_an_active_evidence_writer() {
    let owner = ArtifactCasOwnerV1::new(
        StableId::new("artifact.metrics.external-rebind").expect("id"),
        SigningKey::from_bytes(&[42; 32]),
    )
    .expect("owner")
    .with_metrics_sink(Arc::new(HealthySink));
    assert!(owner.production_metrics_ready());

    let attempted_rebind = owner.with_metrics_sink(Arc::new(HealthySink));
    assert!(!attempted_rebind.production_metrics_ready());
    assert!(!attempted_rebind.flush_production_metrics());
}
