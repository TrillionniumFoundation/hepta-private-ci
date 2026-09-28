//! Instrumented composition over the authenticated reference host.
//!
//! This wrapper does not add authority. It records bounded operational facts
//! around the existing request path and exposes the same durable outcomes.

use std::sync::Arc;
use std::time::Instant;

use crate::ArtifactOwnerFailureClassV1;
use crate::ArtifactOwnerOperationalMetricsV1;
use crate::ArtifactOwnerOperationalSnapshotV1;
use crate::ArtifactOwnerStageV1;

use super::ArtifactOwnerActionV1;
use super::ArtifactOwnerBootstrapV1;
use super::ArtifactOwnerCommandError;
use super::ArtifactOwnerCommandResultV1;
use super::ArtifactOwnerMetricsV1;
use super::ArtifactOwnerRuntimePhaseV1;
use super::ArtifactOwnerRuntimeStatusV1;
use super::LearningArtifactReferenceHostV1;
use super::SignedArtifactOwnerRequestV1;

#[derive(Debug)]
pub struct ObservedLearningArtifactReferenceHostV1 {
    inner: LearningArtifactReferenceHostV1,
    operational: Arc<ArtifactOwnerOperationalMetricsV1>,
}

impl ObservedLearningArtifactReferenceHostV1 {
    pub fn open(bootstrap: ArtifactOwnerBootstrapV1) -> Result<Self, ArtifactOwnerCommandError> {
        Self::open_with_metrics(
            bootstrap,
            Arc::new(ArtifactOwnerOperationalMetricsV1::default()),
        )
    }

    pub fn open_with_metrics(
        bootstrap: ArtifactOwnerBootstrapV1,
        operational: Arc<ArtifactOwnerOperationalMetricsV1>,
    ) -> Result<Self, ArtifactOwnerCommandError> {
        let now = bootstrap.runtime.service.now;
        let started = Instant::now();
        let inner = match LearningArtifactReferenceHostV1::open(bootstrap) {
            Ok(inner) => inner,
            Err(error) => {
                operational.record_stage(
                    ArtifactOwnerStageV1::StartupRecoveryScan,
                    started.elapsed(),
                );
                operational.observe_failure(error.failure_class(), now);
                return Err(error);
            }
        };
        operational.record_stage(
            ArtifactOwnerStageV1::StartupRecoveryScan,
            started.elapsed(),
        );
        let status = inner.status(now, "operational metrics initialization")?;
        observe_phase(&operational, &status, now);
        Ok(Self { inner, operational })
    }

    pub fn handle(
        &self,
        request: SignedArtifactOwnerRequestV1,
        now: u64,
    ) -> Result<ArtifactOwnerCommandResultV1, ArtifactOwnerCommandError> {
        let action = request.action;
        let stage = stage_for_action(action);
        let started = Instant::now();
        let result = self.inner.handle(request, now);
        self.operational.record_stage(stage, started.elapsed());

        match &result {
            Ok(value) => {
                if value.should_shutdown {
                    self.operational.begin_drain(now);
                }
                if action == ArtifactOwnerActionV1::RecoverPublish && !is_error_response(&value.response)
                {
                    self.operational.clear_pending_attempts();
                }
                if action == ArtifactOwnerActionV1::InstallWithdrawalFrontier
                    && !is_error_response(&value.response)
                {
                    self.operational.clear_withdrawal_block();
                }
                if is_error_response(&value.response) {
                    self.operational.observe_failure(
                        failure_from_persisted_response(&value.response),
                        now,
                    );
                }
            }
            Err(error) => self.operational.observe_failure(error.failure_class(), now),
        }

        if matches!(
            action,
            ArtifactOwnerActionV1::Publish
                | ArtifactOwnerActionV1::RecoverPublish
                | ArtifactOwnerActionV1::InstallWithdrawalFrontier
                | ArtifactOwnerActionV1::Shutdown
        ) && let Ok(status) = self.inner.status(now, "operational phase observation")
        {
            observe_phase(&self.operational, &status, now);
        }
        result
    }

    pub fn mark_stopped(&self, now: u64) -> Result<(), ArtifactOwnerCommandError> {
        let result = self.inner.mark_stopped(now);
        match &result {
            Ok(()) => self.operational.finish_drain(),
            Err(error) => self.operational.observe_failure(error.failure_class(), now),
        }
        result
    }

    #[must_use]
    pub fn shutdown_requested(&self) -> bool {
        self.inner.shutdown_requested()
    }

    #[must_use]
    pub fn reference_metrics(&self) -> ArtifactOwnerMetricsV1 {
        self.inner.metrics()
    }

    #[must_use]
    pub fn operational_metrics(&self) -> Arc<ArtifactOwnerOperationalMetricsV1> {
        Arc::clone(&self.operational)
    }

