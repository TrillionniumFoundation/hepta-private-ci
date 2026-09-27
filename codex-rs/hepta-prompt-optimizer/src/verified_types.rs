/// Exact owner/candidate binding carried beside one evaluator attestation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BoundPromptPricingEvidenceV2 {
    pub candidate_set_digest: Digest32,
    pub registry_snapshot_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub realization_id: StableId,
    pub realization_binding_digest: Digest32,
    pub pricing_policy_digest: Digest32,
    pub evidence: PromptPricingEvidenceV1,
}

/// Exact candidate/pricing/graph binding carried beside one pair attestation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BoundPromptPairUtilityEvidenceV2 {
    pub candidate_set_digest: Digest32,
    pub pricing_set_digest: Digest32,
    pub left_realization_binding_digest: Digest32,
    pub right_realization_binding_digest: Digest32,
    pub evidence: PromptPairUtilityEvidenceV1,
}

/// Immutable verification context required to reopen a selected portfolio after
/// persistence or transport. A context is evidence metadata, not authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioVerificationContextV2 {
    candidate_set_digest: Digest32,
    pricing_set_digest: Digest32,
    registry_snapshot_digest: Digest32,
    generation_vector_digest: Digest32,
    model_tuple_digest: Digest32,
    graph_generation_digest: Digest32,
    objective_digest: Digest32,
    state_digest: Digest32,
    scope_digest: Digest32,
    trust_digest: Digest32,
    authority_epoch: u64,
    valid_until_unix_ms: u64,
    evidence_lineage_digest: Digest32,
}

impl PromptPortfolioVerificationContextV2 {
    #[must_use]
    pub const fn candidate_set_digest(&self) -> Digest32 {
        self.candidate_set_digest
    }

    #[must_use]
    pub const fn pricing_set_digest(&self) -> Digest32 {
        self.pricing_set_digest
    }

    #[must_use]
    pub const fn registry_snapshot_digest(&self) -> Digest32 {
        self.registry_snapshot_digest
    }

    #[must_use]
    pub const fn generation_vector_digest(&self) -> Digest32 {
        self.generation_vector_digest
    }

    #[must_use]
    pub const fn model_tuple_digest(&self) -> Digest32 {
        self.model_tuple_digest
    }

    #[must_use]
    pub const fn graph_generation_digest(&self) -> Digest32 {
        self.graph_generation_digest
    }

    #[must_use]
    pub const fn objective_digest(&self) -> Digest32 {
        self.objective_digest
    }

    #[must_use]
    pub const fn state_digest(&self) -> Digest32 {
        self.state_digest
    }

    #[must_use]
    pub const fn scope_digest(&self) -> Digest32 {
        self.scope_digest
    }

    #[must_use]
    pub const fn trust_digest(&self) -> Digest32 {
        self.trust_digest
    }

    #[must_use]
    pub const fn authority_epoch(&self) -> u64 {
        self.authority_epoch
    }

    #[must_use]
    pub const fn valid_until_unix_ms(&self) -> u64 {
        self.valid_until_unix_ms
    }

    #[must_use]
    pub const fn evidence_lineage_digest(&self) -> Digest32 {
        self.evidence_lineage_digest
    }

}

/// Enumerated candidates whose registry/model/order/digest invariants were
/// recomputed by this crate. Fields remain private so callers cannot mint one.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedEnumeratedPromptCandidatesV2 {
    value: EnumeratedPromptCandidatesV1,
    scope_digest: Digest32,
}

impl VerifiedEnumeratedPromptCandidatesV2 {
    #[must_use]
    pub fn canonical(&self) -> &EnumeratedPromptCandidatesV1 {
        &self.value
    }

    #[must_use]
    pub const fn scope_digest(&self) -> Digest32 {
        self.scope_digest
    }
}

/// Priced candidates whose exact realization, trust, objective, role separation
/// and receipt digests were verified. Fields remain private.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedPricedPromptCandidatesV2 {
    value: PricedPromptCandidatesV1,
    scope_digest: Digest32,
    trust_digest: Digest32,
    authority_epoch: u64,
    valid_until_unix_ms: u64,
    evidence_lineage_digest: Digest32,
    generator_controller_id: StableId,
    evaluator_controller_ids: BTreeSet<StableId>,
}

impl VerifiedPricedPromptCandidatesV2 {
    #[must_use]
    pub fn canonical(&self) -> &PricedPromptCandidatesV1 {
        &self.value
    }

    #[must_use]
    pub const fn scope_digest(&self) -> Digest32 {
        self.scope_digest
    }

    #[must_use]
    pub const fn valid_until_unix_ms(&self) -> u64 {
        self.valid_until_unix_ms
    }

    #[must_use]
    pub const fn evidence_lineage_digest(&self) -> Digest32 {
        self.evidence_lineage_digest
    }

    #[must_use]
    pub fn evaluator_controller_ids(&self) -> &BTreeSet<StableId> {
        &self.evaluator_controller_ids
    }
}

/// Selected portfolio whose candidate/pricing/graph/evidence lineage and receipt
/// digests were recomputed. Fields remain private.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedSelectedPromptPortfolioV2 {
    value: SelectedPromptPortfolioV1,
    context: PromptPortfolioVerificationContextV2,
}

impl VerifiedSelectedPromptPortfolioV2 {
    #[must_use]
    pub fn canonical(&self) -> &SelectedPromptPortfolioV1 {
        &self.value
    }

    #[must_use]
    pub fn context(&self) -> &PromptPortfolioVerificationContextV2 {
        &self.context
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum VerifiedPromptErrorV2 {
    EmptyDigest(&'static str),
    BoundExceeded(&'static str),
    NonCanonicalOrder(&'static str),
    DuplicateIdentity(String),
    IdentityMismatch(&'static str),
    DigestMismatch(&'static str),
    AuthorityEscalation,
    ObjectiveMismatch,
    ScopeMismatch,
    ControllerCollision,
    EvidenceExpired,
    TrustRotated,
    GraphDrift,
    GraphExpired,
    Stale,
    Revoked,
    Unavailable(String),
    Incomplete(String),
    Corrupt(String),
    Indeterminate(String),
    Quarantined(String),
    LearningEvidence(String),
    KnowledgeGraph(String),
    Canonical(CanonicalPromptError),
    Arithmetic,
}

impl fmt::Display for VerifiedPromptErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for VerifiedPromptErrorV2 {}

impl From<CanonicalPromptError> for VerifiedPromptErrorV2 {
    fn from(value: CanonicalPromptError) -> Self {
        Self::Canonical(value)
    }
}

