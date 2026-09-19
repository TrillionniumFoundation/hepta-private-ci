use std::error::Error;
use std::fmt;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LedgerError {
    RecordLimitExceeded,
    EmptyCandidateSet,
    CandidateLimitExceeded,
    IncompleteCandidateSet,
    DuplicateCandidate(String),
    MissingAbstainCandidate,
    SelectedCandidateMissing(String),
    ZeroSelectedPropensity,
    EmptyDigest(&'static str),
    InvalidAuthorityEpoch,
    ScopeMismatch,
    AuthorityEpochMismatch,
    EpisodeAlreadyExists(String),
    EpisodeNotFound(String),
    EpisodeRevoked(String),
    EpisodeNotAuthenticated(String),
    OutcomeAlreadyExists(String),
    OutcomeNotFound(String),
    OutcomeRevoked(String),
    OutcomeEpisodeMismatch,
    OutcomeNotTerminal,
    OutcomeNotAuthenticated(String),
    OutcomeStateMismatch,
    PolicySelfLabelsOutcome,
    IdentityRoleCollision(&'static str),
    CorrectionPredecessorMissing(String),
    CorrectionEpisodeMismatch,
    CorrectionNotHead,
    WeakV1WriteDenied,
    CreditIdentityAlreadyExists(String),
    CreditAlreadyAssigned,
    CreditBatchEmpty,
    CreditBatchLimitExceeded,
    DuplicateCreditTarget(String),
    CreditConservation,
    CreditOutcomeValueMismatch,
    CreditParentNotFound(String),
    TargetNotFound(String),
    TargetAlreadyRevoked(String),
    RevocationOfRevocation,
    LineageIdentityAlreadyExists(String),
    LineageEmptySources,
    LineageTargetLimitExceeded,
    DuplicateLineageTarget(String),
    LineagePredecessorMismatch,
    IdentityConflict(String),
    SequenceOverflow,
    SnapshotHeadMismatch,
    SnapshotRecordMismatch(u64),
    InternalInvariant,
}

impl LedgerError {
    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::RecordLimitExceeded
            | Self::EmptyCandidateSet
            | Self::CandidateLimitExceeded
            | Self::IncompleteCandidateSet => "LRN-E001",
            Self::DuplicateCandidate(_)
            | Self::MissingAbstainCandidate
            | Self::SelectedCandidateMissing(_)
            | Self::ZeroSelectedPropensity => "LRN-E002",
            Self::EpisodeAlreadyExists(_)
            | Self::OutcomeAlreadyExists(_)
            | Self::CreditIdentityAlreadyExists(_)
            | Self::LineageIdentityAlreadyExists(_)
            | Self::IdentityConflict(_) => "LRN-E003",
            Self::EpisodeNotFound(_)
            | Self::EpisodeRevoked(_)
            | Self::OutcomeNotFound(_)
            | Self::OutcomeRevoked(_) => "LRN-E004",
            Self::OutcomeEpisodeMismatch
            | Self::OutcomeNotTerminal
            | Self::OutcomeStateMismatch
            | Self::CorrectionPredecessorMissing(_)
            | Self::CorrectionEpisodeMismatch
            | Self::CorrectionNotHead => "LRN-E005",
            Self::PolicySelfLabelsOutcome
            | Self::IdentityRoleCollision(_)
            | Self::EpisodeNotAuthenticated(_)
            | Self::OutcomeNotAuthenticated(_)
            | Self::WeakV1WriteDenied
            | Self::ScopeMismatch
            | Self::AuthorityEpochMismatch
            | Self::InvalidAuthorityEpoch => "LRN-E006",
            Self::CreditAlreadyAssigned
            | Self::CreditBatchEmpty
            | Self::CreditBatchLimitExceeded
            | Self::DuplicateCreditTarget(_)
            | Self::CreditConservation
            | Self::CreditOutcomeValueMismatch
            | Self::CreditParentNotFound(_) => "LRN-E007",
            Self::TargetNotFound(_)
            | Self::TargetAlreadyRevoked(_)
            | Self::LineageEmptySources
            | Self::LineageTargetLimitExceeded
            | Self::DuplicateLineageTarget(_)
            | Self::LineagePredecessorMismatch => "LRN-E008",
            Self::RevocationOfRevocation => "LRN-E009",
            Self::SequenceOverflow => "LRN-E010",
            Self::SnapshotHeadMismatch | Self::SnapshotRecordMismatch(_) => "LRN-E011",
            Self::EmptyDigest(_) | Self::InternalInvariant => "LRN-E012",
        }
    }
}

