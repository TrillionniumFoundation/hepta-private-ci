//! Agentd-owned Neuron runtime composition.
//!
//! This is the named product-host ownership boundary for neuron.runtime source
//! composition.  It owns the long-lived runtime and the inference.control port
//! together so callers cannot bypass the exact feature-receipt adapter by
//! supplying drive/prediction vectors directly.  Constructing this owner does
//! not itself activate it in the daemon startup path.

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::InferenceControlModelPort;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronLocalCheckpointBindingV1;
use codex_hepta_neuron::NeuronRuntime;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_neuron::NeuronRuntimeOutputV1;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::SignedArtifactSelectionV1;
use codex_hepta_learning_artifacts::VerifiedCurrentRegistryViewV1;
use std::fs::File;

use crate::neuron_selected_artifact::NeuronCandidateModelArtifactErrorV1;
use crate::neuron_selected_artifact::NeuronCandidateModelArtifactV1;
use crate::neuron_selected_artifact::verify_pinned_neuron_model_descriptor_v1;

pub struct AgentdNeuronOwner<W, P>
where
    W: AnchorWitnessStore,
    P: NeuronInferenceControlPort,
{
    runtime: NeuronRuntime<W>,
    inference_control: P,
}

impl<W, P> AgentdNeuronOwner<W, P>
where
    W: AnchorWitnessStore,
    P: NeuronInferenceControlPort,
{
    pub fn new(runtime: NeuronRuntime<W>, inference_control: P) -> Self {
        Self {
            runtime,
            inference_control,
        }
    }

    pub fn tick(
        &mut self,
        input: NeuronTickInputV1,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        let mut model = InferenceControlModelPort::new(&mut self.inference_control);
        self.runtime.tick(&mut model, input)
    }

    /// Return the exact locally loaded model configuration and a checkpoint
    /// independently acknowledged by this runtime's Witness store. This does
    /// not prove the current production CNS route selected this runtime.
    /// No inference, mutation or promotion occurs during the read.
    pub fn read_local_checkpoint_binding_v1(
        &self,
    ) -> Result<NeuronLocalCheckpointBindingV1, NeuronRuntimeError> {
        self.runtime.read_local_checkpoint_binding_v1()
    }

    /// Verify one independently signed Model *descriptor* artifact against
    /// this owner-local witnessed config. The artifact is small: the actual
    /// frozen weights remain under their existing physical model/CAS owner.
    /// This does NOT prove CNS route selection or authorize final-use/promotion.
    #[allow(clippy::too_many_arguments)]
    pub fn read_model_artifact_candidate_v1(
        &self,
        verifier: &ArtifactSelectionVerifierV1,
        signed: &SignedArtifactSelectionV1,
        current: VerifiedCurrentRegistryViewV1,
        registry_snapshot: File,
        descriptor_payload: File,
        now: u64,
    ) -> Result<NeuronCandidateModelArtifactV1, NeuronCandidateModelArtifactErrorV1> {
        let local = self.read_local_checkpoint_binding_v1()?;
        verify_pinned_neuron_model_descriptor_v1(
            &local,
            verifier,
            signed,
            current,
            registry_snapshot,
            descriptor_payload,
            now,
        )
    }

    pub fn runtime(&self) -> &NeuronRuntime<W> {
        &self.runtime
    }

    pub fn runtime_mut(&mut self) -> &mut NeuronRuntime<W> {
        &mut self.runtime
    }

    pub fn inference_control_mut(&mut self) -> &mut P {
        &mut self.inference_control
    }
}

#[cfg(test)]
#[path = "neuron_runtime_tests.rs"]
mod tests;
