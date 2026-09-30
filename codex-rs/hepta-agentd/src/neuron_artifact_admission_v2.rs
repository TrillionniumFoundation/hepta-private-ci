use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::LearningArtifactOwnerHost;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::DurableNeuronInferenceControlPort;
use codex_hepta_neuron::NeuronRuntimeV2Error;

use super::AgentdNeuronHandleV2;
use super::AgentdNeuronOwnerV2;
use crate::neuron_artifact_admission::AgentdNeuronArtifactAdmissionV1;
use crate::neuron_artifact_admission::NeuronSelectedArtifactsV1;

impl<W, P> AgentdNeuronOwnerV2<W, P>
where
    W: AnchorWitnessStore + Send + 'static,
    P: DurableNeuronInferenceControlPort + Send + 'static,
{
    /// Install authenticated model, calibration and OOD selections on the
    /// unified owner. The artifact root, clock and trust roots are daemon-owned;
    /// no request field can select or refresh them.
    pub fn into_selected_shared(
        self,
        artifacts: Arc<Mutex<LearningArtifactOwnerHost>>,
        artifact_root: impl AsRef<Path>,
        selector: ArtifactSelectionVerifierV1,
        selections: NeuronSelectedArtifactsV1,
        clock: Arc<dyn AuthorityClock>,
    ) -> Result<AgentdNeuronHandleV2, NeuronRuntimeV2Error> {
        let admission = AgentdNeuronArtifactAdmissionV1::new(
            artifacts,
            artifact_root,
            selector,
            selections,
            clock,
            self.runtime().configuration(),
        )
        .map_err(NeuronRuntimeV2Error::Admission)?;
        self.into_shared(admission)
    }
}
