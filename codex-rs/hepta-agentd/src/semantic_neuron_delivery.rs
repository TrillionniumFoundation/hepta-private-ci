//! Durable product handoff from semantic retrieval into the existing Neuron
//! owner and canonical Agentd consumer.
//!
//! The semantic inference owner, Neuron owner and canonical intelligence runner
//! remain the only writers for their facts. This module carries one exact
//! completed semantic observation across those existing boundaries. It does not
//! execute Laya, issue authority, create another scheduler or acknowledge
//! delivery before the canonical product consumer returns.
//!
//! Preparation reads and validates the semantic result without holding the
//! semantic writer across model execution. After a crash, callers reconstruct
//! the same preparation from the durable semantic record and exact product
//! request. Neuron's durable tick identity prevents a second physical model
//! execution. Finalization revalidates current source/artifact authority and
//! only then persists the semantic delivery acknowledgement.

use std::error::Error as StdError;
use std::fmt;
use std::str::FromStr;

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::semantic::SemanticRecordV1;
use codex_hepta_infer_core::durable_control::Error as SemanticOwnerError;
use codex_hepta_intelligence::CanonicalIntelligenceRunRequestV1;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_neuron::SemanticNeuronFinalUseGuard;
use codex_hepta_neuron::SemanticNeuronProjectionError;
use codex_hepta_neuron::SemanticNeuronProjectionV1;
use codex_hepta_neuron::SemanticNeuronUseContextV1;
use codex_hepta_neuron::project_semantic_retrieval_to_neuron_v1;
use codex_hepta_types::Digest32;

use crate::AgentdIntelligenceOwnerInputsV1;
use crate::AgentdIntelligenceProductError;
use crate::AgentdIntelligenceProductOutcomeV1;
use crate::AgentdIntelligenceProductRunnerV1;
use crate::AgentdNeuronHandleV1;
use crate::AgentdNeuronInvocationV1;
use crate::RuntimeComposition;

#[derive(Debug)]
pub enum AgentdSemanticNeuronDeliveryError {
    SemanticOwner(SemanticOwnerError),
    Projection(SemanticNeuronProjectionError),
    Neuron(NeuronRuntimeError),
    Product(AgentdIntelligenceProductError),
    MissingOperation,
    BindingMismatch,
    InvalidAcknowledgement,
    ConflictingAcknowledgement,
}

impl fmt::Display for AgentdSemanticNeuronDeliveryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for AgentdSemanticNeuronDeliveryError {}

impl From<SemanticOwnerError> for AgentdSemanticNeuronDeliveryError {
    fn from(error: SemanticOwnerError) -> Self {
        Self::SemanticOwner(error)
    }
}

impl From<SemanticNeuronProjectionError> for AgentdSemanticNeuronDeliveryError {
    fn from(error: SemanticNeuronProjectionError) -> Self {
        Self::Projection(error)
    }
}

impl From<NeuronRuntimeError> for AgentdSemanticNeuronDeliveryError {
    fn from(error: NeuronRuntimeError) -> Self {
        Self::Neuron(error)
    }
}

impl From<AgentdIntelligenceProductError> for AgentdSemanticNeuronDeliveryError {
    fn from(error: AgentdIntelligenceProductError) -> Self {
        Self::Product(error)
    }
}

/// Historical observation that the semantic owner already acknowledged an exact
/// downstream delivery. It is not current permission to use the result again.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdSemanticNeuronHistoricalDeliveryV1 {
    pub operation_id: String,
    pub delivery_ack_digest: Digest32,
}

/// Preparation outcome. `AlreadyDelivered` never reconstructs a model
/// invocation and therefore cannot replay the semantic result.
pub enum AgentdSemanticNeuronDeliveryAdmissionV1 {
    Ready(PreparedAgentdSemanticNeuronDeliveryV1),
    AlreadyDelivered(AgentdSemanticNeuronHistoricalDeliveryV1),
}

