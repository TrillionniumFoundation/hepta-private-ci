//! Canonical JSON codecs for the registered prompt contracts and durable state.

use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::FactorAdmissionRecord;
use crate::FactorSource;
use crate::Lifecycle;
use crate::LifecycleEvent;
use crate::LifecycleEventKind;
use crate::MAX_RECORDS;
use crate::PromptFactor;
use crate::PromptRealization;
use crate::PromptRealizationBindingV2;
use crate::PromptRegistry;
use crate::PromptRoleV2;

const MAX_PROTOCOL_BYTES: usize = 262_144;
const MAX_DURABLE_STATE_BYTES: usize = 96 * 1024 * 1024;
const DURABLE_SCHEMA_V1: &str = "hepta.prompt-registry.durable.v1";
const DURABLE_SCHEMA_V0: &str = "hepta.prompt-registry.durable.v0";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptFactorV1 {
    pub factor_id: StableId,
    pub semantic_purpose: String,
    pub authority_class: String,
    pub eligible_objective_dimensions: Vec<StableId>,
    pub lifecycle: Lifecycle,
    pub revision: Revision,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRealizationV1 {
    pub factor_id: StableId,
    pub model_id: StableId,
    pub model_version: String,
    pub tokenizer_digest: Digest32,
    pub system_template_digest: Digest32,
    pub message_role: PromptRoleV2,
    pub payload_digest: Digest32,
    pub token_cost_upper_bound: u32,
    pub expires_unix_ms: Option<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptProtocolError {
    EncodedSizeExceeded,
    InvalidJson(String),
    InvalidIdentifier(&'static str),
    InvalidDigest(&'static str),
    InvalidField(&'static str),
    DuplicateObjectiveDimension(String),
    NonCanonical,
    UnsupportedStateVersion(u32),
    StateIntegrity(String),
}

impl std::fmt::Display for PromptProtocolError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for PromptProtocolError {}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct PromptFactorV1Wire {
    #[serde(rename = "factorId")]
    factor_id: String,
    #[serde(rename = "semanticPurpose")]
    semantic_purpose: String,
    #[serde(rename = "authorityClass")]
    authority_class: String,
    #[serde(rename = "eligibleObjectiveDimensions")]
    eligible_objective_dimensions: Vec<String>,
    lifecycle: String,
    revision: u64,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct PromptRealizationV1Wire {
    #[serde(rename = "factorId")]
    factor_id: String,
    #[serde(rename = "modelId")]
    model_id: String,
    #[serde(rename = "modelVersion")]
    model_version: String,
    #[serde(rename = "tokenizerDigest")]
    tokenizer_digest: String,
    #[serde(rename = "systemTemplateDigest")]
    system_template_digest: String,
    #[serde(rename = "messageRole")]
    message_role: String,
    #[serde(rename = "payloadDigest")]
    payload_digest: String,
    #[serde(rename = "tokenCostUpperBound")]
    token_cost_upper_bound: u32,
    #[serde(rename = "expiresUnixMs")]
    expires_unix_ms: Option<u64>,
}

pub fn encode_prompt_factor_v1(value: &PromptFactorV1) -> Result<Vec<u8>, PromptProtocolError> {
    validate_prompt_factor_v1(value)?;
    let wire = PromptFactorV1Wire {
        factor_id: value.factor_id.to_string(),
        semantic_purpose: value.semantic_purpose.clone(),
        authority_class: value.authority_class.clone(),
        eligible_objective_dimensions: value
            .eligible_objective_dimensions
            .iter()
            .map(ToString::to_string)
            .collect(),
        lifecycle: lifecycle_name(value.lifecycle).to_string(),
        revision: value.revision.get(),
    };
    encode_bounded_json(&wire)
}

pub fn decode_prompt_factor_v1(bytes: &[u8]) -> Result<PromptFactorV1, PromptProtocolError> {
    ensure_protocol_size(bytes)?;
    let wire: PromptFactorV1Wire = serde_json::from_slice(bytes)
        .map_err(|error| PromptProtocolError::InvalidJson(error.to_string()))?;
    let value = PromptFactorV1 {
        factor_id: parse_id("factorId", wire.factor_id)?,
        semantic_purpose: wire.semantic_purpose,
        authority_class: wire.authority_class,
        eligible_objective_dimensions: wire
            .eligible_objective_dimensions
            .into_iter()
            .map(|value| parse_id("eligibleObjectiveDimensions", value))
            .collect::<Result<Vec<_>, _>>()?,
        lifecycle: parse_lifecycle(&wire.lifecycle)?,
        revision: Revision::new(wire.revision)
            .map_err(|_| PromptProtocolError::InvalidField("revision"))?,
    };
    validate_prompt_factor_v1(&value)?;
    if encode_prompt_factor_v1(&value)? != bytes {
        return Err(PromptProtocolError::NonCanonical);
    }
    Ok(value)
}

pub fn encode_prompt_realization_v1(
    value: &PromptRealizationV1,
) -> Result<Vec<u8>, PromptProtocolError> {
    validate_prompt_realization_v1(value)?;
    let wire = PromptRealizationV1Wire {
        factor_id: value.factor_id.to_string(),
        model_id: value.model_id.to_string(),
        model_version: value.model_version.clone(),
        tokenizer_digest: value.tokenizer_digest.to_string(),
        system_template_digest: value.system_template_digest.to_string(),
        message_role: role_name(value.message_role).to_string(),
        payload_digest: value.payload_digest.to_string(),
        token_cost_upper_bound: value.token_cost_upper_bound,
        expires_unix_ms: value.expires_unix_ms,
    };
    encode_bounded_json(&wire)
}

pub fn decode_prompt_realization_v1(
    bytes: &[u8],
) -> Result<PromptRealizationV1, PromptProtocolError> {
    ensure_protocol_size(bytes)?;
    let wire: PromptRealizationV1Wire = serde_json::from_slice(bytes)
        .map_err(|error| PromptProtocolError::InvalidJson(error.to_string()))?;
    let value = PromptRealizationV1 {
        factor_id: parse_id("factorId", wire.factor_id)?,
        model_id: parse_id("modelId", wire.model_id)?,
        model_version: wire.model_version,
        tokenizer_digest: parse_digest("tokenizerDigest", &wire.tokenizer_digest)?,
        system_template_digest: parse_digest("systemTemplateDigest", &wire.system_template_digest)?,
        message_role: parse_role(&wire.message_role)?,
        payload_digest: parse_digest("payloadDigest", &wire.payload_digest)?,
        token_cost_upper_bound: wire.token_cost_upper_bound,
        expires_unix_ms: wire.expires_unix_ms,
    };
    validate_prompt_realization_v1(&value)?;
    if encode_prompt_realization_v1(&value)? != bytes {
        return Err(PromptProtocolError::NonCanonical);
    }
    Ok(value)
}

fn validate_prompt_factor_v1(value: &PromptFactorV1) -> Result<(), PromptProtocolError> {
    if value.semantic_purpose.is_empty() || value.semantic_purpose.len() > 4096 {
        return Err(PromptProtocolError::InvalidField("semanticPurpose"));
    }
    if value.authority_class.is_empty() || value.authority_class.len() > 64 {
        return Err(PromptProtocolError::InvalidField("authorityClass"));
    }
    let mut previous: Option<&StableId> = None;
    let mut encoded_bytes = 0_usize;
    for dimension in &value.eligible_objective_dimensions {
        encoded_bytes = encoded_bytes.saturating_add(dimension.as_str().len());
        if previous.is_some_and(|existing| existing >= dimension) {
            if previous == Some(dimension) {
                return Err(PromptProtocolError::DuplicateObjectiveDimension(
                    dimension.to_string(),
                ));
            }
            return Err(PromptProtocolError::InvalidField(
                "eligibleObjectiveDimensions",
            ));
        }
        previous = Some(dimension);
    }
    if encoded_bytes > 8192 {
        return Err(PromptProtocolError::InvalidField(
            "eligibleObjectiveDimensions",
        ));
    }
    Ok(())
}

fn validate_prompt_realization_v1(value: &PromptRealizationV1) -> Result<(), PromptProtocolError> {
    if value.model_version.is_empty() || value.model_version.len() > 256 {
        return Err(PromptProtocolError::InvalidField("modelVersion"));
    }
    if value.tokenizer_digest.is_zero() {
        return Err(PromptProtocolError::InvalidDigest("tokenizerDigest"));
    }
    if value.system_template_digest.is_zero() {
        return Err(PromptProtocolError::InvalidDigest("systemTemplateDigest"));
    }
    if value.payload_digest.is_zero() {
        return Err(PromptProtocolError::InvalidDigest("payloadDigest"));
    }
    if value.token_cost_upper_bound == 0 {
        return Err(PromptProtocolError::InvalidField("tokenCostUpperBound"));
    }
    if value.expires_unix_ms == Some(0) {
        return Err(PromptProtocolError::InvalidField("expiresUnixMs"));
    }
    Ok(())
}

fn encode_bounded_json<T: Serialize>(value: &T) -> Result<Vec<u8>, PromptProtocolError> {
    let bytes = serde_json::to_vec(value)
        .map_err(|error| PromptProtocolError::InvalidJson(error.to_string()))?;
    ensure_protocol_size(&bytes)?;
    Ok(bytes)
}

fn ensure_protocol_size(bytes: &[u8]) -> Result<(), PromptProtocolError> {
    if bytes.is_empty() || bytes.len() > MAX_PROTOCOL_BYTES {
        return Err(PromptProtocolError::EncodedSizeExceeded);
    }
    Ok(())
}

fn parse_id(field: &'static str, value: String) -> Result<StableId, PromptProtocolError> {
    StableId::new(value).map_err(|_| PromptProtocolError::InvalidIdentifier(field))
}

fn parse_digest(field: &'static str, value: &str) -> Result<Digest32, PromptProtocolError> {
    Digest32::from_str(value).map_err(|_| PromptProtocolError::InvalidDigest(field))
}

fn lifecycle_name(value: Lifecycle) -> &'static str {
    match value {
        Lifecycle::Draft => "draft",
        Lifecycle::Admitted => "admitted",
        Lifecycle::Retired => "retired",
        Lifecycle::Revoked => "revoked",
    }
}

fn parse_lifecycle(value: &str) -> Result<Lifecycle, PromptProtocolError> {
    match value {
        "draft" => Ok(Lifecycle::Draft),
        "admitted" => Ok(Lifecycle::Admitted),
        "retired" => Ok(Lifecycle::Retired),
        "revoked" => Ok(Lifecycle::Revoked),
        _ => Err(PromptProtocolError::InvalidField("lifecycle")),
    }
}

fn role_name(value: PromptRoleV2) -> &'static str {
    match value {
        PromptRoleV2::SystemInstruction => "system_instruction",
        PromptRoleV2::DeveloperInstruction => "developer_instruction",
        PromptRoleV2::UserTemplate => "user_template",
        PromptRoleV2::ToolSchemaFragment => "tool_schema_fragment",
    }
}

fn parse_role(value: &str) -> Result<PromptRoleV2, PromptProtocolError> {
    match value {
        "system_instruction" => Ok(PromptRoleV2::SystemInstruction),
        "developer_instruction" => Ok(PromptRoleV2::DeveloperInstruction),
        "user_template" => Ok(PromptRoleV2::UserTemplate),
        "tool_schema_fragment" => Ok(PromptRoleV2::ToolSchemaFragment),
        _ => Err(PromptProtocolError::InvalidField("messageRole")),
    }
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct DurableStateV1 {
    schema: String,
    #[serde(rename = "schemaVersion")]
    schema_version: u32,
    #[serde(rename = "maximumRecords")]
    maximum_records: u64,
    revision: u64,
    #[serde(rename = "lifecycleFrontier")]
    lifecycle_frontier: u64,
    #[serde(rename = "revocationFrontier")]
    revocation_frontier: u64,
    #[serde(rename = "registryDigest")]
    registry_digest: String,
    factors: Vec<FactorStateWire>,
    admissions: Vec<AdmissionStateWire>,
    #[serde(rename = "lifecycleHistory")]
    lifecycle_history: Vec<LifecycleEventStateWire>,
    realizations: Vec<RealizationStateWire>,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct FactorStateWire {
    #[serde(rename = "factorId")]
    factor_id: String,
    #[serde(rename = "proposerId")]
    proposer_id: String,
    #[serde(rename = "semanticVersion")]
    semantic_version: String,
    #[serde(rename = "contentDigest")]
    content_digest: String,
    source: String,
    lifecycle: String,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct AdmissionStateWire {
    #[serde(rename = "factorId")]
    factor_id: String,
    #[serde(rename = "reviewerId")]
    reviewer_id: String,
    #[serde(rename = "evidenceDigest")]
    evidence_digest: String,
    #[serde(rename = "reviewedScopeDigest")]
    reviewed_scope_digest: String,
    revision: u64,
    #[serde(rename = "admissionDigest")]
    admission_digest: String,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct LifecycleEventStateWire {
    #[serde(rename = "factorId")]
    factor_id: String,
    kind: String,
    from: Option<String>,
    to: String,
    revision: u64,
    #[serde(rename = "actorId")]
    actor_id: String,
    #[serde(rename = "evidenceDigest")]
    evidence_digest: Option<String>,
    #[serde(rename = "reviewedScopeDigest")]
    reviewed_scope_digest: Option<String>,
    #[serde(rename = "reasonDigest")]
    reason_digest: Option<String>,
    #[serde(rename = "cutoffUnixMs")]
    cutoff_unix_ms: Option<u64>,
    #[serde(rename = "eventDigest")]
    event_digest: String,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct RealizationStateWire {
    #[serde(rename = "realizationId")]
    realization_id: String,
    #[serde(rename = "factorId")]
    factor_id: String,
    #[serde(rename = "modelDigest")]
    model_digest: String,
    #[serde(rename = "tokenizerDigest")]
    tokenizer_digest: String,
    #[serde(rename = "contentDigest")]
    content_digest: String,
    active: bool,
    revision: u64,
    binding: Option<RealizationBindingStateWire>,
    #[serde(rename = "payloadHex")]
    payload_hex: Option<String>,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct RealizationBindingStateWire {
    #[serde(rename = "modelDigest")]
    model_digest: String,
    #[serde(rename = "tokenizerDigest")]
    tokenizer_digest: String,
    #[serde(rename = "templateDigest")]
    template_digest: String,
    #[serde(rename = "toolSchemaDigest")]
    tool_schema_digest: String,
    #[serde(rename = "contextProfileDigest")]
    context_profile_digest: String,
    #[serde(rename = "localeId")]
    locale_id: String,
    role: String,
    #[serde(rename = "payloadDigest")]
    payload_digest: String,
    #[serde(rename = "tokenCost")]
    token_cost: u32,
    #[serde(rename = "expiresUnixMs")]
    expires_unix_ms: Option<u64>,
    #[serde(rename = "predecessorRealizationId")]
    predecessor_realization_id: Option<String>,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct DurableStateV0 {
    schema: String,
    #[serde(rename = "schemaVersion")]
    schema_version: u32,
    #[serde(rename = "maximumRecords")]
    maximum_records: u64,
    factors: Vec<FactorStateWire>,
}

pub(crate) struct DecodedRegistryState {
    pub registry: PromptRegistry,
    pub migrated: bool,
}

pub(crate) fn encode_registry_state(
    registry: &PromptRegistry,
) -> Result<Vec<u8>, PromptProtocolError> {
    registry
        .validate_integrity()
        .map_err(|error| PromptProtocolError::StateIntegrity(error.to_string()))?;
    let factors = registry
        .factors
        .values()
        .map(|factor| FactorStateWire {
            factor_id: factor.factor_id.to_string(),
            proposer_id: factor.proposer_id.to_string(),
            semantic_version: factor.semantic_version.to_string(),
            content_digest: factor.content_digest.to_string(),
            source: factor_source_name(factor.source).to_string(),
            lifecycle: lifecycle_name(factor.lifecycle).to_string(),
        })
        .collect();
    let admissions = registry
        .admissions
        .values()
        .map(|record| AdmissionStateWire {
            factor_id: record.factor_id.to_string(),
            reviewer_id: record.reviewer_id.to_string(),
            evidence_digest: record.evidence_digest.to_string(),
            reviewed_scope_digest: record.reviewed_scope_digest.to_string(),
            revision: record.revision.get(),
            admission_digest: record.admission_digest.to_string(),
        })
        .collect();
    let lifecycle_history = registry
        .lifecycle_history
        .iter()
        .map(|event| LifecycleEventStateWire {
            factor_id: event.factor_id.to_string(),
            kind: lifecycle_event_kind_name(event.kind).to_string(),
            from: event.from.map(lifecycle_name).map(str::to_string),
            to: lifecycle_name(event.to).to_string(),
            revision: event.revision.get(),
            actor_id: event.actor_id.to_string(),
            evidence_digest: event.evidence_digest.as_ref().map(ToString::to_string),
            reviewed_scope_digest: event
                .reviewed_scope_digest
                .as_ref()
                .map(ToString::to_string),
            reason_digest: event.reason_digest.as_ref().map(ToString::to_string),
            cutoff_unix_ms: event.cutoff_unix_ms,
            event_digest: event.event_digest.to_string(),
        })
        .collect();
    let mut realizations = Vec::with_capacity(registry.realizations.len());
    for realization in registry.realizations.values() {
        let revision = registry
            .realization_revisions
            .get(&realization.realization_id)
            .ok_or_else(|| {
                PromptProtocolError::StateIntegrity(format!(
                    "missing realization revision: {}",
                    realization.realization_id
                ))
            })?;
        let binding = registry
            .realization_bindings
            .get(&realization.realization_id)
            .map(binding_to_wire);
        let payload_hex = registry
            .realization_payloads
            .get(&realization.realization_id)
            .map(|payload| encode_hex(payload));
        realizations.push(RealizationStateWire {
            realization_id: realization.realization_id.to_string(),
            factor_id: realization.factor_id.to_string(),
            model_digest: realization.model_digest.to_string(),
            tokenizer_digest: realization.tokenizer_digest.to_string(),
            content_digest: realization.content_digest.to_string(),
            active: realization.active,
            revision: revision.get(),
            binding,
            payload_hex,
        });
    }
    let state = DurableStateV1 {
        schema: DURABLE_SCHEMA_V1.to_string(),
        schema_version: 1,
        maximum_records: u64::try_from(registry.maximum_records)
            .map_err(|_| PromptProtocolError::InvalidField("maximumRecords"))?,
        revision: registry.revision.get(),
        lifecycle_frontier: registry.lifecycle_frontier,
        revocation_frontier: registry.revocation_frontier,
        registry_digest: registry.snapshot_digest().to_string(),
        factors,
        admissions,
        lifecycle_history,
        realizations,
    };
    let bytes = serde_json::to_vec(&state)
        .map_err(|error| PromptProtocolError::InvalidJson(error.to_string()))?;
    if bytes.len() > MAX_DURABLE_STATE_BYTES {
        return Err(PromptProtocolError::EncodedSizeExceeded);
    }
    Ok(bytes)
}

pub(crate) fn decode_registry_state(
    bytes: &[u8],
) -> Result<DecodedRegistryState, PromptProtocolError> {
    if bytes.is_empty() || bytes.len() > MAX_DURABLE_STATE_BYTES {
        return Err(PromptProtocolError::EncodedSizeExceeded);
    }
    let value: serde_json::Value = serde_json::from_slice(bytes)
        .map_err(|error| PromptProtocolError::InvalidJson(error.to_string()))?;
    let version = value
        .get("schemaVersion")
        .and_then(serde_json::Value::as_u64)
        .and_then(|value| u32::try_from(value).ok())
        .ok_or(PromptProtocolError::InvalidField("schemaVersion"))?;
    match version {
        0 => decode_registry_state_v0(bytes),
        1 => decode_registry_state_v1(bytes),
        other => Err(PromptProtocolError::UnsupportedStateVersion(other)),
    }
}

fn decode_registry_state_v1(bytes: &[u8]) -> Result<DecodedRegistryState, PromptProtocolError> {
    let state: DurableStateV1 = serde_json::from_slice(bytes)
        .map_err(|error| PromptProtocolError::InvalidJson(error.to_string()))?;
    if state.schema != DURABLE_SCHEMA_V1 || state.schema_version != 1 {
        return Err(PromptProtocolError::UnsupportedStateVersion(
            state.schema_version,
        ));
    }
    let maximum_records = usize::try_from(state.maximum_records)
        .map_err(|_| PromptProtocolError::InvalidField("maximumRecords"))?;
    if maximum_records == 0 || maximum_records > MAX_RECORDS {
        return Err(PromptProtocolError::InvalidField("maximumRecords"));
    }
    let revision =
        Revision::new(state.revision).map_err(|_| PromptProtocolError::InvalidField("revision"))?;
    let mut registry = PromptRegistry::new(maximum_records)
        .map_err(|error| PromptProtocolError::StateIntegrity(error.to_string()))?;
    registry.factors.clear();
    registry.realizations.clear();
    registry.realization_bindings.clear();
    registry.realization_payloads.clear();
    registry.realization_revisions.clear();
    registry.admissions.clear();
    registry.lifecycle_history.clear();
    registry.revision = revision;
    registry.lifecycle_frontier = state.lifecycle_frontier;
    registry.revocation_frontier = state.revocation_frontier;

    for wire in state.factors {
        let factor = PromptFactor {
            factor_id: parse_id("factorId", wire.factor_id)?,
            proposer_id: parse_id("proposerId", wire.proposer_id)?,
            semantic_version: parse_id("semanticVersion", wire.semantic_version)?,
            content_digest: parse_digest("contentDigest", &wire.content_digest)?,
            source: parse_factor_source(&wire.source)?,
            lifecycle: parse_lifecycle(&wire.lifecycle)?,
        };
        let factor_id = factor.factor_id.clone();
        if registry.factors.insert(factor_id.clone(), factor).is_some() {
            return Err(PromptProtocolError::StateIntegrity(format!(
                "duplicate factor: {factor_id}"
            )));
        }
    }
    for wire in state.admissions {
        let record = FactorAdmissionRecord {
            factor_id: parse_id("factorId", wire.factor_id)?,
            reviewer_id: parse_id("reviewerId", wire.reviewer_id)?,
            evidence_digest: parse_digest("evidenceDigest", &wire.evidence_digest)?,
            reviewed_scope_digest: parse_digest(
                "reviewedScopeDigest",
                &wire.reviewed_scope_digest,
            )?,
            revision: Revision::new(wire.revision)
                .map_err(|_| PromptProtocolError::InvalidField("revision"))?,
            admission_digest: parse_digest("admissionDigest", &wire.admission_digest)?,
        };
        let factor_id = record.factor_id.clone();
        if registry
            .admissions
            .insert(factor_id.clone(), record)
            .is_some()
        {
            return Err(PromptProtocolError::StateIntegrity(format!(
                "duplicate admission: {factor_id}"
            )));
        }
    }
    for wire in state.lifecycle_history {
        registry.lifecycle_history.push(LifecycleEvent {
            factor_id: parse_id("factorId", wire.factor_id)?,
            kind: parse_lifecycle_event_kind(&wire.kind)?,
            from: wire.from.as_deref().map(parse_lifecycle).transpose()?,
            to: parse_lifecycle(&wire.to)?,
            revision: Revision::new(wire.revision)
                .map_err(|_| PromptProtocolError::InvalidField("revision"))?,
            actor_id: parse_id("actorId", wire.actor_id)?,
            evidence_digest: wire
                .evidence_digest
                .as_deref()
                .map(|value| parse_digest("evidenceDigest", value))
                .transpose()?,
            reviewed_scope_digest: wire
                .reviewed_scope_digest
                .as_deref()
                .map(|value| parse_digest("reviewedScopeDigest", value))
                .transpose()?,
            reason_digest: wire
                .reason_digest
                .as_deref()
                .map(|value| parse_digest("reasonDigest", value))
                .transpose()?,
            cutoff_unix_ms: wire.cutoff_unix_ms,
            event_digest: parse_digest("eventDigest", &wire.event_digest)?,
        });
    }
    for wire in state.realizations {
        let realization_id = parse_id("realizationId", wire.realization_id)?;
        let factor_id = parse_id("factorId", wire.factor_id)?;
        let realization = PromptRealization {
            realization_id: realization_id.clone(),
            factor_id: factor_id.clone(),
            model_digest: parse_digest("modelDigest", &wire.model_digest)?,
            tokenizer_digest: parse_digest("tokenizerDigest", &wire.tokenizer_digest)?,
            content_digest: parse_digest("contentDigest", &wire.content_digest)?,
            active: wire.active,
        };
        let revision = Revision::new(wire.revision)
            .map_err(|_| PromptProtocolError::InvalidField("revision"))?;
        if registry
            .realizations
            .insert(realization_id.clone(), realization)
            .is_some()
        {
            return Err(PromptProtocolError::StateIntegrity(format!(
                "duplicate realization: {realization_id}"
            )));
        }
        registry
            .realization_revisions
            .insert(realization_id.clone(), revision);
        if let Some(binding_wire) = wire.binding {
            let binding = binding_from_wire(&realization_id, &factor_id, binding_wire)?;
            registry
                .realization_bindings
                .insert(realization_id.clone(), binding);
        }
        if let Some(payload_hex) = wire.payload_hex {
            registry
                .realization_payloads
                .insert(realization_id, decode_hex(&payload_hex)?);
        }
    }
    registry
        .validate_integrity()
        .map_err(|error| PromptProtocolError::StateIntegrity(error.to_string()))?;
    let expected_digest = parse_digest("registryDigest", &state.registry_digest)?;
    if registry.snapshot_digest() != expected_digest {
        return Err(PromptProtocolError::StateIntegrity(
            "registry digest mismatch".to_string(),
        ));
    }
    Ok(DecodedRegistryState {
        registry,
        migrated: false,
    })
}

fn decode_registry_state_v0(bytes: &[u8]) -> Result<DecodedRegistryState, PromptProtocolError> {
    let state: DurableStateV0 = serde_json::from_slice(bytes)
        .map_err(|error| PromptProtocolError::InvalidJson(error.to_string()))?;
    if state.schema != DURABLE_SCHEMA_V0 || state.schema_version != 0 {
        return Err(PromptProtocolError::UnsupportedStateVersion(
            state.schema_version,
        ));
    }
    let maximum_records = usize::try_from(state.maximum_records)
        .map_err(|_| PromptProtocolError::InvalidField("maximumRecords"))?;
    if maximum_records == 0 || maximum_records > MAX_RECORDS {
        return Err(PromptProtocolError::InvalidField("maximumRecords"));
    }
    let mut registry = PromptRegistry::new(maximum_records)
        .map_err(|error| PromptProtocolError::StateIntegrity(error.to_string()))?;
    for wire in state.factors {
        let lifecycle = parse_lifecycle(&wire.lifecycle)?;
        if lifecycle != Lifecycle::Draft {
            return Err(PromptProtocolError::StateIntegrity(
                "v0 migration may import only draft factors".to_string(),
            ));
        }
        let factor = PromptFactor {
            factor_id: parse_id("factorId", wire.factor_id)?,
            proposer_id: parse_id("proposerId", wire.proposer_id)?,
            semantic_version: parse_id("semanticVersion", wire.semantic_version)?,
            content_digest: parse_digest("contentDigest", &wire.content_digest)?,
            source: parse_factor_source(&wire.source)?,
            lifecycle,
        };
        registry
            .register_factor(factor)
            .map_err(|error| PromptProtocolError::StateIntegrity(error.to_string()))?;
    }
    Ok(DecodedRegistryState {
        registry,
        migrated: true,
    })
}

fn binding_to_wire(binding: &PromptRealizationBindingV2) -> RealizationBindingStateWire {
    RealizationBindingStateWire {
        model_digest: binding.model_digest.to_string(),
        tokenizer_digest: binding.tokenizer_digest.to_string(),
        template_digest: binding.template_digest.to_string(),
        tool_schema_digest: binding.tool_schema_digest.to_string(),
        context_profile_digest: binding.context_profile_digest.to_string(),
        locale_id: binding.locale_id.to_string(),
        role: role_name(binding.role).to_string(),
        payload_digest: binding.payload_digest.to_string(),
        token_cost: binding.token_cost,
        expires_unix_ms: binding.expires_unix_ms,
        predecessor_realization_id: binding
            .predecessor_realization_id
            .as_ref()
            .map(ToString::to_string),
    }
}

fn binding_from_wire(
    realization_id: &StableId,
    factor_id: &StableId,
    wire: RealizationBindingStateWire,
) -> Result<PromptRealizationBindingV2, PromptProtocolError> {
    let binding = PromptRealizationBindingV2 {
        realization_id: realization_id.clone(),
        factor_id: factor_id.clone(),
        model_digest: parse_digest("modelDigest", &wire.model_digest)?,
        tokenizer_digest: parse_digest("tokenizerDigest", &wire.tokenizer_digest)?,
        template_digest: parse_digest("templateDigest", &wire.template_digest)?,
        tool_schema_digest: parse_digest("toolSchemaDigest", &wire.tool_schema_digest)?,
        context_profile_digest: parse_digest("contextProfileDigest", &wire.context_profile_digest)?,
        locale_id: parse_id("localeId", wire.locale_id)?,
        role: parse_role(&wire.role)?,
        payload_digest: parse_digest("payloadDigest", &wire.payload_digest)?,
        token_cost: wire.token_cost,
        expires_unix_ms: wire.expires_unix_ms,
        predecessor_realization_id: wire
            .predecessor_realization_id
            .map(|value| parse_id("predecessorRealizationId", value))
            .transpose()?,
    };
    binding
        .validate()
        .map_err(|error| PromptProtocolError::StateIntegrity(error.to_string()))?;
    Ok(binding)
}

fn factor_source_name(value: FactorSource) -> &'static str {
    match value {
        FactorSource::GovernedInternal => "governed_internal",
        FactorSource::ExternalUntrusted => "external_untrusted",
    }
}

fn parse_factor_source(value: &str) -> Result<FactorSource, PromptProtocolError> {
    match value {
        "governed_internal" => Ok(FactorSource::GovernedInternal),
        "external_untrusted" => Ok(FactorSource::ExternalUntrusted),
        _ => Err(PromptProtocolError::InvalidField("source")),
    }
}

fn lifecycle_event_kind_name(value: LifecycleEventKind) -> &'static str {
    match value {
        LifecycleEventKind::Registered => "registered",
        LifecycleEventKind::Admitted => "admitted",
        LifecycleEventKind::Retired => "retired",
        LifecycleEventKind::Revoked => "revoked",
    }
}

fn parse_lifecycle_event_kind(value: &str) -> Result<LifecycleEventKind, PromptProtocolError> {
    match value {
        "registered" => Ok(LifecycleEventKind::Registered),
        "admitted" => Ok(LifecycleEventKind::Admitted),
        "retired" => Ok(LifecycleEventKind::Retired),
        "revoked" => Ok(LifecycleEventKind::Revoked),
        _ => Err(PromptProtocolError::InvalidField("lifecycle event kind")),
    }
}

fn encode_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len().saturating_mul(2));
    for byte in bytes {
        output.push(char::from(HEX[usize::from(*byte >> 4)]));
        output.push(char::from(HEX[usize::from(*byte & 0x0f)]));
    }
    output
}

fn decode_hex(value: &str) -> Result<Vec<u8>, PromptProtocolError> {
    if value.len() % 2 != 0 {
        return Err(PromptProtocolError::InvalidField("payloadHex"));
    }
    let bytes = value.as_bytes();
    let mut output = Vec::with_capacity(bytes.len() / 2);
    for index in (0..bytes.len()).step_by(2) {
        let high = decode_hex_nibble(bytes[index])
            .ok_or(PromptProtocolError::InvalidField("payloadHex"))?;
        let low = decode_hex_nibble(bytes[index + 1])
            .ok_or(PromptProtocolError::InvalidField("payloadHex"))?;
        output.push((high << 4) | low);
    }
    Ok(output)
}

fn decode_hex_nibble(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        _ => None,
    }
}

#[cfg(test)]
#[path = "protocol_tests.rs"]
mod tests;
