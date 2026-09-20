//! Profile-bound admission from the readiness source grammar to the native
//! deterministic objective compiler.
//!
//! The source envelope carries supplied labels and digests. It is not trusted by
//! itself. Admission therefore requires a frozen profile, an independently
//! authenticated source context and exact digest/time/unit mappings. Unknown or
//! unrepresentable semantics fail closed instead of being guessed or dropped.

use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::ActionClass;
use crate::ConfirmationPolicy;
use crate::Constraint;
use crate::ConstraintClass;
use crate::ConstraintRelation;
use crate::ObjectiveCompileReceipt;
use crate::ObjectiveConflictReceipt;
use crate::ObjectiveError;
use crate::ObjectiveEvidenceRequirementV1;
use crate::ObjectivePredicateComparatorV1;
use crate::ObjectiveResourcesV1;
use crate::ObjectiveRiskClassV1;
use crate::ObjectiveRollbackClassV1;
use crate::ObjectiveSoftDirectionV1;
use crate::ObjectiveSourceConstraintV1;
use crate::ObjectiveSourceEnvelope;
use crate::ObjectiveSourceEnvelopeV1;
use crate::ObjectiveSourcePredicateV1;
use crate::ObjectiveSourceTrustV1;
use crate::ObjectiveStructureError;
use crate::PredicateTerminality;
use crate::SoftDirection;
use crate::SoftPreference;
use crate::SourceTrust;
use crate::SuccessPredicate;

