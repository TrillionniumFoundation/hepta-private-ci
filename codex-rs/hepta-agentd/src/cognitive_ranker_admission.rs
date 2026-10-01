//! Evaluated runtime loading with complete pins and final-use trust checks.
//! Host providers are authority dependencies, not fields in a candidate request.

use std::fs::File;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_bellman_operator::LoadedTabularOperatorV2;
use codex_hepta_bellman_operator::TabularOperatorPredictionV1;
use codex_hepta_bellman_operator::TabularPayloadError;
use codex_hepta_bellman_operator::TabularPayloadPinV2;
use codex_hepta_contracts::AgentId;
use codex_hepta_intelligence_eval::VerifiedSelfEvolutionRollbackV1;
use codex_hepta_intelligence_eval::VerifiedSelfEvolutionSelectionV1;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::PinnedCandidateSpec;
use codex_hepta_learning_artifacts::RevalidatingCandidate;
use codex_hepta_learning_artifacts::VerifiedCurrentRegistryUseWindowV1;
use codex_hepta_learning_artifacts::VerifiedCurrentRegistryViewV1;
use codex_hepta_learning_artifacts::load_pinned_candidate;
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::CurrentCognitiveRegistry;
use super::PinnedCognitiveRanker;
use crate::learning_operator_artifact_owner::clock::LearningOperatorUseClockV1;

/// A current host-owned signer registry and clock. The learning-evidence trust
/// and the artifact-owner trust are distinct and both must match at final use.
/// Public callers can construct this value only through the validating
/// constructor; the fields are not part of the public API.
#[derive(Clone, Debug)]
pub struct RankerAdmissionSnapshotV2 {
    pub(crate) learning_trust: ActivatedLearningTrustV1,
    pub(crate) artifact_trust_digest: Digest32,
    pub(crate) runtime_profile_digest: Digest32,
    pub(crate) now_unix_micros: u64,
}

impl RankerAdmissionSnapshotV2 {
    pub fn new(
        learning_trust: ActivatedLearningTrustV1,
        artifact_trust_digest: Digest32,
        runtime_profile_digest: Digest32,
        now_unix_micros: u64,
    ) -> Result<Self, String> {
        learning_trust
            .revalidate_at(now_unix_micros)
            .map_err(|error| error.to_string())?;
        if learning_trust.verifier().trust_digest().is_zero()
            || learning_trust.verifier().authority_epoch() == 0
            || artifact_trust_digest.is_zero()
            || runtime_profile_digest.is_zero()
            || now_unix_micros == 0
        {
            return Err(
                "ranker admission requires current nonzero trust, runtime, authority, and clock"
                    .to_string(),
            );
        }
        Ok(Self {
            learning_trust,
            artifact_trust_digest,
            runtime_profile_digest,
            now_unix_micros,
        })
    }

    #[must_use]
    pub fn learning_verifier(&self) -> &LearningEvidenceVerifierV1 {
        self.learning_trust.verifier()
    }

    #[must_use]
    pub fn artifact_trust_digest(&self) -> Digest32 {
        self.artifact_trust_digest
    }

    #[must_use]
    pub fn runtime_profile_digest(&self) -> Digest32 {
        self.runtime_profile_digest
    }

    #[must_use]
    pub fn now_unix_micros(&self) -> u64 {
        self.now_unix_micros
    }
}

/// Implement this on the authority/configuration host, never on submitted model
/// bytes. Each refresh must validate the active root-signed trust distribution
/// and independently sample current host time. A failed read is terminal for this
/// consumer until explicit reload.
pub trait CurrentRankerAdmission: Send + Sync {
    fn current(&self) -> Result<RankerAdmissionSnapshotV2, String>;
}

pub(super) enum RankerModel {
    #[cfg(test)]
    Fixture(codex_hepta_bellman_operator::LoadedTabularOperatorV1),
    Evaluated(LoadedTabularOperatorV2),
}

impl RankerModel {
    pub(super) fn predict(
        &self,
        sensor: &StableId,
        action: &StableId,
    ) -> Result<TabularOperatorPredictionV1, TabularPayloadError> {
        match self {
            #[cfg(test)]
            Self::Fixture(model) => model.predict(sensor, action),
            Self::Evaluated(model) => model.predict(sensor, action),
        }
    }
}

