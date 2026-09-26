//! Strict canonical ObjectiveFunctionV1 protocol projection.
//!
//! This module is the exported protocol boundary. It revalidates the complete
//! source/receipt relationship, enforces semantic set invariants on decode and
//! offers an authenticated product entrypoint that re-runs admission and native
//! compilation before publishing protocol bytes.

use std::cmp::Ordering;
use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::ConfirmationPolicy;
use crate::Constraint;
use crate::ConstraintClass;
use crate::ConstraintRelation;
use crate::ObjectiveAdmissionContextV1;
use crate::ObjectiveAdmissionProfileV1;
use crate::ObjectiveAdmissionReceiptV1;
use crate::ObjectiveCompileReceipt;
use crate::ObjectiveSourceEnvelopeV1;
use crate::ObjectiveSourceTrustV1;
use crate::PredicateTerminality;
use crate::SoftDirection;
use crate::SourceTrust;
use crate::SuccessPredicate;
use crate::admit_objective_v1;
use crate::canonical_native_objective_semantic_bytes_v1;
use crate::canonical_objective_intent_digest_v1;
use crate::compile_admitted_objective_v1;

pub const MAX_OBJECTIVE_FUNCTION_V1_BYTES: usize = 256 * 1024;
const MICROS_PER_SECOND: u64 = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveFunctionV1Artifact {
    canonical_bytes: Vec<u8>,
    protocol_digest: Digest32,
    native_semantic_digest: Digest32,
}

impl ObjectiveFunctionV1Artifact {
    #[must_use]
    pub fn canonical_bytes(&self) -> &[u8] {
        &self.canonical_bytes
    }

    #[must_use]
    pub const fn protocol_digest(&self) -> Digest32 {
        self.protocol_digest
    }

