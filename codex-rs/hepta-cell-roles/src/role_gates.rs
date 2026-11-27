//! Role-specific transition and acceptance contracts.
//!
//! The older [`CellSplitV1`](codex_hepta_types::CellSplitV1) contract is a
//! topology/state split contract.  This module is deliberately a separate
//! layer: changing a cell's semantic role, or accepting a role-specific split,
//! requires explicit compatibility, state-transform, and evaluation evidence.
//! These values are authority-free descriptions.  They do not install an
//! artifact, change a route, or promote a candidate.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

pub const ROLE_GATES_SCHEMA_V1: &str = "hepta.cell-role.gates.v1";
const PPM_MAX_V1: u64 = 1_000_000;

/// State migration semantics must be named at the transition boundary.  A
/// role split cannot silently copy or reset state just because two schemas
/// happen to have the same shape.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellRoleStateTransformKindV1 {
    Copy,
    Partition,
    Revalidate,
    Reset,
    Custom,
}

impl CellRoleStateTransformKindV1 {
    pub const fn tag(self) -> u8 {
        match self {
            Self::Copy => 0,
            Self::Partition => 1,
            Self::Revalidate => 2,
            Self::Reset => 3,
            Self::Custom => 4,
        }
    }
}

/// Versioned, witnessed state migration plan for one role transition.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellRoleStateTransformV1 {
    pub kind: CellRoleStateTransformKindV1,
    pub source_state_schema_digest: Digest32,
    pub destination_state_schema_digest: Digest32,
    /// Digest of the executable/pure transform specification.  The transform
    /// itself is owned by the state owner; this record only binds it.
    pub transform_digest: Digest32,
    pub precondition_digest: Digest32,
    /// Maximum explicitly accepted information loss, expressed in ppm.
    pub loss_budget_ppm: u32,
}

impl CellRoleStateTransformV1 {
    pub fn validate(&self) -> Result<(), CellRoleGateErrorV1> {
        require_digest(self.source_state_schema_digest, "source state schema")?;
        require_digest(
            self.destination_state_schema_digest,
            "destination state schema",
        )?;
        require_digest(self.transform_digest, "state transform")?;
        require_digest(self.precondition_digest, "state precondition")?;
        if u64::from(self.loss_budget_ppm) > PPM_MAX_V1 {
            return Err(CellRoleGateErrorV1::InvalidPpm("state loss budget"));
        }
        if self.kind == CellRoleStateTransformKindV1::Copy
            && self.source_state_schema_digest != self.destination_state_schema_digest
        {
            return Err(CellRoleGateErrorV1::CopySchemaMismatch);
        }
        Ok(())
    }

    pub fn content_digest(&self) -> Result<Digest32, CellRoleGateErrorV1> {
        self.validate()?;
        Ok(digest_parts(
            b"hepta.cell-role.state-transform.v1",
            &[
                &[self.kind.tag()],
                self.source_state_schema_digest.as_array(),
                self.destination_state_schema_digest.as_array(),
                self.transform_digest.as_array(),
                self.precondition_digest.as_array(),
                &self.loss_budget_ppm.to_be_bytes(),
            ],
        ))
    }
}

/// Whether the parent and child roles are intentionally the same or an
/// explicitly governed cross-role transition.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellRoleTransitionModeV1 {
    SameRole,
    CrossRoleExplicit,
}

impl CellRoleTransitionModeV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::SameRole => 0,
            Self::CrossRoleExplicit => 1,
        }
    }
}

