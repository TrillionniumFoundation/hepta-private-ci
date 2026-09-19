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
    OutcomeNotCurrent(String),
    PolicySelfLabelsOutcome,
    InvalidAuthenticatedPrincipal,
    OutcomeStateMismatch,
    InvalidWatermark,
    CreditIdentityAlreadyExists(String),
    CreditAlreadyAssigned,
    CreditBatchNotFinalized,
    CreditBatchEmpty,
    CreditBatchLimitExceeded,
    DuplicateCreditTarget(String),
    CreditConservation,
    CorrectionPredecessorRequired(String),
    CorrectionPredecessorNotFound(String),
    CorrectionEpisodeMismatch,
    CorrectionNotHead(String),
    CorrectionSelfReference,
    UnlearningSourceNotRevoked(String),
    UnlearningSourceDigestMismatch,
    UnlearningPredecessorRequired(String),
    UnlearningPredecessorNotFound(String),
    UnlearningPredecessorMismatch,
    UnlearningNotHead(String),
    UnlearningSelfReference,
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
            Self::OutcomeEpisodeMismatch | Self::OutcomeNotTerminal | Self::OutcomeNotCurrent(_) => "LRN-E005",
            Self::PolicySelfLabelsOutcome
            | Self::InvalidAuthenticatedPrincipal
            | Self::OutcomeStateMismatch
            | Self::InvalidWatermark => "LRN-E006",
            Self::CreditAlreadyAssigned
            | Self::CreditBatchNotFinalized
            | Self::CreditBatchEmpty
            | Self::CreditBatchLimitExceeded
            | Self::DuplicateCreditTarget(_)
            | Self::CreditConservation => "LRN-E007",
            Self::TargetNotFound(_) | Self::TargetAlreadyRevoked(_) => "LRN-E008",
            Self::RevocationOfRevocation => "LRN-E009",
            Self::CorrectionPredecessorRequired(_)
            | Self::CorrectionPredecessorNotFound(_)
            | Self::CorrectionEpisodeMismatch
            | Self::CorrectionNotHead(_)
            | Self::CorrectionSelfReference => "LRN-E013",
            Self::UnlearningSourceNotRevoked(_)
            | Self::UnlearningSourceDigestMismatch
            | Self::UnlearningPredecessorRequired(_)
            | Self::UnlearningPredecessorNotFound(_)
            | Self::UnlearningPredecessorMismatch
            | Self::UnlearningNotHead(_)
            | Self::UnlearningSelfReference => "LRN-E014",
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
            Self::OutcomeNotCurrent(id) => {
                write!(formatter, "credit assignment requires the current outcome head: {id}")
            }
            Self::PolicySelfLabelsOutcome => {
                formatter.write_str("evaluated policy cannot label its own outcome")
            }
            Self::InvalidAuthenticatedPrincipal => {
                formatter.write_str("authenticated principal metadata is structurally invalid")
            }
            Self::OutcomeStateMismatch => {
                formatter.write_str("authenticated outcome fields do not match terminality")
            }
            Self::InvalidWatermark => {
                formatter.write_str("authenticated outcome watermark is inconsistent")
            }
            Self::CreditIdentityAlreadyExists(id) => {
                write!(formatter, "credit identity already exists: {id}")
            }
            Self::CreditAlreadyAssigned => formatter
                .write_str("credit already exists for this episode, outcome and target artifact"),
            Self::CreditBatchNotFinalized => formatter.write_str("credit batch must be finalized"),
            Self::CreditBatchEmpty => formatter.write_str("credit batch must contain allocations"),
            Self::CreditBatchLimitExceeded => {
                formatter.write_str("credit batch exceeds 256 allocations")
            }
            Self::DuplicateCreditTarget(id) => write!(formatter, "duplicate credit target: {id}"),
            Self::CreditConservation => {
                formatter.write_str("credit allocations plus residual must equal terminal outcome")
            }
            Self::CorrectionPredecessorRequired(id) => {
                write!(formatter, "outcome correction predecessor required after head: {id}")
            }
            Self::CorrectionPredecessorNotFound(id) => {
                write!(formatter, "outcome correction predecessor not found: {id}")
            }
            Self::CorrectionEpisodeMismatch => {
                formatter.write_str("outcome correction predecessor belongs to another episode")
            }
            Self::CorrectionNotHead(id) => {
                write!(formatter, "outcome correction predecessor is not current head: {id}")
            }
            Self::CorrectionSelfReference => {
                formatter.write_str("outcome correction cannot reference itself")
            }
            Self::UnlearningSourceNotRevoked(id) => {
                write!(formatter, "unlearning source is not currently revoked: {id}")
            }
            Self::UnlearningSourceDigestMismatch => {
                formatter.write_str("unlearning source digest does not match the authoritative record")
            }
            Self::UnlearningPredecessorRequired(id) => {
                write!(formatter, "unlearning predecessor required after current head: {id}")
            }
            Self::UnlearningPredecessorNotFound(id) => {
                write!(formatter, "unlearning predecessor not found: {id}")
            }
            Self::UnlearningPredecessorMismatch => {
                formatter.write_str("unlearning predecessor targets another derived object")
            }
            Self::UnlearningNotHead(id) => {
                write!(formatter, "unlearning predecessor is not current head: {id}")
            }
            Self::UnlearningSelfReference => {
                formatter.write_str("unlearning lineage cannot reference itself")
            }
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
