//! Current root-authenticated paired selection at each read consumption boundary.

use std::fs::File;
use std::sync::Arc;
use std::sync::Mutex;

#[cfg(any(test, feature = "qualification-unverified-operator-input"))]
use codex_hepta_agent_components::bellman_operator::LoadedTabularOperatorV1;
use codex_hepta_agent_components::bellman_operator::LoadedTabularOperatorV2;
use codex_hepta_agent_components::bellman_operator::TabularOperatorPredictionV1;
use codex_hepta_agent_components::bellman_operator::TabularPayloadError;
use codex_hepta_agent_components::bellman_operator::TabularPayloadPinV2;
use codex_hepta_agent_components::contracts::AgentId;
use codex_hepta_agent_components::intelligence_eval::VerifiedSelfEvolutionRollbackV2;
use codex_hepta_agent_components::intelligence_eval::VerifiedSelfEvolutionSelectionV2;
use codex_hepta_agent_components::learning_artifacts::ArtifactKind;
use codex_hepta_agent_components::learning_artifacts::PinnedCandidateSpec;
use codex_hepta_agent_components::learning_artifacts::RevalidatingCandidate;
use codex_hepta_agent_components::learning_artifacts::VerifiedCurrentRegistryViewV1;
use codex_hepta_agent_components::learning_artifacts::load_pinned_candidate;
use codex_hepta_agent_components::learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::StableId;

use super::CurrentCognitiveRegistry;
use super::PinnedCognitiveRanker;

/// Host-owned current trust and runtime. Selection retains its own clock;
/// callers cannot give this snapshot a historical consumption timestamp.
#[derive(Clone, Debug)]
pub struct RankerAdmissionSnapshotV3 {
    learning_trust: ActivatedLearningTrustV1,
    artifact_trust_digest: Digest32,
    runtime_profile_digest: Digest32,
}

impl RankerAdmissionSnapshotV3 {
    pub fn new(
        learning_trust: ActivatedLearningTrustV1,
        artifact_trust_digest: Digest32,
        runtime_profile_digest: Digest32,
    ) -> Result<Self, String> {
        if artifact_trust_digest.is_zero() || runtime_profile_digest.is_zero() {
            return Err("ranker authority/runtime context is incomplete".to_owned());
        }
        Ok(Self {
            learning_trust,
            artifact_trust_digest,
            runtime_profile_digest,
        })
    }
}

/// Implement on the authority/configuration host and refresh on trust rotation.
/// A failed read closes the retained candidate until explicit re-admission.
pub trait CurrentRankerAdmissionV3: Send + Sync {
    fn current(&self) -> Result<RankerAdmissionSnapshotV3, String>;
}

pub(super) enum RankerModel {
    #[cfg(any(test, feature = "qualification-unverified-operator-input"))]
    Legacy(LoadedTabularOperatorV1),
    Evaluated(LoadedTabularOperatorV2),
}

impl RankerModel {
    pub(super) fn predict(
        &self,
        sensor: &StableId,
        action: &StableId,
    ) -> Result<TabularOperatorPredictionV1, TabularPayloadError> {
        match self {
            #[cfg(any(test, feature = "qualification-unverified-operator-input"))]
            Self::Legacy(model) => model.predict(sensor, action),
            Self::Evaluated(model) => model.predict(sensor, action),
        }
    }
}

enum Authorization {
    Selection(Box<VerifiedSelfEvolutionSelectionV2>),
    Rollback(Box<VerifiedSelfEvolutionRollbackV2>),
}

impl Authorization {
    fn revalidate(&self, trust: &ActivatedLearningTrustV1) -> Result<(), String> {
        match self {
            Self::Selection(selection) => selection.revalidate_current(trust),
            Self::Rollback(rollback) => rollback.revalidate_current(trust),
        }
        .map_err(|error| error.to_string())
    }
}

pub(super) struct EvaluatedUseV2 {
    provider: Arc<dyn CurrentRankerAdmissionV3>,
    authorization: Authorization,
    learning_trust: Digest32,
    artifact_trust: Digest32,
    runtime_profile: Digest32,
    authority_epoch: u64,
}

impl EvaluatedUseV2 {
    pub(super) fn revalidate(
        &self,
        current: &VerifiedCurrentRegistryViewV1,
    ) -> Result<RankerAdmissionSnapshotV3, String> {
        current
            .revalidate_at(current_wall_millis()?)
            .map_err(|error| error.to_string())?;
        let host = self.provider.current()?;
        if host.learning_trust.verifier().trust_digest() != self.learning_trust
            || host.learning_trust.verifier().authority_epoch() != self.authority_epoch
            || host.artifact_trust_digest != self.artifact_trust
            || current.trust_digest() != self.artifact_trust
            || host.runtime_profile_digest != self.runtime_profile
        {
            return Err("ranker authority/runtime changed; explicit reload required".to_owned());
        }
        self.revalidate_retained(&host)?;
        Ok(host)
    }

    /// The host snapshot was refreshed before owner/materialization work.
    /// Finish with the original selection's owned clock, without another I/O
    /// callback that could itself outlive the validity check.
    pub(super) fn revalidate_retained(
        &self,
        host: &RankerAdmissionSnapshotV3,
    ) -> Result<(), String> {
        self.authorization.revalidate(&host.learning_trust)
    }
}

pub(super) fn current_wall_millis() -> Result<u64, String> {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|error| error.to_string())?
        .as_millis()
        .try_into()
        .map_err(|_| "ranker clock overflow".to_owned())
}

