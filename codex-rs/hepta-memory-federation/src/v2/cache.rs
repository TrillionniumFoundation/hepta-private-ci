use std::collections::{BTreeMap, BTreeSet};
use std::sync::Mutex;

use codex_hepta_types::{Digest32, StableId};

use super::authority::{
    FederationAuthorityV2, FederationClockV2, VerifiedCapabilityReceiptV2, ensure_same_capability,
};
use super::model::{
    FederatedLeaseV2, FederatedQueryV2, FederatedResultV2, FederatedValidityV2, FederationV2Error,
};

#[derive(Clone, Debug, Eq, PartialEq)]
struct FederationCacheEntryV2 {
    query: FederatedQueryV2,
    lease: FederatedLeaseV2,
    capability: VerifiedCapabilityReceiptV2,
    result: FederatedResultV2,
}

#[derive(Default)]
struct FederationCacheStateV2 {
    entries: BTreeMap<Digest32, FederationCacheEntryV2>,
    by_grant: BTreeMap<StableId, BTreeSet<Digest32>>,
    by_key: BTreeMap<StableId, BTreeSet<Digest32>>,
    by_peer: BTreeMap<StableId, BTreeSet<Digest32>>,
}

/// Non-authoritative result projection. Every entry is TTL-bounded by the
/// query, raw lease and verified capability, with reverse indexes for immediate
/// grant/key/peer invalidation.
#[derive(Default)]
pub struct FederationCacheV2 {
    state: Mutex<FederationCacheStateV2>,
}

impl FederationCacheV2 {
    pub fn insert(
        &self,
        now_unix_ms: u64,
        query: FederatedQueryV2,
        lease: FederatedLeaseV2,
        capability: VerifiedCapabilityReceiptV2,
        result: FederatedResultV2,
    ) -> Result<(), FederationV2Error> {
        query.validate(now_unix_ms)?;
        lease.validate_claims_for_query(now_unix_ms, &query)?;
        capability.validate_for_query(now_unix_ms, &query, &lease)?;
        result.validate()?;
        let hard_expiry = query
            .deadline_unix_ms
            .min(lease.expires_unix_ms)
            .min(capability.expires_unix_ms);
        if result.query_binding_digest != query.binding_digest()
            || result.capability_receipt_digest != capability.binding_digest()
            || result.grant_id != capability.grant_id
            || result.lease_id != capability.lease_id
            || result.expires_unix_ms > hard_expiry
            || now_unix_ms >= result.expires_unix_ms
        {
            return Err(FederationV2Error::InvalidCacheEntry);
        }
        let key = result.query_binding_digest;
        let mut state = self.state.lock().map_err(|_| FederationV2Error::CachePoisoned)?;
        remove_cache_key(&mut state, key);
        state.entries.insert(
            key,
            FederationCacheEntryV2 {
                query,
                lease,
                capability: capability.clone(),
                result: result.clone(),
            },
        );
        state.by_grant.entry(capability.grant_id.clone()).or_default().insert(key);
        state.by_key.entry(capability.issuer_key_id.clone()).or_default().insert(key);
        state.by_peer.entry(result.peer_id.clone()).or_default().insert(key);
        Ok(())
    }

    pub fn get(
        &self,
        now_unix_ms: u64,
        query_binding_digest: Digest32,
    ) -> Result<Option<FederatedResultV2>, FederationV2Error> {
        let mut state = self.state.lock().map_err(|_| FederationV2Error::CachePoisoned)?;
        if state
            .entries
            .get(&query_binding_digest)
            .is_some_and(|entry| now_unix_ms >= entry.result.expires_unix_ms)
        {
            remove_cache_key(&mut state, query_binding_digest);
            return Ok(None);
        }
        Ok(state.entries.get(&query_binding_digest).map(|entry| entry.result.clone()))
    }

