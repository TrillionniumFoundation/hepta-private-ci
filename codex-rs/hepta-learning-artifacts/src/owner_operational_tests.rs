use std::collections::BTreeMap;

use codex_hepta_types::Digest32;

use crate::LearningArtifactOwnerServiceError;
use crate::owner::ArtifactOwnerFailureClassV1;
use crate::owner::ArtifactOwnerMetricsV1;
use crate::owner::ArtifactOwnerOperationalMetricsV1;
use crate::owner::ArtifactOwnerRetryDispositionV1;
use crate::owner::ArtifactOwnerStageSampleV1;
use crate::owner::ArtifactOwnerStageSummaryV1;
use crate::owner::ArtifactOwnerStageV1;
use crate::owner::ArtifactRetentionObservationV1;
use crate::owner::measure_stage;

#[test]
fn failure_classes_expose_distinct_operator_actions() {
    let withdrawal = LearningArtifactOwnerServiceError::WithdrawalFrontierConflict;
    assert_eq!(
        withdrawal.failure_class(),
        ArtifactOwnerFailureClassV1::WithdrawalFrontierInsufficient
    );
    assert_eq!(
        withdrawal.retry_disposition(),
        ArtifactOwnerRetryDispositionV1::RefreshWithdrawalFrontier
    );

    let unknown = LearningArtifactOwnerServiceError::WithdrawalDurabilityUnknown;
    assert_eq!(
        unknown.failure_class(),
        ArtifactOwnerFailureClassV1::PersistenceOutcomeUnknown
    );
    assert_eq!(
        unknown.retry_disposition(),
        ArtifactOwnerRetryDispositionV1::ReconcileExactIdentity
    );

    let identity = LearningArtifactOwnerServiceError::RequestMismatch;
    assert_eq!(
        identity.failure_class(),
        ArtifactOwnerFailureClassV1::IdentityConflict
    );
    assert_eq!(
        identity.retry_disposition(),
        ArtifactOwnerRetryDispositionV1::OperatorIntervention
    );
}

#[test]
fn operational_metrics_leave_unowned_retention_unknown() {
    let metrics = ArtifactOwnerOperationalMetricsV1 {
        base: ArtifactOwnerMetricsV1::default(),
        oldest_pending_attempt_age_seconds: Some(17),
        drain_age_seconds: None,
        recovery_reconciliation_failures: 2,
        withdrawal_blocks: 3,
        identity_conflicts: 4,
        stale_owner_rejections: 5,
        persistence_unknown: 6,
        capacity_rejections: 7,
        observability_failures: 0,
        retention: None,
        stage_summaries: BTreeMap::new(),
    };
    let encoded = metrics.response_json();
    assert!(encoded.contains("\"retention\":null"));
    assert!(encoded.contains("\"oldestPendingAttemptAgeSeconds\":17"));
    assert!(encoded.contains("\"persistenceUnknown\":6"));
}

#[test]
fn retention_observation_is_digest_bound_and_explicit() {
    let observation = ArtifactRetentionObservationV1 {
        pinned_bytes: 41,
        pending_physical_erase_bytes: 59,
        observed_at: 7,
        source_digest: Digest32::of_bytes(b"retention-owner-snapshot"),
    };
    let metrics = ArtifactOwnerOperationalMetricsV1 {
        base: ArtifactOwnerMetricsV1::default(),
        oldest_pending_attempt_age_seconds: None,
        drain_age_seconds: None,
        recovery_reconciliation_failures: 0,
        withdrawal_blocks: 0,
        identity_conflicts: 0,
        stale_owner_rejections: 0,
        persistence_unknown: 0,
        capacity_rejections: 0,
        observability_failures: 0,
        retention: Some(observation),
        stage_summaries: BTreeMap::new(),
    };
    let encoded = metrics.response_json();
    assert!(encoded.contains("\"pinnedBytes\":41"));
    assert!(encoded.contains("\"pendingPhysicalEraseBytes\":59"));
    assert!(encoded.contains(&observation.source_digest.to_string()));
}

#[test]
fn stage_measurement_preserves_failed_outcomes() {
    let (result, sample) = measure_stage(
        ArtifactOwnerStageV1::CheckpointSync,
        13,
        1,
        || -> Result<(), &'static str> { Err("injected-cut") },
    );
    assert_eq!(result, Err("injected-cut"));
    assert!(!sample.success);
    assert_eq!(sample.bytes, 13);

    let mut summary = ArtifactOwnerStageSummaryV1::default();
    summary.observe(sample);
    summary.observe(ArtifactOwnerStageSampleV1 {
        stage: ArtifactOwnerStageV1::CheckpointSync,
        elapsed_micros: 1,
        bytes: 0,
        records: 1,
        success: true,
    });
    assert_eq!(summary.samples, 2);
    assert_eq!(summary.failures, 1);
}
