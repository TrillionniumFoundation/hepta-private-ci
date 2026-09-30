//! Operational projection and stable failure taxonomy for the artifact owner.
//!
//! This layer observes the existing authenticated reference host. It does not
//! create a second writer, weaken recovery, or turn metrics into authority.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::sync::Mutex;
use std::time::Instant;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactOwnerHostError;
use crate::LearningArtifactOwnerServiceError;

use super::ArtifactOwnerActionV1;
use super::ArtifactOwnerBootstrapV1;
use super::ArtifactOwnerCommandError;
use super::ArtifactOwnerCommandResultV1;
use super::ArtifactOwnerMetricsV1;
use super::ArtifactOwnerRuntimeStatusV1;
use super::LearningArtifactReferenceHostV1;
use super::OwnerJournalError;
use super::PublishArtifactCommandV1;
use super::SignedArtifactOwnerRequestV1;
use super::measurement::ArtifactOwnerStageSampleV1;
use super::measurement::ArtifactOwnerStageSummaryV1;
use super::measurement::ArtifactOwnerStageV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArtifactOwnerFailureClassV1 {
    IdentityConflict,
    StaleOwner,
    WithdrawalFrontierInsufficient,
    PersistenceOutcomeUnknown,
    CapacityExhausted,
    RecoveryRequired,
    Draining,
    Unauthorized,
    CorruptState,
    Unavailable,
    InvalidConfiguration,
    Internal,
}

impl ArtifactOwnerFailureClassV1 {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::IdentityConflict => "identity_conflict",
            Self::StaleOwner => "stale_owner",
            Self::WithdrawalFrontierInsufficient => "withdrawal_frontier_insufficient",
            Self::PersistenceOutcomeUnknown => "persistence_outcome_unknown",
            Self::CapacityExhausted => "capacity_exhausted",
            Self::RecoveryRequired => "recovery_required",
            Self::Draining => "draining",
            Self::Unauthorized => "unauthorized",
            Self::CorruptState => "corrupt_state",
            Self::Unavailable => "unavailable",
            Self::InvalidConfiguration => "invalid_configuration",
            Self::Internal => "internal",
        }
    }

    #[must_use]
    pub const fn retry_disposition(self) -> ArtifactOwnerRetryDispositionV1 {
        match self {
            Self::IdentityConflict | Self::CorruptState | Self::Internal => {
                ArtifactOwnerRetryDispositionV1::OperatorIntervention
            }
            Self::StaleOwner | Self::Unauthorized | Self::InvalidConfiguration => {
                ArtifactOwnerRetryDispositionV1::RefreshAuthority
            }
            Self::WithdrawalFrontierInsufficient => {
                ArtifactOwnerRetryDispositionV1::RefreshWithdrawalFrontier
            }
            Self::PersistenceOutcomeUnknown | Self::RecoveryRequired => {
                ArtifactOwnerRetryDispositionV1::ReconcileExactIdentity
            }
            Self::CapacityExhausted => ArtifactOwnerRetryDispositionV1::FreeCapacity,
            Self::Draining => ArtifactOwnerRetryDispositionV1::UseReplacementOwner,
            Self::Unavailable => ArtifactOwnerRetryDispositionV1::BoundedBackoff,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArtifactOwnerRetryDispositionV1 {
    OperatorIntervention,
    RefreshAuthority,
    RefreshWithdrawalFrontier,
    ReconcileExactIdentity,
    FreeCapacity,
    UseReplacementOwner,
    BoundedBackoff,
}

impl ArtifactOwnerRetryDispositionV1 {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::OperatorIntervention => "operator_intervention",
            Self::RefreshAuthority => "refresh_authority",
            Self::RefreshWithdrawalFrontier => "refresh_withdrawal_frontier",
            Self::ReconcileExactIdentity => "reconcile_exact_identity",
            Self::FreeCapacity => "free_capacity",
            Self::UseReplacementOwner => "use_replacement_owner",
            Self::BoundedBackoff => "bounded_backoff",
        }
    }
}