enum Authorization {
    Selection(Box<VerifiedSelfEvolutionSelectionV1>),
    Rollback(Box<VerifiedSelfEvolutionRollbackV1>),
}

impl Authorization {
    fn revalidate(&self, snapshot: &RankerAdmissionSnapshotV2) -> Result<(), String> {
        match self {
            Self::Selection(selection) => {
                selection.revalidate(snapshot.learning_verifier(), snapshot.now_unix_micros)
            }
            Self::Rollback(rollback) => {
                rollback.revalidate(snapshot.learning_verifier(), snapshot.now_unix_micros)
            }
        }
        .map_err(|error| error.to_string())
    }
}

pub(super) struct EvaluatedUse {
    provider: Arc<dyn CurrentRankerAdmission>,
    authorization: Authorization,
    learning_trust: Digest32,
    learning_distribution: Digest32,
    artifact_trust: Digest32,
    runtime_profile: Digest32,
    authority_epoch: u64,
    clock: Mutex<LearningOperatorUseClockV1>,
}

impl EvaluatedUse {
    pub(super) fn revalidate(&self, current: &VerifiedCurrentRegistryViewV1) -> Result<(), String> {
        self.revalidate_window(current.trust_digest(), current.use_window())
    }

    pub(super) fn revalidate_window(
        &self,
        artifact_trust: Digest32,
        window: VerifiedCurrentRegistryUseWindowV1,
    ) -> Result<(), String> {
        let mut snapshot = self.provider.current()?;
        if snapshot.learning_verifier().trust_digest() != self.learning_trust
            || snapshot.learning_verifier().authority_epoch() != self.authority_epoch
            || snapshot.learning_trust.distribution_digest() != self.learning_distribution
            || snapshot.artifact_trust_digest != self.artifact_trust
            || artifact_trust != self.artifact_trust
            || snapshot.runtime_profile_digest != self.runtime_profile
        {
            return Err("ranker trust/runtime/clock changed; explicit reload required".to_string());
        }
        snapshot.now_unix_micros = self
            .clock
            .lock()
            .map_err(|_| "ranker clock poisoned".to_string())?
            .observe(snapshot.now_unix_micros)
            .map_err(|error| error.to_string())?;
        snapshot
            .learning_trust
            .revalidate_at(snapshot.now_unix_micros)
            .map_err(|error| error.to_string())?;
        window
            .revalidate_at(snapshot.now_unix_micros)
            .map_err(|error| error.to_string())?;
        self.authorization.revalidate(&snapshot)?;
        Ok(())
    }
}

impl PinnedCognitiveRanker {
    /// Admit a read-only consumer from an independently evaluated selection.
    /// Full payload identity, runtime, both trust domains, expiry and current
    /// registry lineage are checked before the first prediction and every use.
    #[allow(clippy::too_many_arguments)]
    pub fn load_evaluated(
        owner: AgentId,
        body_generation: u64,
        snapshot: File,
        payload: File,
        selected: PinnedCandidateSpec,
        model_pin: TabularPayloadPinV2,
        current: Arc<dyn CurrentCognitiveRegistry>,
        selection: &VerifiedSelfEvolutionSelectionV1,
        admission: Arc<dyn CurrentRankerAdmission>,
    ) -> Result<Self, String> {
        let receipt = selection.receipt();
        if body_generation != receipt.candidate_generation.get()
            || selected.manifest.artifact_id != receipt.candidate_id
            || selected.manifest.generation != receipt.candidate_generation
            || selected.manifest.content_digest != receipt.candidate_artifact_digest
            || selected.manifest.objective_digest != receipt.objective_digest
            || selected.manifest.support_digest != receipt.dataset_digest
            || model_pin.trust_digest != receipt.evaluation_trust_digest
            || model_pin.authority_epoch != selection.authority_epoch()
        {
            return Err(
                "selected ranker does not match independently admitted candidate".to_string(),
            );
        }
        Self::load_authorized(
            owner,
            body_generation,
            snapshot,
            payload,
            selected,
            model_pin,
            current,
            admission,
            Authorization::Selection(Box::new(selection.clone())),
        )
    }

