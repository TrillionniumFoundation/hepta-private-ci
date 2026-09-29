use super::*;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduFbsdeFoldV1 {
    Train,
    Holdout,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduFbsdeStepV1 {
    pub sequence: u32,
    pub start_unix_ms: u64,
    pub end_unix_ms: u64,
    pub feature_observed_unix_ms: u64,
    pub increment_observed_unix_ms: u64,
    pub running_utility_observed_unix_ms: u64,
    pub conditioning_digest: Digest32,
    pub feature_provenance_digest: Digest32,
    pub increment_provenance_digest: Digest32,
    pub running_utility_provenance_digest: Digest32,
    pub features_q24: Vec<i64>,
    pub increment_q24: Vec<i64>,
    pub running_utility_q24: Vec<i64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduFbsdeTrajectoryV1 {
    pub trajectory_digest: Digest32,
    pub episode_digest: Digest32,
    pub principal_scope_digest: Digest32,
    pub fold: NduFbsdeFoldV1,
    pub steps: Vec<NduFbsdeStepV1>,
    pub terminal_utility_q24: Vec<i64>,
    pub terminal_outcome_digest: Digest32,
    pub terminal_provenance_digest: Digest32,
    pub terminal_observed_unix_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduFbsdeDatasetSnapshotV1 {
    pub dataset_digest: Digest32,
    pub immutable_locator_digest: Digest32,
    pub provenance_digest: Digest32,
    pub objective_class_digest: Digest32,
    pub feature_schema_digest: Digest32,
    pub increment_schema_digest: Digest32,
    pub outcome_schema_digest: Digest32,
    pub filtration_digest: Digest32,
    pub normalization_digest: Digest32,
    pub fold_assignment_digest: Digest32,
    pub trusted_time_digest: Digest32,
    pub snapshot_unix_ms: u64,
    pub feature_dimension: usize,
    pub driver_dimension: usize,
    pub utility_dimension: usize,
    pub horizon: usize,
    pub trajectories: Vec<NduFbsdeTrajectoryV1>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct NduFbsdeTrainingPolicyV1 {
    pub dataset_digest: Digest32,
    pub objective_class_digest: Digest32,
    pub feature_schema_digest: Digest32,
    pub increment_schema_digest: Digest32,
    pub outcome_schema_digest: Digest32,
    pub filtration_digest: Digest32,
    pub normalization_digest: Digest32,
    pub runtime_tuple_digest: Digest32,
    pub units_digest: Digest32,
    pub feature_dimension: usize,
    pub driver_dimension: usize,
    pub utility_dimension: usize,
    pub horizon: usize,
    pub maximum_epochs: usize,
    pub ridge_penalty: f64,
    pub convergence_tolerance: f64,
    pub maximum_absolute_input: f64,
    pub maximum_absolute_value: f64,
    pub maximum_step_seconds: f64,
    pub maximum_holdout_rmse: f64,
    pub maximum_calibration_error: f64,
    pub minimum_holdout_improvement: f64,
    pub generator_y: Vec<f64>,
    pub generator_z: Vec<Vec<f64>>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct AdmittedNduFbsdeTrainingPolicyV1 {
    pub(super) specification: NduFbsdeTrainingPolicyV1,
    pub(super) digest: Digest32,
}

impl AdmittedNduFbsdeTrainingPolicyV1 {
    #[must_use]
    pub const fn digest(&self) -> Digest32 {
        self.digest
    }

    #[must_use]
    pub const fn dataset_digest(&self) -> Digest32 {
        self.specification.dataset_digest
    }

    #[must_use]
    pub const fn normalization_digest(&self) -> Digest32 {
        self.specification.normalization_digest
    }

    #[must_use]
    pub const fn runtime_tuple_digest(&self) -> Digest32 {
        self.specification.runtime_tuple_digest
    }

    #[must_use]
    pub const fn units_digest(&self) -> Digest32 {
        self.specification.units_digest
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduFbsdeTrainingError {
    MissingDigest(&'static str),
    AlreadySealed,
    DatasetDigestMismatch,
    PolicyMismatch(&'static str),
    InvalidDimension,
    InvalidHorizon,
    InvalidFold,
    DuplicateTrajectory,
    Sequence,
    Time,
    FutureFeature,
    ObservationAfterSnapshot,
    ConditioningMismatch,
    DurationMismatch,
    NonFinite,
    InputBound,
    InvalidPolicy,
    Covariance,
    SingularRegression,
    Arithmetic,
    DidNotConverge,
    HoldoutRmse,
    Calibration,
    UtilityImprovement,
    CandidateMismatch,
    ArtifactMismatch,
    ProfileMismatch,
    Expired,
    Authority,
    ShadowEvidence,
}

impl fmt::Display for NduFbsdeTrainingError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduFbsdeTrainingError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduFbsdeMetricsV1 {
    pub(super) train_rmse_q24: i64,
    pub(super) holdout_rmse_q24: i64,
    pub(super) holdout_calibration_q24: i64,
    pub(super) holdout_improvement_q24: i64,
    pub(super) maximum_residual_q24: i64,
    pub(super) maximum_update_q24: i64,
    pub(super) train_observation_count: u64,
    pub(super) holdout_observation_count: u64,
    pub(super) epochs: u32,
}

impl NduFbsdeMetricsV1 {
    #[must_use]
    pub const fn train_rmse_q24(&self) -> i64 {
        self.train_rmse_q24
    }

    #[must_use]
    pub const fn holdout_rmse_q24(&self) -> i64 {
        self.holdout_rmse_q24
    }

    #[must_use]
    pub const fn holdout_calibration_q24(&self) -> i64 {
        self.holdout_calibration_q24
    }

    #[must_use]
    pub const fn holdout_improvement_q24(&self) -> i64 {
        self.holdout_improvement_q24
    }

    #[must_use]
    pub const fn maximum_residual_q24(&self) -> i64 {
        self.maximum_residual_q24
    }

    #[must_use]
    pub const fn maximum_update_q24(&self) -> i64 {
        self.maximum_update_q24
    }

    #[must_use]
    pub const fn train_observation_count(&self) -> u64 {
        self.train_observation_count
    }

    #[must_use]
    pub const fn holdout_observation_count(&self) -> u64 {
        self.holdout_observation_count
    }

    #[must_use]
    pub const fn epochs(&self) -> u32 {
        self.epochs
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct NduFbsdeTimeSliceV1 {
    pub(super) conditioning_digest: Digest32,
    pub(super) duration_micros: u64,
    pub(super) value_intercepts_q24: Vec<i64>,
    pub(super) value_weights_q24: Vec<Vec<i64>>,
    pub(super) baseline_intercepts_q24: Vec<i64>,
    pub(super) z_q24: Vec<Vec<i64>>,
    pub(super) condition_estimate: f64,
    pub(super) increment_eigenvalue_lower_estimate: f64,
    pub(super) maximum_relative_residual: f64,
    pub(super) source_evidence_digest: Digest32,
}

impl NduFbsdeTimeSliceV1 {
    #[must_use]
    pub const fn conditioning_digest(&self) -> Digest32 {
        self.conditioning_digest
    }

    #[must_use]
    pub const fn duration_micros(&self) -> u64 {
        self.duration_micros
    }

    #[must_use]
    pub fn value_intercepts_q24(&self) -> &[i64] {
        &self.value_intercepts_q24
    }

    #[must_use]
    pub fn value_weights_q24(&self) -> &[Vec<i64>] {
        &self.value_weights_q24
    }

    #[must_use]
    pub fn z_q24(&self) -> &[Vec<i64>] {
        &self.z_q24
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct NduFbsdeTrainingCandidateV1 {
    pub(super) policy_digest: Digest32,
    pub(super) dataset_digest: Digest32,
    pub(super) objective_class_digest: Digest32,
    pub(super) feature_schema_digest: Digest32,
    pub(super) filtration_digest: Digest32,
    pub(super) normalization_digest: Digest32,
    pub(super) runtime_tuple_digest: Digest32,
    pub(super) units_digest: Digest32,
    pub(super) covariance_profile_digest: Digest32,
    pub(super) feature_dimension: usize,
    pub(super) driver_dimension: usize,
    pub(super) utility_dimension: usize,
    pub(super) time_slices: Vec<NduFbsdeTimeSliceV1>,
    pub(super) metrics: NduFbsdeMetricsV1,
    pub(super) artifact_bytes_digest: Digest32,
    pub(super) candidate_digest: Digest32,
    pub(super) authority: AuthorityPosture,
}

impl NduFbsdeTrainingCandidateV1 {
    #[must_use]
    pub const fn policy_digest(&self) -> Digest32 {
        self.policy_digest
    }

    #[must_use]
    pub const fn dataset_digest(&self) -> Digest32 {
        self.dataset_digest
    }

    #[must_use]
    pub const fn artifact_bytes_digest(&self) -> Digest32 {
        self.artifact_bytes_digest
    }

    #[must_use]
    pub const fn candidate_digest(&self) -> Digest32 {
        self.candidate_digest
    }

    #[must_use]
    pub const fn covariance_profile_digest(&self) -> Digest32 {
        self.covariance_profile_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    #[must_use]
    pub const fn metrics(&self) -> &NduFbsdeMetricsV1 {
        &self.metrics
    }

    #[must_use]
    pub fn time_slices(&self) -> &[NduFbsdeTimeSliceV1] {
        &self.time_slices
    }

    #[must_use]
    pub fn artifact_bytes(&self) -> Vec<u8> {
        encode_candidate_artifact(self)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduFbsdeReferenceReceiptV1 {
    pub(super) candidate_digest: Digest32,
    pub(super) dataset_digest: Digest32,
    pub(super) artifact_bytes_digest: Digest32,
    pub(super) metrics: NduFbsdeMetricsV1,
    pub(super) receipt_digest: Digest32,
    pub(super) authority: AuthorityPosture,
}

impl NduFbsdeReferenceReceiptV1 {
    #[must_use]
    pub const fn candidate_digest(&self) -> Digest32 {
        self.candidate_digest
    }

    #[must_use]
    pub const fn artifact_bytes_digest(&self) -> Digest32 {
        self.artifact_bytes_digest
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn metrics(&self) -> &NduFbsdeMetricsV1 {
        &self.metrics
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduFbsdePublicationBindingV1 {
    pub(super) artifact_manifest_digest: Digest32,
    pub(super) artifact_bytes_digest: Digest32,
    pub(super) coefficient_profile_digest: Digest32,
    pub(super) primary_projection_digest: Digest32,
    pub(super) candidate_digest: Digest32,
    pub(super) publication_digest: Digest32,
    pub(super) authority: AuthorityPosture,
}

impl NduFbsdePublicationBindingV1 {
    #[must_use]
    pub const fn artifact_manifest_digest(&self) -> Digest32 {
        self.artifact_manifest_digest
    }

    #[must_use]
    pub const fn artifact_bytes_digest(&self) -> Digest32 {
        self.artifact_bytes_digest
    }

    #[must_use]
    pub const fn publication_digest(&self) -> Digest32 {
        self.publication_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduFbsdeShadowStageV1 {
    ShadowOnly,
    AdvisoryEligible,
    RestrictedWriteEligible,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduFbsdeShadowPolicyV1 {
    pub policy_digest: Digest32,
    pub minimum_advisory_episodes: u64,
    pub minimum_advisory_decisions: u64,
    pub minimum_restricted_episodes: u64,
    pub minimum_restricted_decisions: u64,
    pub maximum_failures: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduFbsdeShadowEvidenceV1 {
    pub candidate_digest: Digest32,
    pub reference_receipt_digest: Digest32,
    pub convergence_acceptance_digest: Digest32,
    pub calibration_acceptance_digest: Digest32,
    pub utility_improvement_acceptance_digest: Digest32,
    pub regression_acceptance_digest: Digest32,
    pub target_host_receipt_digest: Digest32,
    pub observed_episode_count: u64,
    pub observed_decision_count: u64,
    pub observed_failure_count: u64,
    pub window_start_unix_ms: u64,
    pub window_end_unix_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduFbsdeShadowGateReceiptV1 {
    pub(super) stage: NduFbsdeShadowStageV1,
    pub(super) candidate_digest: Digest32,
    pub(super) evidence_digest: Digest32,
    pub(super) receipt_digest: Digest32,
    pub(super) authority: AuthorityPosture,
    pub(super) production_activation: bool,
}

impl NduFbsdeShadowGateReceiptV1 {
    #[must_use]
    pub const fn stage(&self) -> NduFbsdeShadowStageV1 {
        self.stage
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    #[must_use]
    pub const fn production_activation(&self) -> bool {
        self.production_activation
    }
}

#[derive(Clone, Debug)]
pub(super) struct FittedSlice {
    pub(super) conditioning_digest: Digest32,
    pub(super) duration_micros: u64,
    pub(super) value_intercepts: Vec<f64>,
    pub(super) value_weights: Vec<Vec<f64>>,
    pub(super) baseline_intercepts: Vec<f64>,
    pub(super) z: Vec<Vec<f64>>,
    pub(super) condition_estimate: f64,
    pub(super) increment_eigenvalue_lower_estimate: f64,
    pub(super) maximum_relative_residual: f64,
    pub(super) source_evidence_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Default)]
pub(super) struct MetricAccumulator {
    pub(super) squared_residual: f64,
    pub(super) squared_baseline_residual: f64,
    pub(super) residual_sum: f64,
    pub(super) maximum_absolute_residual: f64,
    pub(super) count: u64,
}

impl MetricAccumulator {
    pub(super) fn observe(&mut self, residual: f64, baseline_residual: f64) {
        self.squared_residual += residual * residual;
        self.squared_baseline_residual += baseline_residual * baseline_residual;
        self.residual_sum += residual;
        self.maximum_absolute_residual =
            self.maximum_absolute_residual.max(residual.abs());
        self.count += 1;
    }

    pub(super) fn rmse(self) -> Result<f64, NduFbsdeTrainingError> {
        if self.count == 0 {
            return Err(NduFbsdeTrainingError::InvalidFold);
        }
        let value = (self.squared_residual / self.count as f64).sqrt();
        finite(value)
    }

    pub(super) fn baseline_rmse(self) -> Result<f64, NduFbsdeTrainingError> {
        if self.count == 0 {
            return Err(NduFbsdeTrainingError::InvalidFold);
        }
        let value = (self.squared_baseline_residual / self.count as f64).sqrt();
        finite(value)
    }

    pub(super) fn calibration(self) -> Result<f64, NduFbsdeTrainingError> {
        if self.count == 0 {
            return Err(NduFbsdeTrainingError::InvalidFold);
        }
        finite((self.residual_sum / self.count as f64).abs())
    }
}
