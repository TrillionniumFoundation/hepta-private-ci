//! One implemented representation adapter into the existing native Cell owner.
//! Explicit coordinate selection and F32-to-Q24 conversion do not assert that
//! a lossy projection preserves EG2/decoder quality or complete tensor meaning.

use std::collections::BTreeSet;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::CellEncodedInputV1;
use crate::CellEncodingRequestV1;
use crate::CellExecutionError;
use crate::CellInferenceReadbackPortV1;
use crate::CellInputEncoderV1;
use crate::CellScopeV1;
use crate::CellStateOwnerV1;
use crate::CellStepEntryV1;
use crate::CellStepInputV1;
use crate::InferredCellStepV1;
use crate::RegisteredCellBackendV1;
use crate::canonical_cell_step_request_digest_v1;
use crate::canonical_feature_vector_digest_v1;
use crate::cell::CellPreparationModeV1;
use crate::cell::prepare_from_snapshot;
use crate::cell_global_feature_schema_digest_v1;
use crate::cell_representation::CellRepresentationV1;
use crate::cell_representation::CellTensorValueV1;
use crate::cell_representation_negotiation::CellRepresentationEndpointUseV1;
use crate::cell_representation_negotiation::CellRepresentationNegotiationV1;
use crate::cell_representation_negotiation::CellRepresentationUseV1;
use crate::cell_representation_profile::CellRepresentationErrorV1;
use crate::cell_representation_profile::CellRepresentationKindV1;
use crate::cell_representation_profile::CellTensorDtypeV1;
use crate::enter_cell_step;
use crate::recover_cell_inference;

const PREFIX: &[u8] = b"hepta.cell.negotiated-native-input.v1\0";
const Q24: i64 = 1 << 24;

/// An ordered, explicit coordinate selection. Missing/out-of-range/non-finite
/// values are refused; there is no padding, clipping or implicit truncation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellGlobalQ24SelectionV1 {
    indices: Vec<u32>,
    parameters_digest: Digest32,
}

impl CellGlobalQ24SelectionV1 {
    pub fn new(indices: Vec<u32>) -> Result<Self, CellRepresentationErrorV1> {
        if indices.is_empty() || indices.len() > 512 {
            return Err(CellRepresentationErrorV1::Capacity);
        }
        if indices.iter().collect::<BTreeSet<_>>().len() != indices.len() {
            return Err(CellRepresentationErrorV1::InvalidProfile);
        }
        let mut bytes = b"hepta.cell.global-q24-selection-parameters.v1\0".to_vec();
        bytes.extend_from_slice(&(indices.len() as u64).to_be_bytes());
        for index in &indices {
            bytes.extend_from_slice(&index.to_be_bytes());
        }
        Ok(Self {
            indices: indices.into_boxed_slice().into_vec(),
            parameters_digest: Digest32::of_bytes(&bytes),
        })
    }

    pub fn parameters_digest(&self) -> Digest32 {
        self.parameters_digest
    }

    pub fn implementation_digest() -> Digest32 {
        Digest32::of_bytes(b"hepta.cell.global-q24-selection.v1\0contiguous-global;unique-ordered-u32-indices;signed-i64-q24-le-or-f32-le;all-inputs-finite-in-closed-[-8,8];f32-to-f64-times-2^24-round-ties-even;no-clip-pad-default;output-signed-i64-q24-le")
    }
}

/// Causal conversion evidence, not an execution or publication capability.
/// Model latency in the existing decision receipt does not measure projection
/// construction; callers must meter that phase separately for full-cost claims.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellRepresentationProjectionReceiptV1 {
    pub source_digest: Digest32,
    pub negotiation_digest: Digest32,
    pub component_digest: Digest32,
    pub parameters_digest: Digest32,
    pub quality_evidence_digest: Digest32,
    pub output_profile_digest: Digest32,
    pub output_digest: Digest32,
    pub source_payload_bytes: u64,
    pub output_payload_bytes: u64,
}

impl CellRepresentationProjectionReceiptV1 {
    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

/// Sealed projection plus the entire admitted source observation. V1 still
/// receives at most 512 Q24 values and uses its original state/receipt owners.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellNativeRepresentationInputV1 {
    backend_digest: Digest32,
    encoder_digest: Digest32,
    scope: CellScopeV1,
    source_frontier: Digest32,
    producer: CellRepresentationEndpointUseV1,
    consumer: CellRepresentationEndpointUseV1,
    observation: Vec<u8>,
    features: Vec<i64>,
    receipt: CellRepresentationProjectionReceiptV1,
}

impl CellNativeRepresentationInputV1 {
    /// Identify this reserved observation protocol for host routing. A prefix
    /// match is not proof of a valid projection or permission to consume it.
    pub fn is_representation_observation(observation: &[u8]) -> bool {
        observation.starts_with(PREFIX)
    }