const MAX_PROFILE_LOCALES: usize = 16;
const MAX_PROFILE_SOURCES: usize = 32;
const MAX_SOURCE_TEXT_BYTES: usize = 128;
const MICROS_PER_SECOND: u64 = 1_000_000;
const Q32_ONE_RAW: i128 = 1_i128 << 32;
const MAX_PROFILE_CONSTRAINTS: usize = 256;
const MAX_PROFILE_PREDICATES: usize = 128;
const MAX_PROFILE_ACTIONS: usize = 128;
const MAX_PROFILE_SOFT_DIMENSIONS: usize = 64;
const MAX_PROFILE_EVIDENCE_REQUIREMENTS: usize = 128;
const MAX_PROFILE_ABSTENTION_RULES: usize = 64;
const MAX_PROFILE_ENCODED_BYTES: usize = 256 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveConstraintProfileV1 {
    pub source_constraint_id: String,
    pub expected_unit: String,
    pub class: ConstraintClass,
    pub axis: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectivePredicateProfileV1 {
    pub source_predicate_id: String,
    pub expected_unit: String,
    pub axis: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveActionProfileV1 {
    pub source_action_class: String,
    pub action_id: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveSoftDimensionProfileV1 {
    pub source_dimension_id: String,
    pub expected_unit: String,
    pub expected_direction: ObjectiveSoftDirectionV1,
    pub dimension: StableId,
    pub baseline_weight: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveEvidenceProfileV1 {
    pub source_requirement_id: String,
    pub axis: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveResourceAxisProfileV1 {
    pub constraint_id: StableId,
    pub axis: StableId,
    pub class: ConstraintClass,
    /// Native Q32 units produced for one source integer unit.
    pub q32_per_source_unit: FixedQ32,
    pub evidence_source: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveResourceProfileV1 {
    pub time_micros: ObjectiveResourceAxisProfileV1,
    pub token_count: ObjectiveResourceAxisProfileV1,
    pub compute_micros: ObjectiveResourceAxisProfileV1,
    pub memory_bytes: ObjectiveResourceAxisProfileV1,
    pub network_bytes: ObjectiveResourceAxisProfileV1,
    pub external_effect_count: ObjectiveResourceAxisProfileV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveAbstentionRuleProfileV1 {
    pub source_rule: String,
    pub value: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveRiskProfileV1 {
    pub evidence_source: StableId,
    pub class: ConstraintClass,
    pub risk_constraint_id: StableId,
    pub risk_axis: StableId,
    pub low_value: FixedQ32,
    pub medium_value: FixedQ32,
    pub high_value: FixedQ32,
    pub critical_value: FixedQ32,
    pub rollback_constraint_id: StableId,
    pub rollback_axis: StableId,
    pub rollback_none_value: FixedQ32,
    pub rollback_reversible_value: FixedQ32,
    pub rollback_compensatable_value: FixedQ32,
    pub rollback_irreversible_value: FixedQ32,
    pub compensation_constraint_id: StableId,
    pub compensation_axis: StableId,
    pub compensation_false_value: FixedQ32,
    pub compensation_true_value: FixedQ32,
    pub abstention_constraint_id: StableId,
    pub abstention_axis: StableId,
    pub abstention_rules: Vec<ObjectiveAbstentionRuleProfileV1>,
}

/// Frozen, caller-selected admission semantics.
///
/// A profile is not authority. The caller must independently authenticate the
/// source and bind the exact computed profile digest into the run snapshot.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveAdmissionProfileV1 {
    pub profile_id: StableId,
    pub profile_revision: Revision,
    pub expected_input_schema_digest: Digest32,
    pub expected_normalization_profile_digest: Digest32,
    pub principal_scope_digest: Digest32,
    pub principal_scope: StableId,
    pub allowed_locales: Vec<String>,
    pub maximum_source_age_micros: u64,
    pub maximum_future_skew_micros: u64,
    pub deadline_required: bool,
    pub allowed_trusted_source_identities: Vec<StableId>,
    pub constraints: Vec<ObjectiveConstraintProfileV1>,
    pub predicates: Vec<ObjectivePredicateProfileV1>,
    pub actions: Vec<ObjectiveActionProfileV1>,
    pub soft_dimensions: Vec<ObjectiveSoftDimensionProfileV1>,
    pub evidence_requirements: Vec<ObjectiveEvidenceProfileV1>,
    pub resources: ObjectiveResourceProfileV1,
    pub risk: ObjectiveRiskProfileV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ObjectiveSourceAuthenticationV1 {
    Principal {
        principal_scope_digest: Digest32,
        source_digest: Digest32,
    },
    TrustedSystem {
        source_identity: StableId,
        source_digest: Digest32,
    },
    AuthorizedAdapter {
        source_identity: StableId,
        source_digest: Digest32,
    },
    UntrustedEvidence {
        source_digest: Digest32,
    },
}

impl ObjectiveSourceAuthenticationV1 {
    fn source_digest(&self) -> Digest32 {
        match self {
            Self::Principal { source_digest, .. }
            | Self::TrustedSystem { source_digest, .. }
            | Self::AuthorizedAdapter { source_digest, .. }
            | Self::UntrustedEvidence { source_digest } => *source_digest,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveAdmissionContextV1 {
    pub revision: Revision,
    pub now_unix_micros: u64,
    pub selected_profile_digest: Digest32,
    pub source_authentication: ObjectiveSourceAuthenticationV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveAdmissionReceiptV1 {
    pub profile_id: StableId,
    pub profile_revision: Revision,
    pub profile_digest: Digest32,
    pub supplied_source_digest: Digest32,
    pub intent_digest: Digest32,
    pub admitted_source_digest: Digest32,
    pub observed_at_unix_micros: u64,
    pub deadline_unix_micros: Option<u64>,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveAdmissionOutcomeV1 {
    pub receipt: ObjectiveAdmissionReceiptV1,
    pub compile_result: Result<ObjectiveCompileReceipt, ObjectiveConflictReceipt>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ObjectiveAdmissionError {
    Structure(ObjectiveStructureError),
    InvalidProfile(&'static str),
    ProfileDigestMismatch,
    InputSchemaMismatch,
    NormalizationProfileMismatch,
    PrincipalScopeMismatch,
    SourceTrustMismatch,
    SourceAuthenticationMismatch,
    SourceDigestMismatch,
    IntentDigestMismatch,
    LocaleNotAllowed,
    InvalidTimestamp(&'static str),
    SourceFromFuture,
    SourceStale,
    DeadlineMissing,
    DeadlineBeforeObservation,
    DeadlineExpired,
    InvalidIdentifier(&'static str),
    UnknownConstraint,
    ConstraintUnitMismatch,
    TerminalConstraintUnsupported,
    UnknownPredicate,
    PredicateUnitMismatch,
    InvalidTerminality,
    UnsupportedComparator,
    UnknownAction,
    ConfirmationActionNotLegal,
    UnknownSoftDimension,
    SoftDimensionMismatch,
    UnknownEvidenceRequirement,
    ResourceOverflow(&'static str),
    Compiler(ObjectiveError),
}

impl ObjectiveAdmissionError {
    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::Structure(_)
            | Self::InvalidProfile(_)
            | Self::InvalidTimestamp(_)
            | Self::InvalidIdentifier(_)
            | Self::ResourceOverflow(_) => "OBJ-E001",
            Self::UnknownConstraint
            | Self::TerminalConstraintUnsupported
            | Self::UnknownPredicate
            | Self::UnsupportedComparator
            | Self::UnknownAction
            | Self::ConfirmationActionNotLegal
            | Self::UnknownSoftDimension
            | Self::UnknownEvidenceRequirement => "OBJ-E002",
            Self::PrincipalScopeMismatch
            | Self::SourceTrustMismatch
            | Self::SourceAuthenticationMismatch => "OBJ-E003",
            Self::ProfileDigestMismatch
            | Self::InputSchemaMismatch
            | Self::NormalizationProfileMismatch
            | Self::SourceDigestMismatch
            | Self::IntentDigestMismatch => "OBJ-E004",
            Self::ConstraintUnitMismatch
            | Self::PredicateUnitMismatch
            | Self::SoftDimensionMismatch => "OBJ-E005",
            Self::LocaleNotAllowed
            | Self::SourceFromFuture
            | Self::SourceStale
            | Self::DeadlineMissing
            | Self::DeadlineBeforeObservation
            | Self::DeadlineExpired => "OBJ-E007",
            Self::InvalidTerminality => "OBJ-E008",
            Self::Compiler(error) => error.code(),
        }
    }
}

impl fmt::Display for ObjectiveAdmissionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Structure(error) => error.fmt(formatter),
            Self::InvalidProfile(field) => write!(formatter, "invalid admission profile: {field}"),
            Self::ProfileDigestMismatch => {
                formatter.write_str("selected admission profile digest mismatch")
            }
            Self::InputSchemaMismatch => {
                formatter.write_str("objective input schema digest mismatch")
            }
            Self::NormalizationProfileMismatch => {
                formatter.write_str("objective normalization profile digest mismatch")
            }
            Self::PrincipalScopeMismatch => {
                formatter.write_str("objective principal scope mismatch")
            }
            Self::SourceTrustMismatch => {
                formatter.write_str("objective source trust class mismatch")
            }
            Self::SourceAuthenticationMismatch => {
                formatter.write_str("objective source authentication mismatch")
            }
            Self::SourceDigestMismatch => formatter.write_str("objective source digest mismatch"),
            Self::IntentDigestMismatch => formatter.write_str("objective intent digest mismatch"),
            Self::LocaleNotAllowed => formatter.write_str("objective locale is not registered"),
            Self::InvalidTimestamp(field) => write!(formatter, "invalid UTC timestamp: {field}"),
            Self::SourceFromFuture => {
                formatter.write_str("objective observation is from the future")
            }
            Self::SourceStale => formatter.write_str("objective observation is stale"),
            Self::DeadlineMissing => formatter.write_str("objective deadline is required"),
            Self::DeadlineBeforeObservation => {
                formatter.write_str("objective deadline precedes observation")
            }
            Self::DeadlineExpired => formatter.write_str("objective deadline has expired"),
            Self::InvalidIdentifier(field) => {
                write!(formatter, "invalid objective identifier: {field}")
            }
            Self::UnknownConstraint => {
                formatter.write_str("objective constraint is not registered")
            }
            Self::ConstraintUnitMismatch => {
                formatter.write_str("objective constraint unit mismatch")
            }
            Self::TerminalConstraintUnsupported => {
                formatter.write_str("terminal hard constraint is not representable")
            }
            Self::UnknownPredicate => formatter.write_str("objective predicate is not registered"),
            Self::PredicateUnitMismatch => formatter.write_str("objective predicate unit mismatch"),
            Self::InvalidTerminality => {
                formatter.write_str("objective predicate terminality mismatch")
            }
            Self::UnsupportedComparator => {
                formatter.write_str("objective comparator is unsupported")
            }
            Self::UnknownAction => formatter.write_str("objective action class is not registered"),
            Self::ConfirmationActionNotLegal => {
                formatter.write_str("confirmation action is not in the legal action set")
            }
            Self::UnknownSoftDimension => {
                formatter.write_str("objective soft dimension is not registered")
            }
            Self::SoftDimensionMismatch => {
                formatter.write_str("objective soft dimension profile mismatch")
            }
            Self::UnknownEvidenceRequirement => {
                formatter.write_str("objective evidence requirement is not registered")
            }
            Self::ResourceOverflow(field) => {
                write!(formatter, "objective resource conversion overflow: {field}")
            }
            Self::Compiler(error) => error.fmt(formatter),
        }
    }
}

impl Error for ObjectiveAdmissionError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Structure(error) => Some(error),
            Self::Compiler(error) => Some(error),
            _ => None,
        }
    }
}

impl From<ObjectiveStructureError> for ObjectiveAdmissionError {
    fn from(value: ObjectiveStructureError) -> Self {
        Self::Structure(value)
    }
}

impl From<ObjectiveError> for ObjectiveAdmissionError {
    fn from(value: ObjectiveError) -> Self {
        Self::Compiler(value)
    }
}

impl ObjectiveAdmissionProfileV1 {
    pub fn digest(&self) -> Result<Digest32, ObjectiveAdmissionError> {
        validate_profile(self)?;
        Ok(profile_digest_unchecked(self))
    }
}

/// Canonical digest of the complete structured intent. Arrays are sorted by
/// semantic identity, so JSON member order and source array order cannot alter
/// the admitted meaning.
pub fn canonical_objective_intent_digest_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
) -> Result<Digest32, ObjectiveAdmissionError> {
    envelope.validate_structure()?;
    Ok(intent_digest_unchecked(envelope))
}

/// Admit a complete source envelope and invoke the existing deterministic
/// compiler without dropping any represented source field.
pub fn admit_and_compile_objective_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
) -> Result<ObjectiveAdmissionOutcomeV1, ObjectiveAdmissionError> {
    envelope.validate_structure()?;
    let profile_digest = profile.digest()?;
    if context.selected_profile_digest != profile_digest {
        return Err(ObjectiveAdmissionError::ProfileDigestMismatch);
    }
    if envelope.input_schema_digest != profile.expected_input_schema_digest {
        return Err(ObjectiveAdmissionError::InputSchemaMismatch);
    }
    if envelope
        .structured_intent
        .provenance
        .normalization_profile_digest
        != profile.expected_normalization_profile_digest
    {
        return Err(ObjectiveAdmissionError::NormalizationProfileMismatch);
    }
    if envelope.principal_scope_digest != profile.principal_scope_digest {
        return Err(ObjectiveAdmissionError::PrincipalScopeMismatch);
    }
    if !profile
        .allowed_locales
        .iter()
        .any(|locale| locale == &envelope.locale)
    {
        return Err(ObjectiveAdmissionError::LocaleNotAllowed);
    }

    validate_authentication(envelope, profile, &context.source_authentication)?;
    let supplied_source_digest = envelope.structured_intent.provenance.source_digest;
    if supplied_source_digest.is_zero()
        || supplied_source_digest != context.source_authentication.source_digest()
    {
        return Err(ObjectiveAdmissionError::SourceDigestMismatch);
    }
    let intent_digest = intent_digest_unchecked(envelope);
    if envelope.intent_digest.is_zero() || envelope.intent_digest != intent_digest {
        return Err(ObjectiveAdmissionError::IntentDigestMismatch);
    }

    let observed_at_unix_micros = parse_utc_micros(&envelope.observed_at)
        .ok_or(ObjectiveAdmissionError::InvalidTimestamp("observedAt"))?;
    let latest_allowed = context
        .now_unix_micros
        .checked_add(profile.maximum_future_skew_micros)
        .ok_or(ObjectiveAdmissionError::InvalidTimestamp("now"))?;
    if observed_at_unix_micros > latest_allowed {
        return Err(ObjectiveAdmissionError::SourceFromFuture);
    }
    if context
        .now_unix_micros
        .saturating_sub(observed_at_unix_micros)
        > profile.maximum_source_age_micros
    {
        return Err(ObjectiveAdmissionError::SourceStale);
    }
    let deadline_unix_micros = match &envelope.deadline {
        Some(deadline) => Some(
            parse_utc_micros(deadline)
                .ok_or(ObjectiveAdmissionError::InvalidTimestamp("deadline"))?,
        ),
        None if profile.deadline_required => return Err(ObjectiveAdmissionError::DeadlineMissing),
        None => None,
    };
    if let Some(deadline) = deadline_unix_micros {
        if deadline < observed_at_unix_micros {
            return Err(ObjectiveAdmissionError::DeadlineBeforeObservation);
        }
        if deadline < context.now_unix_micros {
            return Err(ObjectiveAdmissionError::DeadlineExpired);
        }
    }

    let admitted_source_digest =
        admitted_source_digest(envelope, profile_digest, &context.source_authentication);
    let source = adapt_source(envelope, profile, context, admitted_source_digest)?;
    let compile_result = crate::compile(source)?;
    Ok(ObjectiveAdmissionOutcomeV1 {
        receipt: ObjectiveAdmissionReceiptV1 {
            profile_id: profile.profile_id.clone(),
            profile_revision: profile.profile_revision,
            profile_digest,
            supplied_source_digest,
            intent_digest,
            admitted_source_digest,
            observed_at_unix_micros,
            deadline_unix_micros,
            authority: AuthorityPosture::DENY_ALL,
        },
        compile_result,
    })
}

fn validate_authentication(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    authentication: &ObjectiveSourceAuthenticationV1,
) -> Result<(), ObjectiveAdmissionError> {
    let trusted_identity_allowed = |identity: &StableId| {
        profile
            .allowed_trusted_source_identities
            .iter()
            .any(|allowed| allowed == identity)
    };
    match (&envelope.source_trust_class, authentication) {
        (
            ObjectiveSourceTrustV1::Principal,
            ObjectiveSourceAuthenticationV1::Principal {
                principal_scope_digest,
                ..
            },
        ) if principal_scope_digest == &envelope.principal_scope_digest => Ok(()),
        (
            ObjectiveSourceTrustV1::TrustedSystem,
            ObjectiveSourceAuthenticationV1::TrustedSystem {
                source_identity, ..
            },
        ) if trusted_identity_allowed(source_identity) => Ok(()),
        (
            ObjectiveSourceTrustV1::AuthorizedAdapter,
            ObjectiveSourceAuthenticationV1::AuthorizedAdapter {
                source_identity, ..
            },
        ) if trusted_identity_allowed(source_identity) => Ok(()),
        (
            ObjectiveSourceTrustV1::UntrustedEvidence,
            ObjectiveSourceAuthenticationV1::UntrustedEvidence { .. },
        ) => Ok(()),
        (ObjectiveSourceTrustV1::Principal, _)
        | (ObjectiveSourceTrustV1::TrustedSystem, _)
        | (ObjectiveSourceTrustV1::AuthorizedAdapter, _)
        | (ObjectiveSourceTrustV1::UntrustedEvidence, _) => {
            Err(ObjectiveAdmissionError::SourceAuthenticationMismatch)
        }
    }
}

fn adapt_source(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
    admitted_source_digest: Digest32,
) -> Result<ObjectiveSourceEnvelope, ObjectiveAdmissionError> {
    let request_id = stable_id(&envelope.request_id, "requestId")?;
    let mut constraints = Vec::new();
    for source in &envelope.structured_intent.constraints {
        constraints.push(adapt_constraint(source, profile)?);
    }
    append_resources(
        &mut constraints,
        &envelope.structured_intent.resources,
        &profile.resources,
    )?;
    append_risk(
        &mut constraints,
        &envelope.structured_intent.risk,
        &profile.risk,
    )?;

    let mut success_predicates = Vec::new();
    for source in &envelope.structured_intent.success_predicates {
        success_predicates.push(adapt_predicate(
            source, profile, /*must_be_terminal*/ false,
        )?);
    }
    for source in &envelope.structured_intent.terminal_conditions {
        success_predicates.push(adapt_predicate(
            source, profile, /*must_be_terminal*/ true,
        )?);
    }
    for source in &envelope.structured_intent.evidence_requirements {
        success_predicates.push(adapt_evidence_requirement(source, profile)?);
    }

    let confirmation = envelope
        .structured_intent
        .confirmation_action_classes
        .iter()
        .collect::<BTreeSet<_>>();
    let legal = envelope
        .structured_intent
        .legal_action_classes
        .iter()
        .collect::<BTreeSet<_>>();
    if confirmation.iter().any(|action| !legal.contains(action)) {
        return Err(ObjectiveAdmissionError::ConfirmationActionNotLegal);
    }
    let mut allowed_actions = Vec::new();
    for source in &envelope.structured_intent.legal_action_classes {
        let mapping = action_mapping(profile, source)?;
        allowed_actions.push(ActionClass {
            id: mapping.action_id.clone(),
            confirmation: if confirmation.contains(source) {
                ConfirmationPolicy::Required
            } else {
                ConfirmationPolicy::NotRequired
            },
        });
    }
    let mut forbidden_actions = Vec::new();
    for source in &envelope.structured_intent.forbidden_action_classes {
        forbidden_actions.push(action_mapping(profile, source)?.action_id.clone());
    }

    let mut soft_preferences = Vec::new();
    for source in &envelope.structured_intent.soft_dimensions {
        let mapping = profile
            .soft_dimensions
            .iter()
            .find(|mapping| mapping.source_dimension_id == source.dimension_id)
            .ok_or(ObjectiveAdmissionError::UnknownSoftDimension)?;
        if mapping.expected_unit != source.unit
            || mapping.expected_direction != source.direction
            || mapping.baseline_weight < FixedQ32::ZERO
            || mapping.baseline_weight > FixedQ32::ONE
            || mapping.baseline_weight.raw() < source.minimum_weight_q32
            || mapping.baseline_weight.raw() > source.maximum_weight_q32
        {
            return Err(ObjectiveAdmissionError::SoftDimensionMismatch);
        }
        soft_preferences.push(SoftPreference {
            dimension: mapping.dimension.clone(),
            direction: match source.direction {
                ObjectiveSoftDirectionV1::Maximize => SoftDirection::Maximize,
                ObjectiveSoftDirectionV1::Minimize => SoftDirection::Minimize,
            },
            weight: mapping.baseline_weight,
        });
    }

    Ok(ObjectiveSourceEnvelope {
        request_id,
        principal_scope: profile.principal_scope.clone(),
        revision: context.revision,
        source_trust: match envelope.source_trust_class {
            ObjectiveSourceTrustV1::Principal => SourceTrust::PrincipalStructured,
            ObjectiveSourceTrustV1::TrustedSystem | ObjectiveSourceTrustV1::AuthorizedAdapter => {
                SourceTrust::RegisteredAdapter
            }
            ObjectiveSourceTrustV1::UntrustedEvidence => SourceTrust::UntrustedEvidence,
        },
        source_digest: admitted_source_digest,
        schema_digest: envelope.input_schema_digest,
        constraints,
        success_predicates,
        allowed_actions,
        forbidden_actions,
        soft_preferences,
    })
}

fn adapt_constraint(
    source: &ObjectiveSourceConstraintV1,
    profile: &ObjectiveAdmissionProfileV1,
) -> Result<Constraint, ObjectiveAdmissionError> {
    if source.terminal {
        return Err(ObjectiveAdmissionError::TerminalConstraintUnsupported);
    }
    let mapping = profile
        .constraints
        .iter()
        .find(|mapping| mapping.source_constraint_id == source.constraint_id)
        .ok_or(ObjectiveAdmissionError::UnknownConstraint)?;
    if mapping.expected_unit != source.unit {
        return Err(ObjectiveAdmissionError::ConstraintUnitMismatch);
    }
    Ok(Constraint {
        id: stable_id(&source.constraint_id, "constraintId")?,
        class: mapping.class,
        axis: mapping.axis.clone(),
        relation: constraint_relation(source.comparator)?,
        bound: FixedQ32::from_raw(source.bound_q32),
        evidence_source: stable_id(&source.evidence_source_id, "constraint.evidenceSourceId")?,
    })
}

fn adapt_predicate(
    source: &ObjectiveSourcePredicateV1,
    profile: &ObjectiveAdmissionProfileV1,
    must_be_terminal: bool,
) -> Result<SuccessPredicate, ObjectiveAdmissionError> {
    if must_be_terminal != source.terminal {
        return Err(ObjectiveAdmissionError::InvalidTerminality);
    }
    let mapping = profile
        .predicates
        .iter()
        .find(|mapping| mapping.source_predicate_id == source.predicate_id)
        .ok_or(ObjectiveAdmissionError::UnknownPredicate)?;
    if mapping.expected_unit != source.unit {
        return Err(ObjectiveAdmissionError::PredicateUnitMismatch);
    }
    Ok(SuccessPredicate {
        id: stable_id(&source.predicate_id, "predicateId")?,
        axis: mapping.axis.clone(),
        relation: predicate_relation(source.comparator)?,
        bound: FixedQ32::from_raw(source.bound_q32),
        evidence_source: stable_id(&source.evidence_source_id, "predicate.evidenceSourceId")?,
        terminality: if source.terminal {
            PredicateTerminality::Terminal
        } else {
            PredicateTerminality::Intermediate
        },
    })
}

fn adapt_evidence_requirement(
    source: &ObjectiveEvidenceRequirementV1,
    profile: &ObjectiveAdmissionProfileV1,
) -> Result<SuccessPredicate, ObjectiveAdmissionError> {
    let mapping = profile
        .evidence_requirements
        .iter()
        .find(|mapping| mapping.source_requirement_id == source.requirement_id)
        .ok_or(ObjectiveAdmissionError::UnknownEvidenceRequirement)?;
    if source.minimum_confidence_ppm > 1_000_000 {
        return Err(ObjectiveAdmissionError::ResourceOverflow(
            "minimumConfidencePpm",
        ));
    }
    let raw = (i128::from(source.minimum_confidence_ppm) * Q32_ONE_RAW) / 1_000_000_i128;
    Ok(SuccessPredicate {
        id: stable_id(&source.requirement_id, "requirementId")?,
        axis: mapping.axis.clone(),
        relation: ConstraintRelation::AtLeast,
        bound: FixedQ32::from_raw(
            i64::try_from(raw)
                .map_err(|_| ObjectiveAdmissionError::ResourceOverflow("minimumConfidencePpm"))?,
        ),
        evidence_source: stable_id(&source.evidence_source_id, "requirement.evidenceSourceId")?,
        terminality: if source.terminal {
            PredicateTerminality::Terminal
        } else {
            PredicateTerminality::Intermediate
        },
    })
}

fn append_resources(
    output: &mut Vec<Constraint>,
    source: &ObjectiveResourcesV1,
    profile: &ObjectiveResourceProfileV1,
) -> Result<(), ObjectiveAdmissionError> {
    for (field, value, mapping) in [
        ("timeMicros", source.time_micros, &profile.time_micros),
        ("tokenCount", source.token_count, &profile.token_count),
        (
            "computeMicros",
            source.compute_micros,
            &profile.compute_micros,
        ),
        ("memoryBytes", source.memory_bytes, &profile.memory_bytes),
        ("networkBytes", source.network_bytes, &profile.network_bytes),
        (
            "externalEffectCount",
            u64::from(source.external_effect_count),
            &profile.external_effect_count,
        ),
    ] {
        output.push(Constraint {
            id: mapping.constraint_id.clone(),
            class: mapping.class,
            axis: mapping.axis.clone(),
            relation: ConstraintRelation::AtMost,
            bound: scaled_resource(value, mapping.q32_per_source_unit, field)?,
            evidence_source: mapping.evidence_source.clone(),
        });
    }
    Ok(())
}

fn append_risk(
    output: &mut Vec<Constraint>,
    source: &crate::ObjectiveRiskV1,
    profile: &ObjectiveRiskProfileV1,
) -> Result<(), ObjectiveAdmissionError> {
    let risk_value = match source.risk_class {
        ObjectiveRiskClassV1::Low => profile.low_value,
        ObjectiveRiskClassV1::Medium => profile.medium_value,
        ObjectiveRiskClassV1::High => profile.high_value,
        ObjectiveRiskClassV1::Critical => profile.critical_value,
    };
    let rollback_value = match source.rollback_class {
        ObjectiveRollbackClassV1::None => profile.rollback_none_value,
        ObjectiveRollbackClassV1::Reversible => profile.rollback_reversible_value,
        ObjectiveRollbackClassV1::Compensatable => profile.rollback_compensatable_value,
        ObjectiveRollbackClassV1::Irreversible => profile.rollback_irreversible_value,
    };
    let abstention_value = profile
        .abstention_rules
        .iter()
        .find(|mapping| mapping.source_rule == source.abstention_rule)
        .map(|mapping| mapping.value)
        .ok_or(ObjectiveAdmissionError::InvalidProfile("abstention rule"))?;
    for (id, axis, value) in [
        (&profile.risk_constraint_id, &profile.risk_axis, risk_value),
        (
            &profile.rollback_constraint_id,
            &profile.rollback_axis,
            rollback_value,
        ),
        (
            &profile.compensation_constraint_id,
            &profile.compensation_axis,
            if source.compensation_required {
                profile.compensation_true_value
            } else {
                profile.compensation_false_value
            },
        ),
        (
            &profile.abstention_constraint_id,
            &profile.abstention_axis,
            abstention_value,
        ),
    ] {
        output.push(Constraint {
            id: id.clone(),
            class: profile.class,
            axis: axis.clone(),
            relation: ConstraintRelation::Equal,
            bound: value,
            evidence_source: profile.evidence_source.clone(),
        });
    }
    Ok(())
}

fn scaled_resource(
    value: u64,
    scale: FixedQ32,
    field: &'static str,
) -> Result<FixedQ32, ObjectiveAdmissionError> {
    if scale <= FixedQ32::ZERO {
        return Err(ObjectiveAdmissionError::InvalidProfile(
            "resource scale must be positive",
        ));
    }
    let raw = i128::from(value) * i128::from(scale.raw());
    Ok(FixedQ32::from_raw(i64::try_from(raw).map_err(|_| {
        ObjectiveAdmissionError::ResourceOverflow(field)
    })?))
}

fn constraint_relation(
    comparator: crate::ObjectiveConstraintComparatorV1,
) -> Result<ConstraintRelation, ObjectiveAdmissionError> {
    match comparator {
        crate::ObjectiveConstraintComparatorV1::Equal => Ok(ConstraintRelation::Equal),
        crate::ObjectiveConstraintComparatorV1::LessThanOrEqual => Ok(ConstraintRelation::AtMost),
        crate::ObjectiveConstraintComparatorV1::GreaterThanOrEqual => {
            Ok(ConstraintRelation::AtLeast)
        }
        crate::ObjectiveConstraintComparatorV1::NotEqual
        | crate::ObjectiveConstraintComparatorV1::LessThan
        | crate::ObjectiveConstraintComparatorV1::GreaterThan
        | crate::ObjectiveConstraintComparatorV1::In
        | crate::ObjectiveConstraintComparatorV1::NotInSet => {
            Err(ObjectiveAdmissionError::UnsupportedComparator)
        }
    }
}

fn predicate_relation(
    comparator: ObjectivePredicateComparatorV1,
) -> Result<ConstraintRelation, ObjectiveAdmissionError> {
    match comparator {
        ObjectivePredicateComparatorV1::Equal => Ok(ConstraintRelation::Equal),
        ObjectivePredicateComparatorV1::LessThanOrEqual => Ok(ConstraintRelation::AtMost),
        ObjectivePredicateComparatorV1::GreaterThanOrEqual => Ok(ConstraintRelation::AtLeast),
        ObjectivePredicateComparatorV1::NotEqual
        | ObjectivePredicateComparatorV1::LessThan
        | ObjectivePredicateComparatorV1::GreaterThan => {
            Err(ObjectiveAdmissionError::UnsupportedComparator)
        }
    }
}

fn action_mapping<'a>(
    profile: &'a ObjectiveAdmissionProfileV1,
    source: &str,
) -> Result<&'a ObjectiveActionProfileV1, ObjectiveAdmissionError> {
    profile
        .actions
        .iter()
        .find(|mapping| mapping.source_action_class == source)
        .ok_or(ObjectiveAdmissionError::UnknownAction)
}

fn stable_id(value: &str, field: &'static str) -> Result<StableId, ObjectiveAdmissionError> {
    StableId::new(value.to_owned()).map_err(|_| ObjectiveAdmissionError::InvalidIdentifier(field))
}

fn validate_profile(profile: &ObjectiveAdmissionProfileV1) -> Result<(), ObjectiveAdmissionError> {
    if profile.expected_input_schema_digest.is_zero()
        || profile.expected_normalization_profile_digest.is_zero()
        || profile.principal_scope_digest.is_zero()
        || profile.maximum_source_age_micros == 0
    {
        return Err(ObjectiveAdmissionError::InvalidProfile("identity or time"));
    }
    if profile.allowed_locales.is_empty()
        || profile.allowed_locales.len() > MAX_PROFILE_LOCALES
        || profile.allowed_trusted_source_identities.len() > MAX_PROFILE_SOURCES
    {
        return Err(ObjectiveAdmissionError::InvalidProfile("collection bound"));
    }
    if profile.constraints.len() > MAX_PROFILE_CONSTRAINTS
        || profile.predicates.len() > MAX_PROFILE_PREDICATES
        || profile.actions.len() > MAX_PROFILE_ACTIONS
        || profile.soft_dimensions.len() > MAX_PROFILE_SOFT_DIMENSIONS
        || profile.evidence_requirements.len() > MAX_PROFILE_EVIDENCE_REQUIREMENTS
        || profile.risk.abstention_rules.len() > MAX_PROFILE_ABSTENTION_RULES
    {
        return Err(ObjectiveAdmissionError::InvalidProfile(
            "mapping count bound",
        ));
    }
    if profile_encoded_size(profile) > MAX_PROFILE_ENCODED_BYTES {
        return Err(ObjectiveAdmissionError::InvalidProfile(
            "profile byte bound",
        ));
    }
    if !(profile.risk.low_value <= profile.risk.medium_value
        && profile.risk.medium_value <= profile.risk.high_value
        && profile.risk.high_value <= profile.risk.critical_value
        && profile.risk.rollback_none_value <= profile.risk.rollback_reversible_value
        && profile.risk.rollback_reversible_value <= profile.risk.rollback_compensatable_value
        && profile.risk.rollback_compensatable_value <= profile.risk.rollback_irreversible_value)
    {
        return Err(ObjectiveAdmissionError::InvalidProfile("risk ordering"));
    }
    unique_texts(&profile.allowed_locales, "allowed locales")?;
    for locale in &profile.allowed_locales {
        safe_profile_text(locale, "locale")?;
    }
    unique_stable_ids(
        &profile.allowed_trusted_source_identities,
        "trusted source identities",
    )?;
    validate_source_mappings(profile)?;
    validate_generated_constraint_ids(profile)?;
    for mapping in resource_mappings(&profile.resources) {
        if mapping.q32_per_source_unit <= FixedQ32::ZERO {
            return Err(ObjectiveAdmissionError::InvalidProfile("resource scale"));
        }
    }
    if profile.risk.abstention_rules.is_empty() {
        return Err(ObjectiveAdmissionError::InvalidProfile("abstention rules"));
    }
    let rules = profile
        .risk
        .abstention_rules
        .iter()
        .map(|mapping| mapping.source_rule.clone())
        .collect::<Vec<_>>();
    unique_texts(&rules, "abstention rules")?;
    for rule in rules {
        safe_profile_text(&rule, "abstention rule")?;
    }
    Ok(())
}

fn profile_encoded_size(profile: &ObjectiveAdmissionProfileV1) -> usize {
    let mut size = 1024usize;
    let mut add = |value: &str| {
        size = size.saturating_add(value.len() + 4);
    };
    add(profile.profile_id.as_str());
    add(profile.principal_scope.as_str());
    for value in &profile.allowed_locales {
        add(value);
    }
    for value in &profile.allowed_trusted_source_identities {
        add(value.as_str());
    }
    for value in &profile.constraints {
        add(&value.source_constraint_id);
        add(&value.expected_unit);
        add(value.axis.as_str());
    }
    for value in &profile.predicates {
        add(&value.source_predicate_id);
        add(&value.expected_unit);
        add(value.axis.as_str());
    }
    for value in &profile.actions {
        add(&value.source_action_class);
        add(value.action_id.as_str());
    }
    for value in &profile.soft_dimensions {
        add(&value.source_dimension_id);
        add(&value.expected_unit);
        add(value.dimension.as_str());
    }
    for value in &profile.evidence_requirements {
        add(&value.source_requirement_id);
        add(value.axis.as_str());
    }
    for value in resource_mappings(&profile.resources) {
        add(value.constraint_id.as_str());
        add(value.axis.as_str());
        add(value.evidence_source.as_str());
    }
    add(profile.risk.evidence_source.as_str());
    for value in [
        &profile.risk.risk_constraint_id,
        &profile.risk.risk_axis,
        &profile.risk.rollback_constraint_id,
        &profile.risk.rollback_axis,
        &profile.risk.compensation_constraint_id,
        &profile.risk.compensation_axis,
        &profile.risk.abstention_constraint_id,
        &profile.risk.abstention_axis,
    ] {
        add(value.as_str());
    }
    for value in &profile.risk.abstention_rules {
        add(&value.source_rule);
    }
    size
}

fn validate_source_mappings(
    profile: &ObjectiveAdmissionProfileV1,
) -> Result<(), ObjectiveAdmissionError> {
    let constraints = profile
        .constraints
        .iter()
        .map(|mapping| mapping.source_constraint_id.clone())
        .collect::<Vec<_>>();
    let predicates = profile
        .predicates
        .iter()
        .map(|mapping| mapping.source_predicate_id.clone())
        .collect::<Vec<_>>();
    let actions = profile
        .actions
        .iter()
        .map(|mapping| mapping.source_action_class.clone())
        .collect::<Vec<_>>();
    let dimensions = profile
        .soft_dimensions
        .iter()
        .map(|mapping| mapping.source_dimension_id.clone())
        .collect::<Vec<_>>();
    let evidence = profile
        .evidence_requirements
        .iter()
        .map(|mapping| mapping.source_requirement_id.clone())
        .collect::<Vec<_>>();
    for (values, field) in [
        (constraints, "constraint mappings"),
        (predicates, "predicate mappings"),
        (actions, "action mappings"),
        (dimensions, "soft mappings"),
        (evidence, "evidence mappings"),
    ] {
        unique_texts(&values, field)?;
        for value in values {
            stable_id(&value, field)?;
        }
    }
    for unit in profile
        .constraints
        .iter()
        .map(|mapping| &mapping.expected_unit)
        .chain(
            profile
                .predicates
                .iter()
                .map(|mapping| &mapping.expected_unit),
        )
        .chain(
            profile
                .soft_dimensions
                .iter()
                .map(|mapping| &mapping.expected_unit),
        )
    {
        safe_profile_text(unit, "unit")?;
    }
    for mapping in &profile.soft_dimensions {
        if mapping.baseline_weight < FixedQ32::ZERO || mapping.baseline_weight > FixedQ32::ONE {
            return Err(ObjectiveAdmissionError::InvalidProfile("soft weight"));
        }
    }
    Ok(())
}

fn validate_generated_constraint_ids(
    profile: &ObjectiveAdmissionProfileV1,
) -> Result<(), ObjectiveAdmissionError> {
    let mut ids = resource_mappings(&profile.resources)
        .into_iter()
        .map(|mapping| mapping.constraint_id.clone())
        .collect::<Vec<_>>();
    ids.extend([
        profile.risk.risk_constraint_id.clone(),
        profile.risk.rollback_constraint_id.clone(),
        profile.risk.compensation_constraint_id.clone(),
        profile.risk.abstention_constraint_id.clone(),
    ]);
    unique_stable_ids(&ids, "generated constraint identities")?;
    Ok(())
}

fn resource_mappings(profile: &ObjectiveResourceProfileV1) -> [&ObjectiveResourceAxisProfileV1; 6] {
    [
        &profile.time_micros,
        &profile.token_count,
        &profile.compute_micros,
        &profile.memory_bytes,
        &profile.network_bytes,
        &profile.external_effect_count,
    ]
}

fn unique_texts(values: &[String], field: &'static str) -> Result<(), ObjectiveAdmissionError> {
    let mut unique = BTreeSet::new();
    for value in values {
        if !unique.insert(value.as_str()) {
            return Err(ObjectiveAdmissionError::InvalidProfile(field));
        }
    }
    Ok(())
}

fn unique_stable_ids(
    values: &[StableId],
    field: &'static str,
) -> Result<(), ObjectiveAdmissionError> {
    let mut unique = BTreeSet::new();
    for value in values {
        if !unique.insert(value.as_str()) {
            return Err(ObjectiveAdmissionError::InvalidProfile(field));
        }
    }
    Ok(())
}

fn safe_profile_text(value: &str, field: &'static str) -> Result<(), ObjectiveAdmissionError> {
    if value.is_empty()
        || value.len() > MAX_SOURCE_TEXT_BYTES
        || !value.bytes().all(|byte| (b' '..=b'~').contains(&byte))
    {
        return Err(ObjectiveAdmissionError::InvalidProfile(field));
    }
    Ok(())
}

fn profile_digest_unchecked(profile: &ObjectiveAdmissionProfileV1) -> Digest32 {
    let mut bytes = b"hepta.objective.admission-profile.v1".to_vec();
    push_id(&mut bytes, &profile.profile_id);
    push_u64(&mut bytes, profile.profile_revision.get());
    push_digest(&mut bytes, profile.expected_input_schema_digest);
    push_digest(&mut bytes, profile.expected_normalization_profile_digest);
    push_digest(&mut bytes, profile.principal_scope_digest);
    push_id(&mut bytes, &profile.principal_scope);
    let mut locales = profile.allowed_locales.clone();
    locales.sort();
    push_len(&mut bytes, locales.len());
    for locale in locales {
        push_text(&mut bytes, &locale);
    }
    push_u64(&mut bytes, profile.maximum_source_age_micros);
    push_u64(&mut bytes, profile.maximum_future_skew_micros);
    bytes.push(u8::from(profile.deadline_required));
    let mut identities = profile.allowed_trusted_source_identities.clone();
    identities.sort();
    push_len(&mut bytes, identities.len());
    for identity in identities {
        push_id(&mut bytes, &identity);
    }

    let mut constraints = profile.constraints.clone();
    constraints.sort_by(|left, right| left.source_constraint_id.cmp(&right.source_constraint_id));
    push_len(&mut bytes, constraints.len());
    for mapping in constraints {
        push_text(&mut bytes, &mapping.source_constraint_id);
        push_text(&mut bytes, &mapping.expected_unit);
        bytes.push(mapping.class.tag());
        push_id(&mut bytes, &mapping.axis);
    }
    let mut predicates = profile.predicates.clone();
    predicates.sort_by(|left, right| left.source_predicate_id.cmp(&right.source_predicate_id));
    push_len(&mut bytes, predicates.len());
    for mapping in predicates {
        push_text(&mut bytes, &mapping.source_predicate_id);
        push_text(&mut bytes, &mapping.expected_unit);
        push_id(&mut bytes, &mapping.axis);
    }
    let mut actions = profile.actions.clone();
    actions.sort_by(|left, right| left.source_action_class.cmp(&right.source_action_class));
    push_len(&mut bytes, actions.len());
    for mapping in actions {
        push_text(&mut bytes, &mapping.source_action_class);
        push_id(&mut bytes, &mapping.action_id);
    }
    let mut dimensions = profile.soft_dimensions.clone();
    dimensions.sort_by(|left, right| left.source_dimension_id.cmp(&right.source_dimension_id));
    push_len(&mut bytes, dimensions.len());
    for mapping in dimensions {
        push_text(&mut bytes, &mapping.source_dimension_id);
        push_text(&mut bytes, &mapping.expected_unit);
        bytes.push(soft_direction_tag(mapping.expected_direction));
        push_id(&mut bytes, &mapping.dimension);
        push_i64(&mut bytes, mapping.baseline_weight.raw());
    }
    let mut evidence = profile.evidence_requirements.clone();
    evidence.sort_by(|left, right| left.source_requirement_id.cmp(&right.source_requirement_id));
    push_len(&mut bytes, evidence.len());
    for mapping in evidence {
        push_text(&mut bytes, &mapping.source_requirement_id);
        push_id(&mut bytes, &mapping.axis);
    }
    for mapping in resource_mappings(&profile.resources) {
        push_id(&mut bytes, &mapping.constraint_id);
        push_id(&mut bytes, &mapping.axis);
        bytes.push(mapping.class.tag());
        push_i64(&mut bytes, mapping.q32_per_source_unit.raw());
        push_id(&mut bytes, &mapping.evidence_source);
    }
    push_risk_profile(&mut bytes, &profile.risk);
    Digest32::of_bytes(&bytes)
}

fn push_risk_profile(bytes: &mut Vec<u8>, risk: &ObjectiveRiskProfileV1) {
    push_id(bytes, &risk.evidence_source);
    bytes.push(risk.class.tag());
    for (id, axis) in [
        (&risk.risk_constraint_id, &risk.risk_axis),
        (&risk.rollback_constraint_id, &risk.rollback_axis),
        (&risk.compensation_constraint_id, &risk.compensation_axis),
        (&risk.abstention_constraint_id, &risk.abstention_axis),
    ] {
        push_id(bytes, id);
        push_id(bytes, axis);
    }
    for value in [
        risk.low_value,
        risk.medium_value,
        risk.high_value,
        risk.critical_value,
        risk.rollback_none_value,
        risk.rollback_reversible_value,
        risk.rollback_compensatable_value,
        risk.rollback_irreversible_value,
        risk.compensation_false_value,
        risk.compensation_true_value,
    ] {
        push_i64(bytes, value.raw());
    }
    let mut rules = risk.abstention_rules.clone();
    rules.sort_by(|left, right| left.source_rule.cmp(&right.source_rule));
    push_len(bytes, rules.len());
    for rule in rules {
        push_text(bytes, &rule.source_rule);
        push_i64(bytes, rule.value.raw());
    }
}

fn intent_digest_unchecked(envelope: &ObjectiveSourceEnvelopeV1) -> Digest32 {
    let intent = &envelope.structured_intent;
    let mut bytes = b"hepta.objective.structured-intent.v1".to_vec();
    let mut success = intent.success_predicates.clone();
    success.sort_by(|left, right| left.predicate_id.cmp(&right.predicate_id));
    push_len(&mut bytes, success.len());
    for value in success {
        push_source_predicate(&mut bytes, &value);
    }
    let mut terminal = intent.terminal_conditions.clone();
    terminal.sort_by(|left, right| left.predicate_id.cmp(&right.predicate_id));
    push_len(&mut bytes, terminal.len());
    for value in terminal {
        push_source_predicate(&mut bytes, &value);
    }
    for values in [
        &intent.legal_action_classes,
        &intent.forbidden_action_classes,
        &intent.confirmation_action_classes,
    ] {
        let mut values = values.clone();
        values.sort();
        push_len(&mut bytes, values.len());
        for value in values {
            push_text(&mut bytes, &value);
        }
    }
    let mut constraints = intent.constraints.clone();
    constraints.sort_by(|left, right| left.constraint_id.cmp(&right.constraint_id));
    push_len(&mut bytes, constraints.len());
    for value in constraints {
        push_source_constraint(&mut bytes, &value);
    }
    let mut dimensions = intent.soft_dimensions.clone();
    dimensions.sort_by(|left, right| left.dimension_id.cmp(&right.dimension_id));
    push_len(&mut bytes, dimensions.len());
    for value in dimensions {
        push_text(&mut bytes, &value.dimension_id);
        push_text(&mut bytes, &value.unit);
        bytes.push(soft_direction_tag(value.direction));
        push_i64(&mut bytes, value.minimum_weight_q32);
        push_i64(&mut bytes, value.maximum_weight_q32);
    }
    let mut evidence = intent.evidence_requirements.clone();
    evidence.sort_by(|left, right| left.requirement_id.cmp(&right.requirement_id));
    push_len(&mut bytes, evidence.len());
    for value in evidence {
        push_text(&mut bytes, &value.requirement_id);
        push_text(&mut bytes, &value.evidence_source_id);
        push_u32(&mut bytes, value.minimum_confidence_ppm);
        bytes.push(u8::from(value.terminal));
    }
    for value in [
        intent.resources.time_micros,
        intent.resources.token_count,
        intent.resources.compute_micros,
        intent.resources.memory_bytes,
        intent.resources.network_bytes,
    ] {
        push_u64(&mut bytes, value);
    }
    push_u32(&mut bytes, intent.resources.external_effect_count);
    bytes.push(risk_class_tag(intent.risk.risk_class));
    push_text(&mut bytes, &intent.risk.abstention_rule);
    bytes.push(rollback_class_tag(intent.risk.rollback_class));
    bytes.push(u8::from(intent.risk.compensation_required));
    push_digest(&mut bytes, intent.provenance.source_digest);
    push_digest(&mut bytes, intent.provenance.normalization_profile_digest);
    Digest32::of_bytes(&bytes)
}

fn admitted_source_digest(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile_digest: Digest32,
    authentication: &ObjectiveSourceAuthenticationV1,
) -> Digest32 {
    let mut bytes = b"hepta.objective.admitted-source.v1".to_vec();
    push_digest(&mut bytes, profile_digest);
    push_text(&mut bytes, &envelope.request_id);
    push_digest(&mut bytes, envelope.principal_scope_digest);
    push_digest(&mut bytes, envelope.intent_digest);
    bytes.push(source_trust_tag(envelope.source_trust_class));
    push_text(&mut bytes, &envelope.locale);
    push_text(&mut bytes, &envelope.observed_at);
    match &envelope.deadline {
        Some(deadline) => {
            bytes.push(1);
            push_text(&mut bytes, deadline);
        }
        None => bytes.push(0),
    }
    push_digest(&mut bytes, envelope.input_schema_digest);
    push_digest(
        &mut bytes,
        envelope.structured_intent.provenance.source_digest,
    );
    match authentication {
        ObjectiveSourceAuthenticationV1::Principal {
            principal_scope_digest,
            ..
        } => {
            bytes.push(0);
            push_digest(&mut bytes, *principal_scope_digest);
        }
        ObjectiveSourceAuthenticationV1::TrustedSystem {
            source_identity, ..
        } => {
            bytes.push(1);
            push_id(&mut bytes, source_identity);
        }
        ObjectiveSourceAuthenticationV1::AuthorizedAdapter {
            source_identity, ..
        } => {
            bytes.push(2);
            push_id(&mut bytes, source_identity);
        }
        ObjectiveSourceAuthenticationV1::UntrustedEvidence { .. } => bytes.push(3),
    }
    Digest32::of_bytes(&bytes)
}

fn push_source_predicate(bytes: &mut Vec<u8>, value: &ObjectiveSourcePredicateV1) {
    push_text(bytes, &value.predicate_id);
    push_text(bytes, &value.unit);
    bytes.push(predicate_comparator_tag(value.comparator));
    push_i64(bytes, value.bound_q32);
    push_text(bytes, &value.evidence_source_id);
    bytes.push(u8::from(value.terminal));
}

fn push_source_constraint(bytes: &mut Vec<u8>, value: &ObjectiveSourceConstraintV1) {
    push_text(bytes, &value.constraint_id);
    push_text(bytes, &value.unit);
    bytes.push(constraint_comparator_tag(value.comparator));
    push_i64(bytes, value.bound_q32);
    push_text(bytes, &value.evidence_source_id);
    bytes.push(u8::from(value.terminal));
}

fn parse_utc_micros(value: &str) -> Option<u64> {
    let bytes = value.as_bytes();
    if bytes.len() < 20
        || bytes[4] != b'-'
        || bytes[7] != b'-'
        || bytes[10] != b'T'
        || bytes[13] != b':'
        || bytes[16] != b':'
        || *bytes.last()? != b'Z'
    {
        return None;
    }
    let year = parse_decimal(&bytes[0..4])? as i64;
    let month = parse_decimal(&bytes[5..7])? as u32;
    let day = parse_decimal(&bytes[8..10])? as u32;
    let hour = parse_decimal(&bytes[11..13])? as u32;
    let minute = parse_decimal(&bytes[14..16])? as u32;
    let second = parse_decimal(&bytes[17..19])? as u32;
    if !(1970..=9999).contains(&year)
        || !(1..=12).contains(&month)
        || day == 0
        || day > days_in_month(year, month)
        || hour > 23
        || minute > 59
        || second > 59
    {
        return None;
    }
    let fractional = &bytes[19..bytes.len() - 1];
    let micros = if fractional.is_empty() {
        0
    } else {
        if fractional[0] != b'.' || !(1..=6).contains(&(fractional.len() - 1)) {
            return None;
        }
        let digits = &fractional[1..];
        let parsed = parse_decimal(digits)?;
        parsed.checked_mul(10_u64.pow(u32::try_from(6 - digits.len()).ok()?))?
    };
    let days = days_from_civil(year, month, day)?;
    let seconds = u64::try_from(days)
        .ok()?
        .checked_mul(86_400)?
        .checked_add(u64::from(hour) * 3_600)?
        .checked_add(u64::from(minute) * 60)?
        .checked_add(u64::from(second))?;
    seconds.checked_mul(MICROS_PER_SECOND)?.checked_add(micros)
}

fn parse_decimal(bytes: &[u8]) -> Option<u64> {
    if bytes.is_empty() || bytes.iter().any(|byte| !byte.is_ascii_digit()) {
        return None;
    }
    bytes.iter().try_fold(0_u64, |value, byte| {
        value.checked_mul(10)?.checked_add(u64::from(byte - b'0'))
    })
}

fn days_in_month(year: i64, month: u32) -> u32 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 if is_leap_year(year) => 29,
        2 => 28,
        _ => 0,
    }
}

fn is_leap_year(year: i64) -> bool {
    year % 4 == 0 && (year % 100 != 0 || year % 400 == 0)
}

fn days_from_civil(year: i64, month: u32, day: u32) -> Option<i64> {
    let adjusted_year = year - i64::from(month <= 2);
    let era = adjusted_year.div_euclid(400);
    let year_of_era = adjusted_year - era * 400;
    let shifted_month = i64::from(month) + if month > 2 { -3 } else { 9 };
    let day_of_year = (153 * shifted_month + 2) / 5 + i64::from(day) - 1;
    let day_of_era = year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year;
    era.checked_mul(146_097)?
        .checked_add(day_of_era)?
        .checked_sub(719_468)
}

fn predicate_comparator_tag(value: ObjectivePredicateComparatorV1) -> u8 {
    match value {
        ObjectivePredicateComparatorV1::Equal => 0,
        ObjectivePredicateComparatorV1::NotEqual => 1,
        ObjectivePredicateComparatorV1::LessThan => 2,
        ObjectivePredicateComparatorV1::LessThanOrEqual => 3,
        ObjectivePredicateComparatorV1::GreaterThan => 4,
        ObjectivePredicateComparatorV1::GreaterThanOrEqual => 5,
    }
}

fn constraint_comparator_tag(value: crate::ObjectiveConstraintComparatorV1) -> u8 {
    match value {
        crate::ObjectiveConstraintComparatorV1::Equal => 0,
        crate::ObjectiveConstraintComparatorV1::NotEqual => 1,
        crate::ObjectiveConstraintComparatorV1::LessThan => 2,
        crate::ObjectiveConstraintComparatorV1::LessThanOrEqual => 3,
        crate::ObjectiveConstraintComparatorV1::GreaterThan => 4,
        crate::ObjectiveConstraintComparatorV1::GreaterThanOrEqual => 5,
        crate::ObjectiveConstraintComparatorV1::In => 6,
        crate::ObjectiveConstraintComparatorV1::NotInSet => 7,
    }
}

fn soft_direction_tag(value: ObjectiveSoftDirectionV1) -> u8 {
    match value {
        ObjectiveSoftDirectionV1::Maximize => 0,
        ObjectiveSoftDirectionV1::Minimize => 1,
    }
}

fn risk_class_tag(value: ObjectiveRiskClassV1) -> u8 {
    match value {
        ObjectiveRiskClassV1::Low => 0,
        ObjectiveRiskClassV1::Medium => 1,
        ObjectiveRiskClassV1::High => 2,
        ObjectiveRiskClassV1::Critical => 3,
    }
}

fn rollback_class_tag(value: ObjectiveRollbackClassV1) -> u8 {
    match value {
        ObjectiveRollbackClassV1::None => 0,
        ObjectiveRollbackClassV1::Reversible => 1,
        ObjectiveRollbackClassV1::Compensatable => 2,
        ObjectiveRollbackClassV1::Irreversible => 3,
    }
}

fn source_trust_tag(value: ObjectiveSourceTrustV1) -> u8 {
    match value {
        ObjectiveSourceTrustV1::Principal => 0,
        ObjectiveSourceTrustV1::TrustedSystem => 1,
        ObjectiveSourceTrustV1::AuthorizedAdapter => 2,
        ObjectiveSourceTrustV1::UntrustedEvidence => 3,
    }
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    push_len(bytes, value.len());
    bytes.extend_from_slice(value.as_bytes());
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_text(bytes, value.as_str());
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_i64(bytes: &mut Vec<u8>, value: i64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

fn push_u32(bytes: &mut Vec<u8>, value: u32) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&u32::try_from(value).unwrap_or(u32::MAX).to_be_bytes());
}

#[cfg(test)]
#[path = "objective_admission_tests.rs"]
mod tests;