impl PinnedCognitiveRanker {
    /// Load only the exact independently selected paired candidate. Original
    /// owner provenance and the separate learning authority must both be current.
    #[allow(clippy::too_many_arguments)]
    pub fn load_evaluated_v2(
        owner: AgentId,
        body_generation: u64,
        snapshot: File,
        payload: File,
        selected: PinnedCandidateSpec,
        model_pin: TabularPayloadPinV2,
        current: Arc<dyn CurrentCognitiveRegistry>,
        selection: &VerifiedSelfEvolutionSelectionV2,
        admission: Arc<dyn CurrentRankerAdmissionV3>,
    ) -> Result<Self, String> {
        let receipt = selection.receipt();
        if body_generation != receipt.request.candidate_generation.get()
            || selected.manifest.artifact_id != receipt.request.candidate_id
            || selected.manifest.generation != receipt.request.candidate_generation
            || selected.manifest.content_digest != receipt.request.candidate_artifact_digest
            || selected.manifest.objective_digest != receipt.objective_digest
            || model_pin.trust_digest != receipt.evaluation_trust_digest
            || model_pin.authority_epoch != selection.authority_epoch()
        {
            return Err("ranker differs from original selected paired candidate".to_owned());
        }
        Self::load_authorized_v2(
            owner,
            body_generation,
            snapshot,
            payload,
            selected,
            model_pin,
            current,
            admission,
            Authorization::Selection(Box::new(selection.clone())),
            Some(receipt.dataset_digest),
        )
    }

    /// Restore immutable predecessor bytes while advancing the runtime generation.
    #[allow(clippy::too_many_arguments)]
    pub fn load_evaluated_rollback_v2(
        owner: AgentId,
        body_generation: u64,
        snapshot: File,
        payload: File,
        selected: PinnedCandidateSpec,
        model_pin: TabularPayloadPinV2,
        current: Arc<dyn CurrentCognitiveRegistry>,
        rollback: &VerifiedSelfEvolutionRollbackV2,
        admission: Arc<dyn CurrentRankerAdmissionV3>,
    ) -> Result<Self, String> {
        let receipt = rollback.selection().receipt();
        if body_generation != rollback.rollback_generation().get()
            || selected.manifest.artifact_id != receipt.request.predecessor_id
            || selected.manifest.generation != receipt.request.predecessor_generation
            || selected.manifest.content_digest != receipt.request.predecessor_artifact_digest
            || selected.manifest.objective_digest != receipt.objective_digest
            || model_pin.trust_digest != receipt.evaluation_trust_digest
            || model_pin.authority_epoch != rollback.selection().authority_epoch()
        {
            return Err("ranker differs from independently admitted predecessor".to_owned());
        }
        Self::load_authorized_v2(
            owner,
            body_generation,
            snapshot,
            payload,
            selected,
            model_pin,
            current,
            admission,
            Authorization::Rollback(Box::new(rollback.clone())),
            None,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn load_authorized_v2(
        owner: AgentId,
        body_generation: u64,
        snapshot: File,
        payload: File,
        selected: PinnedCandidateSpec,
        model_pin: TabularPayloadPinV2,
        current: Arc<dyn CurrentCognitiveRegistry>,
        admission: Arc<dyn CurrentRankerAdmissionV3>,
        authorization: Authorization,
        evaluation_dataset: Option<Digest32>,
    ) -> Result<Self, String> {
        let host = admission.current()?;
        authorization.revalidate(&host.learning_trust)?;
        if body_generation == 0
            || selected.manifest.kind != ArtifactKind::Policy
            || selected.manifest.artifact_id != model_pin.artifact_id
            || selected.manifest.producer_id != model_pin.producer_id
            || selected.manifest.content_digest != model_pin.payload_digest
            || selected.manifest.objective_digest != model_pin.objective_digest
            || selected.manifest.generation != model_pin.generation
            || selected.manifest.compatibility_digest != model_pin.runtime_profile_digest
            || selected.registry_receipt.head_digest != model_pin.registry_head_digest
            || model_pin.runtime_profile_digest != host.runtime_profile_digest
            || model_pin.trust_digest != host.learning_trust.verifier().trust_digest()
            || model_pin.authority_epoch != host.learning_trust.verifier().authority_epoch()
        {
            return Err("ranker complete owner/model/runtime/trust pin mismatch".to_owned());
        }
        let witness = current.current()?;
        if witness.trust_digest() != host.artifact_trust_digest
            || !witness.supports_dataset(&selected.manifest, model_pin.dataset_digest)
            || evaluation_dataset
                .is_some_and(|dataset| !witness.supports_dataset(&selected.manifest, dataset))
        {
            return Err(
                "ranker current provenance differs from training/evaluation source".to_owned(),
            );
        }
        let mut candidate = RevalidatingCandidate::new(
            load_pinned_candidate(snapshot, payload, selected)
                .map_err(|error| error.to_string())?,
        );
        let model = candidate
            .with_current(witness, |bytes| {
                LoadedTabularOperatorV2::from_pinned_payload_v2(bytes, &model_pin)
            })
            .map_err(|error| error.to_string())?
            .map_err(|error| error.to_string())?;
        let value = Self {
            owner,
            body_generation,
            policy_digest: model_pin.payload_digest,
            model: RankerModel::Evaluated(model),
            current,
            cache: Mutex::new(Some(candidate)),
            admission: Some(EvaluatedUseV2 {
                provider: admission,
                authorization,
                learning_trust: model_pin.trust_digest,
                artifact_trust: host.artifact_trust_digest,
                runtime_profile: model_pin.runtime_profile_digest,
                authority_epoch: model_pin.authority_epoch,
            }),
        };
        value.revalidate()?;
        Ok(value)
    }
}