impl fmt::Display for LedgerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::RecordLimitExceeded => formatter.write_str("learning ledger record limit exceeded"),
            Self::EmptyCandidateSet => formatter.write_str("candidate set must not be empty"),
            Self::CandidateLimitExceeded => formatter.write_str("candidate set exceeds 128 entries"),
            Self::IncompleteCandidateSet => formatter.write_str("candidate set completeness was not independently asserted"),
            Self::DuplicateCandidate(id) => write!(formatter, "duplicate candidate id: {id}"),
            Self::MissingAbstainCandidate => formatter.write_str("candidate set must contain explicit abstain"),
            Self::SelectedCandidateMissing(id) => write!(formatter, "selected candidate is absent from the candidate set: {id}"),
            Self::ZeroSelectedPropensity => formatter.write_str("selected propensity must be greater than zero"),
            Self::EmptyDigest(kind) => write!(formatter, "{kind} digest must not be zero"),
            Self::InvalidAuthorityEpoch => formatter.write_str("authority epoch must be non-zero"),
            Self::ScopeMismatch => formatter.write_str("authenticated scope does not match episode scope"),
            Self::AuthorityEpochMismatch => formatter.write_str("authority epoch does not match episode authority epoch"),
            Self::EpisodeAlreadyExists(id) => write!(formatter, "episode already exists: {id}"),
            Self::EpisodeNotFound(id) => write!(formatter, "episode not found: {id}"),
            Self::EpisodeRevoked(id) => write!(formatter, "episode decision is revoked: {id}"),
            Self::EpisodeNotAuthenticated(id) => write!(formatter, "episode was not admitted through authenticated V2: {id}"),
            Self::OutcomeAlreadyExists(id) => write!(formatter, "outcome already exists: {id}"),
            Self::OutcomeNotFound(id) => write!(formatter, "outcome not found: {id}"),
            Self::OutcomeRevoked(id) => write!(formatter, "outcome is revoked: {id}"),
            Self::OutcomeEpisodeMismatch => formatter.write_str("outcome and credit episode identities differ"),
            Self::OutcomeNotTerminal => formatter.write_str("credit assignment requires a terminal outcome"),
            Self::OutcomeNotAuthenticated(id) => write!(formatter, "outcome was not admitted through authenticated V2: {id}"),
            Self::OutcomeStateMismatch => formatter.write_str("outcome watermark state is inconsistent"),
            Self::PolicySelfLabelsOutcome => formatter.write_str("evaluated policy cannot label its own outcome"),
            Self::IdentityRoleCollision(kind) => write!(formatter, "learning evidence role collision: {kind}"),
            Self::CorrectionPredecessorMissing(id) => write!(formatter, "correction predecessor not found: {id}"),
            Self::CorrectionEpisodeMismatch => formatter.write_str("correction predecessor belongs to a different episode"),
            Self::CorrectionNotHead => formatter.write_str("correction predecessor is not the current episode outcome head"),
            Self::WeakV1WriteDenied => formatter.write_str("weak V1 outcome or credit writes are denied for authenticated V2 episodes"),
            Self::CreditIdentityAlreadyExists(id) => write!(formatter, "credit identity already exists: {id}"),
            Self::CreditAlreadyAssigned => formatter.write_str("credit already exists for this episode, outcome and target artifact"),
            Self::CreditBatchEmpty => formatter.write_str("credit batch must contain allocations"),
            Self::CreditBatchLimitExceeded => formatter.write_str("credit batch exceeds durable allocation limit"),
            Self::DuplicateCreditTarget(id) => write!(formatter, "duplicate credit target: {id}"),
            Self::CreditConservation => formatter.write_str("credit allocations plus residual do not conserve terminal outcome"),
            Self::CreditOutcomeValueMismatch => formatter.write_str("credit batch terminal outcome does not match the durable outcome"),
            Self::CreditParentNotFound(id) => write!(formatter, "parent credit not found: {id}"),
            Self::TargetNotFound(id) => write!(formatter, "revocation target not found: {id}"),
            Self::TargetAlreadyRevoked(id) => write!(formatter, "revocation target is already revoked: {id}"),
            Self::RevocationOfRevocation => formatter.write_str("revocation records cannot themselves be revoked"),
            Self::LineageIdentityAlreadyExists(id) => write!(formatter, "unlearning lineage identity already exists: {id}"),
            Self::LineageEmptySources => formatter.write_str("unlearning lineage must name at least one source record"),
            Self::LineageTargetLimitExceeded => formatter.write_str("unlearning lineage target list exceeds durable limit"),
            Self::DuplicateLineageTarget(id) => write!(formatter, "duplicate unlearning lineage target: {id}"),
            Self::LineagePredecessorMismatch => formatter.write_str("unlearning lineage predecessor does not match the current scope lineage head"),
            Self::IdentityConflict(id) => write!(formatter, "record id reused with drift: {id}"),
            Self::SequenceOverflow => formatter.write_str("ledger sequence overflow"),
            Self::SnapshotHeadMismatch => formatter.write_str("snapshot head digest mismatch"),
            Self::SnapshotRecordMismatch(sequence) => write!(formatter, "snapshot record mismatch at sequence {sequence}"),
            Self::InternalInvariant => formatter.write_str("ledger internal invariant failed"),
        }
    }
}

impl Error for LedgerError {}
