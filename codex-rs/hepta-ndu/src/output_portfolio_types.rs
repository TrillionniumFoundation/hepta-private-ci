use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

/// Output family used to decide whether a candidate may be blended or must be
/// selected as a whole. Tool actions are represented for accounting only;
/// execution still requires an external safety arbiter.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum OutputProtocolV1 {
    NoChange,
    TextLogit,
    LatentFlow,
    MaskedDiffusion,
    AudioLatent,
    VideoLatent,
    ToolAction,
}
impl OutputProtocolV1 {
    pub(crate) const fn tag(self) -> u8 {
        match self {
            Self::NoChange => 0,
            Self::TextLogit => 1,
            Self::LatentFlow => 2,
            Self::MaskedDiffusion => 3,
            Self::AudioLatent => 4,
            Self::VideoLatent => 5,
            Self::ToolAction => 6,
        }
    }
    /// Tool effects and discrete masked-unmask plans must be selected as
    /// whole candidates. Continuous logits and latent directions are subject
    /// to additional protocol and composition compatibility checks.
    #[must_use]
    pub(crate) const fn requires_whole_candidate(self) -> bool {
        matches!(self, Self::ToolAction | Self::MaskedDiffusion)
    }
}
/// Semantic loss estimates collected over a frozen future window.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SemanticRiskEstimateV1 {
    /// Digest of the independently observed future-window evidence used to
    /// estimate this risk.  The selector only checks binding; it does not
    /// authenticate or manufacture the external observation.
    pub future_window_digest: Digest32,
    pub mean_loss: FixedQ32,
    pub cvar_loss: FixedQ32,
    pub failure_probability: ProbabilityQ32,
    pub cross_modal_inconsistency: FixedQ32,
}
/// Candidate direction emitted by a Cell head from one immutable snapshot.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OutputPortfolioCandidateV1 {
    pub candidate_id: StableId,
    pub candidate_digest: Digest32,
    pub snapshot_digest: Digest32,
    /// Source fence of the Cell proposal. Matching feature bytes do not
    /// authorize reusing a proposal across generations.
    pub generation: Generation,
    /// Exact encoder artifact that produced this Cell proposal.
    pub encoder_digest: Digest32,
    /// Exact codec/vocabulary/latent geometry, phase and denoising schedule
    /// contract for composing directions. Distinct heads may share a snapshot
    /// without sharing a valid output coordinate space.
    pub composition_domain_digest: Digest32,
    pub protocol: OutputProtocolV1,
    pub utility_delta: FixedQ32,
    pub risk: SemanticRiskEstimateV1,
    pub resource_cost: FixedQ32,
    pub latency_cost: FixedQ32,
    pub weight_cap: FixedQ32,
    pub is_no_change: bool,
}
/// Shared context proving that all candidates came from the same encoder
/// output and generation. This is an immutable FeatureSnapshot boundary.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OutputPortfolioContextV1 {
    pub objective_digest: Digest32,
    pub generation: Generation,
    pub encoder_digest: Digest32,
    pub snapshot_digest: Digest32,
    /// All candidate risks must come from this exact externally observed
    /// future window.  A window name or local timestamp is not sufficient.
    pub future_window_digest: Digest32,
    /// Row-major covariance of candidate semantic losses.
    pub semantic_covariance: Vec<FixedQ32>,
}
/// Deterministic budget and risk aversion parameters for one MPC step.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OutputPortfolioBudgetV1 {
    pub max_selected: usize,
    pub risk_budget: FixedQ32,
    pub resource_budget: FixedQ32,
    pub latency_budget: FixedQ32,
    pub risk_aversion: FixedQ32,
    pub cvar_aversion: FixedQ32,
    pub failure_aversion: FixedQ32,
    pub inconsistency_aversion: FixedQ32,
    pub resource_price: FixedQ32,
    pub latency_price: FixedQ32,
    pub switch_penalty: FixedQ32,
}
/// A weight assigned to one output direction. Weights are advisory and sum to
/// one; a caller must still apply protocol-specific composition rules.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OutputPortfolioAllocationV1 {
    pub candidate_id: StableId,
    pub protocol: OutputProtocolV1,
    pub weight: FixedQ32,
    pub adjusted_score: FixedQ32,
}
/// A point on the single-step semantic efficient frontier.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OutputPortfolioFrontierPointV1 {
    pub candidate_id: StableId,
    pub utility_delta: FixedQ32,
    pub semantic_risk: FixedQ32,
    pub resource_cost: FixedQ32,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OutputPortfolioDispositionV1 {
    NoChange,
    AdvisorySelection,
}
/// Replayable advisory receipt. It deliberately contains no execution token.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OutputPortfolioSelectionReceiptV1 {
    pub objective_digest: Digest32,
    pub generation: Generation,
    pub encoder_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub disposition: OutputPortfolioDispositionV1,
    pub allocations: Vec<OutputPortfolioAllocationV1>,
    pub frontier: Vec<OutputPortfolioFrontierPointV1>,
    pub total_utility: FixedQ32,
    pub total_risk: FixedQ32,
    pub total_resource: FixedQ32,
    pub total_latency: FixedQ32,
    pub selection_digest: Digest32,
}