/// Non-authorizing prepared handoff. Fields remain private so a caller cannot
/// substitute another semantic result, product request or Neuron invocation.
pub struct PreparedAgentdSemanticNeuronDeliveryV1 {
    operation_id: String,
    use_context: SemanticNeuronUseContextV1,
    projection: SemanticNeuronProjectionV1,
    request_binding_digest: Digest32,
    invocation: AgentdNeuronInvocationV1,
}

/// The canonical product consumer returned, but the semantic owner has not yet
/// persisted its delivery acknowledgement. A crash at this point is recovered
/// by preparing and consuming the same exact run again; the Neuron operation is
/// durable and idempotent under the same tick identity.
pub struct ConsumedAgentdSemanticNeuronDeliveryV1 {
    operation_id: String,
    use_context: SemanticNeuronUseContextV1,
    projection: SemanticNeuronProjectionV1,
    request_binding_digest: Digest32,
    product_outcome_digest: Digest32,
    product_outcome: AgentdIntelligenceProductOutcomeV1,
}

#[derive(Debug)]
pub struct AgentdSemanticNeuronDeliveredV1 {
    pub operation_id: String,
    pub delivery_ack_digest: Digest32,
    pub product_outcome: AgentdIntelligenceProductOutcomeV1,
}

/// Build one exact product invocation from a cloned durable semantic record.
/// The host can close the semantic owner before calling this function, so no
/// inference-writer lock is retained while Neuron or the product runner executes.
pub fn prepare_semantic_neuron_delivery_v1<G: SemanticNeuronFinalUseGuard>(
    record: &SemanticRecordV1,
    neuron: &AgentdNeuronHandleV1,
    operation_id: &str,
    use_context: SemanticNeuronUseContextV1,
    product_request: &CanonicalIntelligenceRunRequestV1,
    current_use_guard: &mut G,
) -> Result<AgentdSemanticNeuronDeliveryAdmissionV1, AgentdSemanticNeuronDeliveryError> {
    if use_context.operation_id != operation_id {
        return Err(AgentdSemanticNeuronDeliveryError::BindingMismatch);
    }
    if let Some(acknowledgement) = record.delivery_ack_digest.as_deref() {
        return Ok(AgentdSemanticNeuronDeliveryAdmissionV1::AlreadyDelivered(
            AgentdSemanticNeuronHistoricalDeliveryV1 {
                operation_id: operation_id.to_owned(),
                delivery_ack_digest: parse_digest(acknowledgement)?,
            },
        ));
    }

    let projection = project_semantic_retrieval_to_neuron_v1(
        record,
        use_context.clone(),
        current_use_guard,
    )?;
    validate_product_binding(&projection, product_request)?;
    let request_binding_digest = product_request_binding_digest(product_request)?;
    let invocation = neuron.prepare(
        product_request.run_id.clone(),
        runtime_body_digest(product_request),
        projection.input.clone(),
    )?;

    Ok(AgentdSemanticNeuronDeliveryAdmissionV1::Ready(
        PreparedAgentdSemanticNeuronDeliveryV1 {
            operation_id: operation_id.to_owned(),
            use_context,
            projection,
            request_binding_digest,
            invocation,
        },
    ))
}

impl PreparedAgentdSemanticNeuronDeliveryV1 {
    /// Execute the existing seven-owner canonical product path with the exact
    /// Neuron invocation produced by semantic delivery preparation.
    pub async fn consume_for_composition(
        self,
        runner: &AgentdIntelligenceProductRunnerV1,
        composition: &RuntimeComposition,
        product_request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
    ) -> Result<ConsumedAgentdSemanticNeuronDeliveryV1, AgentdSemanticNeuronDeliveryError> {
        if product_request_binding_digest(&product_request)? != self.request_binding_digest {
            return Err(AgentdSemanticNeuronDeliveryError::BindingMismatch);
        }
        validate_product_binding(&self.projection, &product_request)?;
        let outcome = runner
            .prepare_for_composition_with_durable_neuron(
                composition,
                product_request,
                inputs,
                self.invocation,
            )
            .await?;
        let product_outcome_digest =
            product_outcome_digest(&outcome, self.request_binding_digest);
        Ok(ConsumedAgentdSemanticNeuronDeliveryV1 {
            operation_id: self.operation_id,
            use_context: self.use_context,
            projection: self.projection,
            request_binding_digest: self.request_binding_digest,
            product_outcome_digest,
            product_outcome: outcome,
        })
    }
}

