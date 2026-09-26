//! Read-only learned ranking at the existing Agentd cognitive read boundary.
//!
//! An embedding host explicitly supplies a selected model and independently
//! authenticated current registry views. The normal CLI does not invent either.
//! This component can only permute already-admitted SQLite records; it cannot
//! add context, grant access, select a new artifact, train, or dispatch a turn.

use std::fs::File;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_bellman_operator::LoadedTabularOperatorV1;
use codex_hepta_bellman_operator::TabularPayloadError;
use codex_hepta_bellman_operator::TabularPayloadPinV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_intelligence_eval::VerifiedSelfEvolutionRollbackV1;
use codex_hepta_intelligence_eval::VerifiedSelfEvolutionSelectionV1;
use codex_hepta_learning_artifacts::PinnedCandidateSpec;
#[cfg(test)]
use codex_hepta_learning_artifacts::RegistrySnapshotReceipt;
use codex_hepta_learning_artifacts::RevalidatingCandidate;
use codex_hepta_learning_artifacts::VerifiedCurrentRegistryViewV1;
use codex_hepta_learning_artifacts::load_pinned_candidate;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::CognitiveContextItem;

/// The artifact authority, not the model or a caller-supplied receipt,
/// determines currentness. Implementations must return an opaque view issued
/// only after signed CURRENT verification and exact snapshot binding.
pub trait CurrentCognitiveRegistry: Send + Sync {
    fn current(&self) -> Result<VerifiedCurrentRegistryViewV1, String>;
}

#[cfg(test)]
pub(crate) fn verified_fixture_current_view(
    snapshot: File,
    receipt: RegistrySnapshotReceipt,
    expected_predecessor_head_digest: Digest32,
) -> Result<VerifiedCurrentRegistryViewV1, String> {
    use codex_hepta_learning_artifacts::ArtifactOwnerTrustV1;
    use codex_hepta_learning_artifacts::ArtifactOwnerVerifierV1;
    use codex_hepta_learning_artifacts::RegistryHeadRequirementV1;
    use codex_hepta_learning_artifacts::RegistryHeadWitnessV1;
    use codex_hepta_learning_artifacts::SignedCurrentArtifactHeadV1;
    use codex_hepta_learning_artifacts::TrustedArtifactSignerV1;
    use codex_hepta_types::Generation;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    let key = SigningKey::from_bytes(&[23_u8; 32]);
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
        expires_at: 1_000,
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
            issued_at: 20,
            expires_at: 1_000,
        },
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    let requirement = RegistryHeadRequirementV1 {
        registry_id,
        minimum_generation: generation,
        expected_predecessor_head_digest,
        minimum_authority_epoch: 1,
        now: 20,
    };
    verifier
        .verify_current_registry_view(snapshot, receipt, &signed, &requirement)
        .map_err(|error| error.to_string())
}

/// Monotonic product counters for learned-ranker application and degradation.
///
/// These counters expose no artifact bytes or query content. Operators should
/// alert on increases in `current_view_failures`, `revalidation_failures`,
/// `prediction_failures` and `ranker_unavailable`, and should track the ratio of
/// `unsupported_abstentions` to successful `rankings_applied`.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct CognitiveRankerMetricsV1 {
    pub rankings_applied: u64,
    pub unsupported_abstentions: u64,
    pub current_view_failures: u64,
    pub revalidation_failures: u64,
    pub prediction_failures: u64,
    pub ranker_unavailable: u64,
    pub identity_rejections: u64,
    pub input_rejections: u64,
}

#[derive(Debug, Default)]
struct CognitiveRankerCountersV1 {
    rankings_applied: AtomicU64,
    unsupported_abstentions: AtomicU64,
    current_view_failures: AtomicU64,
    revalidation_failures: AtomicU64,
    prediction_failures: AtomicU64,
    ranker_unavailable: AtomicU64,
    identity_rejections: AtomicU64,
    input_rejections: AtomicU64,
}

