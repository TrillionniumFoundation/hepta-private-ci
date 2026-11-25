//! Neural parameters at the existing, read-only CognitiveContext consumer.
//!
//! This does not select, train, install or publish an artifact. A host supplies
//! the original qualified selection and an inference.control implementation.
//! The normal read path still admits records before ranking and materializes
//! their content only after ranking and owner revalidation.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Generation;

use super::*;

/// Immutable model and execution contract retained by the composition owner.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuralCognitivePinV1 {
    pub payload_digest: Digest32,
    pub objective_digest: Digest32,
    pub dataset_digest: Digest32,
    pub generation: Generation,
    pub family_digest: Digest32,
    pub execution_profile_digest: Digest32,
}

impl NeuralCognitivePinV1 {
    /// Canonical compatibility commitment for the original artifact manifest.
    pub fn compatibility_digest(&self) -> Digest32 {
        Digest32::of_parts(&[
            b"hepta.agentd.neural-cognitive-profile.v1\0",
            self.family_digest.as_array(),
            self.execution_profile_digest.as_array(),
        ])
    }
}

/// A bounded raw query and exact, already admitted action identities. It has
/// neither memory text nor target labels, so the runtime cannot read unadmitted
/// content or receive the expected answer from this request.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuralCognitiveRequestV1 {
    pub owner_id: AgentId,
    pub body_generation: u64,
    pub pin: NeuralCognitivePinV1,
    pub query: String,
    pub query_digest: Digest32,
    pub action_ids: Vec<StableId>,
}

/// Real inference observation. An unsupported action set must abstain as a
/// whole; partial scores must not silently reorder an incompletely supported
/// set. No field in this value grants authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuralCognitiveObservationV1 {
    pub request: NeuralCognitiveRequestV1,
    pub scores_q32: Option<Vec<i64>>,
    pub execution_receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

/// Original inference owner port for a selected neural parameter artifact.
///
/// Implementations must load the supplied exact parameter bytes, execute the
/// registered model family on `request.query`, enforce their original resource
/// and final-use admission, and bind the observed result to this exact request.
/// They must not derive scores from labels, a lookup table, or caller vectors.
/// This synchronous port runs only in the existing bounded read worker; an
/// implementation must enforce its own hard execution deadline.
pub trait NeuralCognitiveInferencePortV1: Send + Sync {
    fn execute(
        &self,
        request: &NeuralCognitiveRequestV1,
        parameter_bytes: &[u8],
    ) -> Result<NeuralCognitiveObservationV1, String>;
}

pub(super) struct NeuralCognitiveModelV1 {
    pin: NeuralCognitivePinV1,
    parameters: Vec<u8>,
    inference: Arc<dyn NeuralCognitiveInferencePortV1>,
}

impl NeuralCognitiveModelV1 {
    pub(super) fn score(
        &self,
        owner_id: &AgentId,
        body_generation: u64,
        query: &str,
        items: &[CognitiveContextItem],
    ) -> Result<Option<Vec<i64>>, String> {
        if items.len() > 128 || query.is_empty() || query.len() > 2048 {
            return Err("neural cognitive request exceeds its registered bounds".to_owned());
        }
        if items.is_empty() {
            return Ok(None);
        }
        let request = NeuralCognitiveRequestV1 {
            owner_id: owner_id.clone(),
            body_generation,
            pin: self.pin.clone(),
            query: query.to_owned(),
            query_digest: Digest32::of_bytes(query.as_bytes()),
            action_ids: items
                .iter()
                .map(cognitive_action_id)
                .collect::<Result<_, _>>()?,
        };
        let observation = self.inference.execute(&request, &self.parameters)?;
        if observation.request != request
            || observation.execution_receipt_digest.is_zero()
            || observation.authority.grants_any()
            || observation
                .scores_q32
                .as_ref()
                .is_some_and(|scores| scores.len() != items.len())
        {
            return Err("neural cognitive observation differs from its exact request".to_owned());
        }
        Ok(observation.scores_q32)
    }
}