    #[must_use]
    pub const fn native_semantic_digest(&self) -> Digest32 {
        self.native_semantic_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecodedObjectiveFunctionV1 {
    canonical_bytes: Vec<u8>,
    protocol_digest: Digest32,
}

impl DecodedObjectiveFunctionV1 {
    #[must_use]
    pub fn canonical_bytes(&self) -> &[u8] {
        &self.canonical_bytes
    }

    #[must_use]
    pub const fn protocol_digest(&self) -> Digest32 {
        self.protocol_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ObjectiveFunctionV1Error {
    Json,
    NonCanonicalEncoding,
    Capacity,
    InvalidField(&'static str),
    ProjectionMismatch(&'static str),
}

impl fmt::Display for ObjectiveFunctionV1Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for ObjectiveFunctionV1Error {}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ObjectiveFunctionWireV1 {
    objective_id: String,
    request_digest: String,
    principal_scope: PrincipalScopeWireV1,
    success_predicates: Vec<PredicateWireV1>,
    terminal_conditions: Vec<PredicateWireV1>,
    hard_constraints: Vec<ConstraintWireV1>,
    evidence_requirements: Vec<EvidenceRequirementWireV1>,
    allowed_action_classes: Vec<ActionWireV1>,
    forbidden_action_classes: Vec<String>,
    soft_utility_dimensions: Vec<SoftDimensionWireV1>,
    resource_endowment: ResourceEndowmentWireV1,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    deadline_unix_ms: Option<u64>,
    revision: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PrincipalScopeWireV1 {
    scope_id: String,
    scope_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PredicateWireV1 {
    id: String,
    axis: String,
    relation: String,
    bound_q32: i64,
    evidence_source: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ConstraintWireV1 {
    id: String,
    class: String,
    axis: String,
    relation: String,
    bound_q32: i64,
    evidence_source: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceRequirementWireV1 {
    id: String,
    axis: String,
    minimum_confidence_ppm: u32,
    evidence_source: String,
    terminal: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ActionWireV1 {
    id: String,
    confirmation: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SoftDimensionWireV1 {
    dimension: String,
    direction: String,
    weight_q32: i64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ResourceEndowmentWireV1 {
    time_micros: u64,
    token_count: u64,
    compute_micros: u64,
    memory_bytes: u64,
    network_bytes: u64,
    external_effect_count: u32,
}

/// Encode a frozen admission into canonical protocol bytes.
///
/// This entrypoint re-computes every source field represented by the admission
/// receipt or protocol projection. Product callers that possess the original
/// authenticated context must use [`encode_authenticated_objective_function_v1`]
/// so the complete admission and native lowering are independently replayed.
pub(crate) fn encode_objective_function_v1(
    compiled: &ObjectiveCompileReceipt,
    source: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    admission: &ObjectiveAdmissionReceiptV1,
) -> Result<ObjectiveFunctionV1Artifact, ObjectiveFunctionV1Error> {
    validate_projection_binding(compiled, source, profile, admission)?;
    encode_validated(compiled, source, profile, admission)
}

/// Product-strength projection boundary.
///
/// Re-running authenticated admission and deterministic compilation prevents a
/// caller from combining source, profile, receipt and native output originating
/// from different operations, even if each object is individually well formed.
pub fn encode_authenticated_objective_function_v1(
    compiled: &ObjectiveCompileReceipt,
    source: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
    admission: &ObjectiveAdmissionReceiptV1,
) -> Result<ObjectiveFunctionV1Artifact, ObjectiveFunctionV1Error> {
    let admitted = admit_objective_v1(source, profile, context).map_err(|_| {
        ObjectiveFunctionV1Error::ProjectionMismatch("authenticated admission revalidation")
    })?;
    if admitted.receipt() != admission {
        return Err(ObjectiveFunctionV1Error::ProjectionMismatch(
            "authenticated admission receipt",
        ));
    }
    let rebound = compile_admitted_objective_v1(admitted).map_err(|_| {
        ObjectiveFunctionV1Error::ProjectionMismatch("authenticated native compilation")
    })?;
    let expected = rebound.compile_result.map_err(|_| {
        ObjectiveFunctionV1Error::ProjectionMismatch("compiled/conflict disposition")
    })?;
    if &expected != compiled {
        return Err(ObjectiveFunctionV1Error::ProjectionMismatch(
            "native objective lowering",
        ));
    }
    encode_objective_function_v1(compiled, source, profile, admission)
}

fn validate_projection_binding(
    compiled: &ObjectiveCompileReceipt,
    source: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    admission: &ObjectiveAdmissionReceiptV1,
) -> Result<(), ObjectiveFunctionV1Error> {
    source
        .validate_structure()
        .map_err(|_| ObjectiveFunctionV1Error::ProjectionMismatch("source structure"))?;
    let intent_digest = canonical_objective_intent_digest_v1(source)
        .map_err(|_| ObjectiveFunctionV1Error::ProjectionMismatch("source intent"))?;
    let profile_digest = profile
        .digest()
        .map_err(|_| ObjectiveFunctionV1Error::ProjectionMismatch("profile"))?;
    let observed_at_unix_micros = parse_utc_micros(&source.observed_at).ok_or(
        ObjectiveFunctionV1Error::ProjectionMismatch("observed timestamp"),
    )?;
    let deadline_unix_micros = source
        .deadline
        .as_deref()
        .map(|value| {
            parse_utc_micros(value).ok_or(ObjectiveFunctionV1Error::ProjectionMismatch(
                "deadline timestamp",
            ))
        })
        .transpose()?;

    if intent_digest != source.intent_digest
        || intent_digest != admission.intent_digest
        || profile_digest != admission.profile_digest
        || profile.profile_id != admission.profile_id
        || profile.profile_revision != admission.profile_revision
        || source.principal_scope_digest != profile.principal_scope_digest
        || source.input_schema_digest != profile.expected_input_schema_digest
        || source
            .structured_intent
            .provenance
            .normalization_profile_digest
            != profile.expected_normalization_profile_digest
        || source.structured_intent.provenance.source_digest != admission.supplied_source_digest
        || observed_at_unix_micros != admission.observed_at_unix_micros
        || deadline_unix_micros != admission.deadline_unix_micros
        || admission.authority.grants_any()
    {
        return Err(ObjectiveFunctionV1Error::ProjectionMismatch(
            "admission binding",
        ));
    }

    let objective = &compiled.objective;
    let expected_trust = match source.source_trust_class {
        ObjectiveSourceTrustV1::Principal => SourceTrust::PrincipalStructured,
        ObjectiveSourceTrustV1::TrustedSystem | ObjectiveSourceTrustV1::AuthorizedAdapter => {
            SourceTrust::RegisteredAdapter
        }
        ObjectiveSourceTrustV1::UntrustedEvidence => SourceTrust::UntrustedEvidence,
    };
    if objective.request_id.as_str() != source.request_id
        || objective.principal_scope != profile.principal_scope
        || objective.source_trust != expected_trust
        || objective.source_digest != admission.admitted_source_digest
        || objective.schema_digest != source.input_schema_digest
    {
        return Err(ObjectiveFunctionV1Error::ProjectionMismatch(
            "native objective identity",
        ));
    }
    let native_bytes = canonical_native_objective_semantic_bytes_v1(objective);
    if Digest32::of_bytes(&native_bytes) != objective.semantic_digest {
        return Err(ObjectiveFunctionV1Error::ProjectionMismatch(
            "native semantic digest",
        ));
    }
    Ok(())
}

fn encode_validated(
    compiled: &ObjectiveCompileReceipt,
    source: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    admission: &ObjectiveAdmissionReceiptV1,
) -> Result<ObjectiveFunctionV1Artifact, ObjectiveFunctionV1Error> {
    let objective = &compiled.objective;
    let evidence_ids = source
        .structured_intent
        .evidence_requirements
        .iter()
        .map(|value| value.requirement_id.as_str())
        .collect::<BTreeSet<_>>();
    let mut success_predicates = Vec::new();
    let mut terminal_conditions = Vec::new();
    for predicate in &objective.success_predicates {
        if evidence_ids.contains(predicate.id.as_str()) {
            continue;
        }
        let value = predicate_wire(predicate);
        match predicate.terminality {
            PredicateTerminality::Intermediate => success_predicates.push(value),
            PredicateTerminality::Terminal => terminal_conditions.push(value),
        }
    }

    let mut evidence_requirements = Vec::new();
    for source_requirement in &source.structured_intent.evidence_requirements {
        let predicate = objective
            .success_predicates
            .iter()
            .find(|value| value.id.as_str() == source_requirement.requirement_id)
            .ok_or(ObjectiveFunctionV1Error::ProjectionMismatch(
                "evidence requirement",
            ))?;
        let raw = (i128::from(source_requirement.minimum_confidence_ppm)
            * i128::from(FixedQ32::ONE.raw()))
            / 1_000_000_i128;
        let expected = i64::try_from(raw)
            .map_err(|_| ObjectiveFunctionV1Error::ProjectionMismatch("evidence bound"))?;
        let terminality = if source_requirement.terminal {
            PredicateTerminality::Terminal
        } else {
            PredicateTerminality::Intermediate
        };
        if predicate.bound.raw() != expected
            || predicate.evidence_source.as_str() != source_requirement.evidence_source_id
            || predicate.terminality != terminality
        {
            return Err(ObjectiveFunctionV1Error::ProjectionMismatch(
                "evidence lowering",
            ));
        }
        evidence_requirements.push(EvidenceRequirementWireV1 {
            id: predicate.id.to_string(),
            axis: predicate.axis.to_string(),
            minimum_confidence_ppm: source_requirement.minimum_confidence_ppm,
            evidence_source: predicate.evidence_source.to_string(),
            terminal: source_requirement.terminal,
        });
    }
    evidence_requirements.sort_by(|left, right| left.id.cmp(&right.id));

    let mut forbidden_action_classes = Vec::new();
    for source_action in &source.structured_intent.forbidden_action_classes {
        let mapping = profile
            .actions
            .iter()
            .find(|value| value.source_action_class == *source_action)
            .ok_or(ObjectiveFunctionV1Error::ProjectionMismatch(
                "forbidden action mapping",
            ))?;
        forbidden_action_classes.push(mapping.action_id.to_string());
    }
    forbidden_action_classes.sort();
    forbidden_action_classes.dedup();

    // ObjectiveFunctionV1 carries millisecond deadlines. Flooring is the
    // conservative deterministic projection: it never grants time beyond the
    // exact microsecond deadline retained in the admission/run-start record.
    let deadline_unix_ms = admission.deadline_unix_micros.map(|value| value / 1_000);

    let wire = ObjectiveFunctionWireV1 {
        objective_id: objective.request_id.to_string(),
        request_digest: admission.intent_digest.to_string(),
        principal_scope: PrincipalScopeWireV1 {
            scope_id: objective.principal_scope.to_string(),
            scope_digest: source.principal_scope_digest.to_string(),
        },
        success_predicates,
        terminal_conditions,
        hard_constraints: objective.constraints.iter().map(constraint_wire).collect(),
        evidence_requirements,
        allowed_action_classes: objective
            .legal_actions
            .iter()
            .map(|value| ActionWireV1 {
                id: value.id.to_string(),
                confirmation: match value.confirmation {
                    ConfirmationPolicy::NotRequired => "not_required",
                    ConfirmationPolicy::Required => "required",
                }
                .to_string(),
            })
            .collect(),
        forbidden_action_classes,
        soft_utility_dimensions: objective
            .soft_preferences
            .iter()
            .map(|value| SoftDimensionWireV1 {
                dimension: value.dimension.to_string(),
                direction: match value.direction {
                    SoftDirection::Maximize => "maximize",
                    SoftDirection::Minimize => "minimize",
                }
                .to_string(),
                weight_q32: value.weight.raw(),
            })
            .collect(),
        resource_endowment: ResourceEndowmentWireV1 {
            time_micros: source.structured_intent.resources.time_micros,
            token_count: source.structured_intent.resources.token_count,
            compute_micros: source.structured_intent.resources.compute_micros,
            memory_bytes: source.structured_intent.resources.memory_bytes,
            network_bytes: source.structured_intent.resources.network_bytes,
            external_effect_count: source.structured_intent.resources.external_effect_count,
        },
        deadline_unix_ms,
        revision: objective.revision.get(),
    };
    validate_wire(&wire)?;
    let canonical_bytes = serde_json::to_vec(&wire).map_err(|_| ObjectiveFunctionV1Error::Json)?;
    if canonical_bytes.len() > MAX_OBJECTIVE_FUNCTION_V1_BYTES {
        return Err(ObjectiveFunctionV1Error::Capacity);
    }
    let protocol_digest = Digest32::of_bytes(&canonical_bytes);
    let decoded = decode_objective_function_v1(&canonical_bytes)?;
    if decoded.protocol_digest != protocol_digest || decoded.canonical_bytes != canonical_bytes {
        return Err(ObjectiveFunctionV1Error::NonCanonicalEncoding);
    }
    Ok(ObjectiveFunctionV1Artifact {
        canonical_bytes,
        protocol_digest,
        native_semantic_digest: objective.semantic_digest,
    })
}

pub fn decode_objective_function_v1(
    input: &[u8],
) -> Result<DecodedObjectiveFunctionV1, ObjectiveFunctionV1Error> {
    if input.is_empty() || input.len() > MAX_OBJECTIVE_FUNCTION_V1_BYTES {
        return Err(ObjectiveFunctionV1Error::Capacity);
    }
    let value: ObjectiveFunctionWireV1 =
        serde_json::from_slice(input).map_err(|_| ObjectiveFunctionV1Error::Json)?;
    validate_wire(&value)?;
    let canonical = serde_json::to_vec(&value).map_err(|_| ObjectiveFunctionV1Error::Json)?;
    if canonical != input {
        return Err(ObjectiveFunctionV1Error::NonCanonicalEncoding);
    }
    Ok(DecodedObjectiveFunctionV1 {
        protocol_digest: Digest32::of_bytes(&canonical),
        canonical_bytes: canonical,
    })
}

fn validate_wire(value: &ObjectiveFunctionWireV1) -> Result<(), ObjectiveFunctionV1Error> {
    stable_id(&value.objective_id, "objectiveId")?;
    digest(&value.request_digest, "requestDigest")?;
    stable_id(&value.principal_scope.scope_id, "principalScope.scopeId")?;
    digest(
        &value.principal_scope.scope_digest,
        "principalScope.scopeDigest",
    )?;
    if value.hard_constraints.is_empty()
        || value.success_predicates.is_empty()
        || value.terminal_conditions.is_empty()
        || value.evidence_requirements.is_empty()
        || value.allowed_action_classes.is_empty()
    {
        return Err(ObjectiveFunctionV1Error::InvalidField(
            "required semantic collection",
        ));
    }
    if value.hard_constraints.len() > 256
        || value.success_predicates.len()
            + value.terminal_conditions.len()
            + value.evidence_requirements.len()
            > 128
        || value.allowed_action_classes.len() > 128
        || value.forbidden_action_classes.len() > 128
        || value.soft_utility_dimensions.len() > 64
    {
        return Err(ObjectiveFunctionV1Error::Capacity);
    }

    strictly_ordered(
        &value.success_predicates,
        |left, right| (&left.axis, &left.id).cmp(&(&right.axis, &right.id)),
        "success predicate order",
    )?;
    strictly_ordered(
        &value.terminal_conditions,
        |left, right| (&left.axis, &left.id).cmp(&(&right.axis, &right.id)),
        "terminal condition order",
    )?;
    strictly_ordered(
        &value.hard_constraints,
        |left, right| {
            (constraint_class_rank(&left.class), &left.axis, &left.id).cmp(&(
                constraint_class_rank(&right.class),
                &right.axis,
                &right.id,
            ))
        },
        "hard constraint order",
    )?;
    strictly_ordered(
        &value.evidence_requirements,
        |left, right| left.id.cmp(&right.id),
        "evidence requirement order",
    )?;
    strictly_ordered(
        &value.allowed_action_classes,
        |left, right| left.id.cmp(&right.id),
        "allowed action order",
    )?;
    strictly_ordered(
        &value.forbidden_action_classes,
        std::cmp::Ord::cmp,
        "forbidden action order",
    )?;
    strictly_ordered(
        &value.soft_utility_dimensions,
        |left, right| left.dimension.cmp(&right.dimension),
        "soft dimension order",
    )?;

    let mut semantic_ids = BTreeSet::new();
    for predicate in value
        .success_predicates
        .iter()
        .chain(value.terminal_conditions.iter())
    {
        stable_id(&predicate.id, "predicate.id")?;
        stable_id(&predicate.axis, "predicate.axis")?;
        stable_id(&predicate.evidence_source, "predicate.evidenceSource")?;
        relation(&predicate.relation)?;
        unique(
            &mut semantic_ids,
            &predicate.id,
            "semantic identity uniqueness",
        )?;
    }
    for constraint in &value.hard_constraints {
        stable_id(&constraint.id, "constraint.id")?;
        stable_id(&constraint.axis, "constraint.axis")?;
        stable_id(&constraint.evidence_source, "constraint.evidenceSource")?;
        relation(&constraint.relation)?;
        if constraint_class_rank(&constraint.class) == u8::MAX {
            return Err(ObjectiveFunctionV1Error::InvalidField("constraint.class"));
        }
        unique(
            &mut semantic_ids,
            &constraint.id,
            "semantic identity uniqueness",
        )?;
    }
    for evidence in &value.evidence_requirements {
        stable_id(&evidence.id, "evidence.id")?;
        stable_id(&evidence.axis, "evidence.axis")?;
        stable_id(&evidence.evidence_source, "evidence.evidenceSource")?;
        if evidence.minimum_confidence_ppm > 1_000_000 {
            return Err(ObjectiveFunctionV1Error::InvalidField(
                "evidence.minimumConfidencePpm",
            ));
        }
        unique(
            &mut semantic_ids,
            &evidence.id,
            "semantic identity uniqueness",
        )?;
    }

    let mut allowed = BTreeSet::new();
    let mut abstain_confirmation = None;
    for action in &value.allowed_action_classes {
        stable_id(&action.id, "action.id")?;
        match action.confirmation.as_str() {
            "not_required" | "required" => {}
            _ => {
                return Err(ObjectiveFunctionV1Error::InvalidField(
                    "action.confirmation",
                ));
            }
        }
        if action.id == "abstain" {
            abstain_confirmation = Some(action.confirmation.as_str());
        }
        allowed.insert(action.id.as_str());
    }
    if abstain_confirmation != Some("not_required") {
        return Err(ObjectiveFunctionV1Error::InvalidField("intrinsic abstain"));
    }

    for action in &value.forbidden_action_classes {
        stable_id(action, "forbiddenActionClasses")?;
        if action == "abstain" || allowed.contains(action.as_str()) {
            return Err(ObjectiveFunctionV1Error::InvalidField(
                "allowed/forbidden actions",
            ));
        }
    }

    for dimension in &value.soft_utility_dimensions {
        stable_id(&dimension.dimension, "soft.dimension")?;
        match dimension.direction.as_str() {
            "maximize" | "minimize" => {}
            _ => return Err(ObjectiveFunctionV1Error::InvalidField("soft.direction")),
        }
        if !(0..=FixedQ32::ONE.raw()).contains(&dimension.weight_q32) {
            return Err(ObjectiveFunctionV1Error::InvalidField("soft.weightQ32"));
        }
    }
    if value.revision == 0 || value.deadline_unix_ms == Some(0) {
        return Err(ObjectiveFunctionV1Error::InvalidField("revision/deadline"));
    }
    Ok(())
}

fn strictly_ordered<T>(
    values: &[T],
    mut compare: impl FnMut(&T, &T) -> Ordering,
    field: &'static str,
) -> Result<(), ObjectiveFunctionV1Error> {
    if values
        .windows(2)
        .any(|pair| compare(&pair[0], &pair[1]) != Ordering::Less)
    {
        return Err(ObjectiveFunctionV1Error::InvalidField(field));
    }
    Ok(())
}

fn unique<'a>(
    values: &mut BTreeSet<&'a str>,
    value: &'a str,
    field: &'static str,
) -> Result<(), ObjectiveFunctionV1Error> {
    if !values.insert(value) {
        return Err(ObjectiveFunctionV1Error::InvalidField(field));
    }
    Ok(())
}

fn predicate_wire(value: &SuccessPredicate) -> PredicateWireV1 {
    PredicateWireV1 {
        id: value.id.to_string(),
        axis: value.axis.to_string(),
        relation: relation_name(value.relation).to_string(),
        bound_q32: value.bound.raw(),
        evidence_source: value.evidence_source.to_string(),
    }
}

fn constraint_wire(value: &Constraint) -> ConstraintWireV1 {
    ConstraintWireV1 {
        id: value.id.to_string(),
        class: match value.class {
            ConstraintClass::Constitutional => "constitutional",
            ConstraintClass::Principal => "principal",
            ConstraintClass::Environment => "environment",
            ConstraintClass::Task => "task",
        }
        .to_string(),
        axis: value.axis.to_string(),
        relation: relation_name(value.relation).to_string(),
        bound_q32: value.bound.raw(),
        evidence_source: value.evidence_source.to_string(),
    }
}

const fn relation_name(value: ConstraintRelation) -> &'static str {
    match value {
        ConstraintRelation::AtLeast => "gte",
        ConstraintRelation::AtMost => "lte",
        ConstraintRelation::Equal => "eq",
    }
}

fn relation(value: &str) -> Result<(), ObjectiveFunctionV1Error> {
    match value {
        "gte" | "lte" | "eq" => Ok(()),
        _ => Err(ObjectiveFunctionV1Error::InvalidField("relation")),
    }
}

fn constraint_class_rank(value: &str) -> u8 {
    match value {
        "constitutional" => 0,
        "principal" => 1,
        "environment" => 2,
        "task" => 3,
        _ => u8::MAX,
    }
}

fn stable_id(value: &str, field: &'static str) -> Result<(), ObjectiveFunctionV1Error> {
    StableId::new(value)
        .map(|_| ())
        .map_err(|_| ObjectiveFunctionV1Error::InvalidField(field))
}

fn digest(value: &str, field: &'static str) -> Result<(), ObjectiveFunctionV1Error> {
    let value =
        Digest32::from_str(value).map_err(|_| ObjectiveFunctionV1Error::InvalidField(field))?;
    if value.is_zero() {
        return Err(ObjectiveFunctionV1Error::InvalidField(field));
    }
    Ok(())
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

#[cfg(test)]
#[path = "objective_function_v1_strict_tests.rs"]
mod tests;