impl CognitiveRankerCountersV1 {
    fn snapshot(&self) -> CognitiveRankerMetricsV1 {
        CognitiveRankerMetricsV1 {
            rankings_applied: self.rankings_applied.load(Ordering::Relaxed),
            unsupported_abstentions: self.unsupported_abstentions.load(Ordering::Relaxed),
            current_view_failures: self.current_view_failures.load(Ordering::Relaxed),
            revalidation_failures: self.revalidation_failures.load(Ordering::Relaxed),
            prediction_failures: self.prediction_failures.load(Ordering::Relaxed),
            ranker_unavailable: self.ranker_unavailable.load(Ordering::Relaxed),
            identity_rejections: self.identity_rejections.load(Ordering::Relaxed),
            input_rejections: self.input_rejections.load(Ordering::Relaxed),
        }
    }
}

/// A host-selected, generation-bound read-only ranking consumer. Replacing the
/// model requires an explicit new host/configuration, not a candidate's score.
pub struct PinnedCognitiveRanker {
    owner: AgentId,
    body_generation: u64,
    policy_digest: Digest32,
    model: LoadedTabularOperatorV1,
    current: Arc<dyn CurrentCognitiveRegistry>,
    cache: Mutex<Option<RevalidatingCandidate>>,
    metrics: CognitiveRankerCountersV1,
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
        if selected.manifest.kind != codex_hepta_learning_artifacts::ArtifactKind::Policy
            || body_generation == 0
            || selected.manifest.content_digest != model_pin.payload_digest
            || selected.manifest.objective_digest != model_pin.objective_digest
            || selected.manifest.support_digest != model_pin.dataset_digest
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
        let value = Self {
            owner,
            body_generation,
            policy_digest: model_pin.payload_digest,
            model,
            current,
            cache: Mutex::new(Some(RevalidatingCandidate::new(candidate))),
            metrics: CognitiveRankerCountersV1::default(),
        };
        value.revalidate()?;
        Ok(value)
    }

    /// Load a candidate only after independent longitudinal evaluation and a
    /// separately authenticated selector have admitted the exact artifact.
    /// The opaque selection token cannot be fabricated from registry metadata.
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
        let receipt = selection.receipt();
        if body_generation != receipt.candidate_generation.get()
            || selected.manifest.artifact_id != receipt.candidate_id
            || selected.manifest.generation != receipt.candidate_generation
            || selected.manifest.content_digest != receipt.candidate_artifact_digest
            || selected.manifest.objective_digest != receipt.objective_digest
            || selected.manifest.support_digest != receipt.dataset_digest
        {
            return Err(
                "selected ranker does not match independently admitted candidate".to_string(),
            );
        }
        Self::load(
            owner,
            body_generation,
            snapshot,
            payload,
            selected,
            model_pin,
            current,
        )
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
        if body_generation != rollback.rollback_generation().get()
            || selected.manifest.artifact_id != receipt.predecessor_id
            || selected.manifest.generation != receipt.predecessor_generation
            || selected.manifest.content_digest != receipt.predecessor_artifact_digest
            || selected.manifest.objective_digest != receipt.objective_digest
        {
            return Err(
                "rollback ranker does not match independently admitted predecessor".to_string(),
            );
        }
        Self::load(
            owner,
            body_generation,
            snapshot,
            payload,
            selected,
            model_pin,
            current,
        )
    }

    #[must_use]
    pub fn metrics(&self) -> CognitiveRankerMetricsV1 {
        self.metrics.snapshot()
    }

    pub(crate) fn require_identity(&self, owner: &AgentId, generation: u64) -> Result<(), String> {
        if owner != &self.owner || generation != self.body_generation {
            self.metrics
                .identity_rejections
                .fetch_add(1, Ordering::Relaxed);
            return Err("ranking host belongs to another agent generation".to_string());
        }
        Ok(())
    }

    fn with_current<T>(&self, consume: impl FnOnce() -> Result<T, String>) -> Result<T, String> {
        let mut cache = match self.cache.lock() {
            Ok(cache) => cache,
            Err(_) => {
                self.metrics
                    .ranker_unavailable
                    .fetch_add(1, Ordering::Relaxed);
                return Err("ranker lock poisoned".to_string());
            }
        };
        let Some(mut candidate) = cache.take() else {
            self.metrics
                .ranker_unavailable
                .fetch_add(1, Ordering::Relaxed);
            return Err("ranker unavailable; explicit reload required".to_string());
        };
        // Keep the cache absent on witness errors, panics and failed refreshes.
        // The provider cannot inject a bare file/receipt: the artifact authority
        // must first issue an opaque verified CURRENT view.
        let current = match self.current.current() {
            Ok(current) => current,
            Err(error) => {
                self.metrics
                    .current_view_failures
                    .fetch_add(1, Ordering::Relaxed);
                return Err(error);
            }
        };
        let result = match candidate.with_current(current, |_| consume()) {
            Ok(result) => result?,
            Err(error) => {
                self.metrics
                    .revalidation_failures
                    .fetch_add(1, Ordering::Relaxed);
                return Err(error.to_string());
            }
        };
        *cache = Some(candidate);
        Ok(result)
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
            self.metrics
                .input_rejections
                .fetch_add(1, Ordering::Relaxed);
            return Err("ranking candidates exceed cognitive read bound".to_string());
        }
        let sensor = match cognitive_sensor_id(query) {
            Ok(sensor) => sensor,
            Err(error) => {
                self.metrics
                    .input_rejections
                    .fetch_add(1, Ordering::Relaxed);
                return Err(error);
            }
        };
        self.with_current(|| {
            let mut scored = Vec::with_capacity(items.len());
            for (index, item) in items.iter().enumerate() {
                let action = match cognitive_action_id(item) {
                    Ok(action) => action,
                    Err(error) => {
                        self.metrics
                            .prediction_failures
                            .fetch_add(1, Ordering::Relaxed);
                        return Err(error);
                    }
                };
                match self.model.predict(&sensor, &action) {
                    Ok(prediction) => scored.push((index, prediction.value.raw())),
                    // Partial support abstains from this downstream policy
                    // decision rather than silently assigning a fabricated
                    // propensity to a partially observed action set.
                    Err(TabularPayloadError::UnsupportedCell) => {
                        self.metrics
                            .unsupported_abstentions
                            .fetch_add(1, Ordering::Relaxed);
                        return Ok(CognitiveRankObservation {
                            policy_digest: self.policy_digest,
                            propensity: ProbabilityQ32::ONE,
                            applied: false,
                        });
                    }
                    Err(error) => {
                        self.metrics
                            .prediction_failures
                            .fetch_add(1, Ordering::Relaxed);
                        return Err(error.to_string());
                    }
                }
            }
            scored.sort_by(|left, right| right.1.cmp(&left.1).then(left.0.cmp(&right.0)));
            let original = items.to_vec();
            for (destination, (source, _)) in scored.into_iter().enumerate() {
                items[destination] = original[source].clone();
            }
            self.metrics
                .rankings_applied
                .fetch_add(1, Ordering::Relaxed);
            Ok(CognitiveRankObservation {
                policy_digest: self.policy_digest,
                propensity: ProbabilityQ32::ONE,
                applied: true,
            })
        })
    }
}

