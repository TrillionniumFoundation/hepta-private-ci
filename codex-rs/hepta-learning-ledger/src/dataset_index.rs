//! Replay-built objective-local dataset lookup. This is not a persisted truth
//! source: only validated new appends populate it, and recovery rebuilds it.
//! Revocations remain global because the V2 freeze cut deliberately binds them.
use std::collections::BTreeMap;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::LedgerEvent;

#[derive(Clone, Debug, Default)]
pub(crate) struct DatasetRecordIndex {
    objectives: BTreeMap<Digest32, Vec<usize>>,
    episodes: BTreeMap<StableId, Digest32>,
    revocations: Vec<usize>,
}

impl DatasetRecordIndex {
    pub(crate) fn append(&mut self, event: &LedgerEvent, position: usize) {
        let objective = match event {
            LedgerEvent::AuthenticatedDecisionV2(value) => {
                self.episodes
                    .insert(value.episode_id.clone(), value.objective_digest);
                Some(value.objective_digest)
            }
            LedgerEvent::AuthenticatedOutcomeV2(value) => {
                self.episodes.get(&value.episode_id).copied()
            }
            LedgerEvent::CreditBatchV2(value) => self.episodes.get(&value.episode_id).copied(),
            LedgerEvent::Revocation(_) | LedgerEvent::UnlearningLineageV1(_) => {
                self.revocations.push(position);
                None
            }
            LedgerEvent::Decision(_)
            | LedgerEvent::Outcome(_)
            | LedgerEvent::Credit(_)
            | LedgerEvent::PromptDelivery(_)
            | LedgerEvent::RetrievalAssignment(_) => None,
        };
        if let Some(objective) = objective {
            self.objectives.entry(objective).or_default().push(position);
        }
    }

    pub(crate) fn objective(&self, digest: &Digest32) -> &[usize] {
        self.objectives.get(digest).map_or(&[], Vec::as_slice)
    }

    pub(crate) fn revocations(&self) -> &[usize] {
        &self.revocations
    }
}
