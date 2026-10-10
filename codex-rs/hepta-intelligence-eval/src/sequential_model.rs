//! Typed finite-horizon inputs, evidence gaps and bounded point-estimate receipts.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use std::fmt;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TerminalRewardConvention {
    IncludedInLastReward,
    SeparateTerminalValue,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
/// Selects numeric support floors only; no variant certifies a capability claim.
pub enum TrajectoryClaimScope {
    Qualification,
    SystemLongitudinal,
}

/// A distinct estimand from a single-decision OPE plan; all episodes have H steps.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FiniteHorizonEstimand {
    pub horizon: u16,
    pub terminal_reward: TerminalRewardConvention,
    pub scope: TrajectoryClaimScope,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SequentialPlan {
    pub plan_digest: Digest32,
    pub estimand: FiniteHorizonEstimand,
    pub behavior_policy: Digest32,
    pub evaluation_policy: Digest32,
    pub observation_generation: Generation,
    pub outcome_watermark: u64,
    pub minimum_trajectories: usize,
    pub minimum_depth_ess: FixedQ32,
    pub maximum_step_ratio: FixedQ32,
    pub maximum_cumulative_ratio: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrajectoryAction {
    pub action_id: StableId,
    pub behavior_probability: ProbabilityQ32,
    pub evaluation_probability: ProbabilityQ32,
    /// Caller-supplied held-out Q(H,a), in the pilot range [-129, 129].
    pub predicted_return: FixedQ32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TrajectoryBoundary {
    Continuing,
    Terminal,
    Censored,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrajectoryStep {
    pub decision_id: StableId,
    pub history_digest: Digest32,
    pub next_history_digest: Digest32,
    pub observation_generation: Generation,
    pub complete_actions: bool,
    pub actions: Vec<TrajectoryAction>,
    pub chosen_action: StableId,
    /// A finalized normalized reward in [-1, 1]; missing is pending, never zero.
    pub reward: Option<FixedQ32>,
    pub discount: ProbabilityQ32,
    pub boundary: TrajectoryBoundary,
    pub observed_at: u64,
    pub outcome_evidence: Digest32,
    pub prediction_evidence: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Trajectory {
    pub trajectory_id: StableId,
    pub cluster_id: StableId,
    pub initial_history: Digest32,
    pub behavior_policy: Digest32,
    pub evaluation_policy: Digest32,
    pub terminal_value: FixedQ32,
    pub steps: Vec<TrajectoryStep>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrajectoryEstimate {
    pub trajectory_id: StableId,
    pub per_decision_importance_sampling: FixedQ32,
    pub doubly_robust: FixedQ32,
    pub cumulative_weights: Vec<FixedQ32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DepthSupport {
    pub depth: u16,
    pub effective_sample_size: FixedQ32,
    pub maximum_cumulative_weight: FixedQ32,
    pub positive_weight_trajectories: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SequentialEstimate {
    pub trajectories: Vec<TrajectoryEstimate>,
    /// Number of supplied cluster labels, not a proof of independent sampling.
    pub cluster_count: usize,
    pub per_decision_importance_sampling: FixedQ32,
    pub doubly_robust: FixedQ32,
    pub depth_support: Vec<DepthSupport>,
    pub evidence_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SequentialEvidenceGap {
    IncompleteHistory,
    IncompleteActions,
    UnsupportedAction,
    PendingOutcome,
    CensoredTrajectory,
    MissingEvidence,
    GenerationMismatch,
    OutcomeAfterWatermark,
    WeightLimit,
    NumericResolution,
    DepthSupport,
    InsufficientTrajectories,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SequentialError {
    InvalidPlan,
    ResourceLimit,
    DuplicateIdentity,
    InvalidDistribution,
    InvalidValue,
    TerminalConvention,
    Arithmetic,
    InsufficientEvidence(SequentialEvidenceGap),
}

impl fmt::Display for SequentialError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl std::error::Error for SequentialError {}