    pub fn project(
        backend: &RegisteredCellBackendV1,
        negotiation: &CellRepresentationNegotiationV1,
        source: &CellRepresentationV1,
        current: &CellRepresentationUseV1,
        selection: &CellGlobalQ24SelectionV1,
    ) -> Result<Self, CellRepresentationErrorV1> {
        negotiation.validate_use(source, current)?;
        Self::project_frozen(backend, negotiation, source, selection)
    }

    /// Reconstruct only an exact original admitted/committed observation after
    /// restart. Historical pins need not still be current. This reads no model,
    /// writes no state and grants no fresh execution: entry and dispatch still
    /// require live owner observations. The source owner supplies the original
    /// raw input; a missing or changed admission cannot create a replacement.
    pub fn restore_admitted(
        backend: &RegisteredCellBackendV1,
        owner: &impl CellStateOwnerV1,
        negotiation: &CellRepresentationNegotiationV1,
        source: &CellRepresentationV1,
        selection: &CellGlobalQ24SelectionV1,
        input: &CellStepInputV1,
    ) -> Result<Self, CellExecutionError> {
        let definition = &backend.registration().definition;
        if input.observation.len() > definition.max_input_bytes
            || input.candidates.len() != definition.candidates.len()
        {
            return Err(CellExecutionError::CapacityExceeded);
        }
        let request_digest = canonical_cell_step_request_digest_v1(definition, input)?;
        let committed = match owner.lookup(&input.scope, &input.operation_id, request_digest) {
            Ok(receipt) => receipt,
            Err(CellExecutionError::InferencePending) => None,
            Err(error) => return Err(error),
        };
        let pending = if let Some(receipt) = committed {
            if receipt.operation_id != input.operation_id
                || receipt.semantic_request_digest != request_digest
                || receipt.scope != input.scope
                || receipt.bundle_digest != definition.bundle_digest
                || receipt.source_frontier != input.source_frontier
                || receipt.cost.consumed_input_bytes != input.observation.len()
                || receipt.cost.truncated_input_bytes != 0
                || receipt.authority != AuthorityPosture::DENY_ALL
            {
                return Err(CellExecutionError::OperationConflict);
            }
            None
        } else {
            let pending = owner
                .pending_inference(&input.scope)?
                .ok_or(CellExecutionError::InferenceNotAdmitted)?;
            if pending.operation_id != input.operation_id
                || pending.semantic_request_digest != request_digest
                || pending.deadline_micros != input.deadline_micros
            {
                return Err(CellExecutionError::OperationConflict);
            }
            if owner.snapshot(&input.scope)? != pending.snapshot {
                return Err(CellExecutionError::CommitConflict);
            }
            Some(pending)
        };
        let restored = Self::project_frozen(backend, negotiation, source, selection)
            .map_err(|_| CellExecutionError::EncodingMismatch)?;
        restored.validate_request(&CellEncodingRequestV1 {
            scope: &input.scope,
            source_frontier: input.source_frontier,
            encoder_digest: definition.runtime.encoder_digest,
            observation: &input.observation,
            checkpoint: None,
        })?;
        if let Some(pending) = pending {
            let prepared = prepare_from_snapshot(
                definition,
                pending.snapshot,
                &restored,
                input.clone(),
                pending.admitted_at_micros,
                CellPreparationModeV1::AdmittedRecovery,
            )?;
            if prepared.model_request != pending.model_request {
                return Err(CellExecutionError::OperationConflict);
            }
        }
        Ok(restored)
    }