impl PinnedCognitiveRanker {
    /// Construct a neural consumer only from the original product-qualified
    /// selection and published source manifest. This is the same ordinary
    /// CognitiveContext read path as the existing policy consumer, with neural
    /// execution in place of the legacy tabular predictor. The parameter
    /// artifact must have completed qualification before this method is called.
    #[allow(clippy::too_many_arguments)]
    pub fn load_neural_evaluated_published(
        owner: AgentId,
        body_generation: u64,
        snapshot: File,
        payload: File,
        selected: PinnedCandidateSpec,
        pin: NeuralCognitivePinV1,
        source_manifest: LearningArtifactManifestV2,
        current: Arc<dyn CurrentCognitiveRegistry>,
        selection: &VerifiedSelfEvolutionSelectionV1,
        inference: Arc<dyn NeuralCognitiveInferencePortV1>,
    ) -> Result<Self, String> {
        selection
            .require_product_qualification()
            .map_err(|error| error.to_string())?;
        selection
            .validate_at(current_unix_micros()?)
            .map_err(|error| error.to_string())?;
        let evaluated = selection.receipt();
        let manifest = &selected.manifest;
        let registry = read_registry_snapshot(
            snapshot.try_clone().map_err(|error| error.to_string())?,
            selected.registry_receipt,
        )
        .map_err(|error| error.to_string())?;
        let predecessor = registry
            .manifest(&evaluated.predecessor_id)
            .ok_or("evaluated neural predecessor missing from the selected registry")?;
        if body_generation == 0
            || manifest.kind != codex_hepta_learning_artifacts::ArtifactKind::Parameters
            || manifest.artifact_id != evaluated.candidate_id
            || manifest.predecessor_id.as_ref() != Some(&evaluated.predecessor_id)
            || manifest.content_digest != evaluated.candidate_artifact_digest
            || manifest.content_digest != pin.payload_digest
            || manifest.objective_digest != evaluated.objective_digest
            || manifest.objective_digest != pin.objective_digest
            || manifest.generation != evaluated.candidate_generation
            || manifest.generation != pin.generation
            || pin.dataset_digest != evaluated.dataset_digest
            || pin.family_digest.is_zero()
            || pin.execution_profile_digest.is_zero()
            || predecessor.content_digest != evaluated.predecessor_artifact_digest
            || predecessor.generation != evaluated.predecessor_generation
            || !registry.is_eligible(&evaluated.predecessor_id)
        {
            return Err(
                "neural owner, parameter, family or evaluated lineage binding mismatch".to_owned(),
            );
        }
        if manifest.compatibility_digest != pin.compatibility_digest() {
            return Err(
                "neural execution profile is not committed by the selected manifest".to_owned(),
            );
        }
        let source = validate_published_artifact_manifest_v2(
            manifest,
            source_manifest,
            current_unix_micros()? / 1_000_000,
        )
        .map_err(|error| error.to_string())?;
        if !source
            .manifest
            .source_dataset_digests
            .contains(&pin.dataset_digest)
        {
            return Err("neural published source omits its evaluated dataset".to_owned());
        }
        let loaded = load_pinned_candidate(snapshot, payload, selected)
            .map_err(|error| error.to_string())?;
        // Keep the exact bytes captured by the existing loader. The inference
        // port never receives a mutable payload path to reopen.
        let parameters = loaded.bytes().to_vec();
        let current_view = current.current()?;
        let current_owner_trust_digest = current_view.trust_digest();
        let mut candidate = RevalidatingCandidate::new(loaded);
        candidate
            .with_current(current_view, current_unix_micros()? / 1_000_000, |_| ())
            .map_err(|error| error.to_string())?;
        Ok(Self {
            owner,
            body_generation,
            policy_digest: Digest32::of_parts(&[
                b"hepta.agentd.neural-cognitive-policy.v1\0",
                pin.payload_digest.as_array(),
                pin.compatibility_digest().as_array(),
            ]),
            model: CognitiveRankModel::Neural(NeuralCognitiveModelV1 {
                pin,
                parameters,
                inference,
            }),
            current,
            current_owner_trust_digest,
            admission: RankerEvaluationAdmission::Selected(Box::new(selection.clone())),
            source_window: Some((source.manifest.created_at, source.manifest.expires_at)),
            cache: Mutex::new(Some(candidate)),
        })
    }
}

#[cfg(test)]
#[path = "neural_cognitive_ranker_tests.rs"]
mod tests;
