use std::error::Error;
use std::fmt;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduError {
    EmptyContributions,
    ContributionLimitExceeded,
    CandidateLimitExceeded,
    DimensionLimitExceeded,
    PreferenceDimensionLimitExceeded,
    RequiredOrganLimitExceeded,
    EmptyObjectiveDigest,
    EmptyProfileDigest(&'static str),
    EmptyProtocolDigest(&'static str),
    ProtocolContextMismatch,
    EmptySupportDigest { candidate: String, organ: String },
    MixedObjective,
    MixedGeneration,
    DuplicateOrganContribution { candidate: String, organ: String },
    MissingRequiredOrgan { candidate: String, organ: String },
    MissingAxis { candidate: String, axis: String },
    UnknownAxis(String),
    DuplicateAxis(String),
    NegativeCeiling(String),
    MissingAggregationRule(String),
    DuplicateAggregationRule(String),
    AggregationAxisMismatch(String),
    AggregationConflict(String),
    NegativeTolerance(String),
    MissingAbstainCandidate,
    AbstainInfeasible,
    IncompleteScalarization,
    InvalidWeight(String),
    InvalidEta,
    PreferenceValueOutOfRange(String),
    DimensionMismatch,
    StateDigestMismatch,
    InvalidHierarchyParent { subject: String },
    ConflictingHierarchyArtifact { subject: String },
    SimultaneousHierarchyUpdate(u64),
    Arithmetic,
}

impl NduError {
    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::EmptyContributions
            | Self::ContributionLimitExceeded
            | Self::CandidateLimitExceeded
            | Self::DimensionLimitExceeded
            | Self::PreferenceDimensionLimitExceeded
            | Self::RequiredOrganLimitExceeded => "NDU-E001",
            Self::EmptyObjectiveDigest
            | Self::EmptyProfileDigest(_)
            | Self::EmptyProtocolDigest(_)
            | Self::ProtocolContextMismatch
            | Self::EmptySupportDigest { .. }
            | Self::MixedObjective
            | Self::MixedGeneration => "NDU-E002",
            Self::DuplicateOrganContribution { .. } | Self::MissingRequiredOrgan { .. } => {
                "NDU-E003"
            }
            Self::MissingAxis { .. }
            | Self::UnknownAxis(_)
            | Self::DuplicateAxis(_)
            | Self::NegativeCeiling(_)
            | Self::MissingAggregationRule(_)
            | Self::DuplicateAggregationRule(_)
            | Self::AggregationAxisMismatch(_)
            | Self::AggregationConflict(_)
            | Self::NegativeTolerance(_) => "NDU-E004",
            Self::AbstainInfeasible => "NDU-E005",
            Self::MissingAbstainCandidate => "NDU-E006",
            Self::IncompleteScalarization | Self::InvalidWeight(_) => "NDU-E007",
            Self::InvalidEta
            | Self::PreferenceValueOutOfRange(_)
            | Self::DimensionMismatch
            | Self::StateDigestMismatch => "NDU-E008",
            Self::InvalidHierarchyParent { .. }
            | Self::ConflictingHierarchyArtifact { .. }
            | Self::SimultaneousHierarchyUpdate(_) => "NDU-E009",
            Self::Arithmetic => "NDU-E010",
        }
    }
}

impl fmt::Display for NduError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::EmptyContributions => formatter.write_str("utility contribution set is empty"),
            Self::ContributionLimitExceeded => {
                formatter.write_str("utility contribution set exceeds 4096 records")
            }
            Self::CandidateLimitExceeded => formatter.write_str("candidate limit exceeds 128"),
            Self::DimensionLimitExceeded => formatter.write_str("dimension limit exceeded"),
            Self::PreferenceDimensionLimitExceeded => {
                formatter.write_str("preference dimension must be in the closed interval [1, 64]")
            }
            Self::RequiredOrganLimitExceeded => {
                formatter.write_str("required organ set exceeds 32 entries")
            }
            Self::EmptyObjectiveDigest => formatter.write_str("objective digest must not be zero"),
            Self::EmptyProfileDigest(field) => {
                write!(formatter, "profile digest must not be zero: {field}")
            }
            Self::EmptyProtocolDigest(field) => {
                write!(formatter, "protocol digest must not be zero: {field}")
            }
            Self::ProtocolContextMismatch => {
                formatter.write_str("solver receipt context does not match publication context")
            }
            Self::EmptySupportDigest { candidate, organ } => write!(
                formatter,
                "candidate {candidate} contribution from organ {organ} has an empty support digest"
            ),
            Self::MixedObjective => formatter.write_str("contributions bind different objectives"),
            Self::MixedGeneration => {
                formatter.write_str("contributions bind different generations")
            }
            Self::DuplicateOrganContribution { candidate, organ } => write!(
                formatter,
                "candidate {candidate} has duplicate contribution from organ {organ}"
            ),
            Self::MissingRequiredOrgan { candidate, organ } => write!(
                formatter,
                "candidate {candidate} is missing required organ {organ}"
            ),
            Self::MissingAxis { candidate, axis } => {
                write!(formatter, "candidate {candidate} is missing axis {axis}")
            }
            Self::UnknownAxis(axis) => write!(formatter, "unknown utility axis: {axis}"),
            Self::DuplicateAxis(axis) => write!(formatter, "duplicate utility axis: {axis}"),
            Self::NegativeCeiling(axis) => {
                write!(formatter, "ceiling must be non-negative: {axis}")
            }
            Self::MissingAggregationRule(axis) => {
                write!(formatter, "missing aggregation rule for axis {axis}")
            }
            Self::DuplicateAggregationRule(axis) => {
                write!(formatter, "duplicate aggregation rule for axis {axis}")
            }
            Self::AggregationAxisMismatch(axis) => {
                write!(
                    formatter,
                    "aggregation policy contains unexpected axis {axis}"
                )
            }
            Self::AggregationConflict(axis) => write!(
                formatter,
                "require-equal aggregation received conflicting values for axis {axis}"
            ),
            Self::NegativeTolerance(axis) => {
                write!(
                    formatter,
                    "Pareto tolerance must be non-negative for axis {axis}"
                )
            }
            Self::MissingAbstainCandidate => {
                formatter.write_str("every legal candidate set must contain abstain")
            }
            Self::AbstainInfeasible => formatter.write_str(
                "explicit abstain must remain feasible after hard, risk and resource filtering",
            ),
            Self::IncompleteScalarization => {
                formatter.write_str("scalarization profile is incomplete")
            }
            Self::InvalidWeight(axis) => write!(formatter, "invalid scalarization weight: {axis}"),
            Self::InvalidEta => {
                formatter.write_str("eta must be in the closed interval [1/16, 1/4]")
            }
            Self::PreferenceValueOutOfRange(axis) => {
                write!(formatter, "preference value must be in [-1, 1]: {axis}")
            }
            Self::DimensionMismatch => formatter.write_str("preference dimensions do not match"),
            Self::StateDigestMismatch => formatter.write_str("preference state digest mismatch"),
            Self::InvalidHierarchyParent { subject } => {
                write!(formatter, "invalid direct parent binding for hierarchy subject {subject}")
            }
            Self::ConflictingHierarchyArtifact { subject } => write!(
                formatter,
                "hierarchy subject {subject} selects conflicting artifacts in one generation"
            ),
            Self::SimultaneousHierarchyUpdate(generation) => write!(
                formatter,
                "a direct parent and child update in generation {generation}"
            ),
            Self::Arithmetic => formatter.write_str("deterministic Q32 arithmetic failed"),
        }
    }
}

impl Error for NduError {}
