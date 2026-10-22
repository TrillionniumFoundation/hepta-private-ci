//! Read-only learned ranking at the existing Agentd cognitive read boundary.
//!
//! An embedding host explicitly supplies a selected model and independently
//! authenticated current registry views. The normal CLI does not invent either.
//! This component can only permute already-admitted SQLite records; it cannot
//! add context, grant access, select a new artifact, train, or dispatch a turn.

use std::fs::File;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_bellman_operator::LoadedTabularOperatorV1;
use codex_hepta_bellman_operator::TabularPayloadError;
use codex_hepta_bellman_operator::TabularPayloadPinV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_intelligence_eval::VerifiedSelfEvolutionRollbackV1;
use codex_hepta_intelligence_eval::VerifiedSelfEvolutionSelectionV1;
use codex_hepta_learning_artifacts::LearningArtifactManifestV2;
use codex_hepta_learning_artifacts::PinnedCandidateSpec;
#[cfg(test)]
use codex_hepta_learning_artifacts::RegistrySnapshotReceipt;
use codex_hepta_learning_artifacts::RevalidatingCandidate;
use codex_hepta_learning_artifacts::VerifiedCurrentRegistryViewV1;
use codex_hepta_learning_artifacts::load_pinned_candidate;
use codex_hepta_learning_artifacts::read_registry_snapshot;
use codex_hepta_learning_artifacts::validate_published_artifact_manifest_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::CognitiveContextItem;

#[path = "neural_cognitive_ranker.rs"]
mod neural;
pub use neural::NeuralCognitiveInferencePortV1;
pub use neural::NeuralCognitiveObservationV1;
pub use neural::NeuralCognitivePinV1;
pub use neural::NeuralCognitiveRequestV1;

enum CognitiveRankModel {
    Tabular(LoadedTabularOperatorV1),
    Neural(neural::NeuralCognitiveModelV1),
}

enum RankerEvaluationAdmission {
    HostPinned,
    Selected(Box<VerifiedSelfEvolutionSelectionV1>),
    Rollback(Box<VerifiedSelfEvolutionRollbackV1>),
}

impl RankerEvaluationAdmission {
    fn validate_at(&self, now: u64) -> Result<(), String> {
        match self {
            Self::HostPinned => Ok(()),
            Self::Selected(selection) => selection
                .validate_at(now)
                .map_err(|error| error.to_string()),
            Self::Rollback(rollback) => {
                rollback.validate_at(now).map_err(|error| error.to_string())
            }
        }
    }
}

/// The artifact authority, not the model or a caller-supplied receipt,
/// determines currentness. Implementations must return an opaque view issued
/// only after signed CURRENT verification and exact snapshot binding.
/// Production providers must also hold the original owner's observation fence
/// through settled-ACK reconciliation and reject unsettled or unknown writes.
/// A public host diagnostic view alone does not meet that contract. The ordinary
/// process provider uses `ArtifactOwnerCurrentReaderV1` for this boundary.
pub trait CurrentCognitiveRegistry: Send + Sync {
    fn current(&self) -> Result<VerifiedCurrentRegistryViewV1, String>;
}

#[cfg(test)]
pub(crate) fn verified_fixture_current_view(
    snapshot: File,
    receipt: RegistrySnapshotReceipt,
    expected_predecessor_head_digest: Digest32,
) -> Result<VerifiedCurrentRegistryViewV1, String> {
    verified_fixture_current_view_with_signer(
        snapshot,
        receipt,
        expected_predecessor_head_digest,
        ed25519_dalek::SigningKey::from_bytes(&[23_u8; 32]),
    )
}

#[cfg(test)]
pub(crate) fn verified_fixture_current_view_with_signer(
    snapshot: File,
    receipt: RegistrySnapshotReceipt,
    expected_predecessor_head_digest: Digest32,
    key: ed25519_dalek::SigningKey,
) -> Result<VerifiedCurrentRegistryViewV1, String> {
    verified_fixture_current_view_with_window(
        snapshot,
        receipt,
        expected_predecessor_head_digest,
        key,
        current_unix_micros()? / 1_000_000,
        /*expires_at*/ 4_102_444_800,
    )
}

