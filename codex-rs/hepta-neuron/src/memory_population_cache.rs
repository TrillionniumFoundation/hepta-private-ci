//! Bounded resident tensor cache, without artifact or writer authority.

use std::collections::BTreeMap;
use std::time::Instant;

use codex_hepta_types::Digest32;

use crate::AssociativeMemoryAbstentionV1;
use crate::AssociativeMemoryCellV1;
use crate::AssociativeMemoryError;
use crate::AssociativeMemoryPredictionV1;
use crate::memory_population::MemoryCellPopulationV2;
use crate::memory_population_cost::MemoryPopulationCostV2;

pub(super) struct PopulationCache {
    entries: BTreeMap<usize, (u64, AssociativeMemoryCellV1)>,
    budget: u64,
    reads: u64,
    wakes: u64,
    evictions: u64,
    read_wall_ns: u64,
    wake_wall_ns: u64,
}

impl PopulationCache {
    pub fn new(budget: u64) -> Self {
        Self { entries: BTreeMap::new(), budget, reads: 0, wakes: 0, evictions: 0,
            read_wall_ns: 0, wake_wall_ns: 0 }
    }
    fn evict_oldest(&mut self) {
        if let Some(index) = self.entries.iter().min_by_key(|(index, (tick, _))| (*tick, **index)).map(|(index, _)| *index) {
            self.entries.remove(&index);
            self.evictions = self.evictions.saturating_add(1);
        }
    }
}

impl MemoryCellPopulationV2 {
    /// Change only resident-cache capacity. A shard that exceeds this bound
    /// fails closed; neither raw artifacts nor authority are changed.
    pub fn set_resident_budget(&self, bytes: u64) -> Result<(), AssociativeMemoryError> {
        let mut cache = self.cache.lock().map_err(|_| AssociativeMemoryError::InvalidConfiguration)?;
        cache.budget = bytes;
        while self.resident_bytes(&cache) > bytes { cache.evict_oldest(); }
        Ok(())
    }

    /// Drop all decoded parameter shards. The next supported read must pay the
    /// measured load cost and satisfy the current resident budget.
    pub fn sleep(&self) -> Result<(), AssociativeMemoryError> {
        let mut cache = self.cache.lock().map_err(|_| AssociativeMemoryError::InvalidConfiguration)?;
        while !cache.entries.is_empty() { cache.evict_oldest(); }
        Ok(())
    }

    pub fn cost(&self) -> Result<MemoryPopulationCostV2, AssociativeMemoryError> {
        let cache = self.cache.lock().map_err(|_| AssociativeMemoryError::InvalidConfiguration)?;
        let mut cost = self.costs.clone();
        for index in cache.entries.keys() {
            let shard = self.shard_costs[*index];
            cost.resident_parameter_bytes += shard.parameters;
            cost.resident_catalog_bytes += shard.catalog;
            cost.resident_support_bytes += shard.support;
            cost.resident_lineage_bytes += shard.lineage;
        }
        cost.resident_budget_bytes = cache.budget;
        cost.resident_shards = cache.entries.len();
        cost.wake_count = cache.wakes;
        cost.eviction_count = cache.evictions;
        cost.read_count = cache.reads;
        cost.read_wall_ns = cache.read_wall_ns;
        cost.wake_wall_ns = cache.wake_wall_ns;
        Ok(cost)
    }

    /// Execute the selected shard's tensors. V2 prediction digests bind the
    /// complete routing/parameter population; source IDs come from that shard.
    pub fn predict(&self, key: &str) -> Result<AssociativeMemoryPredictionV1, AssociativeMemoryError> {
        let started = Instant::now();
        if key.is_empty() || key.len() > 4096 { return Err(AssociativeMemoryError::InvalidInput); }
        let mut cache = self.cache.lock().map_err(|_| AssociativeMemoryError::InvalidConfiguration)?;
        cache.reads = cache.reads.saturating_add(1);
        let result = self.predict_locked(key, &mut cache);
        cache.read_wall_ns = cache.read_wall_ns.saturating_add(elapsed(started));
        result
    }

    fn predict_locked(&self, key: &str, cache: &mut PopulationCache) -> Result<AssociativeMemoryPredictionV1, AssociativeMemoryError> {
        let Some(index) = self.routes.get(&Digest32::of_bytes(key.as_bytes()).to_string()).copied() else {
            return Ok(AssociativeMemoryPredictionV1 { kind: self.kind, value: None, confidence: 0.0,
                confidence_kind: "uncalibrated-softmax", source_ids: Vec::new(),
                artifact_digest: self.digest.to_string(), parameter_digest: self.parameter_digest.to_string(),
                abstain: Some(AssociativeMemoryAbstentionV1::OutsideWrittenSupport) });
        };
        let required = self.shard_costs[index].resident_bytes();
        if required > cache.budget { return Err(AssociativeMemoryError::InvalidConfiguration); }
        if !cache.entries.contains_key(&index) {
            while self.resident_bytes(cache) + required > cache.budget { cache.evict_oldest(); }
            let started = Instant::now();
            let shard = &self.shards[index];
            let loaded = AssociativeMemoryCellV1::from_bytes(shard.payload.as_bytes(), Digest32::of_bytes(shard.payload.as_bytes()));
            cache.wake_wall_ns = cache.wake_wall_ns.saturating_add(elapsed(started));
            cache.entries.insert(index, (cache.reads, loaded?));
            cache.wakes = cache.wakes.saturating_add(1);
        }
        let (tick, model) = cache.entries.get_mut(&index).ok_or(AssociativeMemoryError::InvalidConfiguration)?;
        *tick = cache.reads;
        let mut result = model.predict(key)?;
        result.artifact_digest = self.digest.to_string();
        result.parameter_digest = self.parameter_digest.to_string();
        Ok(result)
    }

    fn resident_bytes(&self, cache: &PopulationCache) -> u64 {
        cache.entries.keys().map(|index| self.shard_costs[*index].resident_bytes()).sum()
    }
}

fn elapsed(started: Instant) -> u64 { u64::try_from(started.elapsed().as_nanos()).unwrap_or(u64::MAX) }