/// Explicit semantic-role transition used by role-specific split governance.
///
/// `CellSplitV1` remains unchanged.  A caller must present this record in
/// addition to a topology split when a child has a different semantic role.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellRoleTransitionV1 {
    pub transition_id: StableId,
    pub parent_role: CellRoleV1,
    pub child_role: CellRoleV1,
    pub mode: CellRoleTransitionModeV1,
    pub parent_definition_digest: Digest32,
    pub child_definition_digest: Digest32,
    /// Compatibility of typed input/output/termination ports and owner ABI.
    pub compatibility_digest: Digest32,
    pub state_transform: CellRoleStateTransformV1,
    pub port_abi_digest: Digest32,
    pub evaluation_profile_digest: Digest32,
    pub lineage_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl CellRoleTransitionV1 {
    pub fn validate(&self) -> Result<(), CellRoleGateErrorV1> {
        require_id(&self.transition_id, "transition")?;
        for (label, digest) in [
            ("parent definition", self.parent_definition_digest),
            ("child definition", self.child_definition_digest),
            ("compatibility", self.compatibility_digest),
            ("port ABI", self.port_abi_digest),
            ("evaluation profile", self.evaluation_profile_digest),
            ("lineage", self.lineage_digest),
        ] {
            require_digest(digest, label)?;
        }
        if self.authority.grants_any() {
            return Err(CellRoleGateErrorV1::AuthorityGrant);
        }
        self.state_transform.validate()?;
        let roles_match = self.parent_role == self.child_role;
        match (roles_match, self.mode) {
            (true, CellRoleTransitionModeV1::SameRole)
            | (false, CellRoleTransitionModeV1::CrossRoleExplicit) => Ok(()),
            (true, CellRoleTransitionModeV1::CrossRoleExplicit) => {
                Err(CellRoleGateErrorV1::RedundantCrossRoleTransition)
            }
            (false, CellRoleTransitionModeV1::SameRole) => {
                Err(CellRoleGateErrorV1::ImplicitRoleTransition)
            }
        }
    }

    pub fn content_digest(&self) -> Result<Digest32, CellRoleGateErrorV1> {
        self.validate()?;
        let state_digest = self.state_transform.content_digest()?;
        Ok(digest_parts(
            b"hepta.cell-role.transition.v1",
            &[
                self.transition_id.as_str().as_bytes(),
                &[self.parent_role.tag()],
                &[self.child_role.tag()],
                &[self.mode.tag()],
                self.parent_definition_digest.as_array(),
                self.child_definition_digest.as_array(),
                self.compatibility_digest.as_array(),
                state_digest.as_array(),
                self.port_abi_digest.as_array(),
                self.evaluation_profile_digest.as_array(),
                self.lineage_digest.as_array(),
            ],
        ))
    }
}

/// Canonical role-specific acceptance metrics.  Values are intentionally
/// typed by unit in [`CellRoleMetricV1`], so latency and memory are not
/// confused with bounded quality percentages.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[allow(clippy::enum_variant_names)]
pub enum CellRoleMetricKindV1 {
    RepresentationOod,
    RepresentationCalibration,
    RepresentationMissingness,
    RepresentationDrift,
    RepresentationLatency,
    RepresentationMemory,
    MemoryReadRecallCoverage,
    MemoryReadContradictionDetection,
    MemoryReadFreshness,
    MemoryReadAbstention,
    MemoryReadSourceProvenance,
    PredictorNll,
    PredictorBrier,
    PredictorMultiStepError,
    PredictorCalibration,
    PredictorOod,
    PredictorWorldRevisionCompatibility,
    ValueBellmanResidual,
    ValueBias,
    ValueRiskCalibration,
    ValueCostPrediction,
    ValueNegativeTransfer,
    DecisionRegret,
    DecisionPropensity,
    DecisionCoverage,
    DecisionAbstention,
    DecisionTaskSuccess,
    EvaluatorFalseAccept,
    EvaluatorFalseReject,
    EvaluatorOodDetection,
    EvaluatorRetentionPrecision,
    EvaluatorRollbackPrecision,
    PlannerPlanValidity,
    PlannerConstraintViolation,
    PlannerCost,
    PlannerHorizon,
    PlannerRecovery,
    RouterRouteCoverage,
    RouterLoadBalance,
    RouterLatency,
    RouterResourceCost,
    RouterFallback,
    ActionProposalSchemaValidity,
    ActionProposalPreconditionValidity,
    ActionProposalEffectClassification,
    ActionProposalExpiryHandling,
    PlasticityUpdateUsefulness,
    PlasticityRetention,
    PlasticityForgetting,
    PlasticityRollback,
    PlasticityResourceCost,
    CommunicationDelivery,
    CommunicationOrdering,
    CommunicationDuplicateSuppression,
    CommunicationExpiry,
    CommunicationBackpressure,
}