    fn project_frozen(
        backend: &RegisteredCellBackendV1,
        negotiation: &CellRepresentationNegotiationV1,
        source: &CellRepresentationV1,
        selection: &CellGlobalQ24SelectionV1,
    ) -> Result<Self, CellRepresentationErrorV1> {
        use CellRepresentationErrorV1 as E;

        negotiation.check_source(source)?;
        let registration = backend.registration();
        let component = negotiation
            .projection
            .as_ref()
            .ok_or(E::ProjectionRequired)?;
        let width = registration.definition.runtime.input_feature_dimension;
        if negotiation.consumer.consumer_id != registration.backend_id
            || negotiation.consumer.binding_digest != backend.digest()
            || component.implementation_digest != CellGlobalQ24SelectionV1::implementation_digest()
            || component.parameters_digest != selection.parameters_digest()
            || !matches!(
                negotiation.input_profile.kind,
                CellRepresentationKindV1::GlobalVector
            )
            || !matches!(
                negotiation.output_profile.kind,
                CellRepresentationKindV1::GlobalVector
            )
            || negotiation.output_profile.semantic_schema_digest
                != cell_global_feature_schema_digest_v1(width).map_err(|_| E::Incompatible)?
            || negotiation.output_profile.tensors[0].dtype != CellTensorDtypeV1::SignedQ24Le
            || negotiation.output_profile.tensors[0].shape != vec![width as u64]
            || selection.indices.len() != width
        {
            return Err(E::Incompatible);
        }
        let output_payload_bytes = (width as u64) * 8;
        if output_payload_bytes > negotiation.consumer.max_payload_bytes {
            return Err(E::Capacity);
        }
        let observation_len = (PREFIX.len() + 128 + 24 + source.manifest().len()) as u64
            + source.payload_bytes()
            + output_payload_bytes;
        if observation_len > registration.definition.max_input_bytes as u64 {
            return Err(E::Capacity);
        }
        let layout = &source.profile().tensors[0];
        let CellTensorValueV1::Present(raw) = &source.tensors()[0] else {
            return Err(E::InvalidPayload);
        };
        let element_bytes = layout.dtype.element_bytes() as usize;
        for bytes in raw.chunks_exact(element_bytes) {
            decode_q24(bytes, layout.dtype)?;
        }
        let mut features = Vec::with_capacity(width);
        for index in &selection.indices {
            if u64::from(*index) >= layout.shape[0] {
                return Err(E::InvalidPayload);
            }
            let start = (*index as usize)
                .checked_mul(element_bytes)
                .ok_or(E::Capacity)?;
            let bytes = raw
                .get(start..start + element_bytes)
                .ok_or(E::InvalidPayload)?;
            features.push(decode_q24(bytes, layout.dtype)?);
        }
        let component_digest = component.digest()?;
        let encoder_digest = registration.definition.runtime.encoder_digest;
        let mut observation = Vec::with_capacity(observation_len as usize);
        observation.extend_from_slice(PREFIX);
        for digest in [
            backend.digest(),
            negotiation.digest(),
            component_digest,
            encoder_digest,
        ] {
            observation.extend_from_slice(digest.as_array());
        }
        observation.extend_from_slice(&(source.manifest().len() as u64).to_be_bytes());
        observation.extend_from_slice(source.manifest());
        observation.extend_from_slice(&(raw.len() as u64).to_be_bytes());
        observation.extend_from_slice(raw);
        observation.extend_from_slice(&(features.len() as u64).to_be_bytes());
        for value in &features {
            observation.extend_from_slice(&value.to_le_bytes());
        }
        let receipt = CellRepresentationProjectionReceiptV1 {
            source_digest: source.digest(),
            negotiation_digest: negotiation.digest(),
            component_digest,
            parameters_digest: selection.parameters_digest(),
            quality_evidence_digest: component.quality_evidence_digest,
            output_profile_digest: negotiation.output_profile.digest()?,
            output_digest: canonical_feature_vector_digest_v1(&features),
            source_payload_bytes: source.payload_bytes(),
            output_payload_bytes,
        };
        Ok(Self {
            backend_digest: backend.digest(),
            encoder_digest,
            scope: source.context().scope.clone(),
            source_frontier: source.context().source_frontier,
            producer: CellRepresentationEndpointUseV1 {
                endpoint_id: negotiation.producer.producer_id.clone(),
                generation: negotiation.producer.generation,
                binding_digest: negotiation.producer.binding_digest,
                contract_digest: negotiation.producer.digest()?,
            },
            consumer: CellRepresentationEndpointUseV1 {
                endpoint_id: negotiation.consumer.consumer_id.clone(),
                generation: negotiation.consumer.generation,
                binding_digest: negotiation.consumer.binding_digest,
                contract_digest: negotiation.consumer.digest()?,
            },
            observation,
            features,
            receipt,
        })
    }

    pub fn observation_bytes(&self) -> &[u8] {
        &self.observation
    }

    pub fn projection_receipt(&self) -> &CellRepresentationProjectionReceiptV1 {
        &self.receipt
    }

    /// Re-resolve the authenticated owners before fresh admission and again at
    /// actual dispatch if admission or queueing intervenes. This method compares
    /// observations only; it cannot authenticate the owner's identity or make a
    /// caller-supplied hash an access capability.
    pub fn validate_current_use(
        &self,
        backend: &RegisteredCellBackendV1,
        current: &CellRepresentationUseV1,
    ) -> Result<(), CellExecutionError> {
        self.validate_backend(backend)?;
        if current.scope != self.scope {
            return Err(CellExecutionError::ScopeMismatch);
        }
        if current.source_frontier != self.source_frontier || current.producer != self.producer {
            return Err(CellExecutionError::StaleSource);
        }
        if current.consumer != self.consumer {
            return Err(CellExecutionError::IncompatibleBundle);
        }
        Ok(())
    }

