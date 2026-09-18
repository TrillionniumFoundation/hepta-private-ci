use std::error::Error;
use std::fmt;

/// Stable fail-closed errors for the causal learning ledger.
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
    EpisodeAlreadyExists(String),
    EpisodeNotFound(String),
    EpisodeRevoked(String),
    OutcomeAlreadyExists(String),
    OutcomeNotFound(String),
    OutcomeRevoked(String),
    OutcomeEpisodeMismatch,
    OutcomeNotTerminal,
    OutcomeStateMismatch,
    OutcomeLineageRootExists(String),
    OutcomePredecessorNotFound(String),
    OutcomePredecessorEpisodeMismatch,
    OutcomePredecessorNotHead(String),
    PolicySelfLabelsOutcome,
    CreditIdentityAlreadyExists(String),
    CreditAlreadyAssigned,
    CreditBatchIdentityAlreadyExists(String),
    CreditBatchAlreadyAssigned(String),
    CreditBatchEmpty,
    CreditBatchLimitExceeded,
    DuplicateCreditTarget(String),
    CreditConservation,
    CreditAllocatorNotIndependent,
    TargetNotFound(String),
    TargetAlreadyRevoked(String),
    RevocationOfRevocation,
    UnlearningLineageIdentityAlreadyExists(String),
    UnlearningLineageAlreadyExists,
    UnlearningTargetInvalid,
    IdentityConflict(String),
    SequenceOverflow,
    SnapshotHeadMismatch,
    SnapshotRecordMismatch(u64),
    Arithmetic,
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
            | Self::CreditBatchIdentityAlreadyExists(_)
            | Self::UnlearningLineageIdentityAlreadyExists(_)
            | Self::IdentityConflict(_) => "LRN-E003",
            Self::EpisodeNotFound(_)
            | Self::EpisodeRevoked(_)
            | Self::OutcomeNotFound(_)
            | Self::OutcomeRevoked(_)
            | Self::OutcomePredecessorNotFound(_) => "LRN-E004",
            Self::OutcomeEpisodeMismatch
            | Self::OutcomeNotTerminal
            | Self::OutcomePredecessorEpisodeMismatch
            | Self::OutcomePredecessorNotHead(_)
            | Self::OutcomeLineageRootExists(_)
            | Self::OutcomeStateMismatch => "LRN-E005",
            Self::PolicySelfLabelsOutcome | Self::CreditAllocatorNotIndependent => "LRN-E006",
            Self::CreditAlreadyAssigned
            | Self::CreditBatchAlreadyAssigned(_)
            | Self::DuplicateCreditTarget(_)
            | Self::CreditConservation
            | Self::CreditBatchEmpty
            | Self::CreditBatchLimitExceeded => "LRN-E007",
            Self::TargetNotFound(_)
            | Self::TargetAlreadyRevoked(_)
            | Self::UnlearningTargetInvalid
            | Self::UnlearningLineageAlreadyExists => "LRN-E008",
            Self::RevocationOfRevocation => "LRN-E009",
            Self::SequenceOverflow | Self::Arithmetic => "LRN-E010",
            Self::SnapshotHeadMismatch | Self::SnapshotRecordMismatch(_) => "LRN-E011",
            Self::EmptyDigest(_) | Self::InvalidAuthorityEpoch | Self::InternalInvariant => "LRN-E012",
        }
    }
}