    #[must_use]
    pub fn operational_snapshot(&self, now: u64) -> ArtifactOwnerOperationalSnapshotV1 {
        self.operational.snapshot(now)
    }

    pub fn status(
        &self,
        now: u64,
        detail: impl Into<String>,
    ) -> Result<ArtifactOwnerRuntimeStatusV1, ArtifactOwnerCommandError> {
        self.inner.status(now, detail)
    }
}

const fn stage_for_action(action: ArtifactOwnerActionV1) -> ArtifactOwnerStageV1 {
    match action {
        ArtifactOwnerActionV1::Publish => ArtifactOwnerStageV1::PublicationTotal,
        ArtifactOwnerActionV1::RecoverPublish => {
            ArtifactOwnerStageV1::RecoveryReconciliation
        }
        ArtifactOwnerActionV1::InstallWithdrawalFrontier => {
            ArtifactOwnerStageV1::WithdrawalPersistence
        }
        ArtifactOwnerActionV1::Backup => ArtifactOwnerStageV1::Backup,
        ArtifactOwnerActionV1::Shutdown => ArtifactOwnerStageV1::DrainTransition,
        ArtifactOwnerActionV1::Health
        | ArtifactOwnerActionV1::Ready
        | ArtifactOwnerActionV1::Status
        | ArtifactOwnerActionV1::Metrics
        | ArtifactOwnerActionV1::ReloadAuthz => ArtifactOwnerStageV1::RequestDispatch,
    }
}

fn observe_phase(
    metrics: &ArtifactOwnerOperationalMetricsV1,
    status: &ArtifactOwnerRuntimeStatusV1,
    now: u64,
) {
    match status.phase {
        ArtifactOwnerRuntimePhaseV1::Recovering => {
            metrics.mark_pending_attempt(status.started_at.min(now));
        }
        ArtifactOwnerRuntimePhaseV1::Ready => metrics.clear_pending_attempts(),
        ArtifactOwnerRuntimePhaseV1::Draining => metrics.begin_drain(now),
        ArtifactOwnerRuntimePhaseV1::Starting
        | ArtifactOwnerRuntimePhaseV1::Stopped
        | ArtifactOwnerRuntimePhaseV1::Failed => {}
    }
}

fn is_error_response(response: &[u8]) -> bool {
    response.starts_with(b"{\"schema\":\"hepta.learning-artifactd.error.v1\"")
}

fn failure_from_persisted_response(response: &[u8]) -> ArtifactOwnerFailureClassV1 {
    for (needle, failure) in [
        (
            b"\"code\":\"identity_conflict\"".as_slice(),
            ArtifactOwnerFailureClassV1::IdentityConflict,
        ),
        (
            b"\"code\":\"stale_owner\"".as_slice(),
            ArtifactOwnerFailureClassV1::StaleOwner,
        ),
        (
            b"\"code\":\"withdrawal_frontier_conflict\"".as_slice(),
            ArtifactOwnerFailureClassV1::WithdrawalFrontier,
        ),
        (
            b"\"code\":\"persistence_unknown\"".as_slice(),
            ArtifactOwnerFailureClassV1::PersistenceUnknown,
        ),
        (
            b"\"code\":\"capacity_exhausted\"".as_slice(),
            ArtifactOwnerFailureClassV1::Capacity,
        ),
        (
            b"\"code\":\"recovery_required\"".as_slice(),
            ArtifactOwnerFailureClassV1::RecoveryRequired,
        ),
        (
            b"\"code\":\"draining\"".as_slice(),
            ArtifactOwnerFailureClassV1::Draining,
        ),
    ] {
        if response.windows(needle.len()).any(|window| window == needle) {
            return failure;
        }
    }
    ArtifactOwnerFailureClassV1::InternalInvariant
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_action_maps_to_one_bounded_stage() {
        for action in [
            ArtifactOwnerActionV1::Health,
            ArtifactOwnerActionV1::Ready,
            ArtifactOwnerActionV1::Status,
            ArtifactOwnerActionV1::Metrics,
            ArtifactOwnerActionV1::Publish,
            ArtifactOwnerActionV1::RecoverPublish,
            ArtifactOwnerActionV1::InstallWithdrawalFrontier,
            ArtifactOwnerActionV1::ReloadAuthz,
            ArtifactOwnerActionV1::Backup,
            ArtifactOwnerActionV1::Shutdown,
        ] {
            assert!(ArtifactOwnerStageV1::ALL.contains(&stage_for_action(action)));
        }
    }

    #[test]
    fn stable_error_responses_drive_actionable_counters() {
        let response = b"{\"schema\":\"hepta.learning-artifactd.error.v1\",\"code\":\"capacity_exhausted\"}\n";
        assert!(is_error_response(response));
        assert_eq!(
            failure_from_persisted_response(response),
            ArtifactOwnerFailureClassV1::Capacity
        );
    }
}
