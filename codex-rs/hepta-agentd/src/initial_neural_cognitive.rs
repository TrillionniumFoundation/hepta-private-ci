//! Selected public V2 genesis on the ordinary read-only cognitive route.
//! This profile admits only its independent fixed generation-one capsule.
//! It neither supplies nor converts to evaluated-child product qualification.

use super::*;
use codex_hepta_learning_artifacts::SelectedPublicInitialSmolLmMaterialV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Generation;

/// Exact initial selection and physical model profile, without efficacy claims.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InitialNeuralCognitivePinV2 {
    pub payload_digest: Digest32,
    pub generation: Generation,
    pub selection_digest: Digest32,
    pub family_digest: Digest32,
    pub execution_profile_digest: Digest32,
}

/// Already admitted action identities and bounded ordinary query.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InitialNeuralCognitiveRequestV2 {
    pub owner_id: AgentId,
    pub body_generation: u64,
    pub pin: InitialNeuralCognitivePinV2,
    pub query: String,
    pub action_ids: Vec<StableId>,
}

/// Historical execution result. This grants no selection or effect authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InitialNeuralCognitiveObservationV2 {
    pub request: InitialNeuralCognitiveRequestV2,
    pub scores_q32: Option<Vec<i64>>,
    pub execution_receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

/// Physical initial-model owner, separate from the evaluated inference trait.
/// Implementations must retain the original load association and enforce the
/// original inference.control, resource and FinalUse owners for every read.
pub trait InitialNeuralCognitiveInferencePortV2: Send + Sync {
    fn execute_initial(
        &self,
        request: &InitialNeuralCognitiveRequestV2,
        execution: &NeuralCognitiveExecutionV1,
    ) -> Result<InitialNeuralCognitiveObservationV2, String>;
}

/// Original selected material and owner supplied by the embedding host.
/// The opaque material cannot be constructed from a receipt or an observed root.
pub struct InitialNeuralCognitiveBootstrapV2 {
    pub material: SelectedPublicInitialSmolLmMaterialV2,
    pub current: Arc<dyn CurrentCognitiveRegistry>,
    pub family_digest: Digest32,
    pub execution_profile_digest: Digest32,
    pub inference: Arc<dyn InitialNeuralCognitiveInferencePortV2>,
}

pub(super) struct InitialNeuralCognitiveModelV2 {
    pin: InitialNeuralCognitivePinV2,
    inference: Arc<dyn InitialNeuralCognitiveInferencePortV2>,
}

impl InitialNeuralCognitiveModelV2 {
    pub(super) fn score(
        &self,
        owner_id: &AgentId,
        body_generation: u64,
        query: &str,
        items: &[CognitiveContextItem],
        execution: &NeuralCognitiveExecutionV1,
    ) -> Result<Option<Vec<i64>>, String> {
        execution.check()?;
        if query.is_empty() || query.len() > 2048 || items.len() > 128 {
            return Err("initial cognitive request exceeds its registered bounds".to_owned());
        }
        if items.is_empty() {
            return Ok(None);
        }
        let request = InitialNeuralCognitiveRequestV2 {
            owner_id: owner_id.clone(),
            body_generation,
            pin: self.pin.clone(),
            query: query.to_owned(),
            action_ids: items
                .iter()
                .map(cognitive_action_id)
                .collect::<Result<_, _>>()?,
        };
        let observed = self.inference.execute_initial(&request, execution)?;
        execution.check()?;
        if observed.request != request
            || observed.execution_receipt_digest.is_zero()
            || observed.authority.grants_any()
            || observed
                .scores_q32
                .as_ref()
                .is_some_and(|scores| scores.len() != items.len())
        {
            return Err("initial cognitive observation differs from its exact request".to_owned());
        }
        Ok(observed.scores_q32)
    }
}

impl PinnedCognitiveRanker {
    pub(crate) fn load_selected_initial_neural(
        owner: AgentId,
        body_generation: u64,
        mut input: InitialNeuralCognitiveBootstrapV2,
    ) -> Result<Self, String> {
        let manifest = input.material.manifest();
        if body_generation == 0
            || manifest.generation.get() != 1
            || manifest.predecessor_id.is_some()
            || input.family_digest.is_zero()
            || input.execution_profile_digest.is_zero()
        {
            return Err("initial cognitive owner or genesis profile mismatch".to_owned());
        }
        let pin = InitialNeuralCognitivePinV2 {
            payload_digest: manifest.content_digest,
            generation: manifest.generation,
            selection_digest: input.material.selection_digest(),
            family_digest: input.family_digest,
            execution_profile_digest: input.execution_profile_digest,
        };
        let view = input.current.current()?;
        let current_owner_trust_digest = view.trust_digest();
        if input
            .material
            .with_current(view, current_unix_micros()? / 1_000_000, Digest32::of_bytes)
            .map_err(|error| error.to_string())?
            != pin.payload_digest
        {
            return Err("initial cognitive material differs from its selected root".to_owned());
        }
        Ok(Self {
            owner,
            body_generation,
            policy_digest: Digest32::of_parts(&[
                b"hepta.agentd.public-initial-neural-policy.v2\0",
                pin.payload_digest.as_array(),
                pin.selection_digest.as_array(),
                pin.family_digest.as_array(),
                pin.execution_profile_digest.as_array(),
            ]),
            model: CognitiveRankModel::InitialNeural(InitialNeuralCognitiveModelV2 {
                pin,
                inference: input.inference,
            }),
            current: input.current,
            current_owner_trust_digest,
            admission: RankerEvaluationAdmission::SelectedInitial,
            source_window: None,
            cache: Mutex::new(Some(RankerMaterial::Initial(input.material))),
        })
    }
}

#[cfg(test)]
#[path = "initial_neural_cognitive_tests.rs"]
mod tests;
