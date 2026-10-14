//! Research-only source/artifact fence around the REAL Neuron inference.control port.
//!
//! This module is opt-in behind the amcn-shadow feature. It is not an
//! implementation of cognitive.store or learning.artifacts and grants no model
//! activation, FinalUse, effect, Selector or independent reviewer authority.
//!
//! A hash-only preflight followed by a separate model call is racy. The
//! AmcnSourceArtifactFence host MUST keep its *authoritative* source,
//! quarantine, selected Head and runtime-generation lease held across the
//! supplied model execution closure. There is deliberately no default impl.
//! Hash equality cannot prove that a remote Source Store was fenced.

use codex_hepta_types::{Digest32, Generation, StableId};

use crate::{
    InferenceControlModelPort, NeuronInferenceControlPort, NeuronModelError, NeuronModelOutputV1,
    NeuronModelPort, NeuronModelRequestV1,
};

/// Feature flag guards compilation, not external provenance or source authority.
pub const AMCN_SHADOW_PRODUCTION_ACCEPTED: bool = false;

/// Exact original request and externally witnessed source/parameter lifecycle.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AmcnFencedModelBindingV1 {
    pub scope: StableId,
    pub request_id: StableId,
    pub config_id: StableId,
    pub generation: Generation,
    pub model_id: StableId,
    pub encoder_digest: Digest32,
    pub head_digest: Digest32,
    pub weights_digest: Digest32,
    pub input_digest: Digest32,
    pub expected_output_width: usize,
    pub artifact_manifest_digest: Digest32,
    pub source_frontier_digest: Digest32,
    pub withdrawal_registry_head_digest: Digest32,
    pub quarantine_journal_head_digest: Digest32,
    pub runtime_anchor_digest: Digest32,
}

impl AmcnFencedModelBindingV1 {
    /// Strict one-invocation binding; fail before entering an external fence.
    pub fn validate_request(&self, request: &NeuronModelRequestV1) -> Result<(), NeuronModelError> {
        if self.request_id != request.request_id
            || self.config_id != request.config_id
            || self.generation != request.generation
            || self.model_id != request.model_id
            || self.encoder_digest != request.encoder_digest
            || self.head_digest != request.head_digest
            || self.weights_digest != request.weights_digest
            || self.input_digest != request.input_digest
            || self.expected_output_width != request.expected_output_width
            || !(1..=4_096).contains(&self.expected_output_width)
            || [
                self.encoder_digest,
                self.head_digest,
                self.weights_digest,
                self.input_digest,
                self.artifact_manifest_digest,
                self.source_frontier_digest,
                self.withdrawal_registry_head_digest,
                self.quarantine_journal_head_digest,
                self.runtime_anchor_digest,
            ]
            .iter()
            .any(|digest| digest.is_zero())
        {
            return Err(NeuronModelError::Rejected);
        }
        Ok(())
    }
}

/// To be implemented ONLY by an owner that can atomically fence relevant
/// source revisions, withdrawal records, durable artifact quarantine and
/// runtime witness through the complete synchronous model invocation.
///
/// This trait cannot mint a witness or infer it from the caller's request.
/// Recovery-pending, removed/altered sources, orphaned training ancestors,
/// wrong scope/generation or changed committed-head CAS must reject BEFORE
/// invoking the action. The owner must not release its fence early, even on
/// model failure. A test-double implementation is NOT production admission.
pub trait AmcnSourceArtifactFence {
    fn with_fenced_candidate<T>(
        &mut self,
        binding: &AmcnFencedModelBindingV1,
        request: &NeuronModelRequestV1,
        action: impl FnOnce() -> Result<T, NeuronModelError>,
    ) -> Result<T, NeuronModelError>;
}

/// Calls the existing Neuron inference.control port *inside* a source owner's
/// fenced critical section. There is no unfenced fallback path.
///
/// This is compiled only in research feature builds, and is NOT wired into
/// the default runtime or any production ownership/selection path.
pub struct AmcnFencedNeuronModelPort<'a, F: AmcnSourceArtifactFence, P: NeuronInferenceControlPort> {
    fence: &'a mut F,
    control: &'a mut P,
    binding: AmcnFencedModelBindingV1,
}

impl<'a, F: AmcnSourceArtifactFence, P: NeuronInferenceControlPort>
    AmcnFencedNeuronModelPort<'a, F, P>
{
    pub fn new(
        fence: &'a mut F,
        control: &'a mut P,
        binding: AmcnFencedModelBindingV1,
    ) -> Self {
        Self { fence, control, binding }
    }
}

impl<F: AmcnSourceArtifactFence, P: NeuronInferenceControlPort> NeuronModelPort
    for AmcnFencedNeuronModelPort<'_, F, P>
{
    fn execute(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        self.binding.validate_request(request)?;
        let fence = &mut *self.fence;
        let control = &mut *self.control;
        let binding = &self.binding;

        fence.with_fenced_candidate(binding, request, || {
            // Reuse the real receipt verifier, terminal-status checks and
            // model-output decoder. No parallel fake model port.
            InferenceControlModelPort::new(control).execute(request)
        })
    }
}

#[cfg(test)]
#[path = "amcn_shadow_fence_tests.rs"]
mod tests;
