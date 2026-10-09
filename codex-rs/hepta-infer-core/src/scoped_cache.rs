//! One generic backend for scope/generation/fence/epoch-scoped immutable caches.
//!
//! These are performance hints, never grants. A hit never replaces final-use
//! verification of lease, NDU head, route, revocation or worker authorization.

use std::collections::BTreeMap;
use std::sync::Arc;

use codex_hepta_types::{Digest32, Generation, StableId};

pub const MAX_CACHED_SCOPES: usize = 4096;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CacheFamilyV1 {
    AuthorityObservation,
    NduSnapshot,
    Worker,
    RetrievalClient,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct FenceCacheBindingV1 {
    pub scope: StableId,
    pub generation: Generation,
    pub route_fence: u64,
    pub revocation_epoch: u64,
    /// Digest of the exact admitted cache input (including owner identity).
    pub binding_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FenceCacheErrorV1 {
    Capacity,
    InvalidCapacity,
    InvalidBinding,
    StaleBinding,
    SameEpochConflict,
    InvalidExpiry,
}

#[derive(Debug)]
struct CacheScopeV1<T> {
    binding: FenceCacheBindingV1,
    entry: Option<(Arc<T>, u64)>,
}

/// Each scope has exactly one current binding and at most one immutable value.
/// Replacing or invalidating a scope is O(log scopes), not O(total entries).
#[derive(Debug)]
pub struct GenerationFenceCacheV1<T> {
    pub family: CacheFamilyV1,
    scopes: BTreeMap<StableId, CacheScopeV1<T>>,
    maximum_scopes: usize,
}

impl<T> GenerationFenceCacheV1<T> {
    pub fn new(family: CacheFamilyV1, maximum_scopes: usize) -> Result<Self, FenceCacheErrorV1> {
        if maximum_scopes == 0 || maximum_scopes > MAX_CACHED_SCOPES {
            return Err(FenceCacheErrorV1::InvalidCapacity);
        }
        Ok(Self { family, scopes: BTreeMap::new(), maximum_scopes })
    }

    pub fn scopes(&self) -> usize {
        self.scopes.len()
    }

    /// A new admitted epoch invalidates the old value. A change to the binding
    /// digest in the same epoch is never silently accepted.
    pub fn observe_binding(&mut self, binding: FenceCacheBindingV1) -> Result<(), FenceCacheErrorV1> {
        validate(&binding)?;
        match self.scopes.get_mut(&binding.scope) {
            Some(old) => {
                if binding == old.binding {
                    return Ok(());
                }
                if binding.generation < old.binding.generation
                    || binding.route_fence < old.binding.route_fence
                    || binding.revocation_epoch < old.binding.revocation_epoch
                {
                    return Err(FenceCacheErrorV1::StaleBinding);
                }
                if binding.route_fence == old.binding.route_fence
                    && binding.revocation_epoch == old.binding.revocation_epoch
                {
                    return Err(FenceCacheErrorV1::SameEpochConflict);
                }
                old.binding = binding;
                old.entry = None;
                Ok(())
            }
            None => {
                if self.scopes.len() >= self.maximum_scopes {
                    return Err(FenceCacheErrorV1::Capacity);
                }
                self.scopes.insert(binding.scope.clone(), CacheScopeV1 { binding, entry: None });
                Ok(())
            }
        }
    }

    pub fn put(
        &mut self,
        now_ms: u64,
        binding: &FenceCacheBindingV1,
        value: Arc<T>,
        expires_at_ms: u64,
    ) -> Result<(), FenceCacheErrorV1> {
        if expires_at_ms <= now_ms {
            return Err(FenceCacheErrorV1::InvalidExpiry);
        }
        let state = self.scopes.get_mut(&binding.scope).ok_or(FenceCacheErrorV1::StaleBinding)?;
        if state.binding != *binding {
            return Err(FenceCacheErrorV1::StaleBinding);
        }
        state.entry = Some((value, expires_at_ms));
        Ok(())
    }

    pub fn get(&self, now_ms: u64, binding: &FenceCacheBindingV1) -> Option<Arc<T>> {
        let state = self.scopes.get(&binding.scope)?;
        if state.binding != *binding {
            return None;
        }
        let (value, expiry) = state.entry.as_ref()?;
        (now_ms < *expiry).then(|| Arc::clone(value))
    }

    /// Keep a tombstone watermark at this scope: old epochs cannot re-enter.
    pub fn invalidate(&mut self, new_binding: FenceCacheBindingV1) -> Result<(), FenceCacheErrorV1> {
        self.observe_binding(new_binding.clone())?;
        if let Some(state) = self.scopes.get_mut(&new_binding.scope) {
            state.entry = None;
        }
        Ok(())
    }
}

/// Facade only: all four families use the same backend semantics.
#[derive(Debug)]
pub struct ScopedCachesV1<A, N, W, R> {
    pub authority: GenerationFenceCacheV1<A>,
    pub ndu: GenerationFenceCacheV1<N>,
    pub worker: GenerationFenceCacheV1<W>,
    pub retrieval: GenerationFenceCacheV1<R>,
}

impl<A, N, W, R> ScopedCachesV1<A, N, W, R> {
    pub fn new(maximum_scopes: usize) -> Result<Self, FenceCacheErrorV1> {
        Ok(Self {
            authority: GenerationFenceCacheV1::new(CacheFamilyV1::AuthorityObservation, maximum_scopes)?,
            ndu: GenerationFenceCacheV1::new(CacheFamilyV1::NduSnapshot, maximum_scopes)?,
            worker: GenerationFenceCacheV1::new(CacheFamilyV1::Worker, maximum_scopes)?,
            retrieval: GenerationFenceCacheV1::new(CacheFamilyV1::RetrievalClient, maximum_scopes)?,
        })
    }
}

fn validate(key: &FenceCacheBindingV1) -> Result<(), FenceCacheErrorV1> {
    if key.route_fence == 0 || key.revocation_epoch == 0 || key.binding_digest.is_zero() {
        return Err(FenceCacheErrorV1::InvalidBinding);
    }
    Ok(())
}

#[cfg(test)]
#[path = "scoped_cache_tests.rs"]
mod tests;
