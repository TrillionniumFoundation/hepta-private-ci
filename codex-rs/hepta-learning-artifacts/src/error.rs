use std::error::Error;
use std::fmt;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ArtifactRegistryError {
    RecordLimitExceeded,
    EmptyDigest(&'static str),
    ZeroEncodedSize,
    ArtifactTooLarge { actual: u64, maximum: u64 },
    IdentityConflict(String),
    ArtifactAlreadyExists(String),
    ArtifactNotFound(String),
    PredecessorNotFound(String),
    PredecessorUnavailable(String),
    GenerationNotAdvanced,
    ObjectiveLineageMismatch,
    ArtifactKindLineageMismatch,
    ProducerSelfEvaluates(String),
    StateAlreadyApplied(String),
    RevokedArtifactCannotTransition(String),
    SequenceOverflow,
    SnapshotHeadMismatch,
    SnapshotRecordMismatch(u64),
    InternalInvariant,
}

impl ArtifactRegistryError {
    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::RecordLimitExceeded
            | Self::EmptyDigest(_)
            | Self::ZeroEncodedSize
            | Self::ArtifactTooLarge { .. } => "ART-E001",
            Self::IdentityConflict(_) | Self::ArtifactAlreadyExists(_) => "ART-E002",
            Self::ArtifactNotFound(_)
            | Self::PredecessorNotFound(_)
            | Self::PredecessorUnavailable(_) => "ART-E003",
            Self::GenerationNotAdvanced
            | Self::ObjectiveLineageMismatch
            | Self::ArtifactKindLineageMismatch => "ART-E004",
            Self::ProducerSelfEvaluates(_)
            | Self::StateAlreadyApplied(_)
            | Self::RevokedArtifactCannotTransition(_) => "ART-E005",
            Self::SequenceOverflow => "ART-E006",
            Self::SnapshotHeadMismatch | Self::SnapshotRecordMismatch(_) => "ART-E007",
            Self::InternalInvariant => "ART-E008",
        }
    }
}

impl fmt::Display for ArtifactRegistryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::RecordLimitExceeded => {
                formatter.write_str("artifact registry record limit exceeded")
            }
            Self::EmptyDigest(kind) => write!(formatter, "{kind} digest must not be zero"),
            Self::ZeroEncodedSize => formatter.write_str("artifact encoded size must be non-zero"),
            Self::ArtifactTooLarge { actual, maximum } => {
                write!(
                    formatter,
                    "artifact has {actual} bytes; maximum is {maximum}"
                )
            }
            Self::IdentityConflict(id) => write!(formatter, "event id reused with drift: {id}"),
            Self::ArtifactAlreadyExists(id) => write!(formatter, "artifact already exists: {id}"),
            Self::ArtifactNotFound(id) => write!(formatter, "artifact not found: {id}"),
            Self::PredecessorNotFound(id) => write!(formatter, "predecessor not found: {id}"),
            Self::PredecessorUnavailable(id) => {
                write!(
                    formatter,
                    "predecessor is not eligible for derivation: {id}"
                )
            }
            Self::GenerationNotAdvanced => {
                formatter.write_str("artifact generation must advance beyond its predecessor")
            }
            Self::ObjectiveLineageMismatch => formatter.write_str(
                "artifact objective digest differs from the predecessor objective lineage",
            ),
            Self::ArtifactKindLineageMismatch => {
                formatter.write_str("artifact kind differs from its predecessor lineage")
            }
            Self::ProducerSelfEvaluates(id) => {
                write!(
                    formatter,
                    "artifact producer cannot evaluate its own state change: {id}"
                )
            }
            Self::StateAlreadyApplied(id) => {
                write!(formatter, "artifact state already applied: {id}")
            }
            Self::RevokedArtifactCannotTransition(id) => {
                write!(formatter, "revoked artifact cannot transition: {id}")
            }
            Self::SequenceOverflow => formatter.write_str("artifact record sequence overflow"),
            Self::SnapshotHeadMismatch => formatter.write_str("artifact snapshot head mismatch"),
            Self::SnapshotRecordMismatch(sequence) => {
                write!(
                    formatter,
                    "artifact snapshot mismatch at sequence {sequence}"
                )
            }
            Self::InternalInvariant => {
                formatter.write_str("artifact registry internal invariant failed")
            }
        }
    }
}

impl Error for ArtifactRegistryError {}