#[cfg(test)]
mod metric_tests {
    use super::*;

    #[test]
    fn ranker_metrics_snapshot_is_monotonic_and_reason_specific() {
        let counters = CognitiveRankerCountersV1::default();
        counters.rankings_applied.fetch_add(2, Ordering::Relaxed);
        counters
            .unsupported_abstentions
            .fetch_add(3, Ordering::Relaxed);
        counters
            .current_view_failures
            .fetch_add(5, Ordering::Relaxed);
        counters
            .revalidation_failures
            .fetch_add(7, Ordering::Relaxed);
        counters
            .prediction_failures
            .fetch_add(11, Ordering::Relaxed);
        counters
            .ranker_unavailable
            .fetch_add(13, Ordering::Relaxed);
        counters
            .identity_rejections
            .fetch_add(17, Ordering::Relaxed);
        counters
            .input_rejections
            .fetch_add(19, Ordering::Relaxed);
        assert_eq!(
            counters.snapshot(),
            CognitiveRankerMetricsV1 {
                rankings_applied: 2,
                unsupported_abstentions: 3,
                current_view_failures: 5,
                revalidation_failures: 7,
                prediction_failures: 11,
                ranker_unavailable: 13,
                identity_rejections: 17,
                input_rejections: 19,
            }
        );
    }
}

#[cfg(test)]
#[path = "cognitive_ranker_tests.rs"]
mod tests;