impl fmt::Display for LedgerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::RecordLimitExceeded => {
                formatter.write_str("learning ledger record limit exceeded")
            }
            Self::EmptyCandidateSet => formatter.write_str("candidate set must not be empty"),
            Self::CandidateLimitExceeded => {
                formatter.write_str("candidate set exceeds 128 entries")
            }
            Self::IncompleteCandidateSet => {
                formatter.write_str("candidate set completeness was not independently asserted")
            }
            Self::DuplicateCandidate(id) => write!(formatter, "duplicate candidate id: {id}"),
            Self::MissingAbstainCandidate => {
                formatter.write_str("candidate set must contain explicit abstain")
            }
            Self::SelectedCandidateMissing(id) => {
                write!(
                    formatter,
                    "selected candidate is absent from the candidate set: {id}"
                )
            }
            Self::ZeroSelectedPropensity => {
                formatter.write_str("selected propensity must be greater than zero")
            }
            Self::EmptyDigest(kind) => write!(formatter, "{kind} digest must not be zero"),
            Self::InvalidAuthorityEpoch => formatter.write_str("authority epoch must be non-zero"),
            Self::EpisodeAlreadyExists(id) => write!(formatter, "episode already exists: {id}"),
            Self::EpisodeNotFound(id) => write!(formatter, "episode not found: {id}"),
            Self::EpisodeRevoked(id) => write!(formatter, "episode decision is revoked: {id}"),
            Self::OutcomeAlreadyExists(id) => write!(formatter, "outcome already exists: {id}"),
            Self::OutcomeNotFound(id) => write!(formatter, "outcome not found: {id}"),
            Self::OutcomeRevoked(id) => write!(formatter, "outcome is revoked: {id}"),
            Self::OutcomeEpisodeMismatch => {
                formatter.write_str("outcome and credit episode identities differ")
            }
            Self::OutcomeNotTerminal => {
                formatter.write_str("credit assignment requires a terminal outcome")
            }
            Self::OutcomeStateMismatch => {
                formatter.write_str("authenticated outcome state and watermark fields disagree")
            }
            Self::OutcomeLineageRootExists(id) => {
                write!(formatter, "episode already has an outcome lineage root: {id}")
            }
            Self::OutcomePredecessorNotFound(id) => {
                write!(formatter, "correction predecessor not found: {id}")
            }
            Self::OutcomePredecessorEpisodeMismatch => formatter
                .write_str("correction predecessor belongs to a different episode"),
            Self::OutcomePredecessorNotHead(id) => {
                write!(formatter, "correction predecessor is not current head: {id}")
            }
            Self::PolicySelfLabelsOutcome => {
                formatter.write_str("evaluated policy cannot label its own outcome")
            }
            Self::CreditIdentityAlreadyExists(id) => {
                write!(formatter, "credit identity already exists: {id}")
            }
            Self::CreditAlreadyAssigned => formatter
                .write_str("credit already exists for this episode, outcome and target artifact"),
            Self::CreditBatchIdentityAlreadyExists(id) => {
                write!(formatter, "credit batch identity already exists: {id}")
            }
            Self::CreditBatchAlreadyAssigned(id) => {
                write!(formatter, "terminal outcome already has committed credit: {id}")
            }
            Self::CreditBatchEmpty => formatter.write_str("credit batch must not be empty"),
            Self::CreditBatchLimitExceeded => {
                formatter.write_str("credit batch exceeds 256 allocations")
            }
            Self::DuplicateCreditTarget(id) => {
                write!(formatter, "duplicate credit target in atomic batch: {id}")
            }
            Self::CreditConservation => formatter
                .write_str("credit allocations plus residual must equal terminal outcome"),
            Self::CreditAllocatorNotIndependent => formatter
                .write_str("credit allocator must be independent from generator and observer"),
            Self::TargetNotFound(id) => write!(formatter, "revocation target not found: {id}"),
            Self::TargetAlreadyRevoked(id) => {
                write!(formatter, "revocation target is already revoked: {id}")
            }
            Self::RevocationOfRevocation => {
                formatter.write_str("revocation records cannot themselves be revoked")
            }
            Self::UnlearningLineageIdentityAlreadyExists(id) => {
                write!(formatter, "unlearning lineage identity already exists: {id}")
            }
            Self::UnlearningLineageAlreadyExists => formatter
                .write_str("source, dataset and artifact already have unlearning lineage"),
            Self::UnlearningTargetInvalid => formatter
                .write_str("unlearning source cannot be a revocation or unlearning record"),
            Self::IdentityConflict(id) => write!(formatter, "record id reused with drift: {id}"),
            Self::SequenceOverflow => formatter.write_str("ledger sequence overflow"),
            Self::SnapshotHeadMismatch => formatter.write_str("snapshot head digest mismatch"),
            Self::SnapshotRecordMismatch(sequence) => {
                write!(formatter, "snapshot record mismatch at sequence {sequence}")
            }
            Self::Arithmetic => formatter.write_str("checked ledger arithmetic failed"),
            Self::InternalInvariant => formatter.write_str("ledger internal invariant failed"),
        }
    }
}

impl Error for LedgerError {}
