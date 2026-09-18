//! Canonical V1 admission gate.
//!
//! The historical admission adapter validates/authenticates/maps the source and
//! then invokes the native compiler, whose legacy compatibility path performs a
//! scalar feasibility check internally. The public V1 entry point in this module
//! makes the architectural boundary explicit: all source/profile/authentication
//! checks that can affect hard semantics are completed first, the mapped V1 hard
//! constraint subset is checked by `check_feasibility_v1`, and only feasible
//! inputs proceed to native compilation.
//!
//! `ObjectiveSourceEnvelopeV1` is still a scalar source dialect: it carries a
//! single Q32 bound per hard constraint and has no finite-enum set payload or
//! action-implication payload. The general solver is therefore exercised here on
//! the complete V1 scalar hard-constraint set (including generated resource and
//! risk constraints). Rich enum/action implication support remains an API-level
//! solver capability until a source grammar can represent those atoms without
//! guessing.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::time::Duration;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::AtomPrecedenceV1;
use crate::AtomPredicateV1;
use crate::ConfirmationPolicy;
use crate::ConstraintAtomV1;
use crate::ConstraintClass;
use crate::FeasibilityOutcomeV1;
use crate::ObjectiveAdmissionContextV1;
use crate::ObjectiveAdmissionError;
use crate::ObjectiveAdmissionOutcomeV1;
use crate::ObjectiveAdmissionProfileV1;
use crate::ObjectiveAdmissionReceiptV1;
use crate::ObjectiveCompileReceipt;
use crate::ObjectiveConflictReceipt;
use crate::ObjectiveConstraintComparatorV1;
use crate::ObjectiveError;
use crate::ObjectivePredicateComparatorV1;
use crate::ObjectiveResourceAxisProfileV1;
use crate::ObjectiveRiskClassV1;
use crate::ObjectiveRollbackClassV1;
use crate::ObjectiveSoftDirectionV1;
use crate::ObjectiveSourceAuthenticationV1;
use crate::ObjectiveSourceEnvelopeV1;
use crate::ObjectiveSourceTrustV1;
use crate::OracleBudgetV1;
use crate::PredicateTerminality;
use crate::RegisteredAxisV1;
use crate::RegisteredDomainV1;
use crate::RegisteredGrammarV1;
use crate::check_feasibility_v1;
use crate::objective_admission;

const MICROS_PER_SECOND: u64 = 1_000_000;
const GENERAL_FEASIBILITY_MAX_CALLS: u16 = 257;
const NATIVE_Q32_UNIT: &str = "legacy-fixed-q32-v1";
const CONFLICT_DIGEST_DOMAIN: &[u8] = b"hepta.objective.conflict.v1";
const ABSTAIN_ACTION_ID: &str = "abstain";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct PreparedAdmissionV1 {
    profile_digest: Digest32,
    supplied_source_digest: Digest32,
    intent_digest: Digest32,
    admitted_source_digest: Digest32,
    observed_at_unix_micros: u64,
    deadline_unix_micros: Option<u64>,
}

/// Admit a complete V1 source through the general feasibility gate before
/// delegating feasible work to the deterministic native compiler.
///
/// The native compiler intentionally retains its legacy scalar feasibility
/// check as a defense-in-depth compatibility recheck. It is no longer the only
/// feasibility gate on the public V1 admission path.
pub fn admit_and_compile_objective_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
) -> Result<ObjectiveAdmissionOutcomeV1, ObjectiveAdmissionError> {
    let prepared = prepare_admission(envelope, profile, context)?;
    let (registry, atoms) =
        mapped_v1_hard_constraints(envelope, profile, prepared.admitted_source_digest)?;
    validate_lowered_nonconstraint_semantics(envelope, profile, &atoms)?;

    let feasibility = check_feasibility_v1(
        &registry,
        atoms,
        OracleBudgetV1 {
            max_calls: GENERAL_FEASIBILITY_MAX_CALLS,
            // Canonical V1 admission is deterministic and count-bounded. Host
            // latency measurement belongs to product composition, not semantic
            // admission, so wall-clock cancellation is disabled here exactly as
            // in the native compatibility check.
            wall_time: Duration::MAX,
        },
    );

    match feasibility.outcome {
        FeasibilityOutcomeV1::Feasible(_) => {
            objective_admission::admit_and_compile_objective_v1(envelope, profile, context)
        }
        FeasibilityOutcomeV1::Infeasible {
            inclusion_minimal_conflicting_ids,
        } => Ok(ObjectiveAdmissionOutcomeV1 {
            receipt: admission_receipt(profile, prepared),
            compile_result: Err(conflict_receipt(
                envelope,
                context,
                prepared.admitted_source_digest,
                inclusion_minimal_conflicting_ids,
            )?),
        }),
        FeasibilityOutcomeV1::Unsupported { .. } => Err(ObjectiveAdmissionError::Compiler(
            ObjectiveError::UnsupportedConstraintLanguage,
        )),
        FeasibilityOutcomeV1::Exhausted => Err(ObjectiveAdmissionError::Compiler(
            ObjectiveError::FeasibilityBudgetExhausted,
        )),
    }
}