    pub async fn revalidate_remote<A, C>(
        &self,
        authority: &A,
        clock: &C,
        query_binding_digest: Digest32,
    ) -> Result<FederatedValidityV2, FederationV2Error>
    where
        A: FederationAuthorityV2 + ?Sized,
        C: FederationClockV2 + ?Sized,
    {
        let entry = {
            let state = self.state.lock().map_err(|_| FederationV2Error::CachePoisoned)?;
            state
                .entries
                .get(&query_binding_digest)
                .cloned()
                .ok_or(FederationV2Error::CacheMiss)?
        };
        let now = clock.now_unix_ms()?;
        if now >= entry.result.expires_unix_ms {
            self.purge_query(query_binding_digest)?;
            return Ok(FederatedValidityV2::Indeterminate);
        }
        let refreshed = match authority
            .revalidate(now, &entry.query, &entry.lease, &entry.capability)
            .await
        {
            Ok(receipt) => receipt,
            Err(FederationV2Error::LeaseRevoked) => {
                self.purge_grant(&entry.capability.grant_id)?;
                return Ok(FederatedValidityV2::Revoked);
            }
            Err(error) => {
                self.purge_query(query_binding_digest)?;
                return Err(error);
            }
        };
        refreshed.validate_for_query(now, &entry.query, &entry.lease)?;
        ensure_same_capability(&entry.capability, &refreshed)?;
        if refreshed.revocation_epoch < entry.capability.revocation_epoch {
            self.purge_grant(&entry.capability.grant_id)?;
            return Err(FederationV2Error::RevocationEpochRegressed);
        }
        if refreshed.binding_digest() != entry.result.capability_receipt_digest {
            self.purge_query(query_binding_digest)?;
            return Ok(FederatedValidityV2::Indeterminate);
        }
        Ok(entry.result.validity)
    }

    pub fn purge_query(&self, digest: Digest32) -> Result<usize, FederationV2Error> {
        let mut state = self.state.lock().map_err(|_| FederationV2Error::CachePoisoned)?;
        Ok(usize::from(remove_cache_key(&mut state, digest)))
    }

    pub fn purge_grant(&self, id: &StableId) -> Result<usize, FederationV2Error> {
        self.purge_indexed(id, CacheIndexV2::Grant)
    }

    pub fn purge_key(&self, id: &StableId) -> Result<usize, FederationV2Error> {
        self.purge_indexed(id, CacheIndexV2::Key)
    }

    pub fn purge_peer(&self, id: &StableId) -> Result<usize, FederationV2Error> {
        self.purge_indexed(id, CacheIndexV2::Peer)
    }

    pub fn purge_expired(&self, now_unix_ms: u64) -> Result<usize, FederationV2Error> {
        let mut state = self.state.lock().map_err(|_| FederationV2Error::CachePoisoned)?;
        let keys = state
            .entries
            .iter()
            .filter_map(|(key, entry)| (now_unix_ms >= entry.result.expires_unix_ms).then_some(*key))
            .collect::<Vec<_>>();
        let count = keys.len();
        for key in keys {
            remove_cache_key(&mut state, key);
        }
        Ok(count)
    }

    fn purge_indexed(&self, id: &StableId, index: CacheIndexV2) -> Result<usize, FederationV2Error> {
        let mut state = self.state.lock().map_err(|_| FederationV2Error::CachePoisoned)?;
        let keys = match index {
            CacheIndexV2::Grant => state.by_grant.get(id),
            CacheIndexV2::Key => state.by_key.get(id),
            CacheIndexV2::Peer => state.by_peer.get(id),
        }
        .cloned()
        .unwrap_or_default();
        let count = keys.len();
        for key in keys {
            remove_cache_key(&mut state, key);
        }
        Ok(count)
    }
}

#[derive(Clone, Copy)]
enum CacheIndexV2 {
    Grant,
    Key,
    Peer,
}

fn remove_cache_key(state: &mut FederationCacheStateV2, key: Digest32) -> bool {
    let Some(entry) = state.entries.remove(&key) else {
        return false;
    };
    remove_reverse_index(&mut state.by_grant, &entry.capability.grant_id, key);
    remove_reverse_index(&mut state.by_key, &entry.capability.issuer_key_id, key);
    remove_reverse_index(&mut state.by_peer, &entry.result.peer_id, key);
    true
}

fn remove_reverse_index(
    index: &mut BTreeMap<StableId, BTreeSet<Digest32>>,
    id: &StableId,
    key: Digest32,
) {
    let remove_id = index.get_mut(id).is_some_and(|keys| {
        keys.remove(&key);
        keys.is_empty()
    });
    if remove_id {
        index.remove(id);
    }
}
