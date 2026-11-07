//! Representation dispatch keeps the original owner admission and requires
//! fresh producer/consumer observations at the actual model contact boundary.

use codex_hepta_types::Digest32;

use crate::CellExecutionError;
use crate::CellEncodingRequestV1;
use crate::CellNativeRepresentationInputV1;
use crate::CellRepresentationUseV1;
use crate::CellScopeV1;
use crate::CellStateOwnerV1;
use crate::InferredCellStepV1;
use crate::NeuronFeatureReceiptV1;
use crate::NeuronFeatureRequestV1;
use crate::NeuronInferenceControlPort;
use crate::NeuronModelError;
use crate::PreparedCellStepV1;
use crate::RegisteredCellBackendV1;
use crate::cell_inference::infer_admitted_cell;

/// Resolve and authenticate the existing source and consumer owners' current
/// observations. Copying the input's frozen pins is not a current observation.
/// Implementations must return promptly; this comparison grants no source
/// access, independent owner lease, or external effect authority.
pub trait CellRepresentationResolverV1 {
    fn current_use(
        &self,
        scope: &CellScopeV1,
    ) -> Result<CellRepresentationUseV1, CellExecutionError>;
}

/// Only the checked representation entry creates this context. The negotiation
/// binds both complete endpoint contracts, and the source binds scope/frontier
/// and all original bytes. No second copy of the tensor payload is retained.
#[derive(Debug, Eq, PartialEq)]
pub(crate) struct CellRepresentationPreparedV1 {
    pub(crate) backend_digest: Digest32,
    pub(crate) negotiation_digest: Digest32,
    pub(crate) source_digest: Digest32,
    pub(crate) output_digest: Digest32,
}

impl CellNativeRepresentationInputV1 {
    // Callers validate the sealed backend before constructing or comparing this
    // private context. Its digests bind complete pins, never a mutable boolean.
    pub(crate) fn prepared_context(
        &self,
        backend: &RegisteredCellBackendV1,
    ) -> CellRepresentationPreparedV1 {
        let receipt = self.projection_receipt();
        CellRepresentationPreparedV1 {
            backend_digest: backend.digest(),
            negotiation_digest: receipt.negotiation_digest,
            source_digest: receipt.source_digest,
            output_digest: receipt.output_digest,
        }
    }

    fn validate_prepared(
        &self,
        backend: &RegisteredCellBackendV1,
        prepared: &PreparedCellStepV1,
    ) -> Result<(), CellExecutionError> {
        self.validate_backend(backend)?;
        if prepared.representation.as_ref() != Some(&self.prepared_context(backend))
            || prepared.definition != backend.registration().definition
        {
            return Err(CellExecutionError::EncodingMismatch);
        }
        self.validate_request(&CellEncodingRequestV1 {
            scope: &prepared.input.scope,
            source_frontier: prepared.input.source_frontier,
            encoder_digest: prepared.definition.runtime.encoder_digest,
            observation: &prepared.input.observation,
            checkpoint: prepared.snapshot.checkpoint.as_ref(),
        })
    }
}

impl RegisteredCellBackendV1 {
    /// Dispatch a prepared representation through the original durable owner.
    /// Both current contracts are resolved before admission and again after its
    /// durable write. The live Cell clock is sampled after each resolution;
    /// expiry or rollback at contact refuses the supplied control port. A late
    /// refusal preserves the original pending identity and permits only readback.
    /// The host still validates any enclosing Circuit lease at its final use.
    pub fn infer_representation(
        &self,
        owner: &mut impl CellStateOwnerV1,
        representation: &CellNativeRepresentationInputV1,
        prepared: PreparedCellStepV1,
        resolver: &impl CellRepresentationResolverV1,
        control: &mut impl NeuronInferenceControlPort,
        mut clock_micros: impl FnMut() -> u64,
    ) -> Result<InferredCellStepV1, CellExecutionError> {
        representation.validate_prepared(self, &prepared)?;
        let scope = prepared.input.scope.clone();
        representation.validate_current_use(self, &resolver.current_use(&scope)?)?;
        let admitted_at_micros = clock_micros();
        let mut guarded = RepresentationDispatch {
            backend: self,
            representation,
            scope,
            resolver,
            control,
            clock_micros: &mut clock_micros,
            not_before_micros: admitted_at_micros,
            deadline_micros: prepared.input.deadline_micros,
            observed_at_micros: None,
        };
        let mut inferred = infer_admitted_cell(prepared, owner, &mut guarded, admitted_at_micros)?;
        inferred.not_before_micros = guarded.observed_at_micros
            .ok_or(CellExecutionError::ModelBindingMismatch)?;
        Ok(inferred)
    }
}

struct RepresentationDispatch<'a, R, P, C> {
    backend: &'a RegisteredCellBackendV1,
    representation: &'a CellNativeRepresentationInputV1,
    scope: CellScopeV1,
    resolver: &'a R,
    control: &'a mut P,
    clock_micros: &'a mut C,
    not_before_micros: u64,
    deadline_micros: u64,
    observed_at_micros: Option<u64>,
}

impl<R, P, C> NeuronInferenceControlPort for RepresentationDispatch<'_, R, P, C>
where
    R: CellRepresentationResolverV1,
    P: NeuronInferenceControlPort,
    C: FnMut() -> u64,
{
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        let current = self
            .resolver
            .current_use(&self.scope)
            .map_err(|_| NeuronModelError::Rejected)?;
        self.representation
            .validate_current_use(self.backend, &current)
            .map_err(|_| NeuronModelError::Rejected)?;
        let now = (self.clock_micros)();
        if now < self.not_before_micros || now >= self.deadline_micros {
            return Err(NeuronModelError::Rejected);
        }
        self.observed_at_micros = Some(now);
        self.control.execute_feature(request)
    }
}
