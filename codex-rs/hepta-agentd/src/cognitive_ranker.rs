//! Read-only learned ranking at the existing Agentd cognitive read boundary.
//!
//! An embedding host explicitly supplies a selected model and independently
//! authenticated current registry views. The normal CLI does not invent either.
//! This component can only permute already-admitted SQLite records; it cannot
//! add context, grant access, select a new artifact, train, or dispatch a turn.

use std::fs::File;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_bellman_operator::LoadedTabularOperatorV1;
use codex_hepta_bellman_operator::TabularPayloadError;
use codex_hepta_bellman_operator::TabularPayloadPinV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_learning_artifacts::PinnedCandidateSpec;
use codex_hepta_learning_artifacts::RegistrySnapshotReceipt;
use codex_hepta_learning_artifacts::RevalidatingCandidate;
use codex_hepta_learning_artifacts::load_pinned_candidate;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CognitiveContextItem;

/// The authenticated host, not the model or snapshot file, determines currentness.
/// Implementations must use trusted file capabilities, enforce current epoch and
/// scope, and bound I/O. A failure closes the consumer; no old-view fallback.
pub trait CurrentCognitiveRegistry: Send + Sync {
    fn current(&self) -> Result<(File, RegistrySnapshotReceipt), String>;
}

/// A host-selected, generation-bound read-only ranking consumer. Replacing the
/// model requires an explicit new host/configuration, not a candidate's score.
pub struct PinnedCognitiveRanker {
    owner: AgentId,
    body_generation: u64,
    model: LoadedTabularOperatorV1,
    current: Arc<dyn CurrentCognitiveRegistry>,
    cache: Mutex<Option<RevalidatingCandidate>>,
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
    pub fn load(
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
            model,
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
        let mut cache = self
            .cache
            .lock()
            .map_err(|_| "ranker lock poisoned".to_string())?;
        let Some(mut candidate) = cache.take() else {
            return Err("ranker unavailable; explicit reload required".to_string());
        };
        // Keep the cache absent on witness errors, panics and failed refreshes.
        let (file, receipt) = self.current.current()?;
        let result = candidate
            .with_current(file, receipt, |_| consume())
            .map_err(|error| error.to_string())??;
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
    ) -> Result<(), String> {
        self.require_identity(owner, generation)?;
        if items.len() > 1024 {
            return Err("ranking candidates exceed cognitive read bound".to_string());
        }
        let sensor = cognitive_sensor_id(query)?;
        self.with_current(|| {
            let mut scored = Vec::with_capacity(items.len());
            for (index, item) in items.iter().enumerate() {
                match self.model.predict(&sensor, &cognitive_action_id(item)?) {
                    Ok(prediction) => scored.push((index, prediction.value.raw())),
                    // Partial support must not silently outrank unobserved records.
                    Err(TabularPayloadError::UnsupportedCell) => return Ok(()),
                    Err(error) => return Err(error.to_string()),
                }
            }
            scored.sort_by(|left, right| right.1.cmp(&left.1).then(left.0.cmp(&right.0)));
            let original = items.to_vec();
            for (destination, (source, _)) in scored.into_iter().enumerate() {
                items[destination] = original[source].clone();
            }
            Ok(())
        })
    }
}

#[cfg(test)]
#[path = "cognitive_ranker_tests.rs"]
mod tests;