impl LearningArtifactOwnerServiceError {
    #[must_use]
    pub fn failure_class(&self) -> ArtifactOwnerFailureClassV1 {
        match self {
            Self::Host(error) => classify_host_error(error),
            Self::Publication(_) => ArtifactOwnerFailureClassV1::IdentityConflict,
            Self::ControlIo(_) | Self::WithdrawalDurabilityUnknown => {
                ArtifactOwnerFailureClassV1::PersistenceOutcomeUnknown
            }
            Self::InvalidConfiguration => ArtifactOwnerFailureClassV1::InvalidConfiguration,
            Self::WithdrawalFrontierConflict => {
                ArtifactOwnerFailureClassV1::WithdrawalFrontierInsufficient
            }
            Self::RecoveryConflict | Self::CheckpointShape | Self::UnexpectedPhase => {
                ArtifactOwnerFailureClassV1::CorruptState
            }
            Self::RecoveryRequired(_) => ArtifactOwnerFailureClassV1::RecoveryRequired,
            Self::RequestMismatch | Self::CheckpointMismatch => {
                ArtifactOwnerFailureClassV1::IdentityConflict
            }
            Self::Draining => ArtifactOwnerFailureClassV1::Draining,
        }
    }

    #[must_use]
    pub fn stable_code(&self) -> &'static str {
        self.failure_class().as_str()
    }

    #[must_use]
    pub fn retry_disposition(&self) -> ArtifactOwnerRetryDispositionV1 {
        self.failure_class().retry_disposition()
    }
}

