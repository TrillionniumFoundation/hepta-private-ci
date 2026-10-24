//! Explicit neural composition at the original evaluated bootstrap owner.
//! Descriptors carry immutable pins only. The host supplies an existing
//! inference.control/FinalUse port; no field here grants execution authority.

use std::path::Path;
use std::sync::Arc;

use codex_hepta_bellman_operator::TabularPayloadPinV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::EvaluatedCognitiveBootstrapV1;
use crate::NeuralCognitiveInferencePortV1;
use crate::NeuralCognitivePinV1;
use crate::cognitive_process_bootstrap::load_cognitive_process_model_v1;
use crate::cognitive_process_wire::Digest;
use crate::cognitive_process_wire::GenerationWire;

/// Host-owned neural model material. The port must enforce the original
/// inference resource and FinalUse owners for every execution. Possessing this
/// struct does not establish product qualification or admit installation.
pub struct NeuralCognitiveBootstrapModelV1 {
    pub pin: NeuralCognitivePinV1,
    pub inference: Arc<dyn NeuralCognitiveInferencePortV1>,
}

/// The complete original evaluated bootstrap inputs, with one neural model.
pub type EvaluatedNeuralCognitiveBootstrapV1 =
    EvaluatedCognitiveBootstrapV1<NeuralCognitiveBootstrapModelV1>;

// Keep family dispatch private and exhaustive. External callers cannot add a
// family that replaces the canonical qualification, selector or payload owner.
pub(super) enum CognitiveBootstrapModelV1 {
    Tabular(TabularPayloadPinV1),
    Neural(NeuralCognitiveBootstrapModelV1),
}

impl<Model> EvaluatedCognitiveBootstrapV1<Model> {
    pub(super) fn map_model<Mapped>(
        self,
        map: impl FnOnce(Model) -> Mapped,
    ) -> EvaluatedCognitiveBootstrapV1<Mapped> {
        EvaluatedCognitiveBootstrapV1 {
            snapshot: self.snapshot,
            payload: self.payload,
            selected: self.selected,
            model_pin: map(self.model_pin),
            source_manifest: self.source_manifest,
            current: self.current,
            policy: self.policy,
            selection_request: self.selection_request,
            evaluation_bundle: self.evaluation_bundle,
            metric_roles: self.metric_roles,
            evaluation_evidence: self.evaluation_evidence,
            longitudinal_time: self.longitudinal_time,
            dataset_receipt: self.dataset_receipt,
            ledger_snapshot: self.ledger_snapshot,
            verifier: self.verifier,
            selector_evidence: self.selector_evidence,
            product_qualification: self.product_qualification,
            product_candidate_binding_evidence: self.product_candidate_binding_evidence,
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct NeuralCognitivePinV1Raw {
    payload_digest: Digest,
    objective_digest: Digest,
    dataset_digest: Digest,
    generation: GenerationWire,
    family_digest: Digest,
    execution_profile_digest: Digest,
}

impl From<NeuralCognitivePinV1Raw> for NeuralCognitivePinV1 {
    fn from(raw: NeuralCognitivePinV1Raw) -> Self {
        Self {
            payload_digest: raw.payload_digest.into(),
            objective_digest: raw.objective_digest.into(),
            dataset_digest: raw.dataset_digest.into(),
            generation: raw.generation.into(),
            family_digest: raw.family_digest.into(),
            execution_profile_digest: raw.execution_profile_digest.into(),
        }
    }
}

/// Read explicit v3 neural inputs through the existing protected material and
/// owner replay path. The independently pinned descriptor cannot contain a
/// runtime, resource grant, FinalUse token or opaque selection receipt. The
/// supplied port is retained but never invoked during descriptor loading.
/// Installation still requires `with_evaluated_neural_cognitive_bootstrap`.
pub fn load_neural_cognitive_process_bootstrap_v1(
    path: &Path,
    expected_descriptor_digest: Digest32,
    identity: &AgentdIdentity,
    inference: Arc<dyn NeuralCognitiveInferencePortV1>,
) -> Result<EvaluatedNeuralCognitiveBootstrapV1, AgentdError> {
    load_cognitive_process_model_v1(
        path,
        expected_descriptor_digest,
        identity,
        "hepta.agentd.cognitive-bootstrap.v3",
        "published_neural_product_qualification_v1",
        |raw: NeuralCognitivePinV1Raw| NeuralCognitiveBootstrapModelV1 {
            pin: raw.into(),
            inference,
        },
    )
}

#[cfg(test)]
#[path = "cognitive_neural_bootstrap_tests.rs"]
mod tests;