    /// Rollback restores immutable predecessor bytes, with a fresh runtime
    /// generation and still-current independently authenticated trust.
    #[allow(clippy::too_many_arguments)]
    pub fn load_evaluated_rollback(
        owner: AgentId,
        body_generation: u64,
        snapshot: File,
        payload: File,
        selected: PinnedCandidateSpec,
        model_pin: TabularPayloadPinV2,
        current: Arc<dyn CurrentCognitiveRegistry>,
        rollback: &VerifiedSelfEvolutionRollbackV1,
        admission: Arc<dyn CurrentRankerAdmission>,
    ) -> Result<Self, String> {
        let receipt = rollback.selection().receipt();
        if body_generation != rollback.rollback_generation().get()
            || selected.manifest.artifact_id != receipt.predecessor_id
            || selected.manifest.generation != receipt.predecessor_generation
            || selected.manifest.content_digest != receipt.predecessor_artifact_digest
            || selected.manifest.objective_digest != receipt.objective_digest
            || model_pin.trust_digest != receipt.evaluation_trust_digest
            || model_pin.authority_epoch != rollback.selection().authority_epoch()
        {
            return Err(
                "rollback ranker does not match independently admitted predecessor".to_string(),
            );
        }
        Self::load_authorized(
            owner,
            body_generation,
            snapshot,
            payload,
            selected,
            model_pin,
            current,
            admission,
            Authorization::Rollback(Box::new(rollback.clone())),
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn load_authorized(
        owner: AgentId,
        body_generation: u64,
        snapshot: File,
        payload: File,
        selected: PinnedCandidateSpec,
        model_pin: TabularPayloadPinV2,
        current: Arc<dyn CurrentCognitiveRegistry>,
        admission: Arc<dyn CurrentRankerAdmission>,
        authorization: Authorization,
    ) -> Result<Self, String> {
        let host = admission.current()?;
        let clock = LearningOperatorUseClockV1::new(host.now_unix_micros);
        host.learning_trust
            .revalidate_at(host.now_unix_micros)
            .map_err(|error| error.to_string())?;
        authorization.revalidate(&host)?;
        if body_generation == 0
            || selected.manifest.kind != ArtifactKind::Policy
            || selected.manifest.artifact_id != model_pin.artifact_id
            || selected.manifest.producer_id != model_pin.producer_id
            || selected.manifest.content_digest != model_pin.payload_digest
            || selected.manifest.objective_digest != model_pin.objective_digest
            || selected.manifest.support_digest != model_pin.dataset_digest
            || selected.manifest.generation != model_pin.generation
            || selected.manifest.compatibility_digest != model_pin.runtime_profile_digest
            || selected.registry_receipt.head_digest != model_pin.registry_head_digest
            || model_pin.runtime_profile_digest != host.runtime_profile_digest
            || model_pin.trust_digest != host.learning_verifier().trust_digest()
            || model_pin.authority_epoch != host.learning_verifier().authority_epoch()
            || host.artifact_trust_digest.is_zero()
            || host.now_unix_micros == 0
        {
            return Err("ranker full owner/model/runtime/trust pin mismatch".to_string());
        }
        let candidate = load_pinned_candidate(snapshot, payload, selected)
            .map_err(|error| error.to_string())?;
        let model = LoadedTabularOperatorV2::from_pinned_payload_v2(candidate.bytes(), &model_pin)
            .map_err(|error| error.to_string())?;
        let value = Self {
            owner,
            body_generation,
            policy_digest: model_pin.payload_digest,
            model: RankerModel::Evaluated(model),
            current,
            cache: Mutex::new(Some(RevalidatingCandidate::new(candidate))),
            admission: Some(EvaluatedUse {
                provider: admission,
                authorization,
                learning_trust: model_pin.trust_digest,
                learning_distribution: host.learning_trust.distribution_digest(),
                artifact_trust: host.artifact_trust_digest,
                runtime_profile: model_pin.runtime_profile_digest,
                authority_epoch: model_pin.authority_epoch,
                clock: Mutex::new(clock),
            }),
        };
        value.revalidate()?;
        Ok(value)
    }
}