fn classify_host_error(error: &ArtifactOwnerHostError) -> ArtifactOwnerFailureClassV1 {
    match error {
        ArtifactOwnerHostError::WriterLeaseContext
        | ArtifactOwnerHostError::WriterFenceBusy
        | ArtifactOwnerHostError::SignerContext
        | ArtifactOwnerHostError::SignerRevoked
        | ArtifactOwnerHostError::CurrentHeadExpired => ArtifactOwnerFailureClassV1::StaleOwner,
        ArtifactOwnerHostError::InvalidTrust
        | ArtifactOwnerHostError::InvalidKey
        | ArtifactOwnerHostError::UnknownSigner
        | ArtifactOwnerHostError::InvalidSignature => ArtifactOwnerFailureClassV1::Unauthorized,
        ArtifactOwnerHostError::RegistryPredecessorMismatch
        | ArtifactOwnerHostError::CurrentHeadConflict
        | ArtifactOwnerHostError::CurrentHeadRollback
        | ArtifactOwnerHostError::CheckpointMismatch
        | ArtifactOwnerHostError::IdentityConflict => ArtifactOwnerFailureClassV1::IdentityConflict,
        ArtifactOwnerHostError::CurrentHeadFork
        | ArtifactOwnerHostError::CheckpointMissing
        | ArtifactOwnerHostError::CheckpointGap
        | ArtifactOwnerHostError::CurrentHeadContext
        | ArtifactOwnerHostError::PathBoundary => ArtifactOwnerFailureClassV1::CorruptState,
        ArtifactOwnerHostError::Capacity => ArtifactOwnerFailureClassV1::CapacityExhausted,
        ArtifactOwnerHostError::Io(_) | ArtifactOwnerHostError::Indeterminate => {
            ArtifactOwnerFailureClassV1::PersistenceOutcomeUnknown
        }
        ArtifactOwnerHostError::Storage(_)
        | ArtifactOwnerHostError::Publication(_)
        | ArtifactOwnerHostError::Registry(_) => ArtifactOwnerFailureClassV1::Unavailable,
        ArtifactOwnerHostError::InternalInvariant => ArtifactOwnerFailureClassV1::Internal,
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ArtifactRetentionObservationV1 {
    pub pinned_bytes: u64,
    pub pending_physical_erase_bytes: u64,
    pub observed_at: u64,
    pub source_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArtifactOperationalObservationError {
    ZeroSourceDigest,
    FutureObservation,
    Poisoned,
}

impl fmt::Display for ArtifactOperationalObservationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ArtifactOperationalObservationError {}

#[derive(Clone, Debug, Default)]
struct ArtifactOperationalStateV1 {
    pending_attempts: BTreeMap<StableId, u64>,
    drain_started_at: Option<u64>,
    recovery_reconciliation_failures: u64,
    withdrawal_blocks: u64,
    identity_conflicts: u64,
    stale_owner_rejections: u64,
    persistence_unknown: u64,
    capacity_rejections: u64,
    observability_failures: u64,
    retention: Option<ArtifactRetentionObservationV1>,
    stages: BTreeMap<ArtifactOwnerStageV1, ArtifactOwnerStageSummaryV1>,
}

#[derive(Clone, Debug)]
pub struct ArtifactOwnerOperationalMetricsV1 {
    pub base: ArtifactOwnerMetricsV1,
    pub oldest_pending_attempt_age_seconds: Option<u64>,
    pub drain_age_seconds: Option<u64>,
    pub recovery_reconciliation_failures: u64,
    pub withdrawal_blocks: u64,
    pub identity_conflicts: u64,
    pub stale_owner_rejections: u64,
    pub persistence_unknown: u64,
    pub capacity_rejections: u64,
    pub observability_failures: u64,
    pub retention: Option<ArtifactRetentionObservationV1>,
    pub stage_summaries: BTreeMap<ArtifactOwnerStageV1, ArtifactOwnerStageSummaryV1>,
}

impl ArtifactOwnerOperationalMetricsV1 {
    /// Prometheus textfile projection for node_exporter or another local
    /// collector. Observability is never accepted as authority or qualification.
    #[must_use]
    pub fn prometheus_text(&self) -> String {
        let mut output = String::new();
        macro_rules! counter {
            ($name:literal, $value:expr) => {
                output.push_str(concat!("# TYPE ", $name, " counter\n", $name, " "));
                output.push_str(&$value.to_string());
                output.push('\n');
            };
        }
        macro_rules! gauge {
            ($name:literal, $value:expr) => {
                output.push_str(concat!("# TYPE ", $name, " gauge\n", $name, " "));
                output.push_str(&$value.to_string());
                output.push('\n');
            };
        }

        counter!(
            "hepta_learning_artifact_requests_received_total",
            self.base.requests_received
        );
        counter!(
            "hepta_learning_artifact_requests_authenticated_total",
            self.base.requests_authenticated
        );
        counter!(
            "hepta_learning_artifact_authentication_failures_total",
            self.base.authentication_failures
        );
        counter!(
            "hepta_learning_artifact_exact_replays_total",
            self.base.exact_replays
        );
        counter!(
            "hepta_learning_artifact_replay_conflicts_total",
            self.base.replay_conflicts
        );
        counter!(
            "hepta_learning_artifact_publications_succeeded_total",
            self.base.publications_succeeded
        );
        counter!(
            "hepta_learning_artifact_publications_failed_total",
            self.base.publications_failed
        );
        counter!(
            "hepta_learning_artifact_recovery_publications_succeeded_total",
            self.base.recovery_publications_succeeded
        );
        counter!(
            "hepta_learning_artifact_withdrawal_frontiers_installed_total",
            self.base.withdrawal_frontiers_installed
        );
        counter!(
            "hepta_learning_artifact_authz_reloads_total",
            self.base.authz_reloads
        );
        counter!(
            "hepta_learning_artifact_backups_succeeded_total",
            self.base.backups_succeeded
        );
        counter!(
            "hepta_learning_artifact_command_failures_total",
            self.base.command_failures
        );
        counter!(
            "hepta_learning_artifact_recovery_reconciliation_failures_total",
            self.recovery_reconciliation_failures
        );
        counter!(
            "hepta_learning_artifact_withdrawal_blocks_total",
            self.withdrawal_blocks
        );
        counter!(
            "hepta_learning_artifact_identity_conflicts_total",
            self.identity_conflicts
        );
        counter!(
            "hepta_learning_artifact_stale_owner_rejections_total",
            self.stale_owner_rejections
        );
        counter!(
            "hepta_learning_artifact_persistence_unknown_total",
            self.persistence_unknown
        );
        counter!(
            "hepta_learning_artifact_capacity_rejections_total",
            self.capacity_rejections
        );
        counter!(
            "hepta_learning_artifact_observability_failures_total",
            self.observability_failures
        );
        if let Some(value) = self.oldest_pending_attempt_age_seconds {
            gauge!("hepta_learning_artifact_oldest_pending_attempt_age_seconds", value);
        }
        if let Some(value) = self.drain_age_seconds {
            gauge!("hepta_learning_artifact_drain_age_seconds", value);
        }
        if let Some(retention) = self.retention {
            gauge!("hepta_learning_artifact_pinned_bytes", retention.pinned_bytes);
            gauge!(
                "hepta_learning_artifact_pending_physical_erase_bytes",
                retention.pending_physical_erase_bytes
            );
            gauge!(
                "hepta_learning_artifact_retention_observed_at_seconds",
                retention.observed_at
            );
        }
        for (stage, summary) in &self.stage_summaries {
            output.push_str(&format!(
                "hepta_learning_artifact_stage_samples_total{{stage=\"{}\"}} {}\n",
                stage.as_str(),
                summary.samples
            ));
            output.push_str(&format!(
                "hepta_learning_artifact_stage_failures_total{{stage=\"{}\"}} {}\n",
                stage.as_str(),
                summary.failures
            ));
            output.push_str(&format!(
                "hepta_learning_artifact_stage_elapsed_micros_total{{stage=\"{}\"}} {}\n",
                stage.as_str(),
                summary.total_micros
            ));
            output.push_str(&format!(
                "hepta_learning_artifact_stage_maximum_micros{{stage=\"{}\"}} {}\n",
                stage.as_str(),
                summary.maximum_micros
            ));
        }
        output
    }

    #[must_use]
    pub fn response_json(&self) -> String {
        let base = self.base.response_json();
        let stages = self
            .stage_summaries
            .iter()
            .map(|(stage, summary)| {
                format!("\"{}\":{}", stage.as_str(), summary.response_json())
            })
            .collect::<Vec<_>>()
            .join(",");
        let retention = self.retention.map_or_else(
            || "null".to_owned(),
            |value| {
                format!(
                    concat!(
                        "{{\"pinnedBytes\":{},\"pendingPhysicalEraseBytes\":{},",
                        "\"observedAt\":{},\"sourceDigest\":\"{}\"}}"
                    ),
                    value.pinned_bytes,
                    value.pending_physical_erase_bytes,
                    value.observed_at,
                    value.source_digest,
                )
            },
        );
        let mut output = format!(
            concat!(
                "{{\"schema\":\"hepta.learning-artifactd.operational-metrics.v1\",",
                "\"base\":{},\"oldestPendingAttemptAgeSeconds\":{},",
                "\"drainAgeSeconds\":{},\"recoveryReconciliationFailures\":{},",
                "\"withdrawalBlocks\":{},\"identityConflicts\":{},",
                "\"staleOwnerRejections\":{},\"persistenceUnknown\":{},",
                "\"capacityRejections\":{},\"observabilityFailures\":{},",
                "\"retention\":{},\"stageSummaries\":{{"
            ),
            base.trim(),
            optional_u64(self.oldest_pending_attempt_age_seconds),
            optional_u64(self.drain_age_seconds),
            self.recovery_reconciliation_failures,
            self.withdrawal_blocks,
            self.identity_conflicts,
            self.stale_owner_rejections,
            self.persistence_unknown,
            self.capacity_rejections,
            self.observability_failures,
            retention,
        );
        output.push_str(&stages);
        output.push_str("}}");
        output
    }
}

pub struct InstrumentedLearningArtifactReferenceHostV1 {
    inner: LearningArtifactReferenceHostV1,
    operational: Mutex<ArtifactOperationalStateV1>,
}

impl fmt::Debug for InstrumentedLearningArtifactReferenceHostV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("InstrumentedLearningArtifactReferenceHostV1")
            .field("inner", &self.inner)
            .finish_non_exhaustive()
    }
}

impl InstrumentedLearningArtifactReferenceHostV1 {
    pub fn open(bootstrap: ArtifactOwnerBootstrapV1) -> Result<Self, ArtifactOwnerCommandError> {
        let now = bootstrap.runtime.service.now;
        let started = Instant::now();
        let inner = LearningArtifactReferenceHostV1::open(bootstrap)?;
        let elapsed = elapsed_micros(started);
        let status = inner.status(now, "operational projection initialized")?;
        let mut operational = ArtifactOperationalStateV1::default();
        operational.observe(ArtifactOwnerStageSampleV1 {
            stage: ArtifactOwnerStageV1::StartupRecoveryScan,
            elapsed_micros: elapsed,
            bytes: 0,
            records: 0,
            success: true,
        });
        if let Some(operation_id) = status.recovery_operation_id {
            operational
                .pending_attempts
                .insert(operation_id, status.started_at.min(now));
        }
        if status.phase == super::ArtifactOwnerRuntimePhaseV1::Draining {
            operational.drain_started_at = Some(status.observed_at.min(now));
        }
        Ok(Self {
            inner,
            operational: Mutex::new(operational),
        })
    }

    pub fn handle(
        &self,
        request: SignedArtifactOwnerRequestV1,
        now: u64,
    ) -> Result<ArtifactOwnerCommandResultV1, ArtifactOwnerCommandError> {
        let action = request.action;
        let issued_at = request.issued_at.min(now);
        let attempt_id = if matches!(
            action,
            ArtifactOwnerActionV1::Publish | ArtifactOwnerActionV1::RecoverPublish
        ) {
            PublishArtifactCommandV1::decode(&request.payload)
                .map(|command| command.operation_id)
                .unwrap_or_else(|_| request.request_id.clone())
        } else {
            request.request_id.clone()
        };
        if matches!(
            action,
            ArtifactOwnerActionV1::Publish | ArtifactOwnerActionV1::RecoverPublish
        ) {
            self.operational
                .lock()
                .map_err(|_| ArtifactOwnerCommandError::Poisoned)?
                .pending_attempts
                .entry(attempt_id.clone())
                .or_insert(issued_at);
        }

        let started = Instant::now();
        let result = self.inner.handle(request, now);
        let elapsed = elapsed_micros(started);
        let command_success = match &result {
            Ok(response) => !response_is_error(&response.response),
            Err(_) => false,
        };
        let status = self
            .inner
            .status(now, "operational post-request observation")
            .ok();
        let mut state = self
            .operational
            .lock()
            .map_err(|_| ArtifactOwnerCommandError::Poisoned)?;
        state.observe(ArtifactOwnerStageSampleV1 {
            stage: ArtifactOwnerStageV1::RequestTotal,
            elapsed_micros: elapsed,
            bytes: 0,
            records: 0,
            success: command_success,
        });
        let action_stage = action_stage(action);
        if action_stage != ArtifactOwnerStageV1::RequestTotal {
            state.observe(ArtifactOwnerStageSampleV1 {
                stage: action_stage,
                elapsed_micros: elapsed,
                bytes: 0,
                records: 0,
                success: command_success,
            });
        }

        match &result {
            Ok(response) => {
                if matches!(
                    action,
                    ArtifactOwnerActionV1::Publish | ArtifactOwnerActionV1::RecoverPublish
                ) {
                    if response_is_publication_success(&response.response) {
                        state.pending_attempts.remove(&attempt_id);
                    } else if let Some(observed) = status.as_ref() {
                        if let Some(operation_id) = observed.recovery_operation_id.clone() {
                            state
                                .pending_attempts
                                .entry(operation_id)
                                .or_insert(issued_at);
                        } else {
                            state.pending_attempts.remove(&attempt_id);
                        }
                    }
                    if action == ArtifactOwnerActionV1::RecoverPublish
                        && !response_is_publication_success(&response.response)
                    {
                        state.recovery_reconciliation_failures = state
                            .recovery_reconciliation_failures
                            .saturating_add(1);
                    }
                }
                if action == ArtifactOwnerActionV1::Shutdown && response.should_shutdown {
                    state.drain_started_at.get_or_insert(now);
                }
                state.observe_response(&response.response);
            }
            Err(error) => {
                state.observe_failure(command_failure_class(error));
                if matches!(
                    action,
                    ArtifactOwnerActionV1::Publish | ArtifactOwnerActionV1::RecoverPublish
                ) && status
                    .as_ref()
                    .and_then(|value| value.recovery_operation_id.as_ref())
                    != Some(&attempt_id)
                {
                    state.pending_attempts.remove(&attempt_id);
                }
            }
        }
        result
    }

    pub fn observe_retention(
        &self,
        observation: ArtifactRetentionObservationV1,
        now: u64,
    ) -> Result<(), ArtifactOperationalObservationError> {
        if observation.source_digest.is_zero() {
            return Err(ArtifactOperationalObservationError::ZeroSourceDigest);
        }
        if observation.observed_at > now {
            return Err(ArtifactOperationalObservationError::FutureObservation);
        }
        self.operational
            .lock()
            .map_err(|_| ArtifactOperationalObservationError::Poisoned)?
            .retention = Some(observation);
        Ok(())
    }

    pub fn observe_stage(
        &self,
        sample: ArtifactOwnerStageSampleV1,
    ) -> Result<(), ArtifactOperationalObservationError> {
        self.operational
            .lock()
            .map_err(|_| ArtifactOperationalObservationError::Poisoned)?
            .observe(sample);
        Ok(())
    }

    pub fn operational_metrics(
        &self,
        now: u64,
    ) -> Result<ArtifactOwnerOperationalMetricsV1, ArtifactOwnerCommandError> {
        let base = self.inner.metrics();
        let state = self
            .operational
            .lock()
            .map_err(|_| ArtifactOwnerCommandError::Poisoned)?;
        Ok(ArtifactOwnerOperationalMetricsV1 {
            base,
            oldest_pending_attempt_age_seconds: state
                .pending_attempts
                .values()
                .min()
                .map(|started| now.saturating_sub(*started)),
            drain_age_seconds: state
                .drain_started_at
                .map(|started| now.saturating_sub(started)),
            recovery_reconciliation_failures: state.recovery_reconciliation_failures,
            withdrawal_blocks: state.withdrawal_blocks,
            identity_conflicts: state.identity_conflicts,
            stale_owner_rejections: state.stale_owner_rejections,
            persistence_unknown: state.persistence_unknown,
            capacity_rejections: state.capacity_rejections,
            observability_failures: state.observability_failures,
            retention: state.retention,
            stage_summaries: state.stages.clone(),
        })
    }

    pub fn status(
        &self,
        now: u64,
        detail: impl Into<String>,
    ) -> Result<ArtifactOwnerRuntimeStatusV1, ArtifactOwnerCommandError> {
        self.inner.status(now, detail)
    }

    #[must_use]
    pub fn base_metrics(&self) -> ArtifactOwnerMetricsV1 {
        self.inner.metrics()
    }

    #[must_use]
    pub fn shutdown_requested(&self) -> bool {
        self.inner.shutdown_requested()
    }

    pub fn mark_stopped(&self, now: u64) -> Result<(), ArtifactOwnerCommandError> {
        self.inner.mark_stopped(now)
    }

    #[must_use]
    pub const fn inner(&self) -> &LearningArtifactReferenceHostV1 {
        &self.inner
    }
}

impl ArtifactOperationalStateV1 {
    fn observe(&mut self, sample: ArtifactOwnerStageSampleV1) {
        self.stages.entry(sample.stage).or_default().observe(sample);
    }

    fn observe_response(&mut self, response: &[u8]) {
        if !response_is_error(response) {
            return;
        }
        let class = if contains(response, b"WithdrawalFrontierConflict")
            || contains(response, b"WithdrawnDataset")
        {
            ArtifactOwnerFailureClassV1::WithdrawalFrontierInsufficient
        } else if contains(response, b"WithdrawalDurabilityUnknown")
            || contains(response, b"Indeterminate")
            || contains(response, b"ControlIo")
        {
            ArtifactOwnerFailureClassV1::PersistenceOutcomeUnknown
        } else if contains(response, b"WriterLeaseContext")
            || contains(response, b"WriterFenceBusy")
            || contains(response, b"CurrentHeadExpired")
        {
            ArtifactOwnerFailureClassV1::StaleOwner
        } else if contains(response, b"Capacity") {
            ArtifactOwnerFailureClassV1::CapacityExhausted
        } else if contains(response, b"RequestMismatch")
            || contains(response, b"IdentityConflict")
            || contains(response, b"CheckpointMismatch")
        {
            ArtifactOwnerFailureClassV1::IdentityConflict
        } else if contains(response, b"RecoveryRequired") {
            ArtifactOwnerFailureClassV1::RecoveryRequired
        } else {
            ArtifactOwnerFailureClassV1::Unavailable
        };
        self.observe_failure(class);
    }

    fn observe_failure(&mut self, class: ArtifactOwnerFailureClassV1) {
        match class {
            ArtifactOwnerFailureClassV1::IdentityConflict => {
                self.identity_conflicts = self.identity_conflicts.saturating_add(1);
            }
            ArtifactOwnerFailureClassV1::StaleOwner => {
                self.stale_owner_rejections = self.stale_owner_rejections.saturating_add(1);
            }
            ArtifactOwnerFailureClassV1::WithdrawalFrontierInsufficient => {
                self.withdrawal_blocks = self.withdrawal_blocks.saturating_add(1);
            }
            ArtifactOwnerFailureClassV1::PersistenceOutcomeUnknown => {
                self.persistence_unknown = self.persistence_unknown.saturating_add(1);
            }
            ArtifactOwnerFailureClassV1::CapacityExhausted => {
                self.capacity_rejections = self.capacity_rejections.saturating_add(1);
            }
            ArtifactOwnerFailureClassV1::RecoveryRequired => {
                self.recovery_reconciliation_failures = self
                    .recovery_reconciliation_failures
                    .saturating_add(1);
            }
            ArtifactOwnerFailureClassV1::Draining
            | ArtifactOwnerFailureClassV1::Unauthorized
            | ArtifactOwnerFailureClassV1::CorruptState
            | ArtifactOwnerFailureClassV1::Unavailable
            | ArtifactOwnerFailureClassV1::InvalidConfiguration
            | ArtifactOwnerFailureClassV1::Internal => {
                self.observability_failures = self.observability_failures.saturating_add(1);
            }
        }
    }
}

fn command_failure_class(error: &ArtifactOwnerCommandError) -> ArtifactOwnerFailureClassV1 {
    match error {
        ArtifactOwnerCommandError::Service(error) => error.failure_class(),
        ArtifactOwnerCommandError::Capability(_) => ArtifactOwnerFailureClassV1::Unauthorized,
        ArtifactOwnerCommandError::Journal(OwnerJournalError::ReplayConflict) => {
            ArtifactOwnerFailureClassV1::IdentityConflict
        }
        ArtifactOwnerCommandError::Journal(OwnerJournalError::Capacity) => {
            ArtifactOwnerFailureClassV1::CapacityExhausted
        }
        ArtifactOwnerCommandError::Journal(_) | ArtifactOwnerCommandError::Io(_) => {
            ArtifactOwnerFailureClassV1::PersistenceOutcomeUnknown
        }
        ArtifactOwnerCommandError::Decode(_)
        | ArtifactOwnerCommandError::Admission(_)
        | ArtifactOwnerCommandError::RecoveryOperationMismatch
        | ArtifactOwnerCommandError::RequestTimeMismatch
        | ArtifactOwnerCommandError::UnexpectedPayload => {
            ArtifactOwnerFailureClassV1::IdentityConflict
        }
        ArtifactOwnerCommandError::Storage(_)
        | ArtifactOwnerCommandError::Reconciliation(_)
        | ArtifactOwnerCommandError::Status(_)
        | ArtifactOwnerCommandError::Owner(_)
        | ArtifactOwnerCommandError::SnapshotPath => ArtifactOwnerFailureClassV1::Unavailable,
        ArtifactOwnerCommandError::Config(_) | ArtifactOwnerCommandError::KeyringRollback => {
            ArtifactOwnerFailureClassV1::InvalidConfiguration
        }
        ArtifactOwnerCommandError::NotReady => ArtifactOwnerFailureClassV1::Draining,
        ArtifactOwnerCommandError::RecoveryNotRequired => {
            ArtifactOwnerFailureClassV1::RecoveryRequired
        }
        ArtifactOwnerCommandError::Poisoned | ArtifactOwnerCommandError::InvalidState => {
            ArtifactOwnerFailureClassV1::CorruptState
        }
    }
}

const fn action_stage(action: ArtifactOwnerActionV1) -> ArtifactOwnerStageV1 {
    match action {
        ArtifactOwnerActionV1::Publish => ArtifactOwnerStageV1::PublicationTotal,
        ArtifactOwnerActionV1::RecoverPublish => ArtifactOwnerStageV1::RecoveryTotal,
        ArtifactOwnerActionV1::InstallWithdrawalFrontier => {
            ArtifactOwnerStageV1::WithdrawalInstallTotal
        }
        ArtifactOwnerActionV1::Backup => ArtifactOwnerStageV1::BackupTotal,
        ArtifactOwnerActionV1::Shutdown => ArtifactOwnerStageV1::ShutdownTotal,
        ArtifactOwnerActionV1::Health
        | ArtifactOwnerActionV1::Ready
        | ArtifactOwnerActionV1::Status
        | ArtifactOwnerActionV1::Metrics
        | ArtifactOwnerActionV1::ReloadAuthz => ArtifactOwnerStageV1::RequestTotal,
    }
}

fn response_is_publication_success(response: &[u8]) -> bool {
    contains(response, b"hepta.learning-artifactd.publication.v1")
}

fn response_is_error(response: &[u8]) -> bool {
    contains(response, b"hepta.learning-artifactd.error.v1")
}

fn contains(haystack: &[u8], needle: &[u8]) -> bool {
    haystack.windows(needle.len()).any(|window| window == needle)
}

fn elapsed_micros(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX)
}

fn optional_u64(value: Option<u64>) -> String {
    value.map_or_else(|| "null".to_owned(), |value| value.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn service_errors_have_actionable_retry_contracts() {
        let error = LearningArtifactOwnerServiceError::WithdrawalFrontierConflict;
        assert_eq!(
            error.failure_class(),
            ArtifactOwnerFailureClassV1::WithdrawalFrontierInsufficient
        );
        assert_eq!(
            error.retry_disposition(),
            ArtifactOwnerRetryDispositionV1::RefreshWithdrawalFrontier
        );
    }

    #[test]
    fn retention_metrics_never_invent_an_observation() {
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
            retention: None,
            stage_summaries: BTreeMap::new(),
        };
        assert!(metrics.response_json().contains("\"retention\":null"));
    }
}
