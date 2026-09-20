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
    EpisodeAlreadyExists(String),
    EpisodeNotFound(String),
    EpisodeRevoked(String),
    OutcomeAlreadyExists(String),
    OutcomeNotFound(String),
    OutcomeRevoked(String),
    OutcomeEpisodeMismatch,
    OutcomeNotTerminal,
    PolicySelfLabelsOutcome,
    CreditIdentityAlreadyExists(String),
    CreditAlreadyAssigned,
    TargetNotFound(String),
    TargetAlreadyRevoked(String),
    RevocationOfRevocation,
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
            | Self::IdentityConflict(_) => "LRN-E003",
            Self::EpisodeNotFound(_)
            | Self::EpisodeRevoked(_)
            | Self::OutcomeNotFound(_)
            | Self::OutcomeRevoked(_) => "LRN-E004",
            Self::OutcomeEpisodeMismatch | Self::OutcomeNotTerminal => "LRN-E005",
            Self::PolicySelfLabelsOutcome => "LRN-E006",
            Self::CreditAlreadyAssigned => "LRN-E007",
            Self::TargetNotFound(_) | Self::TargetAlreadyRevoked(_) => "LRN-E008",
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
            Self::PolicySelfLabelsOutcome => {
                formatter.write_str("evaluated policy cannot label its own outcome")
            }
            Self::CreditIdentityAlreadyExists(id) => {
                write!(formatter, "credit identity already exists: {id}")
            }
            Self::CreditAlreadyAssigned => formatter
                .write_str("credit already exists for this episode, outcome and target artifact"),
            Self::TargetNotFound(id) => write!(formatter, "revocation target not found: {id}"),
            Self::TargetAlreadyRevoked(id) => {
                write!(formatter, "revocation target is already revoked: {id}")
            }
            Self::RevocationOfRevocation => {
                formatter.write_str("revocation records cannot themselves be revoked")
            }
            Self::IdentityConflict(id) => write!(formatter, "record id reused with drift: {id}"),
            Self::SequenceOverflow => formatter.write_str("ledger sequence overflow"),
            Self::SnapshotHeadMismatch => formatter.write_str("snapshot head digest mismatch"),
            Self::SnapshotRecordMismatch(sequence) => {
                write!(formatter, "snapshot record mismatch at sequence {sequence}")
            }
            Self::InternalInvariant => formatter.write_str("ledger internal invariant failed"),
        }
    }
}

impl Error for LedgerError {}
