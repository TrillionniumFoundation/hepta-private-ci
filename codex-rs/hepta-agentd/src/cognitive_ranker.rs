//! Read-only learned ranking at the existing Agentd cognitive read boundary.
//!
//! An embedding host explicitly supplies a selected model and independently
//! authenticated current registry views. The normal CLI does not invent either.
//! This component can only permute already-admitted SQLite records; it cannot
//! add context, grant access, select a new artifact, train, or dispatch a turn.

#[cfg(test)]
use std::fs::File;
use std::sync::Arc;
use std::sync::Mutex;

#[cfg(test)]
use codex_hepta_bellman_operator::LoadedTabularOperatorV1;
use codex_hepta_bellman_operator::OperatorAdmissionStageV1;
use codex_hepta_bellman_operator::TabularPayloadError;
#[cfg(test)]
use codex_hepta_bellman_operator::TabularPayloadPinV1;
use codex_hepta_contracts::AgentId;
#[cfg(test)]
use codex_hepta_learning_artifacts::PinnedCandidateSpec;
#[cfg(test)]
use codex_hepta_learning_artifacts::RegistrySnapshotReceipt;
use codex_hepta_learning_artifacts::RevalidatingCandidate;
use codex_hepta_learning_artifacts::VerifiedCurrentRegistryViewV1;
#[cfg(test)]
use codex_hepta_learning_artifacts::load_pinned_candidate;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::CognitiveContextItem;

const MAX_RANKER_ITEMS: usize = 1024;
// Matches the native memory owner's admitted revision size. Ranking borrows
// these bytes and never clones, hashes or drops an item's content.
const MAX_RANKER_ITEM_CONTENT_BYTES: usize = 64 * 1024;

#[path = "cognitive_ranker_cache.rs"]
mod candidate_cache;
use candidate_cache::with_exclusive_candidate;
#[path = "cognitive_ranker_admission.rs"]
mod admission;
pub use admission::CurrentRankerAdmission;
use admission::EvaluatedUse;
pub use admission::RankerAdmissionSnapshotV2;
use admission::RankerModel;

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
    verified_fixture_current_view_with_window(
        snapshot,
        receipt,
        expected_predecessor_head_digest,
        FixtureCurrentWindow {
            issued_at: 20,
            expires_at: 1_000,
            verified_at: 20,
            signer_expires_at: 1_000,
            signer_revoked_at: None,
        },
    )
}

#[cfg(test)]
#[derive(Clone, Copy)]
pub(crate) struct FixtureCurrentWindow {
    issued_at: u64,
    expires_at: u64,
    verified_at: u64,
    signer_expires_at: u64,
    signer_revoked_at: Option<u64>,
}

#[cfg(test)]
pub(crate) fn verified_fixture_current_view_with_window(
    snapshot: File,
    receipt: RegistrySnapshotReceipt,
    expected_predecessor_head_digest: Digest32,
    window: FixtureCurrentWindow,
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
        expires_at: window.signer_expires_at,
        revoked_at: window.signer_revoked_at,
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
            issued_at: window.issued_at,
            expires_at: window.expires_at,
        },
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    let requirement = RegistryHeadRequirementV1 {
        registry_id,
        minimum_generation: generation,
        expected_predecessor_head_digest,
        minimum_authority_epoch: 1,
        now: window.verified_at,
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
    model: RankerModel,
    admission: Option<EvaluatedUse>,
    current: Arc<dyn CurrentCognitiveRegistry>,
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
    if item.memory_id.is_empty()
        || item.memory_id.len() > 256
        || item.content_sha256.len() != 64
        || !item
            .content_sha256
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit())
    {
        return Err("ranking memory identity outside bounded read profile".to_string());
    }
    let mut bytes = Vec::new();
    bytes.extend_from_slice(&(item.memory_id.len() as u64).to_be_bytes());
    bytes.extend_from_slice(item.memory_id.as_bytes());
    bytes.extend_from_slice(&item.revision.to_be_bytes());
    bytes.extend_from_slice(item.content_sha256.as_bytes());
    StableId::new(format!("memory-{}", Digest32::of_bytes(&bytes)))
        .map_err(|error| error.to_string())
}