impl ConsumedAgentdSemanticNeuronDeliveryV1 {
    /// Re-read present source/artifact authority and persist the semantic
    /// delivery acknowledgement only after the actual product consumer returns.
    pub fn acknowledge<G: SemanticNeuronFinalUseGuard>(
        self,
        control: &mut DurableInferenceControl,
        current_use_guard: &mut G,
    ) -> Result<AgentdSemanticNeuronDeliveredV1, AgentdSemanticNeuronDeliveryError> {
        let record = control
            .semantic_record(&self.operation_id)?
            .cloned()
            .ok_or(AgentdSemanticNeuronDeliveryError::MissingOperation)?;
        let acknowledgement = delivery_ack_digest(
            &self.operation_id,
            self.request_binding_digest,
            self.product_outcome_digest,
            &self.projection,
        )?;
        if let Some(existing) = record.delivery_ack_digest.as_deref() {
            if parse_digest(existing)? != acknowledgement {
                return Err(AgentdSemanticNeuronDeliveryError::ConflictingAcknowledgement);
            }
            return Ok(AgentdSemanticNeuronDeliveredV1 {
                operation_id: self.operation_id,
                delivery_ack_digest: acknowledgement,
                product_outcome: self.product_outcome,
            });
        }

        let current_projection = project_semantic_retrieval_to_neuron_v1(
            &record,
            self.use_context.clone(),
            current_use_guard,
        )?;
        if current_projection != self.projection {
            return Err(AgentdSemanticNeuronDeliveryError::BindingMismatch);
        }

        let acknowledgement_text = acknowledgement.to_string();
        let acknowledged = control.acknowledge_semantic_delivery(
            &self.operation_id,
            acknowledgement_text.clone(),
        )?;
        if acknowledged.delivery_pending()
            || acknowledged.delivery_ack_digest.as_deref() != Some(acknowledgement_text.as_str())
        {
            return Err(AgentdSemanticNeuronDeliveryError::InvalidAcknowledgement);
        }

        Ok(AgentdSemanticNeuronDeliveredV1 {
            operation_id: self.operation_id,
            delivery_ack_digest: acknowledgement,
            product_outcome: self.product_outcome,
        })
    }
}

fn validate_product_binding(
    projection: &SemanticNeuronProjectionV1,
    request: &CanonicalIntelligenceRunRequestV1,
) -> Result<(), AgentdSemanticNeuronDeliveryError> {
    if projection.input.tick_id != request.run_id
        || projection.input.objective_digest != request.snapshot.objective_digest()
        || projection.input.body_generation != Some(request.snapshot.body_generation().get())
    {
        return Err(AgentdSemanticNeuronDeliveryError::BindingMismatch);
    }
    Ok(())
}

