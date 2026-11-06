//! Bind functional contracts and replaceable backend families to native Cells.
//!
//! This opt-in numeric execution profile resolves immutable declarations. It
//! neither loads models nor authenticates artifacts, sources or owner custody.
//! Family/role membership is not evidence of behavioral quality or deployment.

use std::collections::BTreeMap;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CellCapabilityContractV1;
use crate::CellDefinitionV1;
use crate::CellEncodedInputV1;
use crate::CellEncodingRequestV1;
use crate::CellExecutionError;
use crate::CellExpertVersionV1;
use crate::CellGlobalFeatureProjectionV1;
use crate::CellInferenceReadbackPortV1;
use crate::CellInputEncoderV1;
use crate::CellStateOwnerV1;
use crate::CellStepEntryV1;
use crate::CellStepInputV1;
use crate::InferredCellStepV1;
use crate::cell_global_feature_schema_digest_v1;
use crate::enter_cell_step;
use crate::recover_cell_inference;

const PREFIX: &[u8] = b"hepta.cell.registered-input.v1\0";
const MAX_BACKENDS: usize = 4096;

/// Implementation families, independent of functional roles and HNMF engrams.
/// The native profile consumes bounded global features and emits proposals;
/// decoder payloads and complete trainable state remain with their own owners.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellBackendFamilyV1 {
    FrozenRepresentationPrivateHead,
    GenerativeAdapterState,
    TrainableStateModel,
}

/// One concrete profile. A functional type may have multiple expert versions
/// and backend instances; no family is prescribed for any of the seven roles.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellBackendRegistrationV1 {
    pub backend_id: StableId,
    pub family: CellBackendFamilyV1,
    pub capability: CellCapabilityContractV1,
    pub expert: CellExpertVersionV1,
    pub definition: CellDefinitionV1,
}

/// The existing typed CellDecisionReceiptV1 profile, including candidate masks,
/// native execution cost fields and DENY_ALL. It is not a language/media output
/// schema or independent semantic-quality certificate.
pub fn cell_native_decision_schema_digest_v1() -> Digest32 {
    Digest32::of_bytes(b"hepta.cell.native-decision.v1\0CellDecisionReceiptV1:operation_id,operation_digest,semantic_request_digest,scope,bundle_digest,source_frontier,checkpoint_before,checkpoint_after,model_output_digest,policy,selected_candidate,confidence_ppm,ood_ppm,deadline_exceeded,cost,authority=DENY_ALL")
}