impl CellRoleMetricKindV1 {
    pub const fn role(self) -> CellRoleV1 {
        match self {
            Self::RepresentationOod
            | Self::RepresentationCalibration
            | Self::RepresentationMissingness
            | Self::RepresentationDrift
            | Self::RepresentationLatency
            | Self::RepresentationMemory => CellRoleV1::Representation,
            Self::MemoryReadRecallCoverage
            | Self::MemoryReadContradictionDetection
            | Self::MemoryReadFreshness
            | Self::MemoryReadAbstention
            | Self::MemoryReadSourceProvenance => CellRoleV1::MemoryRead,
            Self::PredictorNll
            | Self::PredictorBrier
            | Self::PredictorMultiStepError
            | Self::PredictorCalibration
            | Self::PredictorOod
            | Self::PredictorWorldRevisionCompatibility => CellRoleV1::Predictor,
            Self::ValueBellmanResidual
            | Self::ValueBias
            | Self::ValueRiskCalibration
            | Self::ValueCostPrediction
            | Self::ValueNegativeTransfer => CellRoleV1::Value,
            Self::DecisionRegret
            | Self::DecisionPropensity
            | Self::DecisionCoverage
            | Self::DecisionAbstention
            | Self::DecisionTaskSuccess => CellRoleV1::Decision,
            Self::EvaluatorFalseAccept
            | Self::EvaluatorFalseReject
            | Self::EvaluatorOodDetection
            | Self::EvaluatorRetentionPrecision
            | Self::EvaluatorRollbackPrecision => CellRoleV1::Evaluator,
            Self::PlannerPlanValidity
            | Self::PlannerConstraintViolation
            | Self::PlannerCost
            | Self::PlannerHorizon
            | Self::PlannerRecovery => CellRoleV1::Planner,
            Self::RouterRouteCoverage
            | Self::RouterLoadBalance
            | Self::RouterLatency
            | Self::RouterResourceCost
            | Self::RouterFallback => CellRoleV1::Router,
            Self::ActionProposalSchemaValidity
            | Self::ActionProposalPreconditionValidity
            | Self::ActionProposalEffectClassification
            | Self::ActionProposalExpiryHandling => CellRoleV1::ActionProposal,
            Self::PlasticityUpdateUsefulness
            | Self::PlasticityRetention
            | Self::PlasticityForgetting
            | Self::PlasticityRollback
            | Self::PlasticityResourceCost => CellRoleV1::Plasticity,
            Self::CommunicationDelivery
            | Self::CommunicationOrdering
            | Self::CommunicationDuplicateSuppression
            | Self::CommunicationExpiry
            | Self::CommunicationBackpressure => CellRoleV1::Communication,
        }
    }

    pub const fn tag(self) -> u8 {
        match self {
            Self::RepresentationOod => 0,
            Self::RepresentationCalibration => 1,
            Self::RepresentationMissingness => 2,
            Self::RepresentationDrift => 3,
            Self::RepresentationLatency => 4,
            Self::RepresentationMemory => 5,
            Self::MemoryReadRecallCoverage => 10,
            Self::MemoryReadContradictionDetection => 11,
            Self::MemoryReadFreshness => 12,
            Self::MemoryReadAbstention => 13,
            Self::MemoryReadSourceProvenance => 14,
            Self::PredictorNll => 20,
            Self::PredictorBrier => 21,
            Self::PredictorMultiStepError => 22,
            Self::PredictorCalibration => 23,
            Self::PredictorOod => 24,
            Self::PredictorWorldRevisionCompatibility => 25,
            Self::ValueBellmanResidual => 30,
            Self::ValueBias => 31,
            Self::ValueRiskCalibration => 32,
            Self::ValueCostPrediction => 33,
            Self::ValueNegativeTransfer => 34,
            Self::DecisionRegret => 40,
            Self::DecisionPropensity => 41,
            Self::DecisionCoverage => 42,
            Self::DecisionAbstention => 43,
            Self::DecisionTaskSuccess => 44,
            Self::EvaluatorFalseAccept => 50,
            Self::EvaluatorFalseReject => 51,
            Self::EvaluatorOodDetection => 52,
            Self::EvaluatorRetentionPrecision => 53,
            Self::EvaluatorRollbackPrecision => 54,
            Self::PlannerPlanValidity => 60,
            Self::PlannerConstraintViolation => 61,
            Self::PlannerCost => 62,
            Self::PlannerHorizon => 63,
            Self::PlannerRecovery => 64,
            Self::RouterRouteCoverage => 70,
            Self::RouterLoadBalance => 71,
            Self::RouterLatency => 72,
            Self::RouterResourceCost => 73,
            Self::RouterFallback => 74,
            Self::ActionProposalSchemaValidity => 80,
            Self::ActionProposalPreconditionValidity => 81,
            Self::ActionProposalEffectClassification => 82,
            Self::ActionProposalExpiryHandling => 83,
            Self::PlasticityUpdateUsefulness => 90,
            Self::PlasticityRetention => 91,
            Self::PlasticityForgetting => 92,
            Self::PlasticityRollback => 93,
            Self::PlasticityResourceCost => 94,
            Self::CommunicationDelivery => 100,
            Self::CommunicationOrdering => 101,
            Self::CommunicationDuplicateSuppression => 102,
            Self::CommunicationExpiry => 103,
            Self::CommunicationBackpressure => 104,
        }
    }

