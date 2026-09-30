//! Generation-view cache with validation typestate and per-digest singleflight.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;
use std::sync::Condvar;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use crate::KnowledgeGenerationErrorV2;
use crate::KnowledgeGenerationV2;
use crate::VerifiedKnowledgeGenerationV2;
use crate::validation::ValidatedKnowledgeGenerationV2;

use super::KnowledgePhysicalLimitsV2;
use super::KnowledgePhysicalUsageV2;
use super::KnowledgeResourceErrorCodeV2;
use super::KnowledgeResourceErrorV2;
use super::validate_generation_physical_limits_v2;


impl KnowledgePhysicalUsageV2 {
    /// Returns the deterministic canonical cost used for admission receipts.
    /// This is not allocator RSS, SQLite page growth, or wire-encoding size.
    #[must_use]
    pub const fn canonical_cost_bytes(self) -> u64 {
        self.canonical_bytes
    }
}

struct CachedGenerationV2 {
    view: Arc<VerifiedKnowledgeGenerationV2>,
    bytes: u64,
    last_access: u64,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct KnowledgeGenerationCacheMetricsV2 {
    pub hits: u64,
    pub misses: u64,
    pub builds: u64,
    pub build_waits: u64,
    pub evictions: u64,
    pub validation_nanos: u64,
    pub index_build_nanos: u64,
    pub coordination_lock_wait_nanos: u64,
    pub resident_entries: u64,
    pub resident_canonical_cost_bytes: u64,
}

#[derive(Default)]
struct KnowledgeGenerationCacheCountersV2 {
    hits: AtomicU64,
    misses: AtomicU64,
    builds: AtomicU64,
    build_waits: AtomicU64,
    evictions: AtomicU64,
    validation_nanos: AtomicU64,
    index_build_nanos: AtomicU64,
    coordination_lock_wait_nanos: AtomicU64,
}

struct KnowledgeGenerationBuildSlotV2 {
    completed: Mutex<bool>,
    ready: Condvar,
}

impl KnowledgeGenerationBuildSlotV2 {
    fn new() -> Self {
        Self {
            completed: Mutex::new(false),
            ready: Condvar::new(),
        }
    }
}

#[derive(Debug)]
pub enum KnowledgeCacheErrorV2 {
    Generation(KnowledgeGenerationErrorV2),
    Resource(KnowledgeResourceErrorV2),
}

impl fmt::Display for KnowledgeCacheErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Generation(error) => write!(formatter, "{error}"),
            Self::Resource(error) => write!(formatter, "{error}"),
        }
    }
}

impl StdError for KnowledgeCacheErrorV2 {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Generation(error) => Some(error),
            Self::Resource(error) => Some(error),
        }
    }
}

struct KnowledgeGenerationCacheStateV2 {
    clock: u64,
    bytes: u64,
    entries: BTreeMap<String, CachedGenerationV2>,
}

pub struct KnowledgeGenerationCacheV2 {
    maximum_entries: usize,
    maximum_bytes: u64,
    limits: KnowledgePhysicalLimitsV2,
    state: Mutex<KnowledgeGenerationCacheStateV2>,
    builds: Mutex<BTreeMap<String, Arc<KnowledgeGenerationBuildSlotV2>>>,
    counters: KnowledgeGenerationCacheCountersV2,
}

impl KnowledgeGenerationCacheV2 {
    pub fn new(
        maximum_entries: usize,
        maximum_bytes: u64,
        limits: KnowledgePhysicalLimitsV2,
    ) -> Self {
        Self {
            maximum_entries,
            maximum_bytes,
            limits,
            state: Mutex::new(KnowledgeGenerationCacheStateV2 {
                clock: 0,
                bytes: 0,
                entries: BTreeMap::new(),
            }),
            builds: Mutex::new(BTreeMap::new()),
            counters: KnowledgeGenerationCacheCountersV2::default(),
        }
    }

