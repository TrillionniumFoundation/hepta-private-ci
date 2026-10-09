//! Read-only, authority-free generation/fence-scoped cache. The caller must
//! authenticate every lane rotation with its registry/authority owner.

use std::collections::BTreeMap;
use std::sync::Arc;

use codex_hepta_types::StableId;

use crate::bounded_batch::BatchLaneKeyV1;

const MAX_CACHE_ITEMS: usize = 4_096;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CacheDomainV1 {
    Authority,
    Ndu,
    Worker,
    Retrieval,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CacheErrorV1 {
    InvalidCapacity,
    InvalidLane,
    StaleLane,
    CapacityExceeded,
    AlreadyPresent,
}

#[derive(Debug)]
pub struct GenerationScopedCacheV1<T> {
    domain: CacheDomainV1,
    active: BatchLaneKeyV1,
    maximum_items: usize,
    entries: BTreeMap<StableId, Arc<T>>,
}

impl<T> GenerationScopedCacheV1<T> {
    pub fn new(
        domain: CacheDomainV1,
        lane: BatchLaneKeyV1,
        maximum_items: usize,
    ) -> Result<Self, CacheErrorV1> {
        if maximum_items == 0 || maximum_items > MAX_CACHE_ITEMS {
            return Err(CacheErrorV1::InvalidCapacity);
        }
        lane.validate().map_err(|_| CacheErrorV1::InvalidLane)?;
        Ok(Self {
            domain,
            active: lane,
            maximum_items,
            entries: BTreeMap::new(),
        })
    }

    pub fn domain(&self) -> CacheDomainV1 {
        self.domain
    }

    pub fn active_lane(&self) -> BatchLaneKeyV1 {
        self.active
    }

    /// A changed fence or revocation frontier invalidates ALL old snapshots.
    /// Rotations with a regressing generation or authority epoch are rejected.
    /// An authenticated registry owner must supply the new lane.
    pub fn rotate(&mut self, lane: BatchLaneKeyV1) -> Result<bool, CacheErrorV1> {
        lane.validate().map_err(|_| CacheErrorV1::InvalidLane)?;
        if lane == self.active {
            return Ok(false);
        }
        if lane.generation < self.active.generation
            || lane.authority_epoch < self.active.authority_epoch
            || (lane.generation == self.active.generation
                && lane.authority_epoch == self.active.authority_epoch)
        {
            return Err(CacheErrorV1::StaleLane);
        }
        self.entries.clear();
        self.active = lane;
        Ok(true)
    }

    /// Snapshots are immutable within a lane. Replacing an existing value
    /// requires rotation to a newer trusted generation/authority epoch.
    pub fn insert(
        &mut self,
        lane: BatchLaneKeyV1,
        id: StableId,
        value: Arc<T>,
    ) -> Result<(), CacheErrorV1> {
        if lane != self.active {
            return Err(CacheErrorV1::StaleLane);
        }
        if self.entries.contains_key(&id) {
            return Err(CacheErrorV1::AlreadyPresent);
        }
        if self.entries.len() >= self.maximum_items {
            return Err(CacheErrorV1::CapacityExceeded);
        }
        self.entries.insert(id, value);
        Ok(())
    }

    pub fn get(&self, lane: BatchLaneKeyV1, id: &StableId) -> Option<Arc<T>> {
        if lane != self.active {
            return None;
        }
        self.entries.get(id).cloned()
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
}

#[cfg(test)]
#[path = "scoped_cache_tests.rs"]
mod tests;
