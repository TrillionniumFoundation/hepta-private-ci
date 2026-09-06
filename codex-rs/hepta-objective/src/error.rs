use std::error::Error;
use std::fmt;

/// Stable objective compiler failures. Codes map to the V8.2 execution spec.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ObjectiveError {
    InvalidBound {
        kind: &'static str,
        maximum: usize,
        actual: usize,
    },
    DuplicateSemanticId(String),
    EmptyPrincipalScope,
    EmptyDigest(&'static str),
    InvalidSoftWeight(String),
    UntrustedAuthorityEscalation,
    UnsupportedConstraintLanguage,
    FeasibilityBudgetExhausted,
    Arithmetic,
}

impl ObjectiveError {
    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::InvalidBound { .. }
            | Self::DuplicateSemanticId(_)
            | Self::InvalidSoftWeight(_)
            | Self::Arithmetic => "OBJ-E001",
            Self::EmptyPrincipalScope => "OBJ-E003",
            Self::EmptyDigest(_) => "OBJ-E004",
            Self::UntrustedAuthorityEscalation => "OBJ-E009",
            Self::UnsupportedConstraintLanguage => "OBJ-E002",
            Self::FeasibilityBudgetExhausted => "OBJ-E007",
        }
    }
}

impl fmt::Display for ObjectiveError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidBound {
                kind,
                maximum,
                actual,
            } => write!(formatter, "{kind} count {actual} exceeds maximum {maximum}"),
            Self::DuplicateSemanticId(id) => write!(formatter, "duplicate semantic id: {id}"),
            Self::EmptyPrincipalScope => formatter.write_str("principal scope must not be empty"),
            Self::EmptyDigest(kind) => write!(formatter, "{kind} digest must not be zero"),
            Self::InvalidSoftWeight(dimension) => write!(
                formatter,
                "soft preference weight must be in [0, 1] for dimension {dimension}"
            ),
            Self::UntrustedAuthorityEscalation => formatter.write_str(
                "untrusted evidence cannot create privileged constraints or legal actions",
            ),
            Self::Arithmetic => formatter.write_str("objective fixed-point arithmetic failed"),
            Self::UnsupportedConstraintLanguage => {
                formatter.write_str("objective constraint language is unsupported")
            }
            Self::FeasibilityBudgetExhausted => formatter.write_str(
                "objective feasibility budget exhausted; original constraints remain unchanged",
            ),
        }
    }
}

impl Error for ObjectiveError {}