    pub const fn is_bounded_ppm(self) -> bool {
        matches!(self.unit(), CellRoleMetricUnitV1::Ppm)
    }

    /// Exact wire unit for this metric.  Numerical metric definitions (for
    /// example, binary versus multiclass Brier score, or the utility units
    /// used by a cost function) remain bound by the acceptance policy.
    pub const fn unit(self) -> CellRoleMetricUnitV1 {
        match self {
            Self::RepresentationLatency | Self::RouterLatency => CellRoleMetricUnitV1::Microseconds,
            Self::RepresentationMemory => CellRoleMetricUnitV1::Bytes,
            Self::PlannerHorizon => CellRoleMetricUnitV1::Count,
            Self::RepresentationDrift
            | Self::PredictorNll
            | Self::PredictorBrier
            | Self::PredictorMultiStepError
            | Self::ValueBellmanResidual
            | Self::ValueBias
            | Self::ValueCostPrediction
            | Self::DecisionRegret
            | Self::PlannerCost
            | Self::RouterResourceCost
            | Self::PlasticityResourceCost => CellRoleMetricUnitV1::Q32,
            _ => CellRoleMetricUnitV1::Ppm,
        }
    }

    /// Value bias is signed.  NLL is Q32 and unbounded above, but remains a
    /// nonnegative loss; error magnitudes, costs, counts, time and bounded
    /// rates are also nonnegative.
    pub const fn permits_negative(self) -> bool {
        matches!(self, Self::ValueBias)
    }

    /// Full acceptance set for the role.  A profile can add metrics, but it
    /// cannot omit one of these under profile validation.
    pub const fn standard_for_role(role: CellRoleV1) -> &'static [Self] {
        match role {
            CellRoleV1::Representation => &[
                Self::RepresentationOod,
                Self::RepresentationCalibration,
                Self::RepresentationMissingness,
                Self::RepresentationDrift,
                Self::RepresentationLatency,
                Self::RepresentationMemory,
            ],
            CellRoleV1::MemoryRead => &[
                Self::MemoryReadRecallCoverage,
                Self::MemoryReadContradictionDetection,
                Self::MemoryReadFreshness,
                Self::MemoryReadAbstention,
                Self::MemoryReadSourceProvenance,
            ],
            CellRoleV1::Predictor => &[
                Self::PredictorNll,
                Self::PredictorBrier,
                Self::PredictorMultiStepError,
                Self::PredictorCalibration,
                Self::PredictorOod,
                Self::PredictorWorldRevisionCompatibility,
            ],
            CellRoleV1::Value => &[
                Self::ValueBellmanResidual,
                Self::ValueBias,
                Self::ValueRiskCalibration,
                Self::ValueCostPrediction,
                Self::ValueNegativeTransfer,
            ],
            CellRoleV1::Decision => &[
                Self::DecisionRegret,
                Self::DecisionPropensity,
                Self::DecisionCoverage,
                Self::DecisionAbstention,
                Self::DecisionTaskSuccess,
            ],
            CellRoleV1::Evaluator => &[
                Self::EvaluatorFalseAccept,
                Self::EvaluatorFalseReject,
                Self::EvaluatorOodDetection,
                Self::EvaluatorRetentionPrecision,
                Self::EvaluatorRollbackPrecision,
            ],
            CellRoleV1::Planner => &[
                Self::PlannerPlanValidity,
                Self::PlannerConstraintViolation,
                Self::PlannerCost,
                Self::PlannerHorizon,
                Self::PlannerRecovery,
            ],
            CellRoleV1::Router => &[
                Self::RouterRouteCoverage,
                Self::RouterLoadBalance,
                Self::RouterLatency,
                Self::RouterResourceCost,
                Self::RouterFallback,
            ],
            CellRoleV1::ActionProposal => &[
                Self::ActionProposalSchemaValidity,
                Self::ActionProposalPreconditionValidity,
                Self::ActionProposalEffectClassification,
                Self::ActionProposalExpiryHandling,
            ],
            CellRoleV1::Plasticity => &[
                Self::PlasticityUpdateUsefulness,
                Self::PlasticityRetention,
                Self::PlasticityForgetting,
                Self::PlasticityRollback,
                Self::PlasticityResourceCost,
            ],
            CellRoleV1::Communication => &[
                Self::CommunicationDelivery,
                Self::CommunicationOrdering,
                Self::CommunicationDuplicateSuppression,
                Self::CommunicationExpiry,
                Self::CommunicationBackpressure,
            ],
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellRoleMetricUnitV1 {
    Ppm,
    Microseconds,
    Bytes,
    Count,
    /// Signed fixed-point with scale 2^32, matching `FixedQ32::raw()`.
    Q32,
}

impl CellRoleMetricUnitV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Ppm => 0,
            Self::Microseconds => 1,
            Self::Bytes => 2,
            Self::Count => 3,
            Self::Q32 => 4,
        }
    }
}