    /// Check the frozen backend identity even on historical readback. This does
    /// not establish that the backend or either endpoint is still current.
    pub fn validate_backend(
        &self,
        backend: &RegisteredCellBackendV1,
    ) -> Result<(), CellExecutionError> {
        if self.backend_digest != backend.digest() {
            return Err(CellExecutionError::IncompatibleBundle);
        }
        Ok(())
    }

    fn validate_request(
        &self,
        request: &CellEncodingRequestV1<'_>,
    ) -> Result<(), CellExecutionError> {
        if request.scope != &self.scope {
            return Err(CellExecutionError::ScopeMismatch);
        }
        if request.source_frontier != self.source_frontier {
            return Err(CellExecutionError::StaleSource);
        }
        if request.encoder_digest != self.encoder_digest || request.observation != self.observation
        {
            return Err(CellExecutionError::EncodingMismatch);
        }
        Ok(())
    }
}

impl CellInputEncoderV1 for CellNativeRepresentationInputV1 {
    fn encode(
        &self,
        request: &CellEncodingRequestV1<'_>,
    ) -> Result<CellEncodedInputV1, CellExecutionError> {
        self.validate_request(request)?;
        Ok(CellEncodedInputV1 {
            encoder_digest: self.encoder_digest,
            feature_vector_q24: self.features.clone(),
            consumed_bytes: self.observation.len(),
            truncated_bytes: 0,
        })
    }
}

impl RegisteredCellBackendV1 {
    /// The negotiation, component, complete source and projected values enter
    /// the original semantic request identity before inference admission. Fresh
    /// endpoint observations are required even when reusing a sealed projection.
    pub fn enter_representation(
        &self,
        owner: &impl CellStateOwnerV1,
        representation: &CellNativeRepresentationInputV1,
        current: &CellRepresentationUseV1,
        input: CellStepInputV1,
        now_micros: u64,
    ) -> Result<CellStepEntryV1, CellExecutionError> {
        representation.validate_current_use(self, current)?;
        representation.validate_request(&CellEncodingRequestV1 {
            scope: &input.scope,
            source_frontier: input.source_frontier,
            encoder_digest: self.registration().definition.runtime.encoder_digest,
            observation: &input.observation,
            checkpoint: None,
        })?;
        let snapshot = owner.snapshot(&input.scope)?;
        if snapshot.definition_digest != self.registration().definition.semantic_digest()? {
            return Err(CellExecutionError::IncompatibleBundle);
        }
        if snapshot.source_frontier != input.source_frontier {
            return Err(CellExecutionError::StaleSource);
        }
        enter_cell_step(
            &self.registration().definition,
            owner,
            representation,
            input,
            now_micros,
        )
    }

    /// Reconstruct and read back the original admission. UNKNOWN still owns
    /// its operation ID and reservation; this route cannot submit a new worker.
    /// Readback uses the original frozen pins, so later endpoint changes cannot
    /// erase an admitted fact or prevent its reconciliation. This is not fresh
    /// permission to consume the source or dispatch another computation.
    pub fn recover_representation(
        &self,
        owner: &impl CellStateOwnerV1,
        representation: &CellNativeRepresentationInputV1,
        input: CellStepInputV1,
        readback: &mut impl CellInferenceReadbackPortV1,
        now_micros: u64,
    ) -> Result<InferredCellStepV1, CellExecutionError> {
        representation.validate_backend(self)?;
        representation.validate_request(&CellEncodingRequestV1 {
            scope: &input.scope,
            source_frontier: input.source_frontier,
            encoder_digest: self.registration().definition.runtime.encoder_digest,
            observation: &input.observation,
            checkpoint: None,
        })?;
        recover_cell_inference(
            &self.registration().definition,
            owner,
            representation,
            input,
            readback,
            now_micros,
        )
    }
}

fn decode_q24(bytes: &[u8], dtype: CellTensorDtypeV1) -> Result<i64, CellRepresentationErrorV1> {
    use CellRepresentationErrorV1 as E;

    let value = match dtype {
        CellTensorDtypeV1::SignedQ24Le => {
            i64::from_le_bytes(bytes.try_into().map_err(|_| E::InvalidPayload)?)
        }
        CellTensorDtypeV1::F32Le => {
            let value = f64::from(f32::from_le_bytes(
                bytes.try_into().map_err(|_| E::InvalidPayload)?,
            ));
            if !value.is_finite() || !(-8.0..=8.0).contains(&value) {
                return Err(E::InvalidPayload);
            }
            (value * Q24 as f64).round_ties_even() as i64
        }
        CellTensorDtypeV1::U8
        | CellTensorDtypeV1::I32Le
        | CellTensorDtypeV1::I64Le
        | CellTensorDtypeV1::F16Le
        | CellTensorDtypeV1::F64Le => return Err(E::Incompatible),
    };
    if !(-8 * Q24..=8 * Q24).contains(&value) {
        return Err(E::InvalidPayload);
    }
    Ok(value)
}