#[cfg(test)]
fn verified_fixture_current_view_with_window(
    snapshot: File,
    receipt: RegistrySnapshotReceipt,
    expected_predecessor_head_digest: Digest32,
    key: ed25519_dalek::SigningKey,
    now: u64,
    expires_at: u64,
) -> Result<VerifiedCurrentRegistryViewV1, String> {
    use codex_hepta_learning_artifacts::ArtifactOwnerTrustV1;
    use codex_hepta_learning_artifacts::ArtifactOwnerVerifierV1;
    use codex_hepta_learning_artifacts::RegistryHeadRequirementV1;
    use codex_hepta_learning_artifacts::RegistryHeadWitnessV1;
    use codex_hepta_learning_artifacts::SignedCurrentArtifactHeadV1;
    use codex_hepta_learning_artifacts::TrustedArtifactSignerV1;
    use codex_hepta_types::Generation;
    use ed25519_dalek::Signer;
    let verifying_key = key.verifying_key().to_bytes();
    let signer_id = StableId::new("agentd-current-fixture-signer".to_owned())
        .map_err(|error| error.to_string())?;
    let registry_id = StableId::new("agentd-current-fixture-registry".to_owned())
        .map_err(|error| error.to_string())?;
    let scope_digest = Digest32::of_bytes(b"agentd-current-fixture-scope");
    let signer = TrustedArtifactSignerV1 {
        signer_id: signer_id.clone(),
        verifying_key,
        minimum_authority_epoch: 1,
        maximum_authority_epoch: 10,
        valid_from: 1,
        // Keep owner trust identical when only the head's signed validity
        // changes, so expiry tests cannot pass via trust-substitution refusal.
        expires_at: 4_102_444_800,
        revoked_at: None,
    };
    let verifier = ArtifactOwnerVerifierV1::new(ArtifactOwnerTrustV1 {
        registry_id: registry_id.clone(),
        withdrawal_scope_digest: scope_digest,
        minimum_registry_generation: Generation::new(1).map_err(|error| error.to_string())?,
        genesis_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        writer_signers: vec![signer.clone()],
        head_signers: vec![signer],
    })
    .map_err(|error| error.to_string())?;
    let generation =
        Generation::new(u64::try_from(receipt.records).map_err(|error| error.to_string())?)
            .map_err(|error| error.to_string())?;
    let mut signed = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: scope_digest,
        binding: receipt.binding,
        witness: RegistryHeadWitnessV1 {
            registry_id: registry_id.clone(),
            generation,
            head_digest: receipt.head_digest,
            predecessor_head_digest: expected_predecessor_head_digest,
            authority_epoch: 1,
            signer_id,
            signing_key_digest: Digest32::of_bytes(&verifying_key),
            issued_at: now,
            expires_at,
        },
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    let requirement = RegistryHeadRequirementV1 {
        registry_id,
        minimum_generation: generation,
        expected_predecessor_head_digest,
        minimum_authority_epoch: 1,
        now,
    };
    verifier
        .verify_current_registry_view(snapshot, receipt, &signed, &requirement)
        .map_err(|error| error.to_string())
}

/// A host-selected, generation-bound read-only ranking consumer. Replacing the
/// model requires an explicit new host/configuration, not a candidate's score.
pub struct PinnedCognitiveRanker {
    owner: AgentId,
    body_generation: u64,
    policy_digest: Digest32,
    model: CognitiveRankModel,
    current: Arc<dyn CurrentCognitiveRegistry>,
    current_owner_trust_digest: Digest32,
    admission: RankerEvaluationAdmission,
    source_window: Option<(u64, u64)>,
    cache: Mutex<Option<RevalidatingCandidate>>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct CognitiveRankObservation {
    pub(crate) policy_digest: Digest32,
    pub(crate) propensity: ProbabilityQ32,
    pub(crate) applied: bool,
}

/// Stable query encoder shared by the trainer and runtime. It is not an
/// embedding model, and unobserved queries cause whole-ranking abstention.
pub fn cognitive_sensor_id(query: &str) -> Result<StableId, String> {
    if query.is_empty() || query.len() > 2048 {
        return Err("ranking query outside bounded read profile".to_string());
    }
    StableId::new(format!("query-{}", Digest32::of_bytes(query.as_bytes())))
        .map_err(|error| error.to_string())
}

/// Bind an action to the *exact* admitted revision and content. A correction or
/// deletion cannot inherit a score merely by retaining the same memory ID.
pub fn cognitive_action_id(item: &CognitiveContextItem) -> Result<StableId, String> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(&(item.memory_id.len() as u64).to_be_bytes());
    bytes.extend_from_slice(item.memory_id.as_bytes());
    bytes.extend_from_slice(&item.revision.to_be_bytes());
    bytes.extend_from_slice(item.content_sha256.as_bytes());
    StableId::new(format!("memory-{}", Digest32::of_bytes(&bytes)))
        .map_err(|error| error.to_string())
}