    pub fn get_or_insert(
        &self,
        generation: KnowledgeGenerationV2,
    ) -> Result<Arc<VerifiedKnowledgeGenerationV2>, KnowledgeCacheErrorV2> {
        let validation_started = Instant::now();
        let validated = ValidatedKnowledgeGenerationV2::new(generation)
            .map_err(KnowledgeCacheErrorV2::Generation)?;
        self.counters.validation_nanos.fetch_add(
            duration_nanos(validation_started.elapsed()),
            Ordering::Relaxed,
        );
        let digest = validated.generation().generation_digest.to_string();
        let usage = validate_generation_physical_limits_v2(validated.generation(), self.limits)
            .map_err(KnowledgeCacheErrorV2::Resource)?;
        if usage.canonical_bytes > self.maximum_bytes || self.maximum_entries == 0 {
            return Err(KnowledgeCacheErrorV2::Resource(
                KnowledgeResourceErrorV2::exceeded(
                    KnowledgeResourceErrorCodeV2::CacheCapacityExceeded,
                    usage.canonical_bytes,
                    self.maximum_bytes,
                    "single cached generation canonical cost",
                ),
            ));
        }

        let mut validated = Some(validated);
        let mut initial_lookup = true;
        loop {
            if let Some(view) = self.cached_view(&digest)? {
                self.counters.hits.fetch_add(1, Ordering::Relaxed);
                return Ok(view);
            }
            if initial_lookup {
                self.counters.misses.fetch_add(1, Ordering::Relaxed);
                initial_lookup = false;
            }

            let (slot, is_builder) = self.claim_build(&digest)?;
            if !is_builder {
                self.counters.build_waits.fetch_add(1, Ordering::Relaxed);
                self.wait_for_build(&slot)?;
                continue;
            }

            // Close the lookup/claim race without constructing a second index.
            match self.cached_view(&digest) {
                Ok(Some(view)) => {
                    self.counters.hits.fetch_add(1, Ordering::Relaxed);
                    return self.finish_build_result(&digest, &slot, Ok(view));
                }
                Ok(None) => {}
                Err(error) => {
                    return self.finish_build_result(&digest, &slot, Err(error));
                }
            }

            let Some(validated) = validated.take() else {
                return self.finish_build_result(
                    &digest,
                    &slot,
                    Err(cache_state_error(
                        "validated generation ownership during cache build",
                    )),
                );
            };
            let build_started = Instant::now();
            let built = Arc::new(VerifiedKnowledgeGenerationV2::from_validated(validated));
            self.counters.builds.fetch_add(1, Ordering::Relaxed);
            self.counters.index_build_nanos.fetch_add(
                duration_nanos(build_started.elapsed()),
                Ordering::Relaxed,
            );
            let result = self.insert_built_view(&digest, usage.canonical_bytes, built);
            return self.finish_build_result(&digest, &slot, result);
        }
    }

    fn cached_view(
        &self,
        digest: &str,
    ) -> Result<Option<Arc<VerifiedKnowledgeGenerationV2>>, KnowledgeCacheErrorV2> {
        let lock_started = Instant::now();
        let mut state = self
            .state
            .lock()
            .map_err(|_| cache_state_error("generation cache mutex"))?;
        self.record_coordination_wait(lock_started.elapsed());
        state.clock = state.clock.saturating_add(1);
        let clock = state.clock;
        Ok(state.entries.get_mut(digest).map(|entry| {
            entry.last_access = clock;
            Arc::clone(&entry.view)
        }))
    }

    fn claim_build(
        &self,
        digest: &str,
    ) -> Result<(Arc<KnowledgeGenerationBuildSlotV2>, bool), KnowledgeCacheErrorV2> {
        let lock_started = Instant::now();
        let mut builds = self
            .builds
            .lock()
            .map_err(|_| cache_state_error("generation cache build registry"))?;
        self.record_coordination_wait(lock_started.elapsed());
        if let Some(slot) = builds.get(digest) {
            return Ok((Arc::clone(slot), false));
        }
        let slot = Arc::new(KnowledgeGenerationBuildSlotV2::new());
        builds.insert(digest.to_string(), Arc::clone(&slot));
        Ok((slot, true))
    }