fn runtime_body_digest(request: &CanonicalIntelligenceRunRequestV1) -> Digest32 {
    let mut bytes = b"hepta.agentd.intelligence-body.v1\0".to_vec();
    bytes.extend_from_slice(request.snapshot.digest().as_array());
    bytes.extend_from_slice(&request.snapshot.body_generation().get().to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn product_request_binding_digest(
    request: &CanonicalIntelligenceRunRequestV1,
) -> Result<Digest32, AgentdSemanticNeuronDeliveryError> {
    let mut bytes = b"hepta.agentd.semantic-neuron-product-request.v1\0".to_vec();
    push_text(&mut bytes, request.run_id.as_str())?;
    bytes.extend_from_slice(request.snapshot.digest().as_array());
    bytes.extend_from_slice(request.snapshot.objective_digest().as_array());
    bytes.extend_from_slice(&request.snapshot.body_generation().get().to_be_bytes());
    push_text(&mut bytes, request.legal_candidates.candidate_set_id.as_str())?;
    bytes.extend_from_slice(request.legal_candidates.state_digest.as_array());
    push_text(&mut bytes, request.legal_candidates.generator_id.as_str())?;
    bytes.extend_from_slice(request.legal_candidates.grammar_digest.as_array());
    bytes.extend_from_slice(&request.legal_candidates.support_floor_ppm.to_be_bytes());
    push_len(&mut bytes, request.legal_candidates.candidates.len())?;
    for candidate in &request.legal_candidates.candidates {
        push_text(&mut bytes, candidate.candidate_id.as_str())?;
        bytes.extend_from_slice(candidate.support_digest.as_array());
    }
    for value in [
        request.budget.total_micros,
        request.budget.objective_micros,
        request.budget.utility_micros,
        request.budget.neural_micros,
        request.budget.prompt_micros,
        request.budget.intuition_micros,
        request.budget.context_micros,
        request.budget.evaluation_micros,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn product_outcome_digest(
    outcome: &AgentdIntelligenceProductOutcomeV1,
    request_binding_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.agentd.semantic-neuron-product-outcome.v1\0".to_vec();
    bytes.extend_from_slice(request_binding_digest.as_array());
    match outcome {
        AgentdIntelligenceProductOutcomeV1::Ready(prepared) => {
            bytes.push(0);
            bytes.extend_from_slice(prepared.envelope.envelope_digest.as_array());
            bytes.extend_from_slice(prepared.dispatch_proposal_digest.as_array());
        }
        AgentdIntelligenceProductOutcomeV1::Abstained => bytes.push(1),
        AgentdIntelligenceProductOutcomeV1::SlowPath => bytes.push(2),
    }
    Digest32::of_bytes(&bytes)
}

fn delivery_ack_digest(
    operation_id: &str,
    request_binding_digest: Digest32,
    product_outcome_digest: Digest32,
    projection: &SemanticNeuronProjectionV1,
) -> Result<Digest32, AgentdSemanticNeuronDeliveryError> {
    let mut bytes = b"hepta.agentd.semantic-neuron-delivery.v1\0".to_vec();
    push_text(&mut bytes, operation_id)?;
    bytes.extend_from_slice(request_binding_digest.as_array());
    bytes.extend_from_slice(product_outcome_digest.as_array());
    bytes.extend_from_slice(projection.semantic_request_digest.as_array());
    bytes.extend_from_slice(projection.semantic_reply_digest.as_array());
    bytes.extend_from_slice(projection.completion_digest.as_array());
    bytes.extend_from_slice(projection.provenance_digest.as_array());
    bytes.extend_from_slice(projection.input.semantic_digest()?.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

fn parse_digest(value: &str) -> Result<Digest32, AgentdSemanticNeuronDeliveryError> {
    let digest = Digest32::from_str(value)
        .map_err(|_| AgentdSemanticNeuronDeliveryError::InvalidAcknowledgement)?;
    if digest.is_zero() {
        return Err(AgentdSemanticNeuronDeliveryError::InvalidAcknowledgement);
    }
    Ok(digest)
}

fn push_text(
    bytes: &mut Vec<u8>,
    value: &str,
) -> Result<(), AgentdSemanticNeuronDeliveryError> {
    push_len(bytes, value.len())?;
    bytes.extend_from_slice(value.as_bytes());
    Ok(())
}

fn push_len(
    bytes: &mut Vec<u8>,
    length: usize,
) -> Result<(), AgentdSemanticNeuronDeliveryError> {
    let length =
        u64::try_from(length).map_err(|_| AgentdSemanticNeuronDeliveryError::BindingMismatch)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    Ok(())
}
