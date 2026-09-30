//! Indexed authenticated admission used by the canonical product path.
//!
//! The raw-profile admission implementation remains a compatibility surface.
//! This module consumes one generation-frozen `ValidatedAdmissionProfileV1` and
//! performs every source mapping through its prevalidated indexes. Request-local
//! authentication, freshness, deadline and digest checks are still repeated on
//! every call.

use std::collections::BTreeSet;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::ActionClass;
use crate::ConfirmationPolicy;
use crate::Constraint;
use crate::ConstraintRelation;
use crate::ObjectiveAdmissionContextV1;
use crate::ObjectiveAdmissionError;
use crate::ObjectiveAdmissionReceiptV1;
use crate::ObjectiveEvidenceRequirementV1;
use crate::ObjectivePredicateComparatorV1;
use crate::ObjectiveResourceAxisProfileV1;
use crate::ObjectiveResourcesV1;
use crate::ObjectiveRiskClassV1;
use crate::ObjectiveRiskProfileV1;
use crate::ObjectiveRollbackClassV1;
use crate::ObjectiveSoftDirectionV1;
use crate::ObjectiveSourceAuthenticationV1;
use crate::ObjectiveSourceConstraintV1;
use crate::ObjectiveSourceEnvelopeV1;
use crate::ObjectiveSourcePredicateV1;
use crate::ObjectiveSourceTrustV1;
use crate::PredicateTerminality;
use crate::SoftDirection;
use crate::SoftPreference;
use crate::SourceTrust;
use crate::SuccessPredicate;
use crate::ValidatedAdmissionProfileV1;
use crate::canonical_objective_intent_digest_v1;
use crate::model::ObjectiveSourceEnvelope;

const MICROS_PER_SECOND: u64 = 1_000_000;
const Q32_ONE_RAW: i128 = 1_i128 << 32;