fn prepare_admission(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
) -> Result<PreparedAdmissionV1, ObjectiveAdmissionError> {
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
        || supplied_source_digest != authentication_source_digest(&context.source_authentication)
    {
        return Err(ObjectiveAdmissionError::SourceDigestMismatch);
    }
    let intent_digest = objective_admission::canonical_objective_intent_digest_v1(envelope)?;
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

    Ok(PreparedAdmissionV1 {
        profile_digest,
        supplied_source_digest,
        intent_digest,
        admitted_source_digest: admitted_source_digest(
            envelope,
            profile_digest,
            &context.source_authentication,
        ),
        observed_at_unix_micros,
        deadline_unix_micros,
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

fn authentication_source_digest(authentication: &ObjectiveSourceAuthenticationV1) -> Digest32 {
    match authentication {
        ObjectiveSourceAuthenticationV1::Principal { source_digest, .. }
        | ObjectiveSourceAuthenticationV1::TrustedSystem { source_digest, .. }
        | ObjectiveSourceAuthenticationV1::AuthorizedAdapter { source_digest, .. }
        | ObjectiveSourceAuthenticationV1::UntrustedEvidence { source_digest } => *source_digest,
    }
}

fn mapped_v1_hard_constraints(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    admitted_source_digest: Digest32,
) -> Result<(RegisteredGrammarV1, Vec<ConstraintAtomV1>), ObjectiveAdmissionError> {
    let unit = stable_id(NATIVE_Q32_UNIT, "native feasibility unit")?;
    let mut registry = RegisteredGrammarV1 {
        schema_digest: envelope.input_schema_digest,
        axes: BTreeMap::new(),
        evidence_sources: BTreeSet::new(),
    };
    let mut atoms = Vec::new();
    let mut semantic_ids = BTreeSet::new();

    for source in &envelope.structured_intent.constraints {
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
        let id = stable_id(&source.constraint_id, "constraintId")?;
        let evidence_source = stable_id(&source.evidence_source_id, "constraint.evidenceSourceId")?;
        let bound = FixedQ32::from_raw(source.bound_q32);
        let (lower, upper) = scalar_interval_for_constraint(source.comparator, bound)?;
        push_scalar_atom(
            &mut registry,
            &mut atoms,
            &mut semantic_ids,
            id,
            mapping.class,
            mapping.axis.clone(),
            lower,
            upper,
            unit.clone(),
            evidence_source,
            admitted_source_digest,
        )?;
    }

    for (field, value, mapping) in [
        (
            "timeMicros",
            envelope.structured_intent.resources.time_micros,
            &profile.resources.time_micros,
        ),
        (
            "tokenCount",
            envelope.structured_intent.resources.token_count,
            &profile.resources.token_count,
        ),
        (
            "computeMicros",
            envelope.structured_intent.resources.compute_micros,
            &profile.resources.compute_micros,
        ),
        (
            "memoryBytes",
            envelope.structured_intent.resources.memory_bytes,
            &profile.resources.memory_bytes,
        ),
        (
            "networkBytes",
            envelope.structured_intent.resources.network_bytes,
            &profile.resources.network_bytes,
        ),
        (
            "externalEffectCount",
            u64::from(envelope.structured_intent.resources.external_effect_count),
            &profile.resources.external_effect_count,
        ),
    ] {
        let bound = scaled_resource(value, mapping, field)?;
        push_scalar_atom(
            &mut registry,
            &mut atoms,
            &mut semantic_ids,
            mapping.constraint_id.clone(),
            mapping.class,
            mapping.axis.clone(),
            FixedQ32::from_raw(i64::MIN),
            bound,
            unit.clone(),
            mapping.evidence_source.clone(),
            admitted_source_digest,
        )?;
    }

    let risk = &envelope.structured_intent.risk;
    let risk_profile = &profile.risk;
    let risk_value = match risk.risk_class {
        ObjectiveRiskClassV1::Low => risk_profile.low_value,
        ObjectiveRiskClassV1::Medium => risk_profile.medium_value,
        ObjectiveRiskClassV1::High => risk_profile.high_value,
        ObjectiveRiskClassV1::Critical => risk_profile.critical_value,
    };
    let rollback_value = match risk.rollback_class {
        ObjectiveRollbackClassV1::None => risk_profile.rollback_none_value,
        ObjectiveRollbackClassV1::Reversible => risk_profile.rollback_reversible_value,
        ObjectiveRollbackClassV1::Compensatable => risk_profile.rollback_compensatable_value,
        ObjectiveRollbackClassV1::Irreversible => risk_profile.rollback_irreversible_value,
    };
    let compensation_value = if risk.compensation_required {
        risk_profile.compensation_true_value
    } else {
        risk_profile.compensation_false_value
    };
    let abstention_value = risk_profile
        .abstention_rules
        .iter()
        .find(|mapping| mapping.source_rule == risk.abstention_rule)
        .map(|mapping| mapping.value)
        .ok_or(ObjectiveAdmissionError::InvalidProfile("abstention rule"))?;
    for (id, axis, value) in [
        (
            &risk_profile.risk_constraint_id,
            &risk_profile.risk_axis,
            risk_value,
        ),
        (
            &risk_profile.rollback_constraint_id,
            &risk_profile.rollback_axis,
            rollback_value,
        ),
        (
            &risk_profile.compensation_constraint_id,
            &risk_profile.compensation_axis,
            compensation_value,
        ),
        (
            &risk_profile.abstention_constraint_id,
            &risk_profile.abstention_axis,
            abstention_value,
        ),
    ] {
        push_scalar_atom(
            &mut registry,
            &mut atoms,
            &mut semantic_ids,
            id.clone(),
            risk_profile.class,
            axis.clone(),
            value,
            value,
            unit.clone(),
            risk_profile.evidence_source.clone(),
            admitted_source_digest,
        )?;
    }

    Ok((registry, atoms))
}

#[allow(clippy::too_many_arguments)]
fn push_scalar_atom(
    registry: &mut RegisteredGrammarV1,
    atoms: &mut Vec<ConstraintAtomV1>,
    semantic_ids: &mut BTreeSet<StableId>,
    id: StableId,
    class: ConstraintClass,
    axis: StableId,
    lower: FixedQ32,
    upper: FixedQ32,
    unit: StableId,
    evidence_source: StableId,
    origin_digest: Digest32,
) -> Result<(), ObjectiveAdmissionError> {
    if !semantic_ids.insert(id.clone()) {
        return Err(ObjectiveAdmissionError::Compiler(
            ObjectiveError::DuplicateSemanticId(id.to_string()),
        ));
    }
    registry
        .axes
        .entry(axis.clone())
        .or_insert_with(|| RegisteredAxisV1 {
            unit: unit.clone(),
            domain: RegisteredDomainV1::Scalar {
                lower: FixedQ32::from_raw(i64::MIN),
                upper: FixedQ32::from_raw(i64::MAX),
            },
        });
    registry.evidence_sources.insert(evidence_source.clone());
    atoms.push(ConstraintAtomV1 {
        id,
        precedence: AtomPrecedenceV1::Hard(class),
        axis,
        predicate: AtomPredicateV1::ScalarInterval { lower, upper },
        unit,
        evidence_source,
        terminality: PredicateTerminality::Intermediate,
        origin_digest,
    });
    Ok(())
}

fn scalar_interval_for_constraint(
    comparator: ObjectiveConstraintComparatorV1,
    bound: FixedQ32,
) -> Result<(FixedQ32, FixedQ32), ObjectiveAdmissionError> {
    match comparator {
        ObjectiveConstraintComparatorV1::Equal => Ok((bound, bound)),
        ObjectiveConstraintComparatorV1::LessThanOrEqual => {
            Ok((FixedQ32::from_raw(i64::MIN), bound))
        }
        ObjectiveConstraintComparatorV1::GreaterThanOrEqual => {
            Ok((bound, FixedQ32::from_raw(i64::MAX)))
        }
        ObjectiveConstraintComparatorV1::NotEqual
        | ObjectiveConstraintComparatorV1::LessThan
        | ObjectiveConstraintComparatorV1::GreaterThan
        | ObjectiveConstraintComparatorV1::In
        | ObjectiveConstraintComparatorV1::NotInSet => {
            Err(ObjectiveAdmissionError::UnsupportedComparator)
        }
    }
}

fn scaled_resource(
    value: u64,
    mapping: &ObjectiveResourceAxisProfileV1,
    field: &'static str,
) -> Result<FixedQ32, ObjectiveAdmissionError> {
    let raw = i128::from(value) * i128::from(mapping.q32_per_source_unit.raw());
    Ok(FixedQ32::from_raw(i64::try_from(raw).map_err(|_| {
        ObjectiveAdmissionError::ResourceOverflow(field)
    })?))
}

fn validate_lowered_nonconstraint_semantics(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    hard_atoms: &[ConstraintAtomV1],
) -> Result<(), ObjectiveAdmissionError> {
    // Match the native compiler's cross-kind semantic-id check before a hard
    // conflict can be published by the pre-compile feasibility gate.
    let mut semantic_ids = hard_atoms
        .iter()
        .map(|atom| atom.id.clone())
        .collect::<BTreeSet<_>>();

    for source in &envelope.structured_intent.success_predicates {
        validate_predicate_mapping(source, profile, /*must_be_terminal*/ false)?;
        insert_semantic_id(
            &mut semantic_ids,
            stable_id(&source.predicate_id, "predicateId")?,
        )?;
    }
    for source in &envelope.structured_intent.terminal_conditions {
        validate_predicate_mapping(source, profile, /*must_be_terminal*/ true)?;
        insert_semantic_id(
            &mut semantic_ids,
            stable_id(&source.predicate_id, "predicateId")?,
        )?;
    }
    for source in &envelope.structured_intent.evidence_requirements {
        let _mapping = profile
            .evidence_requirements
            .iter()
            .find(|mapping| mapping.source_requirement_id == source.requirement_id)
            .ok_or(ObjectiveAdmissionError::UnknownEvidenceRequirement)?;
        if source.minimum_confidence_ppm > 1_000_000 {
            return Err(ObjectiveAdmissionError::ResourceOverflow(
                "minimumConfidencePpm",
            ));
        }
        stable_id(&source.evidence_source_id, "requirement.evidenceSourceId")?;
        insert_semantic_id(
            &mut semantic_ids,
            stable_id(&source.requirement_id, "requirementId")?,
        )?;
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

    let mut native_legal_actions = BTreeSet::new();
    for source in &envelope.structured_intent.legal_action_classes {
        let mapping = action_mapping(profile, source)?;
        if !native_legal_actions.insert(mapping.action_id.clone()) {
            return Err(ObjectiveAdmissionError::Compiler(
                ObjectiveError::DuplicateSemanticId(mapping.action_id.to_string()),
            ));
        }
        if mapping.action_id.as_str() == ABSTAIN_ACTION_ID && confirmation.contains(source) {
            return Err(ObjectiveAdmissionError::Compiler(
                ObjectiveError::AbstainUnavailable,
            ));
        }
    }
    for source in &envelope.structured_intent.forbidden_action_classes {
        let mapping = action_mapping(profile, source)?;
        if mapping.action_id.as_str() == ABSTAIN_ACTION_ID {
            return Err(ObjectiveAdmissionError::Compiler(
                ObjectiveError::AbstainUnavailable,
            ));
        }
    }

    let mut native_dimensions = BTreeSet::new();
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
        if !native_dimensions.insert(mapping.dimension.clone()) {
            return Err(ObjectiveAdmissionError::Compiler(
                ObjectiveError::DuplicateSemanticId(mapping.dimension.to_string()),
            ));
        }
    }

    // The native compiler applies this authority invariant before feasibility.
    // Preserve that ordering so an untrusted source cannot receive a semantic
    // conflict receipt for authority it was never allowed to create.
    if envelope.source_trust_class == ObjectiveSourceTrustV1::UntrustedEvidence {
        let privileged_constraint = hard_atoms.iter().any(|atom| {
            !matches!(
                atom.precedence,
                AtomPrecedenceV1::Hard(ConstraintClass::Task)
            )
        });
        if privileged_constraint || !native_legal_actions.is_empty() {
            return Err(ObjectiveAdmissionError::Compiler(
                ObjectiveError::UntrustedAuthorityEscalation,
            ));
        }
    }

    // Request-id conversion happens during native adaptation before compile.
    stable_id(&envelope.request_id, "requestId")?;
    Ok(())
}

fn validate_predicate_mapping(
    source: &crate::ObjectiveSourcePredicateV1,
    profile: &ObjectiveAdmissionProfileV1,
    must_be_terminal: bool,
) -> Result<(), ObjectiveAdmissionError> {
    if source.terminal != must_be_terminal {
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
    stable_id(&source.evidence_source_id, "predicate.evidenceSourceId")?;
    match source.comparator {
        ObjectivePredicateComparatorV1::Equal
        | ObjectivePredicateComparatorV1::LessThanOrEqual
        | ObjectivePredicateComparatorV1::GreaterThanOrEqual => Ok(()),
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
) -> Result<&'a crate::ObjectiveActionProfileV1, ObjectiveAdmissionError> {
    profile
        .actions
        .iter()
        .find(|mapping| mapping.source_action_class == source)
        .ok_or(ObjectiveAdmissionError::UnknownAction)
}

fn insert_semantic_id(
    ids: &mut BTreeSet<StableId>,
    id: StableId,
) -> Result<(), ObjectiveAdmissionError> {
    if !ids.insert(id.clone()) {
        return Err(ObjectiveAdmissionError::Compiler(
            ObjectiveError::DuplicateSemanticId(id.to_string()),
        ));
    }
    Ok(())
}

fn admission_receipt(
    profile: &ObjectiveAdmissionProfileV1,
    prepared: PreparedAdmissionV1,
) -> ObjectiveAdmissionReceiptV1 {
    ObjectiveAdmissionReceiptV1 {
        profile_id: profile.profile_id.clone(),
        profile_revision: profile.profile_revision,
        profile_digest: prepared.profile_digest,
        supplied_source_digest: prepared.supplied_source_digest,
        intent_digest: prepared.intent_digest,
        admitted_source_digest: prepared.admitted_source_digest,
        observed_at_unix_micros: prepared.observed_at_unix_micros,
        deadline_unix_micros: prepared.deadline_unix_micros,
        authority: AuthorityPosture::DENY_ALL,
    }
}

fn conflict_receipt(
    envelope: &ObjectiveSourceEnvelopeV1,
    context: &ObjectiveAdmissionContextV1,
    admitted_source_digest: Digest32,
    mut conflicting_ids: Vec<StableId>,
) -> Result<ObjectiveConflictReceipt, ObjectiveAdmissionError> {
    let request_id = stable_id(&envelope.request_id, "requestId")?;
    conflicting_ids.sort();
    conflicting_ids.dedup();
    let mut bytes = Vec::new();
    bytes.extend_from_slice(CONFLICT_DIGEST_DOMAIN);
    push_id(&mut bytes, &request_id);
    push_u64(&mut bytes, context.revision.get());
    push_digest(&mut bytes, admitted_source_digest);
    push_len(&mut bytes, conflicting_ids.len());
    for id in &conflicting_ids {
        push_id(&mut bytes, id);
    }
    Ok(ObjectiveConflictReceipt {
        request_id,
        revision: context.revision,
        source_digest: admitted_source_digest,
        conflicting_ids,
        conflict_digest: Digest32::of_bytes(&bytes),
    })
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

fn source_trust_tag(value: ObjectiveSourceTrustV1) -> u8 {
    match value {
        ObjectiveSourceTrustV1::Principal => 0,
        ObjectiveSourceTrustV1::TrustedSystem => 1,
        ObjectiveSourceTrustV1::AuthorizedAdapter => 2,
        ObjectiveSourceTrustV1::UntrustedEvidence => 3,
    }
}

fn stable_id(value: &str, field: &'static str) -> Result<StableId, ObjectiveAdmissionError> {
    StableId::new(value.to_owned()).map_err(|_| ObjectiveAdmissionError::InvalidIdentifier(field))
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

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&u32::try_from(value).unwrap_or(u32::MAX).to_be_bytes());
}

// Keep these imports tied to the native lowering contract even though the gate
// only needs their enum values for parity checks above. This makes accidental
// drift between the gate and the native adapter visible to the compiler/lints.
const _: Option<ConfirmationPolicy> = None;
const _: Option<ObjectiveCompileReceipt> = None;
const _: Option<ObjectiveSoftDirectionV1> = None;
