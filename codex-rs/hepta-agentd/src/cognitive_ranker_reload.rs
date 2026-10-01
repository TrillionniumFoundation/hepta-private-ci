//! RCU-style replacement for independently admitted immutable rankers.
//!
//! Readers clone one `Arc` without blocking a reload. The caller must construct
//! the successor through the same evaluated selection/rollback admission before
//! publishing it here; this wrapper never selects or validates model bytes.

use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use arc_swap::ArcSwap;
use codex_hepta_contracts::AgentId;

use super::CognitiveRankObservation;
use super::PinnedCognitiveRanker;
use crate::CognitiveContextItem;

pub struct ReloadableCognitiveRanker {
    current: ArcSwap<PinnedCognitiveRanker>,
    reload_count: AtomicU64,
}

impl ReloadableCognitiveRanker {
    #[must_use]
    pub fn new(initial: Arc<PinnedCognitiveRanker>) -> Self {
        Self {
            current: ArcSwap::from(initial),
            reload_count: AtomicU64::new(0),
        }
    }

    #[must_use]
    pub fn snapshot(&self) -> Arc<PinnedCognitiveRanker> {
        self.current.load_full()
    }

    /// Publish only an already-admitted immutable successor or rollback model.
    pub fn reload(&self, next: Arc<PinnedCognitiveRanker>) -> u64 {
        self.current.store(next);
        self.reload_count
            .fetch_add(1, Ordering::AcqRel)
            .saturating_add(1)
    }

    #[must_use]
    pub fn reload_count(&self) -> u64 {
        self.reload_count.load(Ordering::Acquire)
    }

    pub(crate) fn rank(
        &self,
        owner: &AgentId,
        generation: u64,
        query: &str,
        items: &mut [CognitiveContextItem],
    ) -> Result<CognitiveRankObservation, String> {
        self.current
            .load()
            .rank(owner, generation, query, items)
    }
}
