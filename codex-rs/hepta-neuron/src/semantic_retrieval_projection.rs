//! Exact final-use projection from one durable semantic-retrieval observation
//! into the existing numeric Neuron input profile.
//!
//! This module does not execute a model, grant source authority, acknowledge
//! delivery or install a second inference owner. The caller must provide a
//! trusted current-use guard. A projection is returned only for the complete,
//! unacknowledged result owned by `DurableInferenceControl`, after exact source,
//! generation, objective, bundle, authority and deadline binding.

use std::error::Error as StdError;
use std::fmt;
use std::str::FromStr;

use codex_hepta_infer_core::RetrievalWireError;
use codex_hepta_infer_core::SemanticRetrievalReplyV1;
use codex_hepta_infer_core::SemanticRetrievalRequestV1;
use codex_hepta_infer_core::durable_control::semantic::SemanticRecordV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::NeuronRuntimeError;
use crate::NeuronTickInputV1;
use crate::canonical_feature_vector_digest_v1;

const PPM: u64 = 1_000_000;
const Q24_ONE: u64 = 1 << 24;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SemanticNeuronSourceBindingV1 {
    pub source_id: String,
    pub revision: u64,
    pub content_sha256: String,
}

/// Facts re-read at the actual downstream-use boundary. Constructing this
/// value is not authority: the product host must still install a trusted
/// `SemanticNeuronFinalUseGuard` that verifies these facts against their owners.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SemanticNeuronUseContextV1 {
    pub operation_id: String,
    pub workspace_id: String,
    pub semantic_generation: u64,
    pub authority_binding_digest: String,
    pub objective_digest: Digest32,
    pub observation_digest: Digest32,
    pub bundle_digest: Digest32,
    pub current_sources: Vec<SemanticNeuronSourceBindingV1>,
    pub now_ms: u64,
    pub tick_id: StableId,
    pub subject_id: StableId,
    pub logical_sequence: u64,
    pub monotonic_time_micros: u64,
    pub checkpoint_digest: Digest32,
    pub ndu_snapshot_digest: Digest32,
    pub body_generation: u64,
    pub modulator_digest: Option<Digest32>,
}