    fn wait_for_build(
        &self,
        slot: &KnowledgeGenerationBuildSlotV2,
    ) -> Result<(), KnowledgeCacheErrorV2> {
        let lock_started = Instant::now();
        let mut completed = slot
            .completed
            .lock()
            .map_err(|_| cache_state_error("generation cache build slot"))?;
        self.record_coordination_wait(lock_started.elapsed());
        while !*completed {
            completed = slot
                .ready
                .wait(completed)
                .map_err(|_| cache_state_error("generation cache build wait"))?;
        }
        Ok(())
    }

    fn finish_build_result<T>(
        &self,
        digest: &str,
        slot: &Arc<KnowledgeGenerationBuildSlotV2>,
        result: Result<T, KnowledgeCacheErrorV2>,
    ) -> Result<T, KnowledgeCacheErrorV2> {
        let finish = self.finish_build(digest, slot);
        match (result, finish) {
            (Ok(value), Ok(())) => Ok(value),
            (Err(error), _) => Err(error),
            (Ok(_), Err(error)) => Err(error),
        }
    }

    fn finish_build(
        &self,
        digest: &str,
        slot: &Arc<KnowledgeGenerationBuildSlotV2>,
    ) -> Result<(), KnowledgeCacheErrorV2> {
        {
            let mut completed = slot
                .completed
                .lock()
                .map_err(|_| cache_state_error("generation cache build completion"))?;
            *completed = true;
            slot.ready.notify_all();
        }
        let lock_started = Instant::now();
        let mut builds = self
            .builds
            .lock()
            .map_err(|_| cache_state_error("generation cache build registry"))?;
        self.record_coordination_wait(lock_started.elapsed());
        let remove = builds
            .get(digest)
            .is_some_and(|current| Arc::ptr_eq(current, slot));
        if remove {
            builds.remove(digest);
        }
        Ok(())
    }

    fn insert_built_view(
        &self,
        digest: &str,
        canonical_cost_bytes: u64,
        view: Arc<VerifiedKnowledgeGenerationV2>,
    ) -> Result<Arc<VerifiedKnowledgeGenerationV2>, KnowledgeCacheErrorV2> {
        let lock_started = Instant::now();
        let mut state = self
            .state
            .lock()
            .map_err(|_| cache_state_error("generation cache mutex"))?;
        self.record_coordination_wait(lock_started.elapsed());
        state.clock = state.clock.saturating_add(1);
        let clock = state.clock;
        if let Some(entry) = state.entries.get_mut(digest) {
            entry.last_access = clock;
            return Ok(Arc::clone(&entry.view));
        }
        while state.entries.len() >= self.maximum_entries
            || state.bytes.saturating_add(canonical_cost_bytes) > self.maximum_bytes
        {
            let Some(oldest) = state
                .entries
                .iter()
                .min_by_key(|(_, entry)| entry.last_access)
                .map(|(key, _)| key.clone())
            else {
                break;
            };
            if let Some(removed) = state.entries.remove(&oldest) {
                state.bytes = state.bytes.saturating_sub(removed.bytes);
                self.counters.evictions.fetch_add(1, Ordering::Relaxed);
            }
        }
        state.bytes = state.bytes.saturating_add(canonical_cost_bytes);
        state.entries.insert(
            digest.to_string(),
            CachedGenerationV2 {
                view: Arc::clone(&view),
                bytes: canonical_cost_bytes,
                last_access: clock,
            },
        );
        Ok(view)
    }

    fn record_coordination_wait(&self, duration: Duration) {
        self.counters.coordination_lock_wait_nanos.fetch_add(
            duration_nanos(duration),
            Ordering::Relaxed,
        );
    }