/// One measured metric with an evidence binding.  `value` is an integer for
/// PPM/count/bytes/microseconds and signed raw fixed-point for Q32.  Validation
/// checks representation and units; it does not evaluate an acceptance policy.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellRoleMetricV1 {
    pub kind: CellRoleMetricKindV1,
    pub unit: CellRoleMetricUnitV1,
    pub value: i64,
    pub sample_count: u64,
    pub observation_digest: Digest32,
}

impl CellRoleMetricV1 {
    pub fn validate(&self) -> Result<(), CellRoleGateErrorV1> {
        if self.sample_count == 0 {
            return Err(CellRoleGateErrorV1::ZeroSampleCount(self.kind));
        }
        require_digest(self.observation_digest, "metric observation")?;
        if self.unit != self.kind.unit() {
            return Err(CellRoleGateErrorV1::MetricUnitMismatch(self.kind));
        }
        if self.value < 0 && !self.kind.permits_negative() {
            return Err(CellRoleGateErrorV1::InvalidMetricValue(self.kind));
        }
        if self.kind.is_bounded_ppm() && self.value > PPM_MAX_V1 as i64 {
            return Err(CellRoleGateErrorV1::InvalidMetricValue(self.kind));
        }
        Ok(())
    }
}

/// Acceptance profile for one role.  `required_metrics` must contain only
/// metrics belonging to `role`; a standard profile is available for each P5
/// role and includes the complete list from the design contract.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellRoleMetricProfileV1 {
    pub role: CellRoleV1,
    pub required_metrics: Vec<CellRoleMetricKindV1>,
    pub objective_digest: Digest32,
    pub no_change_baseline_digest: Digest32,
    pub acceptance_policy_digest: Digest32,
    pub future_window_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl CellRoleMetricProfileV1 {
    pub fn standard_for_role(
        role: CellRoleV1,
        objective_digest: Digest32,
        no_change_baseline_digest: Digest32,
        acceptance_policy_digest: Digest32,
        future_window_digest: Digest32,
    ) -> Self {
        Self {
            role,
            required_metrics: CellRoleMetricKindV1::standard_for_role(role).to_vec(),
            objective_digest,
            no_change_baseline_digest,
            acceptance_policy_digest,
            future_window_digest,
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    pub fn validate(&self) -> Result<(), CellRoleGateErrorV1> {
        if self.required_metrics.is_empty() {
            return Err(CellRoleGateErrorV1::EmptyMetricProfile(self.role));
        }
        for (index, metric) in self.required_metrics.iter().enumerate() {
            if metric.role() != self.role {
                return Err(CellRoleGateErrorV1::MetricRoleMismatch {
                    expected: self.role,
                    actual: metric.role(),
                });
            }
            if self.required_metrics[..index].contains(metric) {
                return Err(CellRoleGateErrorV1::DuplicateMetric(*metric));
            }
        }
        for metric in CellRoleMetricKindV1::standard_for_role(self.role) {
            if !self.required_metrics.contains(metric) {
                return Err(CellRoleGateErrorV1::MissingCanonicalMetric(*metric));
            }
        }
        for (label, digest) in [
            ("objective", self.objective_digest),
            ("no-change baseline", self.no_change_baseline_digest),
            ("acceptance policy", self.acceptance_policy_digest),
            ("future window", self.future_window_digest),
        ] {
            require_digest(digest, label)?;
        }
        if self.authority.grants_any() {
            return Err(CellRoleGateErrorV1::AuthorityGrant);
        }
        Ok(())
    }

    pub fn content_digest(&self) -> Result<Digest32, CellRoleGateErrorV1> {
        self.validate()?;
        let mut bytes = Vec::new();
        bytes.extend_from_slice(ROLE_GATES_SCHEMA_V1.as_bytes());
        bytes.push(self.role.tag());
        for metric in &self.required_metrics {
            bytes.push(metric.tag());
        }
        for digest in [
            self.objective_digest,
            self.no_change_baseline_digest,
            self.acceptance_policy_digest,
            self.future_window_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

/// Replayable role measurement result.  Structural validation checks that
/// every required metric is present exactly once and joins the frozen baseline
/// and future window.  This record deliberately has no `accepted` flag.
/// Independent owner signatures, observations and policy execution must be
/// verified by the existing learning-ledger/evaluator owner before retention
/// or activation can be authorized.  Distinct identifiers are a necessary
/// structural boundary, not proof that two evaluators are independent.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellRoleMetricReceiptV1 {
    pub cell_id: StableId,
    pub generation: Generation,
    pub role: CellRoleV1,
    pub proposer_id: StableId,
    pub evaluator_id: StableId,
    pub profile_digest: Digest32,
    pub baseline_digest: Digest32,
    pub evaluation_window_digest: Digest32,
    pub metrics: Vec<CellRoleMetricV1>,
    pub evidence_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl CellRoleMetricReceiptV1 {
    pub fn validate_structure_against(
        &self,
        profile: &CellRoleMetricProfileV1,
    ) -> Result<(), CellRoleGateErrorV1> {
        require_id(&self.cell_id, "cell")?;
        require_id(&self.proposer_id, "proposer")?;
        require_id(&self.evaluator_id, "evaluator")?;
        if self.proposer_id == self.evaluator_id {
            return Err(CellRoleGateErrorV1::EvaluatorIsProposer);
        }
        for (label, digest) in [
            ("profile", self.profile_digest),
            ("baseline", self.baseline_digest),
            ("evaluation window", self.evaluation_window_digest),
            ("evidence", self.evidence_digest),
        ] {
            require_digest(digest, label)?;
        }
        if self.authority.grants_any() {
            return Err(CellRoleGateErrorV1::AuthorityGrant);
        }
        profile.validate()?;
        if self.role != profile.role {
            return Err(CellRoleGateErrorV1::MetricRoleMismatch {
                expected: profile.role,
                actual: self.role,
            });
        }
        if self.profile_digest != profile.content_digest()? {
            return Err(CellRoleGateErrorV1::ProfileDigestMismatch);
        }
        if self.baseline_digest != profile.no_change_baseline_digest {
            return Err(CellRoleGateErrorV1::BaselineDigestMismatch);
        }
        if self.evaluation_window_digest != profile.future_window_digest {
            return Err(CellRoleGateErrorV1::FutureWindowDigestMismatch);
        }
        if self.metrics.is_empty() {
            return Err(CellRoleGateErrorV1::EmptyMetricReceipt(self.role));
        }
        for (index, metric) in self.metrics.iter().enumerate() {
            metric.validate()?;
            if metric.kind.role() != self.role {
                return Err(CellRoleGateErrorV1::MetricRoleMismatch {
                    expected: self.role,
                    actual: metric.kind.role(),
                });
            }
            if self.metrics[..index]
                .iter()
                .any(|previous| previous.kind == metric.kind)
            {
                return Err(CellRoleGateErrorV1::DuplicateMetric(metric.kind));
            }
        }
        for required in &profile.required_metrics {
            if !self.metrics.iter().any(|metric| metric.kind == *required) {
                return Err(CellRoleGateErrorV1::MissingMetric(*required));
            }
        }
        Ok(())
    }

    pub fn content_digest(
        &self,
        profile: &CellRoleMetricProfileV1,
    ) -> Result<Digest32, CellRoleGateErrorV1> {
        self.validate_structure_against(profile)?;
        let mut bytes = Vec::new();
        bytes.extend_from_slice(b"hepta.cell-role.metric-receipt.v1");
        bytes.extend_from_slice(&(self.cell_id.as_str().len() as u64).to_be_bytes());
        bytes.extend_from_slice(self.cell_id.as_str().as_bytes());
        bytes.extend_from_slice(&(self.proposer_id.as_str().len() as u64).to_be_bytes());
        bytes.extend_from_slice(self.proposer_id.as_str().as_bytes());
        bytes.extend_from_slice(&(self.evaluator_id.as_str().len() as u64).to_be_bytes());
        bytes.extend_from_slice(self.evaluator_id.as_str().as_bytes());
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        bytes.push(self.role.tag());
        for digest in [
            self.profile_digest,
            self.baseline_digest,
            self.evaluation_window_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        for metric in &self.metrics {
            bytes.push(metric.kind.tag());
            bytes.push(metric.unit.tag());
            bytes.extend_from_slice(&metric.value.to_be_bytes());
            bytes.extend_from_slice(&metric.sample_count.to_be_bytes());
            bytes.extend_from_slice(metric.observation_digest.as_array());
        }
        bytes.extend_from_slice(self.evidence_digest.as_array());
        Ok(Digest32::of_bytes(&bytes))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellRoleGateErrorV1 {
    EmptyId(&'static str),
    EmptyDigest(&'static str),
    AuthorityGrant,
    InvalidPpm(&'static str),
    CopySchemaMismatch,
    ImplicitRoleTransition,
    RedundantCrossRoleTransition,
    EmptyMetricProfile(CellRoleV1),
    EmptyMetricReceipt(CellRoleV1),
    MetricRoleMismatch {
        expected: CellRoleV1,
        actual: CellRoleV1,
    },
    DuplicateMetric(CellRoleMetricKindV1),
    MissingCanonicalMetric(CellRoleMetricKindV1),
    MissingMetric(CellRoleMetricKindV1),
    ZeroSampleCount(CellRoleMetricKindV1),
    MetricUnitMismatch(CellRoleMetricKindV1),
    InvalidMetricValue(CellRoleMetricKindV1),
    ProfileDigestMismatch,
    BaselineDigestMismatch,
    FutureWindowDigestMismatch,
    EvaluatorIsProposer,
}

impl fmt::Display for CellRoleGateErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CellRoleGateErrorV1 {}

fn require_id(id: &StableId, label: &'static str) -> Result<(), CellRoleGateErrorV1> {
    if id.as_str().is_empty() {
        Err(CellRoleGateErrorV1::EmptyId(label))
    } else {
        Ok(())
    }
}

fn require_digest(digest: Digest32, label: &'static str) -> Result<(), CellRoleGateErrorV1> {
    if digest.is_zero() {
        Err(CellRoleGateErrorV1::EmptyDigest(label))
    } else {
        Ok(())
    }
}

fn digest_parts(domain: &[u8], parts: &[&[u8]]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(domain);
    for part in parts {
        bytes.extend_from_slice(&(part.len() as u64).to_be_bytes());
        bytes.extend_from_slice(part);
    }
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(seed: u8) -> Digest32 {
        Digest32::of_bytes(&[seed])
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    fn transform() -> CellRoleStateTransformV1 {
        CellRoleStateTransformV1 {
            kind: CellRoleStateTransformKindV1::Revalidate,
            source_state_schema_digest: digest(1),
            destination_state_schema_digest: digest(2),
            transform_digest: digest(3),
            precondition_digest: digest(4),
            loss_budget_ppm: 10,
        }
    }

    fn transition(mode: CellRoleTransitionModeV1) -> CellRoleTransitionV1 {
        CellRoleTransitionV1 {
            transition_id: id("transition.1"),
            parent_role: CellRoleV1::Decision,
            child_role: CellRoleV1::Value,
            mode,
            parent_definition_digest: digest(5),
            child_definition_digest: digest(6),
            compatibility_digest: digest(7),
            state_transform: transform(),
            port_abi_digest: digest(8),
            evaluation_profile_digest: digest(9),
            lineage_digest: digest(10),
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    #[test]
    fn cross_role_transition_requires_explicit_mode() {
        assert_eq!(
            transition(CellRoleTransitionModeV1::SameRole).validate(),
            Err(CellRoleGateErrorV1::ImplicitRoleTransition)
        );
        let explicit = transition(CellRoleTransitionModeV1::CrossRoleExplicit);
        assert!(
            !explicit
                .content_digest()
                .expect("transition digest")
                .is_zero()
        );
    }

    #[test]
    fn same_role_transition_cannot_claim_cross_role() {
        let mut value = transition(CellRoleTransitionModeV1::SameRole);
        value.child_role = value.parent_role;
        value.mode = CellRoleTransitionModeV1::CrossRoleExplicit;
        assert_eq!(
            value.validate(),
            Err(CellRoleGateErrorV1::RedundantCrossRoleTransition)
        );
    }

    #[test]
    fn standard_profile_requires_all_role_metrics() {
        let profile = CellRoleMetricProfileV1::standard_for_role(
            CellRoleV1::Router,
            digest(20),
            digest(21),
            digest(22),
            digest(23),
        );
        assert_eq!(profile.required_metrics.len(), 5);
        assert!(profile.validate().is_ok());
        let profile_digest = profile.content_digest().expect("profile digest");
        let metrics = profile
            .required_metrics
            .iter()
            .map(|kind| CellRoleMetricV1 {
                kind: *kind,
                unit: kind.unit(),
                value: 1,
                sample_count: 1,
                observation_digest: digest(kind.tag()),
            })
            .collect();
        let receipt = CellRoleMetricReceiptV1 {
            cell_id: id("cell.router.1"),
            generation: Generation::new(2).expect("generation"),
            role: CellRoleV1::Router,
            proposer_id: id("planner.router.proposer"),
            evaluator_id: id("learning.eval.router"),
            profile_digest,
            baseline_digest: digest(21),
            evaluation_window_digest: digest(23),
            metrics,
            evidence_digest: digest(25),
            authority: AuthorityPosture::DENY_ALL,
        };
        assert!(receipt.validate_structure_against(&profile).is_ok());
    }

    #[test]
    fn receipt_rejects_missing_metric_and_nonzero_digest_is_required() {
        let profile = CellRoleMetricProfileV1::standard_for_role(
            CellRoleV1::Decision,
            digest(30),
            digest(31),
            digest(32),
            digest(33),
        );
        let receipt = CellRoleMetricReceiptV1 {
            cell_id: id("cell.decision.1"),
            generation: Generation::new(1).expect("generation"),
            role: CellRoleV1::Decision,
            proposer_id: id("decision.proposer"),
            evaluator_id: id("learning.eval.decision"),
            profile_digest: profile.content_digest().expect("profile"),
            baseline_digest: digest(31),
            evaluation_window_digest: digest(33),
            metrics: vec![CellRoleMetricV1 {
                kind: CellRoleMetricKindV1::DecisionRegret,
                unit: CellRoleMetricKindV1::DecisionRegret.unit(),
                value: 2,
                sample_count: 1,
                observation_digest: digest(35),
            }],
            evidence_digest: digest(36),
            authority: AuthorityPosture::DENY_ALL,
        };
        assert!(matches!(
            receipt.validate_structure_against(&profile),
            Err(CellRoleGateErrorV1::MissingMetric(_))
        ));
        let mut bad = receipt;
        bad.evidence_digest = Digest32::ZERO;
        assert_eq!(
            bad.validate_structure_against(&profile),
            Err(CellRoleGateErrorV1::EmptyDigest("evidence"))
        );
    }

    #[test]
    fn metric_units_and_signed_values_are_explicit() {
        let mut metric = CellRoleMetricV1 {
            kind: CellRoleMetricKindV1::ValueBias,
            unit: CellRoleMetricUnitV1::Q32,
            value: -1,
            sample_count: 1,
            observation_digest: digest(40),
        };
        assert!(metric.validate().is_ok());
        metric.unit = CellRoleMetricUnitV1::Ppm;
        assert_eq!(
            metric.validate(),
            Err(CellRoleGateErrorV1::MetricUnitMismatch(
                CellRoleMetricKindV1::ValueBias
            ))
        );
        metric.kind = CellRoleMetricKindV1::DecisionCoverage;
        metric.unit = CellRoleMetricUnitV1::Ppm;
        metric.value = -1;
        assert_eq!(
            metric.validate(),
            Err(CellRoleGateErrorV1::InvalidMetricValue(
                CellRoleMetricKindV1::DecisionCoverage
            ))
        );
        metric.kind = CellRoleMetricKindV1::PredictorNll;
        metric.unit = CellRoleMetricUnitV1::Q32;
        metric.value = 2_000_000;
        assert!(metric.validate().is_ok());
        metric.value = -1;
        assert_eq!(
            metric.validate(),
            Err(CellRoleGateErrorV1::InvalidMetricValue(
                CellRoleMetricKindV1::PredictorNll
            ))
        );
    }
}