// The caller's exclusive borrow keeps intermediate permutations private.
// Any error or unwind restores the exact original ordering with numeric swaps;
// neither success nor rollback copies or destroys owned item payloads.
struct RankerOrderTransaction<'a> {
    items: &'a mut [CognitiveContextItem],
    undo: Vec<(usize, usize)>,
}

impl Drop for RankerOrderTransaction<'_> {
    fn drop(&mut self) {
        for &(left, right) in self.undo.iter().rev() {
            self.items.swap(left, right);
        }
    }
}

impl PinnedCognitiveRanker {
    #[must_use]
    pub fn admission_stage(&self) -> OperatorAdmissionStageV1 {
        if self.admission.is_some() {
            OperatorAdmissionStageV1::SelectedReadOnly
        } else {
            OperatorAdmissionStageV1::StructurallyValidated
        }
    }

    #[cfg(test)]
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
            model: RankerModel::Fixture(model),
            admission: None,
            current,
            cache: Mutex::new(Some(RevalidatingCandidate::new(candidate))),
        };
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
        with_exclusive_candidate(&self.cache, |candidate| {
            // The provider cannot inject a bare file/receipt: the artifact
            // authority must first issue an opaque verified CURRENT view.
            // Both owner I/O and immutable model lookups run outside the mutex.
            let current = self.current.current()?;
            if let Some(admission) = &self.admission {
                admission.revalidate(&current)?;
            }
            let result = candidate
                .with_current(current, |_| consume())
                .map_err(|error| error.to_string())??;
            let current = self.current.current()?;
            if let Some(admission) = &self.admission {
                admission.revalidate(&current)?;
            }
            let current_trust = current.trust_digest();
            let current_window = current.use_window();
            candidate
                .with_current(current, |_| ())
                .map_err(|error| error.to_string())?;
            if let Some(admission) = &self.admission {
                admission.revalidate_window(current_trust, current_window)?;
            }
            Ok(result)
        })
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
        if items.len() > MAX_RANKER_ITEMS
            || items
                .iter()
                .any(|item| item.content.len() > MAX_RANKER_ITEM_CONTENT_BYTES)
        {
            return Err("ranking candidates exceed cognitive read bound".to_string());
        }
        let sensor = cognitive_sensor_id(query)?;
        let count = items.len();
        let mut order = RankerOrderTransaction {
            items,
            undo: Vec::with_capacity(count),
        };
        let observation = self.with_current(|| {
            let mut scored = Vec::with_capacity(count);
            for (index, item) in order.items.iter().enumerate() {
                match self.model.predict(&sensor, &cognitive_action_id(item)?) {
                    Ok(prediction) => scored.push((index, prediction.value.raw())),
                    // Partial support abstains from this downstream policy
                    // decision rather than silently assigning a fabricated
                    // propensity to a partially observed action set.
                    Err(TabularPayloadError::UnsupportedCell) => {
                        return Ok(CognitiveRankObservation {
                            policy_digest: self.policy_digest,
                            propensity: ProbabilityQ32::ONE,
                            applied: false,
                        });
                    }
                    Err(error) => return Err(error.to_string()),
                }
            }
            scored.sort_by(|left, right| right.1.cmp(&left.1).then(left.0.cmp(&right.0)));
            let mut destinations = [0_usize; MAX_RANKER_ITEMS];
            for (destination, (source, _)) in scored.into_iter().enumerate() {
                destinations[source] = destination;
            }
            for source in 0..count {
                while destinations[source] != source {
                    let destination = destinations[source];
                    order.items.swap(source, destination);
                    destinations.swap(source, destination);
                    order.undo.push((source, destination));
                }
            }
            Ok(CognitiveRankObservation {
                policy_digest: self.policy_digest,
                propensity: ProbabilityQ32::ONE,
                applied: true,
            })
        })?;
        // Only bounded numeric bookkeeping remains after the release guard.
        order.undo.clear();
        Ok(observation)
    }
}

#[cfg(test)]
#[path = "cognitive_ranker_tests.rs"]
mod tests;

#[cfg(all(test, unix))]
#[path = "cognitive_ranker_evaluated_tests.rs"]
pub(crate) mod evaluated_tests;