    pub fn metrics(
        &self,
    ) -> Result<KnowledgeGenerationCacheMetricsV2, KnowledgeResourceErrorV2> {
        let lock_started = Instant::now();
        let state = self.state.lock().map_err(|_| {
            KnowledgeResourceErrorV2::exceeded(
                KnowledgeResourceErrorCodeV2::StatePoisoned,
                1,
                0,
                "generation cache mutex",
            )
        })?;
        self.record_coordination_wait(lock_started.elapsed());
        Ok(KnowledgeGenerationCacheMetricsV2 {
            hits: self.counters.hits.load(Ordering::Relaxed),
            misses: self.counters.misses.load(Ordering::Relaxed),
            builds: self.counters.builds.load(Ordering::Relaxed),
            build_waits: self.counters.build_waits.load(Ordering::Relaxed),
            evictions: self.counters.evictions.load(Ordering::Relaxed),
            validation_nanos: self.counters.validation_nanos.load(Ordering::Relaxed),
            index_build_nanos: self.counters.index_build_nanos.load(Ordering::Relaxed),
            coordination_lock_wait_nanos: self
                .counters
                .coordination_lock_wait_nanos
                .load(Ordering::Relaxed),
            resident_entries: u64::try_from(state.entries.len()).unwrap_or(u64::MAX),
            resident_canonical_cost_bytes: state.bytes,
        })
    }

    pub fn len(&self) -> Result<usize, KnowledgeResourceErrorV2> {
        self.state
            .lock()
            .map(|state| state.entries.len())
            .map_err(|_| {
                KnowledgeResourceErrorV2::exceeded(
                    KnowledgeResourceErrorCodeV2::StatePoisoned,
                    1,
                    0,
                    "generation cache mutex",
                )
            })
    }

    pub fn is_empty(&self) -> Result<bool, KnowledgeResourceErrorV2> {
        self.len().map(|length| length == 0)
    }
}

fn cache_state_error(context: &'static str) -> KnowledgeCacheErrorV2 {
    KnowledgeCacheErrorV2::Resource(KnowledgeResourceErrorV2::exceeded(
        KnowledgeResourceErrorCodeV2::StatePoisoned,
        1,
        0,
        context,
    ))
}

fn duration_nanos(duration: Duration) -> u64 {
    u64::try_from(duration.as_nanos()).unwrap_or(u64::MAX)
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;
    use std::sync::Barrier;
    use std::thread;

    use codex_hepta_types::Digest32;
    use codex_hepta_types::Generation;

    use super::*;
    use crate::KnowledgeProjectionInputV2;
    use crate::MAX_KNOWLEDGE_GENERATION_BYTES_V2;
    use crate::build_complete_generation;
    use crate::measure_generation_v2;

    fn generation(number: u64) -> KnowledgeGenerationV2 {
        build_complete_generation(
            Generation::new(number).unwrap_or_else(|_| panic!("valid generation: {number}")),
            KnowledgeProjectionInputV2 {
                source_snapshot_digest: Digest32::of_bytes(b"cache-source"),
                generation_vector_digest: Digest32::of_bytes(b"cache-vector"),
                graph_profile_digest: Digest32::of_bytes(b"cache-profile"),
                complete_source_cut: true,
                nodes: Vec::new(),
                edges: Vec::new(),
            },
        )
        .unwrap_or_else(|error| panic!("cache fixture generation: {error}"))
    }

    #[test]
    fn generation_cache_singleflights_concurrent_index_builds() {
        let cache = Arc::new(KnowledgeGenerationCacheV2::new(
            2,
            MAX_KNOWLEDGE_GENERATION_BYTES_V2,
            KnowledgePhysicalLimitsV2::default(),
        ));
        let start = Arc::new(Barrier::new(8));
        let mut workers = Vec::new();
        for _ in 0..8 {
            let cache = Arc::clone(&cache);
            let start = Arc::clone(&start);
            workers.push(thread::spawn(move || {
                start.wait();
                cache
                    .get_or_insert(generation(1))
                    .unwrap_or_else(|error| panic!("concurrent cache view: {error}"))
            }));
        }
        let views = workers
            .into_iter()
            .map(|worker| worker.join().unwrap_or_else(|_| panic!("cache worker join")))
            .collect::<Vec<_>>();
        for view in &views[1..] {
            assert!(Arc::ptr_eq(&views[0], view));
        }
        let metrics = cache
            .metrics()
            .unwrap_or_else(|error| panic!("cache metrics: {error}"));
        assert_eq!(metrics.builds, 1);
        assert_eq!(metrics.resident_entries, 1);
        assert_eq!(
            metrics.resident_canonical_cost_bytes,
            measure_generation_v2(&generation(1)).canonical_cost_bytes()
        );
    }

}
