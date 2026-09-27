//! Verified, authority-free prompt policy pipeline.
//!
//! Raw DTOs can be inspected or copied, but cannot be converted into verified
//! phases. Every phase is constructed here and exposes only immutable access.
//! Evidence sources are host-installed capabilities, never request parameters
//! decoded from untrusted prompt material. They must reread their owner stores.

use std::fmt;
use std::ops::Deref;
use std::sync::Arc;

use codex_hepta_kg::KnowledgeGenerationV2;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_prompt_registry::PromptRegistry;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::canonical_engine as engine;

pub use engine::EnumeratedPromptCandidatesV1 as RawEnumeratedPromptCandidatesV1;
pub use engine::MAX_CANONICAL_INTERACTION_EDGES;
pub use engine::MAX_CANONICAL_PROMPT_FACTORS;
pub use engine::MAX_CANONICAL_SELECTED_FACTORS;
pub use engine::MAX_CANONICAL_TOKEN_BUDGET;
pub use engine::PricedPromptCandidatesV1 as RawPricedPromptCandidatesV1;
pub use engine::PromptCandidateBindingV1;
pub use engine::PromptCandidateSetReceiptV1;
pub use engine::PromptConfidenceIntervalV1;
pub use engine::PromptDecisionBoundaryV1;
pub use engine::PromptEnumerationRequestV1;
pub use engine::PromptExerciseActionV1;
pub use engine::PromptExerciseDecisionV1 as RawPromptExerciseDecisionV1;
pub use engine::PromptExerciseRequestV1;
pub use engine::PromptOptimalityDisclosureV1;
pub use engine::PromptPairUtilityEvidenceV1;
pub use engine::PromptPortfolioReceiptV1;
pub use engine::PromptPortfolioRequestV1;
pub use engine::PromptPricingEvidenceV1;
pub use engine::PromptPricingPolicyV1;
pub use engine::PromptPricingReceiptV1;
pub use engine::PromptSelectionMethodV1;
pub use engine::SelectedPromptPortfolioV1 as RawSelectedPromptPortfolioV1;
pub use engine::candidate_completeness_signing_payload_v1;
pub use engine::pair_utility_evidence_signing_payload_v1;
pub use engine::pricing_evidence_signing_payload_v1;

#[path = "canonical_admission.rs"]
mod admission;
#[path = "canonical_audit.rs"]
mod audit;
pub use admission::interaction_admission_signing_payload_v1;
pub use admission::pricing_admission_signing_payload_v1;
pub use audit::PromptCandidateAuditV1;
pub use audit::PromptCandidateDispositionV1;
pub use audit::PromptPortfolioAuditV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CanonicalPromptError {
    Core(engine::CanonicalPromptError),
    Integrity(&'static str),
    Evidence(String),
    ObjectiveMismatch,
    ScopeMismatch,
    SourceChanged,
    TrustChanged,
    GraphChanged,
    PolicyChanged,
    PolicyInvalid,
    BoundaryDenied,
    EvidenceExpired,
    UnsatisfiableConstraints(String),
    MissingPairSupport(String, String),
    Unavailable(String),
    TimedOut,
    Corrupt(String),
    Indeterminate,
    Quarantined,
}
impl fmt::Display for CanonicalPromptError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for CanonicalPromptError {}
impl From<engine::CanonicalPromptError> for CanonicalPromptError {
    fn from(value: engine::CanonicalPromptError) -> Self {
        Self::Core(value)
    }
}

/// Host-owned policy for this objective/state generation. The wait valuation
/// and allowed boundaries are actual policy inputs, not caller-chosen labels.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExercisePolicyV1 {
    pub policy_id: StableId,
    pub objective_digest: Digest32,
    pub scope_digest: Digest32,
    pub state_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub allowed_boundaries: Vec<PromptDecisionBoundaryV1>,
    pub wait_value_q32: FixedQ32,
    pub not_before_unix_ms: u64,
    pub valid_until_unix_ms: u64,
}
impl PromptExercisePolicyV1 {
    pub fn digest(&self) -> Result<Digest32, CanonicalPromptError> {
        admission::exercise_policy_digest(self)
    }
}