impl CellBackendRegistrationV1 {
    /// Resolve schema and expert bindings before retaining a registration.
    /// Capability generation and model generation are independent identities;
    /// both are bound, without treating one as the other's revision counter.
    pub fn digest(&self) -> Result<Digest32, CellExecutionError> {
        let capability = self
            .capability
            .digest()
            .map_err(|_| CellExecutionError::InvalidDefinition)?;
        let definition = self.definition.semantic_digest()?;
        if self.expert.type_id != self.capability.type_id
            || self.expert.capability_digest != capability
            || self.expert.shared_base_digest.is_zero()
            || self.expert.parameter_bundle_digest != self.definition.bundle_digest
            || self.capability.state_schema_digest != self.definition.state_schema_digest
            || self.capability.input_schema_digest
                != cell_global_feature_schema_digest_v1(
                    self.definition.runtime.input_feature_dimension,
                )?
            || self.capability.output_schema_digest != cell_native_decision_schema_digest_v1()
        {
            return Err(CellExecutionError::IncompatibleBundle);
        }
        let mut bytes = b"hepta.cell.backend-registration.v1\0".to_vec();
        for id in [&self.backend_id, &self.expert.version_id] {
            bytes.extend_from_slice(&(id.as_str().len() as u64).to_be_bytes());
            bytes.extend_from_slice(id.as_str().as_bytes());
        }
        bytes.push(match self.family {
            CellBackendFamilyV1::FrozenRepresentationPrivateHead => 0,
            CellBackendFamilyV1::GenerativeAdapterState => 1,
            CellBackendFamilyV1::TrainableStateModel => 2,
        });
        for digest in [
            capability,
            definition,
            self.expert.shared_base_digest,
            self.expert.parameter_bundle_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

/// A sealed immutable lookup table. Replacing it requires explicit caller
/// re-resolution; it provides no dynamic model publication or lifecycle rights.
pub struct CellBackendRegistryV1 {
    entries: BTreeMap<StableId, RegisteredCellBackendV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RegisteredCellBackendV1 {
    registration: CellBackendRegistrationV1,
    digest: Digest32,
}

impl CellBackendRegistryV1 {
    pub fn new(
        registrations: Vec<CellBackendRegistrationV1>,
        max_backends: usize,
    ) -> Result<Self, CellExecutionError> {
        if !(1..=MAX_BACKENDS).contains(&max_backends) || registrations.len() > max_backends {
            return Err(CellExecutionError::CapacityExceeded);
        }
        let mut entries = BTreeMap::new();
        for registration in registrations {
            let digest = registration.digest()?;
            if entries.contains_key(&registration.backend_id) {
                return Err(CellExecutionError::InvalidDefinition);
            }
            entries.insert(
                registration.backend_id.clone(),
                RegisteredCellBackendV1 { registration, digest },
            );
        }
        Ok(Self { entries })
    }

    pub fn resolve(
        &self,
        backend_id: &StableId,
        expected_digest: Digest32,
    ) -> Result<&RegisteredCellBackendV1, CellExecutionError> {
        self.entries
            .get(backend_id)
            .filter(|entry| entry.digest == expected_digest)
            .ok_or(CellExecutionError::IncompatibleBundle)
    }
}

impl RegisteredCellBackendV1 {
    pub fn registration(&self) -> &CellBackendRegistrationV1 {
        &self.registration
    }

    pub fn digest(&self) -> Digest32 {
        self.digest
    }

    /// Use the existing prepare/infer/decide/commit owner path. The registration
    /// is included in semantic and operation identities, so relabeling a role,
    /// family or expert cannot reinterpret an earlier pending/committed request.
    pub fn enter(
        &self,
        owner: &impl CellStateOwnerV1,
        projection: &CellGlobalFeatureProjectionV1,
        input: CellStepInputV1,
        now_micros: u64,
    ) -> Result<CellStepEntryV1, CellExecutionError> {
        let input = self.bind_input(projection, input)?;
        let snapshot = owner.snapshot(&input.scope)?;
        if snapshot.definition_digest != self.registration.definition.semantic_digest()? {
            return Err(CellExecutionError::IncompatibleBundle);
        }
        if snapshot.source_frontier != input.source_frontier {
            return Err(CellExecutionError::StaleSource);
        }
        enter_cell_step(
            &self.registration.definition,
            owner,
            &BoundProjection { registration: self.digest, projection },
            input,
            now_micros,
        )
    }

    /// Resolve only the original durable inference admission. Unknown receipts
    /// remain pending; changing a registration cannot create a fresh dispatch.
    pub fn recover(
        &self,
        owner: &impl CellStateOwnerV1,
        projection: &CellGlobalFeatureProjectionV1,
        input: CellStepInputV1,
        readback: &mut impl CellInferenceReadbackPortV1,
        now_micros: u64,
    ) -> Result<InferredCellStepV1, CellExecutionError> {
        recover_cell_inference(
            &self.registration.definition,
            owner,
            &BoundProjection { registration: self.digest, projection },
            self.bind_input(projection, input)?,
            readback,
            now_micros,
        )
    }

    fn bind_input(
        &self,
        projection: &CellGlobalFeatureProjectionV1,
        mut input: CellStepInputV1,
    ) -> Result<CellStepInputV1, CellExecutionError> {
        if projection.schema_digest() != self.registration.capability.input_schema_digest {
            return Err(CellExecutionError::EncodingMismatch);
        }
        projection.validate_request(&CellEncodingRequestV1 {
            scope: &input.scope,
            source_frontier: input.source_frontier,
            encoder_digest: self.registration.definition.runtime.encoder_digest,
            observation: &input.observation,
            checkpoint: None,
        })?;
        let mut observation = Vec::with_capacity(PREFIX.len() + 32 + input.observation.len());
        observation.extend_from_slice(PREFIX);
        observation.extend_from_slice(self.digest.as_array());
        observation.extend_from_slice(&input.observation);
        input.observation = observation;
        Ok(input)
    }
}

struct BoundProjection<'a> {
    registration: Digest32,
    projection: &'a CellGlobalFeatureProjectionV1,
}

impl CellInputEncoderV1 for BoundProjection<'_> {
    fn encode(
        &self,
        request: &CellEncodingRequestV1<'_>,
    ) -> Result<CellEncodedInputV1, CellExecutionError> {
        let observation = request
            .observation
            .strip_prefix(PREFIX)
            .and_then(|rest| rest.strip_prefix(self.registration.as_array().as_slice()))
            .ok_or(CellExecutionError::EncodingMismatch)?;
        let mut encoded = self.projection.encode(&CellEncodingRequestV1 {
            scope: request.scope,
            source_frontier: request.source_frontier,
            encoder_digest: request.encoder_digest,
            observation,
            checkpoint: request.checkpoint,
        })?;
        encoded.consumed_bytes += PREFIX.len() + 32;
        Ok(encoded)
    }
}

#[cfg(test)]
#[path = "cell_registry_tests.rs"]
mod tests;