/// Trusted product-host seam. Implementations must re-read present authority,
/// source revisions and artifact state; a cached historical allow decision is
/// not a valid implementation.
pub trait SemanticNeuronFinalUseGuard {
    fn check(
        &mut self,
        record: &SemanticRecordV1,
        request: &SemanticRetrievalRequestV1,
        reply: &SemanticRetrievalReplyV1,
        context: &SemanticNeuronUseContextV1,
    ) -> Result<(), SemanticNeuronProjectionError>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SemanticNeuronProjectionV1 {
    pub input: NeuronTickInputV1,
    /// Abstain first, followed by source IDs in ASCII order, matching HPTARS V1.
    pub feature_order: Vec<String>,
    pub semantic_request_digest: Digest32,
    pub semantic_reply_digest: Digest32,
    pub completion_digest: Digest32,
    /// Binds the exact owner observation, current-use facts and projected tick.
    /// It is evidence identity, not an authorization or delivery receipt.
    pub provenance_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SemanticNeuronProjectionError {
    NotDeliverable,
    MissingCompletion,
    CorruptCompletion,
    BindingMismatch,
    StaleSource,
    Expired,
    Revoked,
    CurrentnessUnavailable,
    InvalidContext,
    Arithmetic,
    Wire(RetrievalWireError),
    Neuron(NeuronRuntimeError),
}

impl fmt::Display for SemanticNeuronProjectionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for SemanticNeuronProjectionError {}

impl From<RetrievalWireError> for SemanticNeuronProjectionError {
    fn from(error: RetrievalWireError) -> Self {
        Self::Wire(error)
    }
}

impl From<NeuronRuntimeError> for SemanticNeuronProjectionError {
    fn from(error: NeuronRuntimeError) -> Self {
        Self::Neuron(error)
    }
}

pub fn project_semantic_retrieval_to_neuron_v1<G: SemanticNeuronFinalUseGuard>(
    record: &SemanticRecordV1,
    context: SemanticNeuronUseContextV1,
    guard: &mut G,
) -> Result<SemanticNeuronProjectionV1, SemanticNeuronProjectionError> {
    if !record.delivery_pending() {
        return Err(SemanticNeuronProjectionError::NotDeliverable);
    }
    let completion = record
        .completion
        .as_ref()
        .ok_or(SemanticNeuronProjectionError::MissingCompletion)?;
    let completion_digest = record
        .completion_digest
        .as_deref()
        .ok_or(SemanticNeuronProjectionError::MissingCompletion)
        .and_then(parse_digest)?;
    let encoded_completion = serde_json::to_vec(completion)
        .map_err(|_| SemanticNeuronProjectionError::CorruptCompletion)?;
    if Digest32::of_bytes(&encoded_completion) != completion_digest {
        return Err(SemanticNeuronProjectionError::CorruptCompletion);
    }

    let request = SemanticRetrievalRequestV1::decode(&record.admission.request_wire)?;
    let reply = request.decode_reply(&completion.reply_wire)?;
    validate_current_use(record, &request, &context)?;
    guard.check(record, &request, &reply, &context)?;

    let feature_vector_q24 = ppm_to_exact_q24(&reply.prediction_ppm)?;
    let input_feature_digest = canonical_feature_vector_digest_v1(&feature_vector_q24);
    let input = NeuronTickInputV1 {
        tick_id: context.tick_id.clone(),
        subject_id: context.subject_id.clone(),
        logical_sequence: context.logical_sequence,
        monotonic_time_micros: context.monotonic_time_micros,
        checkpoint_digest: context.checkpoint_digest,
        input_feature_digest,
        feature_vector_q24,
        objective_digest: context.objective_digest,
        ndu_snapshot_digest: context.ndu_snapshot_digest,
        body_generation: Some(context.body_generation),
        modulator_digest: context.modulator_digest,
    };
    let input_digest = input.semantic_digest()?;

    let current_sources = canonical_source_bindings(&context.current_sources)?;
    let mut feature_order = Vec::with_capacity(current_sources.len() + 1);
    feature_order.push("abstain".to_string());
    feature_order.extend(
        current_sources
            .iter()
            .map(|source| source.source_id.clone()),
    );
    if feature_order.len() != reply.prediction_ppm.len() {
        return Err(SemanticNeuronProjectionError::BindingMismatch);
    }

    let semantic_reply_digest = Digest32::of_bytes(&completion.reply_wire);
    let provenance_digest = projection_provenance_digest(
        record,
        &record.admission.request_wire,
        &completion.reply_wire,
        completion_digest,
        input_digest,
        &context,
        &current_sources,
    )?;

    Ok(SemanticNeuronProjectionV1 {
        input,
        feature_order,
        semantic_request_digest: reply.request_digest,
        semantic_reply_digest,
        completion_digest,
        provenance_digest,
    })
}

fn validate_current_use(
    record: &SemanticRecordV1,
    request: &SemanticRetrievalRequestV1,
    context: &SemanticNeuronUseContextV1,
) -> Result<(), SemanticNeuronProjectionError> {
    if context.now_ms == 0
        || context.body_generation == 0
        || context.objective_digest.is_zero()
        || context.observation_digest.is_zero()
        || context.bundle_digest.is_zero()
        || context.ndu_snapshot_digest.is_zero()
        || context.modulator_digest.is_some_and(Digest32::is_zero)
    {
        return Err(SemanticNeuronProjectionError::InvalidContext);
    }
    if context.now_ms >= request.deadline_ms {
        return Err(SemanticNeuronProjectionError::Expired);
    }
    if request.operation_id != context.operation_id
        || request.workspace_id != context.workspace_id
        || request.generation != context.semantic_generation
        || record.admission.authority_binding_digest != context.authority_binding_digest
        || parse_digest(&request.objective_digest)? != context.objective_digest
        || parse_digest(&request.observation_digest)? != context.observation_digest
        || parse_digest(&request.bundle_digest)? != context.bundle_digest
        || parse_digest(&record.admission.authority_binding_digest)?.is_zero()
    {
        return Err(SemanticNeuronProjectionError::BindingMismatch);
    }

    let expected = request
        .sources
        .iter()
        .map(|source| SemanticNeuronSourceBindingV1 {
            source_id: source.source_id.clone(),
            revision: source.revision,
            content_sha256: source.content_sha256.clone(),
        })
        .collect::<Vec<_>>();
    if canonical_source_bindings(&expected)? != canonical_source_bindings(&context.current_sources)?
    {
        return Err(SemanticNeuronProjectionError::StaleSource);
    }
    Ok(())
}

fn canonical_source_bindings(
    sources: &[SemanticNeuronSourceBindingV1],
) -> Result<Vec<SemanticNeuronSourceBindingV1>, SemanticNeuronProjectionError> {
    if sources.is_empty() || sources.len() > 15 {
        return Err(SemanticNeuronProjectionError::InvalidContext);
    }
    let mut canonical = sources.to_vec();
    canonical.sort_by(|left, right| left.source_id.cmp(&right.source_id));
    let mut previous: Option<&str> = None;
    for source in &canonical {
        if source.source_id.is_empty()
            || source.revision == 0
            || parse_digest(&source.content_sha256)?.is_zero()
            || previous == Some(source.source_id.as_str())
        {
            return Err(SemanticNeuronProjectionError::InvalidContext);
        }
        previous = Some(source.source_id.as_str());
    }
    Ok(canonical)
}

fn ppm_to_exact_q24(values: &[u32]) -> Result<Vec<i64>, SemanticNeuronProjectionError> {
    if values.is_empty() || values.len() > 16 {
        return Err(SemanticNeuronProjectionError::BindingMismatch);
    }
    let total = values
        .iter()
        .try_fold(0_u64, |sum, value| sum.checked_add(u64::from(*value)));
    if total != Some(PPM) {
        return Err(SemanticNeuronProjectionError::BindingMismatch);
    }

    let mut projected = Vec::with_capacity(values.len());
    let mut remainders = Vec::with_capacity(values.len());
    let mut assigned = 0_u64;
    for (index, value) in values.iter().copied().enumerate() {
        let product = u64::from(value)
            .checked_mul(Q24_ONE)
            .ok_or(SemanticNeuronProjectionError::Arithmetic)?;
        let base = product / PPM;
        assigned = assigned
            .checked_add(base)
            .ok_or(SemanticNeuronProjectionError::Arithmetic)?;
        projected.push(i64::try_from(base).map_err(|_| SemanticNeuronProjectionError::Arithmetic)?);
        remainders.push((product % PPM, index));
    }
    let residual = Q24_ONE
        .checked_sub(assigned)
        .ok_or(SemanticNeuronProjectionError::Arithmetic)?;
    remainders.sort_by(|left, right| right.0.cmp(&left.0).then_with(|| left.1.cmp(&right.1)));
    for (_, index) in remainders
        .into_iter()
        .take(usize::try_from(residual).map_err(|_| SemanticNeuronProjectionError::Arithmetic)?)
    {
        projected[index] = projected[index]
            .checked_add(1)
            .ok_or(SemanticNeuronProjectionError::Arithmetic)?;
    }
    if projected.iter().copied().sum::<i64>()
        != i64::try_from(Q24_ONE).map_err(|_| SemanticNeuronProjectionError::Arithmetic)?
    {
        return Err(SemanticNeuronProjectionError::Arithmetic);
    }
    Ok(projected)
}

#[allow(clippy::too_many_arguments)]
fn projection_provenance_digest(
    record: &SemanticRecordV1,
    request_wire: &[u8],
    reply_wire: &[u8],
    completion_digest: Digest32,
    input_digest: Digest32,
    context: &SemanticNeuronUseContextV1,
    current_sources: &[SemanticNeuronSourceBindingV1],
) -> Result<Digest32, SemanticNeuronProjectionError> {
    let mut bytes = b"hepta.neuron.semantic-retrieval-projection.v1\0".to_vec();
    push_bytes(&mut bytes, request_wire)?;
    push_bytes(&mut bytes, reply_wire)?;
    bytes.extend_from_slice(&record.revision.to_be_bytes());
    bytes.extend_from_slice(&record.admitted_at_ms.to_be_bytes());
    push_text(&mut bytes, &record.admission.principal_id)?;
    push_text(&mut bytes, &record.admission.reservation_id)?;
    push_text(&mut bytes, &record.admission.worker_id)?;
    bytes.extend_from_slice(&record.admission.worker_generation.to_be_bytes());
    bytes.extend_from_slice(&record.admission.maximum_tokens.to_be_bytes());
    bytes.extend_from_slice(&record.admission.maximum_memory_bytes.to_be_bytes());
    bytes.extend_from_slice(parse_digest(&record.admission.authority_binding_digest)?.as_array());
    match &record.resource_limits {
        Some(limits) => {
            bytes.push(1);
            push_text(&mut bytes, &limits.model_id)?;
            bytes.extend_from_slice(&limits.resident_bytes.to_be_bytes());
            bytes.extend_from_slice(&limits.kv_bytes.to_be_bytes());
            bytes.extend_from_slice(&limits.transient_bytes.to_be_bytes());
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(completion_digest.as_array());
    bytes.extend_from_slice(input_digest.as_array());
    bytes.extend_from_slice(&context.now_ms.to_be_bytes());
    bytes.extend_from_slice(&context.body_generation.to_be_bytes());
    for source in current_sources {
        push_text(&mut bytes, &source.source_id)?;
        bytes.extend_from_slice(&source.revision.to_be_bytes());
        bytes.extend_from_slice(parse_digest(&source.content_sha256)?.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn parse_digest(value: &str) -> Result<Digest32, SemanticNeuronProjectionError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(SemanticNeuronProjectionError::BindingMismatch);
    }
    let digest =
        Digest32::from_str(value).map_err(|_| SemanticNeuronProjectionError::BindingMismatch)?;
    if digest.is_zero() {
        return Err(SemanticNeuronProjectionError::BindingMismatch);
    }
    Ok(digest)
}

fn push_text(bytes: &mut Vec<u8>, value: &str) -> Result<(), SemanticNeuronProjectionError> {
    push_bytes(bytes, value.as_bytes())
}

fn push_bytes(bytes: &mut Vec<u8>, value: &[u8]) -> Result<(), SemanticNeuronProjectionError> {
    let length =
        u64::try_from(value.len()).map_err(|_| SemanticNeuronProjectionError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value);
    Ok(())
}

#[cfg(test)]
#[path = "semantic_retrieval_projection_tests.rs"]
mod tests;