pub(crate) fn admit_indexed_objective_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ValidatedAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
) -> Result<(ObjectiveSourceEnvelope, ObjectiveAdmissionReceiptV1), ObjectiveAdmissionError> {
    envelope.validate_structure()?;
    let raw = profile.profile();
    let profile_digest = profile.profile_digest();
    if context.selected_profile_digest != profile_digest {
        return Err(ObjectiveAdmissionError::ProfileDigestMismatch);
    }
    if envelope.input_schema_digest != raw.expected_input_schema_digest {
        return Err(ObjectiveAdmissionError::InputSchemaMismatch);
    }
    if envelope
        .structured_intent
        .provenance
        .normalization_profile_digest
        != raw.expected_normalization_profile_digest
    {
        return Err(ObjectiveAdmissionError::NormalizationProfileMismatch);
    }
    if envelope.principal_scope_digest != raw.principal_scope_digest {
        return Err(ObjectiveAdmissionError::PrincipalScopeMismatch);
    }
    if !profile.locale_allowed(&envelope.locale) {
        return Err(ObjectiveAdmissionError::LocaleNotAllowed);
    }

    validate_authentication(envelope, profile, &context.source_authentication)?;
    let supplied_source_digest = envelope.structured_intent.provenance.source_digest;
    if supplied_source_digest.is_zero()
        || supplied_source_digest != authentication_source_digest(&context.source_authentication)
    {
        return Err(ObjectiveAdmissionError::SourceDigestMismatch);
    }
    let intent_digest = canonical_objective_intent_digest_v1(envelope)?;
    if envelope.intent_digest.is_zero() || envelope.intent_digest != intent_digest {
        return Err(ObjectiveAdmissionError::IntentDigestMismatch);
    }

    let observed_at_unix_micros = parse_utc_micros(&envelope.observed_at)
        .ok_or(ObjectiveAdmissionError::InvalidTimestamp("observedAt"))?;
    let latest_allowed = context
        .now_unix_micros
        .checked_add(raw.maximum_future_skew_micros)
        .ok_or(ObjectiveAdmissionError::InvalidTimestamp("now"))?;
    if observed_at_unix_micros > latest_allowed {
        return Err(ObjectiveAdmissionError::SourceFromFuture);
    }
    if context
        .now_unix_micros
        .saturating_sub(observed_at_unix_micros)
        > raw.maximum_source_age_micros
    {
        return Err(ObjectiveAdmissionError::SourceStale);
    }
    let deadline_unix_micros = match &envelope.deadline {
        Some(deadline) => Some(
            parse_utc_micros(deadline)
                .ok_or(ObjectiveAdmissionError::InvalidTimestamp("deadline"))?,
        ),
        None if raw.deadline_required => return Err(ObjectiveAdmissionError::DeadlineMissing),
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

    let admitted_source_digest = admitted_source_digest(
        envelope,
        profile_digest,
        &context.source_authentication,
    );
    let source = adapt_source(envelope, profile, context, admitted_source_digest)?;
    let receipt = ObjectiveAdmissionReceiptV1 {
        profile_id: raw.profile_id.clone(),
        profile_revision: raw.profile_revision,
        profile_digest,
        supplied_source_digest,
        intent_digest,
        admitted_source_digest,
        observed_at_unix_micros,
        deadline_unix_micros,
        authority: AuthorityPosture::DENY_ALL,
    };
    Ok((source, receipt))
}

fn validate_authentication(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ValidatedAdmissionProfileV1,
    authentication: &ObjectiveSourceAuthenticationV1,
) -> Result<(), ObjectiveAdmissionError> {
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
        ) if profile.trusted_source_identity_allowed(source_identity) => Ok(()),
        (
            ObjectiveSourceTrustV1::AuthorizedAdapter,
            ObjectiveSourceAuthenticationV1::AuthorizedAdapter {
                source_identity, ..
            },
        ) if profile.trusted_source_identity_allowed(source_identity) => Ok(()),
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

fn authentication_source_digest(authentication: &ObjectiveSourceAuthenticationV1) -> Digest32 {
    match authentication {
        ObjectiveSourceAuthenticationV1::Principal { source_digest, .. }
        | ObjectiveSourceAuthenticationV1::TrustedSystem { source_digest, .. }
        | ObjectiveSourceAuthenticationV1::AuthorizedAdapter { source_digest, .. }
        | ObjectiveSourceAuthenticationV1::UntrustedEvidence { source_digest } => *source_digest,
    }
}

fn adapt_source(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ValidatedAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
    admitted_source_digest: Digest32,
) -> Result<ObjectiveSourceEnvelope, ObjectiveAdmissionError> {
    let request_id = stable_id(&envelope.request_id, "requestId")?;
    let raw = profile.profile();
    let mut constraints = Vec::new();
    for source in &envelope.structured_intent.constraints {
        constraints.push(adapt_constraint(source, profile)?);
    }
    append_resources(
        &mut constraints,
        &envelope.structured_intent.resources,
        &raw.resources,
    )?;
    append_risk(
        &mut constraints,
        &envelope.structured_intent.risk,
        profile,
    )?;

    let mut success_predicates = Vec::new();
    for source in &envelope.structured_intent.success_predicates {
        success_predicates.push(adapt_predicate(source, profile, false)?);
    }
    for source in &envelope.structured_intent.terminal_conditions {
        success_predicates.push(adapt_predicate(source, profile, true)?);
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
        let mapping = profile
            .action(source)
            .ok_or(ObjectiveAdmissionError::UnknownAction)?;
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
        forbidden_actions.push(
            profile
                .action(source)
                .ok_or(ObjectiveAdmissionError::UnknownAction)?
                .action_id
                .clone(),
        );
    }

    let mut soft_preferences = Vec::new();
    for source in &envelope.structured_intent.soft_dimensions {
        let mapping = profile
            .soft_dimension(&source.dimension_id)
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
        principal_scope: raw.principal_scope.clone(),
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
    profile: &ValidatedAdmissionProfileV1,
) -> Result<Constraint, ObjectiveAdmissionError> {
    if source.terminal {
        return Err(ObjectiveAdmissionError::TerminalConstraintUnsupported);
    }
    let mapping = profile
        .constraint(&source.constraint_id)
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
    profile: &ValidatedAdmissionProfileV1,
    must_be_terminal: bool,
) -> Result<SuccessPredicate, ObjectiveAdmissionError> {
    if must_be_terminal != source.terminal {
        return Err(ObjectiveAdmissionError::InvalidTerminality);
    }
    let mapping = profile
        .predicate(&source.predicate_id)
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
    profile: &ValidatedAdmissionProfileV1,
) -> Result<SuccessPredicate, ObjectiveAdmissionError> {
    let mapping = profile
        .evidence_requirement(&source.requirement_id)
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
    profile: &crate::ObjectiveResourceProfileV1,
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
    profile: &ValidatedAdmissionProfileV1,
) -> Result<(), ObjectiveAdmissionError> {
    let raw: &ObjectiveRiskProfileV1 = &profile.profile().risk;
    let risk_value = match source.risk_class {
        ObjectiveRiskClassV1::Low => raw.low_value,
        ObjectiveRiskClassV1::Medium => raw.medium_value,
        ObjectiveRiskClassV1::High => raw.high_value,
        ObjectiveRiskClassV1::Critical => raw.critical_value,
    };
    let rollback_value = match source.rollback_class {
        ObjectiveRollbackClassV1::None => raw.rollback_none_value,
        ObjectiveRollbackClassV1::Reversible => raw.rollback_reversible_value,
        ObjectiveRollbackClassV1::Compensatable => raw.rollback_compensatable_value,
        ObjectiveRollbackClassV1::Irreversible => raw.rollback_irreversible_value,
    };
    let abstention_value = profile
        .abstention_rule(&source.abstention_rule)
        .map(|mapping| mapping.value)
        .ok_or(ObjectiveAdmissionError::InvalidProfile("abstention rule"))?;
    for (id, axis, value) in [
        (&raw.risk_constraint_id, &raw.risk_axis, risk_value),
        (
            &raw.rollback_constraint_id,
            &raw.rollback_axis,
            rollback_value,
        ),
        (
            &raw.compensation_constraint_id,
            &raw.compensation_axis,
            if source.compensation_required {
                raw.compensation_true_value
            } else {
                raw.compensation_false_value
            },
        ),
        (
            &raw.abstention_constraint_id,
            &raw.abstention_axis,
            abstention_value,
        ),
    ] {
        output.push(Constraint {
            id: id.clone(),
            class: raw.class,
            axis: axis.clone(),
            relation: ConstraintRelation::Equal,
            bound: value,
            evidence_source: raw.evidence_source.clone(),
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

fn stable_id(value: &str, field: &'static str) -> Result<StableId, ObjectiveAdmissionError> {
    StableId::new(value.to_owned()).map_err(|_| ObjectiveAdmissionError::InvalidIdentifier(field))
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

fn source_trust_tag(value: ObjectiveSourceTrustV1) -> u8 {
    match value {
        ObjectiveSourceTrustV1::Principal => 0,
        ObjectiveSourceTrustV1::TrustedSystem => 1,
        ObjectiveSourceTrustV1::AuthorizedAdapter => 2,
        ObjectiveSourceTrustV1::UntrustedEvidence => 3,
    }
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    let len = u32::try_from(value.len()).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&len.to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_text(bytes, value.as_str());
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}