impl PinnedCognitiveRanker {
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn load(
        owner: AgentId,
        body_generation: u64,
        snapshot: File,
        payload: File,
        selected: PinnedCandidateSpec,
        model_pin: TabularPayloadPinV1,
        current: Arc<dyn CurrentCognitiveRegistry>,
    ) -> Result<Self, String> {
        Self::load_source(
            owner,
            body_generation,
            snapshot,
            payload,
            selected,
            model_pin,
            current,
            None,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn load_source(
        owner: AgentId,
        body_generation: u64,
        snapshot: File,
        payload: File,
        selected: PinnedCandidateSpec,
        model_pin: TabularPayloadPinV1,
        current: Arc<dyn CurrentCognitiveRegistry>,
        source: Option<LearningArtifactManifestV2>,
    ) -> Result<Self, String> {
        let source_window = match source {
            Some(source) => {
                let validated = validate_published_artifact_manifest_v2(
                    &selected.manifest,
                    source,
                    current_unix_micros()? / 1_000_000,
                )
                .map_err(|error| error.to_string())?;
                if !validated
                    .manifest
                    .source_dataset_digests
                    .contains(&model_pin.dataset_digest)
                {
                    return Err(
                        "published ranker source does not include the model dataset".to_owned()
                    );
                }
                Some((validated.manifest.created_at, validated.manifest.expires_at))
            }
            None => {
                if selected.manifest.support_digest != model_pin.dataset_digest {
                    return Err("legacy ranker dataset pin mismatch".to_owned());
                }
                None
            }
        };
        if selected.manifest.kind != codex_hepta_learning_artifacts::ArtifactKind::Policy
            || body_generation == 0
            || selected.manifest.content_digest != model_pin.payload_digest
            || selected.manifest.objective_digest != model_pin.objective_digest
            || selected.manifest.generation != model_pin.generation
        {
            return Err("ranker owner/model pin binding mismatch".to_string());
        }
        let candidate = load_pinned_candidate(snapshot, payload, selected)
            .map_err(|error| error.to_string())?;
        let model = LoadedTabularOperatorV1::from_pinned_payload(candidate.bytes(), &model_pin)
            .map_err(|error| error.to_string())?;
        if model.artifact_id() != &candidate.spec().manifest.artifact_id {
            return Err("model identity differs from selected registry artifact".to_string());
        }
        let current_view = current.current()?;
        let current_owner_trust_digest = current_view.trust_digest();
        let mut candidate = RevalidatingCandidate::new(candidate);
        candidate
            .with_current(current_view, current_unix_micros()? / 1_000_000, |_| ())
            .map_err(|error| error.to_string())?;
        Ok(Self {
            owner,
            body_generation,
            policy_digest: model_pin.payload_digest,
            model: CognitiveRankModel::Tabular(model),
            current,
            current_owner_trust_digest,
            admission: RankerEvaluationAdmission::HostPinned,
            source_window,
            cache: Mutex::new(Some(candidate)),
        })
    }

    /// Compatibility profile for a V1 index that pins its dataset in support.
    /// It requires the original signed evaluation and independent selector,
    /// but does not establish canonical product qualification. Ordinary named
    /// publication installation uses `load_evaluated_published` instead.
    #[allow(clippy::too_many_arguments)]
    pub fn load_evaluated(
        owner: AgentId,
        body_generation: u64,
        snapshot: File,
        payload: File,
        selected: PinnedCandidateSpec,
        model_pin: TabularPayloadPinV1,
        current: Arc<dyn CurrentCognitiveRegistry>,
        selection: &VerifiedSelfEvolutionSelectionV1,
    ) -> Result<Self, String> {
        Self::load_evaluated_source(
            owner,
            body_generation,
            snapshot,
            payload,
            selected,
            model_pin,
            current,
            selection,
            None,
        )
    }

    /// Named-owner publication profile. The V1 index must commit to the full
    /// validated V2 source, whose dataset set must bind the model and selection.
    /// Selection must retain the canonical runner's sealed qualification and
    /// evaluator byte binding. There is no fallback to the compatibility path.
    #[allow(clippy::too_many_arguments)]
    pub fn load_evaluated_published(
        owner: AgentId,
        body_generation: u64,
        snapshot: File,
        payload: File,
        selected: PinnedCandidateSpec,
        model_pin: TabularPayloadPinV1,
        source_manifest: LearningArtifactManifestV2,
        current: Arc<dyn CurrentCognitiveRegistry>,
        selection: &VerifiedSelfEvolutionSelectionV1,
    ) -> Result<Self, String> {
        selection
            .require_product_qualification()
            .map_err(|error| error.to_string())?;
        Self::load_evaluated_source(
            owner,
            body_generation,
            snapshot,
            payload,
            selected,
            model_pin,
            current,
            selection,
            Some(source_manifest),
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn load_evaluated_source(
        owner: AgentId,
        body_generation: u64,
        snapshot: File,
        payload: File,
        selected: PinnedCandidateSpec,
        model_pin: TabularPayloadPinV1,
        current: Arc<dyn CurrentCognitiveRegistry>,
        selection: &VerifiedSelfEvolutionSelectionV1,
        source: Option<LearningArtifactManifestV2>,
    ) -> Result<Self, String> {
        let receipt = selection.receipt();
        selection
            .validate_at(current_unix_micros()?)
            .map_err(|error| error.to_string())?;
        let registry = read_registry_snapshot(
            snapshot.try_clone().map_err(|error| error.to_string())?,
            selected.registry_receipt,
        )
        .map_err(|error| error.to_string())?;
        let predecessor = registry
            .manifest(&receipt.predecessor_id)
            .ok_or("independently evaluated predecessor is absent from the selected snapshot")?;
        if predecessor.generation != receipt.predecessor_generation
            || predecessor.content_digest != receipt.predecessor_artifact_digest
            || !registry.is_eligible(&receipt.predecessor_id)
        {
            return Err(
                "selected registry predecessor differs from independent evaluation".to_string(),
            );
        }
        // Fleet launch epochs and learned-artifact lineage generations are
        // independent counters. The launch is bound by require_identity;
        // the model is bound by the exact selected/evaluated generation.
        if selected.manifest.artifact_id != receipt.candidate_id
            || selected.manifest.predecessor_id.as_ref() != Some(&receipt.predecessor_id)
            || selected.manifest.generation != receipt.candidate_generation
            || selected.manifest.content_digest != receipt.candidate_artifact_digest
            || selected.manifest.objective_digest != receipt.objective_digest
            || model_pin.dataset_digest != receipt.dataset_digest
        {
            return Err(
                "selected ranker does not match independently admitted candidate".to_string(),
            );
        }
        let mut value = Self::load_source(
            owner,
            body_generation,
            snapshot,
            payload,
            selected,
            model_pin,
            current,
            source,
        )?;
        value.admission = RankerEvaluationAdmission::Selected(Box::new(selection.clone()));
        value.revalidate()?;
        Ok(value)
    }

    /// Reload the exact predecessor only after an independent evaluator has
    /// admitted rollback for the selected candidate. Rollback restores bytes,
    /// not the old runtime generation or a revoked current witness.
    #[allow(clippy::too_many_arguments)]
    pub fn load_evaluated_rollback(
        owner: AgentId,
        body_generation: u64,
        snapshot: File,
        payload: File,
        selected: PinnedCandidateSpec,
        model_pin: TabularPayloadPinV1,
        current: Arc<dyn CurrentCognitiveRegistry>,
        rollback: &VerifiedSelfEvolutionRollbackV1,
    ) -> Result<Self, String> {
        let receipt = rollback.selection().receipt();
        if selected.manifest.artifact_id != receipt.predecessor_id
            || selected.manifest.generation != receipt.predecessor_generation
            || selected.manifest.content_digest != receipt.predecessor_artifact_digest
            || selected.manifest.objective_digest != receipt.objective_digest
        {
            return Err(
                "rollback ranker does not match independently admitted predecessor".to_string(),
            );
        }
        let mut value = Self::load(
            owner,
            body_generation,
            snapshot,
            payload,
            selected,
            model_pin,
            current,
        )?;
        value.admission = RankerEvaluationAdmission::Rollback(Box::new(rollback.clone()));
        value.revalidate()?;
        Ok(value)
    }

    pub(crate) fn require_identity(&self, owner: &AgentId, generation: u64) -> Result<(), String> {
        if owner != &self.owner || generation != self.body_generation {
            return Err("ranking host belongs to another agent generation".to_string());
        }
        Ok(())
    }

    fn with_current<T>(&self, consume: impl FnOnce() -> Result<T, String>) -> Result<T, String> {
        let mut cache = self
            .cache
            .lock()
            .map_err(|_| "ranker lock poisoned".to_string())?;
        let Some(mut candidate) = cache.take() else {
            return Err("ranker unavailable; explicit reload required".to_string());
        };
        self.admission.validate_at(current_unix_micros()?)?;
        self.validate_source_window(current_unix_micros()? / 1_000_000)?;
        // Keep the cache absent on witness errors, panics and failed refreshes.
        // The provider cannot inject a bare file/receipt: the artifact authority
        // must first issue an opaque verified CURRENT view.
        let current = self.current.current()?;
        let current_validity = current.validity();
        if current.trust_digest() != self.current_owner_trust_digest {
            return Err(
                "ranker CURRENT owner trust changed; independent reload required".to_string(),
            );
        }
        let result = candidate
            .with_current(current, current_unix_micros()? / 1_000_000, |_| consume())
            .map_err(|error| error.to_string())??;
        // Reobserve the original owner before making a computed permutation
        // visible. A publication or revocation while computing must extend the
        // same frontier and leave this exact candidate eligible. The outer
        // product FinalUse fence still owns serialization with actual effects.
        let current_after = self.current.current()?;
        let validity_after = current_after.validity();
        if current_after.trust_digest() != self.current_owner_trust_digest {
            return Err("ranker CURRENT owner trust changed during read".to_owned());
        }
        candidate
            .with_current(current_after, current_unix_micros()? / 1_000_000, |_| ())
            .map_err(|error| error.to_string())?;
        let completed_at = current_unix_micros()?;
        current_validity
            .validate_at(completed_at / 1_000_000)
            .map_err(|error| error.to_string())?;
        validity_after
            .validate_at(completed_at / 1_000_000)
            .map_err(|error| error.to_string())?;
        self.admission.validate_at(completed_at)?;
        self.validate_source_window(completed_at / 1_000_000)?;
        *cache = Some(candidate);
        Ok(result)
    }

    fn validate_source_window(&self, now: u64) -> Result<(), String> {
        if self
            .source_window
            .is_some_and(|(created_at, expires_at)| now < created_at || now > expires_at)
        {
            return Err("published ranker source validity ended".to_owned());
        }
        Ok(())
    }

    pub(crate) fn revalidate(&self) -> Result<(), String> {
        self.with_current(|| Ok(()))
    }

    pub(crate) fn rank(
        &self,
        owner: &AgentId,
        generation: u64,
        query: &str,
        items: &mut [CognitiveContextItem],
    ) -> Result<CognitiveRankObservation, String> {
        self.require_identity(owner, generation)?;
        if items.len() > 1024 {
            return Err("ranking candidates exceed cognitive read bound".to_string());
        }
        let sensor = cognitive_sensor_id(query)?;
        let (observation, ranked) = self.with_current(|| {
            if let CognitiveRankModel::Neural(model) = &self.model {
                let scores = model.score(owner, generation, query, items)?;
                let applied = scores.is_some();
                let ranked = scores.map(|scores| {
                    let mut order = scores.into_iter().enumerate().collect::<Vec<_>>();
                    order.sort_by(|left, right| right.1.cmp(&left.1).then(left.0.cmp(&right.0)));
                    order
                        .into_iter()
                        .map(|(index, _)| items[index].clone())
                        .collect::<Vec<_>>()
                });
                return Ok((
                    CognitiveRankObservation {
                        policy_digest: self.policy_digest,
                        propensity: ProbabilityQ32::ONE,
                        applied,
                    },
                    ranked,
                ));
            }
            let CognitiveRankModel::Tabular(model) = &self.model else {
                return Err("unsupported cognitive model profile".to_owned());
            };
            let mut scored = Vec::with_capacity(items.len());
            for (index, item) in items.iter().enumerate() {
                match model.predict(&sensor, &cognitive_action_id(item)?) {
                    Ok(prediction) => scored.push((index, prediction.value.raw())),
                    // Partial support abstains from this downstream policy
                    // decision rather than silently assigning a fabricated
                    // propensity to a partially observed action set.
                    Err(TabularPayloadError::UnsupportedCell) => {
                        return Ok((
                            CognitiveRankObservation {
                                policy_digest: self.policy_digest,
                                propensity: ProbabilityQ32::ONE,
                                applied: false,
                            },
                            None,
                        ));
                    }
                    Err(error) => return Err(error.to_string()),
                }
            }
            scored.sort_by(|left, right| right.1.cmp(&left.1).then(left.0.cmp(&right.0)));
            let ranked = scored
                .into_iter()
                .map(|(source, _)| items[source].clone())
                .collect::<Vec<_>>();
            Ok((
                CognitiveRankObservation {
                    policy_digest: self.policy_digest,
                    propensity: ProbabilityQ32::ONE,
                    applied: true,
                },
                Some(ranked),
            ))
        })?;
        if let Some(ranked) = ranked {
            items.clone_from_slice(&ranked);
        }
        Ok(observation)
    }
}

fn current_unix_micros() -> Result<u64, String> {
    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| error.to_string())?;
    u64::try_from(elapsed.as_micros()).map_err(|error| error.to_string())
}

#[cfg(test)]
#[path = "cognitive_ranker_tests.rs"]
mod tests;