/// A fresh read from named host-owned trust, graph and policy stores. The host
/// must not implement `current` as an indefinitely cached request-supplied view.
#[derive(Clone, Debug)]
pub struct PromptEvidenceSnapshotV1 {
    pub source_id: StableId,
    pub verifier: LearningEvidenceVerifierV1,
    pub graph: KnowledgeGenerationV2,
    pub pricing_policy: PromptPricingPolicyV1,
    pub exercise_policy: PromptExercisePolicyV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingAdmissionV1 {
    pub completeness: CandidateSetCompletenessReceiptV1,
    pub completeness_evidence: SignedLearningEvidenceV1,
    pub estimates: Vec<PromptPricingEvidenceV1>,
    /// Evaluator signature binds the complete batch to the exact candidate
    /// receipt, realization bindings, scope and pricing policy. The individual
    /// estimate signatures are retained and verified for provenance continuity.
    pub binding_evidence: SignedLearningEvidenceV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptMissingPairPolicyV1 {
    RequireExplicit,
    /// This assumption must be endorsed by the independent batch evaluator.
    AssumeZeroWithWitness,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptInteractionAdmissionV1 {
    pub pairs: Vec<PromptPairUtilityEvidenceV1>,
    pub missing_pairs: PromptMissingPairPolicyV1,
    pub binding_evidence: SignedLearningEvidenceV1,
}

/// Installed by the trusted embedding, not by prompt or remote evidence bytes.
/// Reads must preserve owner authentication, revocation and typed failures.
/// The optimizer never writes these stores or fabricates scientific evidence.
pub trait PromptEvidenceSourceV1: Send + Sync {
    fn current(&self) -> Result<PromptEvidenceSnapshotV1, CanonicalPromptError>;
    fn pricing(
        &self,
        candidates: &EnumeratedPromptCandidatesV1,
        now_unix_ms: u64,
    ) -> Result<PromptPricingAdmissionV1, CanonicalPromptError>;
    fn interactions(
        &self,
        priced: &PricedPromptCandidatesV1,
        now_unix_ms: u64,
    ) -> Result<PromptInteractionAdmissionV1, CanonicalPromptError>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EnumeratedPromptCandidatesV1 {
    inner: RawEnumeratedPromptCandidatesV1,
}
impl Deref for EnumeratedPromptCandidatesV1 {
    type Target = RawEnumeratedPromptCandidatesV1;
    fn deref(&self) -> &Self::Target {
        &self.inner
    }
}

#[derive(Clone)]
pub struct PricedPromptCandidatesV1 {
    inner: RawPricedPromptCandidatesV1,
    admission: PromptPricingAdmissionV1,
    source: Arc<dyn PromptEvidenceSourceV1>,
    source_id: StableId,
    trust_digest: Digest32,
    scope_digest: Digest32,
    valid_until_unix_ms: u64,
}
impl Deref for PricedPromptCandidatesV1 {
    type Target = RawPricedPromptCandidatesV1;
    fn deref(&self) -> &Self::Target {
        &self.inner
    }
}
impl fmt::Debug for PricedPromptCandidatesV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("PricedPromptCandidatesV1")
            .field("pricing_set_digest", &self.inner.pricing_set_digest)
            .field("source_id", &self.source_id)
            .field("valid_until_unix_ms", &self.valid_until_unix_ms)
            .finish_non_exhaustive()
    }
}
impl PartialEq for PricedPromptCandidatesV1 {
    fn eq(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.source, &other.source)
            && self.inner == other.inner
            && self.admission == other.admission
            && self.source_id == other.source_id
            && self.trust_digest == other.trust_digest
            && self.scope_digest == other.scope_digest
            && self.valid_until_unix_ms == other.valid_until_unix_ms
    }
}
impl Eq for PricedPromptCandidatesV1 {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelectedPromptPortfolioV1 {
    inner: RawSelectedPromptPortfolioV1,
    priced: PricedPromptCandidatesV1,
    interactions: PromptInteractionAdmissionV1,
    exercise_policy_digest: Digest32,
    audit: PromptPortfolioAuditV1,
}
impl Deref for SelectedPromptPortfolioV1 {
    type Target = RawSelectedPromptPortfolioV1;
    fn deref(&self) -> &Self::Target {
        &self.inner
    }
}
impl SelectedPromptPortfolioV1 {
    pub fn audit(&self) -> &PromptPortfolioAuditV1 {
        &self.audit
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseDecisionV1 {
    inner: RawPromptExerciseDecisionV1,
}
impl Deref for PromptExerciseDecisionV1 {
    type Target = RawPromptExerciseDecisionV1;
    fn deref(&self) -> &Self::Target {
        &self.inner
    }
}

pub fn enumerate_factors_v1(
    registry: &PromptRegistry,
    request: PromptEnumerationRequestV1,
) -> Result<EnumeratedPromptCandidatesV1, CanonicalPromptError> {
    let inner = engine::enumerate_factors_v1(registry, request)?;
    admission::validate_candidates(&inner)?;
    Ok(EnumeratedPromptCandidatesV1 { inner })
}

pub fn price_factors_v1(
    candidates: EnumeratedPromptCandidatesV1,
    material: PromptPricingAdmissionV1,
    source: Arc<dyn PromptEvidenceSourceV1>,
    now_unix_ms: u64,
) -> Result<PricedPromptCandidatesV1, CanonicalPromptError> {
    let current = source.current()?;
    let valid_until_unix_ms =
        admission::verify_pricing(&candidates, &material, &current, now_unix_ms)?;
    let inner = engine::price_factors_v1(
        candidates.inner,
        &material.completeness,
        &material.completeness_evidence,
        material.estimates.clone(),
        &current.verifier,
        &current.pricing_policy,
        now_unix_ms,
    )?;
    Ok(PricedPromptCandidatesV1 {
        inner,
        admission: material,
        source,
        source_id: current.source_id,
        trust_digest: current.verifier.trust_digest(),
        scope_digest: current.verifier.scope_digest(),
        valid_until_unix_ms,
    })
}

pub fn select_portfolio_v1(
    priced: &PricedPromptCandidatesV1,
    interactions: PromptInteractionAdmissionV1,
    mut request: PromptPortfolioRequestV1,
    now_unix_ms: u64,
) -> Result<SelectedPromptPortfolioV1, CanonicalPromptError> {
    let current = priced.source.current()?;
    admission::revalidate_priced(priced, &current, now_unix_ms)?;
    let valid_until = admission::verify_interactions(priced, &interactions, &current, now_unix_ms)?;
    request.requested_valid_until_unix_ms = request
        .requested_valid_until_unix_ms
        .min(valid_until)
        .min(priced.valid_until_unix_ms)
        .min(current.exercise_policy.valid_until_unix_ms);
    let token_budget = request.token_budget;
    let mut inner = engine::select_portfolio_v1(
        &priced.inner,
        &current.graph,
        interactions.pairs.clone(),
        &current.verifier,
        request,
        now_unix_ms,
    )?;
    // No mutation of caller-owned data: the raw engine result is sealed only
    // after complete admission, explicit missing-edge policy and audit checks.
    admission::validate_selection(priced, &inner, &interactions)?;
    let audit = audit::build_audit(priced, &inner, &interactions, token_budget, now_unix_ms)?;
    inner.receipt.authority = codex_hepta_types::AuthorityPosture::DENY_ALL;
    Ok(SelectedPromptPortfolioV1 {
        inner,
        priced: priced.clone(),
        interactions,
        exercise_policy_digest: current.exercise_policy.digest()?,
        audit,
    })
}

pub fn exercise_v1(
    registry: &PromptRegistry,
    portfolio: &SelectedPromptPortfolioV1,
    request: PromptExerciseRequestV1,
) -> Result<PromptExerciseDecisionV1, CanonicalPromptError> {
    let current = portfolio.priced.source.current()?;
    admission::revalidate_priced(&portfolio.priced, &current, request.now_unix_ms)?;
    if current.graph.generation_digest != portfolio.inner.graph_generation_digest {
        return Err(CanonicalPromptError::GraphChanged);
    }
    let policy_digest = current.exercise_policy.digest()?;
    if policy_digest != portfolio.exercise_policy_digest
        || request.policy_digest != policy_digest
        || request.wait_value_q32 != current.exercise_policy.wait_value_q32
    {
        return Err(CanonicalPromptError::PolicyChanged);
    }
    if !current
        .exercise_policy
        .allowed_boundaries
        .contains(&request.decision_boundary)
    {
        return Err(CanonicalPromptError::BoundaryDenied);
    }
    admission::verify_interactions(
        &portfolio.priced,
        &portfolio.interactions,
        &current,
        request.now_unix_ms,
    )?;
    admission::validate_selection(&portfolio.priced, &portfolio.inner, &portfolio.interactions)?;
    Ok(PromptExerciseDecisionV1 {
        inner: engine::exercise_v1(registry, &portfolio.inner, request)?,
    })
}

/// One source-level composition entrypoint. Provider dispatch and durable
/// terminal observation remain the existing runtime/ledger owners' operations.
pub fn build_verified_prompt_portfolio_v1(
    registry: &PromptRegistry,
    enumeration: PromptEnumerationRequestV1,
    selection: PromptPortfolioRequestV1,
    source: Arc<dyn PromptEvidenceSourceV1>,
    now_unix_ms: u64,
) -> Result<SelectedPromptPortfolioV1, CanonicalPromptError> {
    if enumeration.now_unix_ms != now_unix_ms {
        return Err(CanonicalPromptError::Integrity("enumeration clock"));
    }
    let candidates = enumerate_factors_v1(registry, enumeration)?;
    let material = source.pricing(&candidates, now_unix_ms)?;
    let priced = price_factors_v1(candidates, material, Arc::clone(&source), now_unix_ms)?;
    let interactions = source.interactions(&priced, now_unix_ms)?;
    select_portfolio_v1(&priced, interactions, selection, now_unix_ms)
}

#[cfg(test)]
#[path = "canonical_verified_tests.rs"]
mod tests;
