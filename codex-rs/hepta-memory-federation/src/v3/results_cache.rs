#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedFederationAuthorityReceiptV3 {
    pub issuer_id: String,
    pub key_id: String,
    pub grant_id: String,
    pub authority_epoch: u64,
    pub principal_id: StableId,
    pub peer_id: StableId,
    pub scope_digest: Digest32,
    pub purpose_digest: Digest32,
    pub query_binding_digest: Digest32,
    pub expires_unix_ms: u64,
    pub signed_grant_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl VerifiedFederationAuthorityReceiptV3 {
    fn from_verified_grant(
        query: &FederatedPeerQueryV3,
        grant: &SignedFinalUseGrant,
        key_id: &str,
    ) -> Result<Self, FederationV3Error> {
        if !external_identifier(key_id)
            || !external_identifier(&grant.grant.signer_id)
            || !external_identifier(&grant.grant.grant_id)
        {
            return Err(FederationV3Error::InvalidAuthorityReceipt);
        }
        let mut proof_bytes = grant
            .grant
            .signing_bytes()
            .map_err(FederationV3Error::Authority)?;
        push_len(&mut proof_bytes, grant.signature.len());
        proof_bytes.extend_from_slice(&grant.signature);
        let signed_grant_digest = Digest32::of_bytes(&proof_bytes);
        let mut receipt = Self {
            issuer_id: grant.grant.signer_id.clone(),
            key_id: key_id.to_owned(),
            grant_id: grant.grant.grant_id.clone(),
            authority_epoch: grant.grant.authority_epoch,
            principal_id: query.principal_id.clone(),
            peer_id: query.peer_id.clone(),
            scope_digest: query.scope_digest,
            purpose_digest: query.purpose_digest,
            query_binding_digest: query.binding_digest(),
            expires_unix_ms: grant.grant.expires_at_unix_ms,
            signed_grant_digest,
            receipt_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt.receipt_digest = receipt.compute_receipt_digest();
        receipt.validate()?;
        Ok(receipt)
    }

    #[must_use]
    pub fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(AUTHORITY_RECEIPT_DOMAIN_V3);
        push_text(&mut bytes, &self.issuer_id);
        push_text(&mut bytes, &self.key_id);
        push_text(&mut bytes, &self.grant_id);
        push_u64(&mut bytes, self.authority_epoch);
        push_id(&mut bytes, &self.principal_id);
        push_id(&mut bytes, &self.peer_id);
        push_digest(&mut bytes, self.scope_digest);
        push_digest(&mut bytes, self.purpose_digest);
        push_digest(&mut bytes, self.query_binding_digest);
        push_u64(&mut bytes, self.expires_unix_ms);
        push_digest(&mut bytes, self.signed_grant_digest);
        Digest32::of_bytes(&bytes)
    }

    pub fn validate(&self) -> Result<(), FederationV3Error> {
        if !external_identifier(&self.issuer_id)
            || !external_identifier(&self.key_id)
            || !external_identifier(&self.grant_id)
            || self.authority_epoch == 0
            || self.expires_unix_ms == 0
        {
            return Err(FederationV3Error::InvalidAuthorityReceipt);
        }
        for (name, digest) in [
            ("authority_scope", self.scope_digest),
            ("authority_purpose", self.purpose_digest),
            ("authority_query_binding", self.query_binding_digest),
            ("signed_grant", self.signed_grant_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.authority.grants_any()
            || self.receipt_digest != self.compute_receipt_digest()
        {
            return Err(FederationV3Error::InvalidAuthorityReceipt);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedPeerResultV3 {
    pub query_id: StableId,
    pub peer_id: StableId,
    pub principal_id: StableId,
    pub query_binding_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub authority_receipt: VerifiedFederationAuthorityReceiptV3,
    pub grant_id: String,
    pub peer_key_id: String,
    pub enrollment_epoch: u64,
    pub observed_frontier: u64,
    pub expires_unix_ms: u64,
    pub items: Vec<FederatedEvidenceItemV2>,
    pub completeness: FederatedCompletenessV2,
    pub validity: FederatedValidityV2,
    pub truncated_items: u32,
    pub remote_payload_digest: Digest32,
    pub result_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl FederatedPeerResultV3 {
    #[must_use]
    pub fn compute_result_digest(&self) -> Digest32 {
        let mut items = self.items.iter().collect::<Vec<_>>();
        items.sort_by(|left, right| {
            left.source_owner_id
                .cmp(&right.source_owner_id)
                .then_with(|| left.record_id.cmp(&right.record_id))
                .then_with(|| left.record_revision.cmp(&right.record_revision))
        });
        let mut bytes = Vec::new();
        bytes.extend_from_slice(PEER_RESULT_DOMAIN_V3);
        push_id(&mut bytes, &self.query_id);
        push_id(&mut bytes, &self.peer_id);
        push_id(&mut bytes, &self.principal_id);
        push_digest(&mut bytes, self.query_binding_digest);
        push_digest(&mut bytes, self.generation_vector_digest);
        push_digest(&mut bytes, self.authority_receipt.receipt_digest);
        push_text(&mut bytes, &self.grant_id);
        push_text(&mut bytes, &self.peer_key_id);
        push_u64(&mut bytes, self.enrollment_epoch);
        push_u64(&mut bytes, self.observed_frontier);
        push_u64(&mut bytes, self.expires_unix_ms);
        push_len(&mut bytes, items.len());
        for item in items {
            push_evidence_item(&mut bytes, item);
        }
        bytes.push(completeness_code(self.completeness));
        bytes.push(validity_code(self.validity));
        push_u64(&mut bytes, u64::from(self.truncated_items));
        push_digest(&mut bytes, self.remote_payload_digest);
        Digest32::of_bytes(&bytes)
    }

    pub fn validate(&self) -> Result<(), FederationV3Error> {
        ensure_digest("query_binding", self.query_binding_digest)?;
        ensure_digest("generation_vector", self.generation_vector_digest)?;
        ensure_digest("remote_payload", self.remote_payload_digest)?;
        self.authority_receipt.validate()?;
        if self.authority_receipt.principal_id != self.principal_id
            || self.authority_receipt.peer_id != self.peer_id
            || self.authority_receipt.query_binding_digest != self.query_binding_digest
            || self.authority_receipt.grant_id != self.grant_id
        {
            return Err(FederationV3Error::InvalidAuthorityReceipt);
        }
        if self.enrollment_epoch == 0 || self.observed_frontier == 0 || self.expires_unix_ms == 0 {
            return Err(FederationV3Error::InvalidPeerResult);
        }
        if !external_identifier(&self.grant_id) || !external_identifier(&self.peer_key_id) {
            return Err(FederationV3Error::InvalidPeerResult);
        }
        if self.items.len() > MAX_FEDERATED_RESULTS_V2 {
            return Err(FederationV3Error::ResultLimitExceeded);
        }
        if matches!(self.validity, FederatedValidityV2::StaleGeneration | FederatedValidityV2::Revoked)
            && !self.items.is_empty()
        {
            return Err(FederationV3Error::StaleEvidenceExposed);
        }
        if matches!(self.completeness, FederatedCompletenessV2::Empty) && !self.items.is_empty() {
            return Err(FederationV3Error::InvalidCompleteness);
        }
        if matches!(self.completeness, FederatedCompletenessV2::Complete) && self.items.is_empty() {
            return Err(FederationV3Error::InvalidCompleteness);
        }
        if matches!(self.completeness, FederatedCompletenessV2::Indeterminate) {
            return Err(FederationV3Error::InvalidCompleteness);
        }
        let mut identities = BTreeSet::new();
        for item in &self.items {
            validate_evidence_item(item)?;
            if !identities.insert((
                item.source_owner_id.clone(),
                item.record_id.clone(),
                item.record_revision,
            )) {
                return Err(FederationV3Error::DuplicateResultIdentity);
            }
        }
        if self.authority.grants_any() {
            return Err(FederationV3Error::AuthorityGranted);
        }
        if self.result_digest != self.compute_result_digest() {
            return Err(FederationV3Error::DigestMismatch("peer_result"));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederationPeerFailureV3 {
    Unavailable,
    TimedOut,
    Cancelled,
    Revoked,
    Expired,
    StaleEnrollment,
    InvalidResponse,
    Rejected,
    Internal,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedPeerCoverageV3 {
    pub peer_id: StableId,
    pub completeness: FederatedCompletenessV2,
    pub validity: FederatedValidityV2,
    pub returned_items: u32,
    pub truncated_items: u32,
    pub failure: Option<FederationPeerFailureV3>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedCoverageV3 {
    pub requested_peers: u32,
    pub completed_peers: u32,
    pub failed_peers: u32,
    pub truncated_items: u32,
    pub peers: Vec<FederatedPeerCoverageV3>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedAggregateResultV3 {
    pub query_id: StableId,
    pub principal_id: StableId,
    pub scope_digest: Digest32,
    pub purpose_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub expires_unix_ms: u64,
    pub items: Vec<FederatedEvidenceItemV2>,
    pub coverage: FederatedCoverageV3,
    pub completeness: FederatedCompletenessV2,
    pub validity: FederatedValidityV2,
    pub result_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl FederatedAggregateResultV3 {
    #[must_use]
    pub fn compute_result_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(AGGREGATE_RESULT_DOMAIN_V3);
        push_id(&mut bytes, &self.query_id);
        push_id(&mut bytes, &self.principal_id);
        push_digest(&mut bytes, self.scope_digest);
        push_digest(&mut bytes, self.purpose_digest);
        push_digest(&mut bytes, self.generation_vector_digest);
        push_u64(&mut bytes, self.expires_unix_ms);
        push_len(&mut bytes, self.items.len());
        for item in &self.items {
            push_evidence_item(&mut bytes, item);
        }
        push_u64(&mut bytes, u64::from(self.coverage.requested_peers));
        push_u64(&mut bytes, u64::from(self.coverage.completed_peers));
        push_u64(&mut bytes, u64::from(self.coverage.failed_peers));
        push_u64(&mut bytes, u64::from(self.coverage.truncated_items));
        for peer in &self.coverage.peers {
            push_id(&mut bytes, &peer.peer_id);
            bytes.push(completeness_code(peer.completeness));
            bytes.push(validity_code(peer.validity));
            push_u64(&mut bytes, u64::from(peer.returned_items));
            push_u64(&mut bytes, u64::from(peer.truncated_items));
            bytes.push(peer.failure.map(failure_code).unwrap_or(u8::MAX));
        }
        bytes.push(completeness_code(self.completeness));
        bytes.push(validity_code(self.validity));
        Digest32::of_bytes(&bytes)
    }

    pub fn validate(&self) -> Result<(), FederationV3Error> {
        for (name, digest) in [
            ("scope", self.scope_digest),
            ("purpose", self.purpose_digest),
            ("generation_vector", self.generation_vector_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.expires_unix_ms == 0
            || self.coverage.requested_peers == 0
            || usize::try_from(self.coverage.requested_peers).unwrap_or(usize::MAX)
                > MAX_FEDERATED_PEERS_V3
            || self.coverage.completed_peers.saturating_add(self.coverage.failed_peers)
                != self.coverage.requested_peers
            || self.coverage.peers.len()
                != usize::try_from(self.coverage.requested_peers).unwrap_or(usize::MAX)
            || self.items.len() > MAX_FEDERATED_RESULTS_V2
        {
            return Err(FederationV3Error::InvalidAggregateResult);
        }
        if self.coverage.completed_peers == 0
            && !matches!(self.completeness, FederatedCompletenessV2::Indeterminate)
        {
            return Err(FederationV3Error::InvalidCompleteness);
        }
        if self.coverage.failed_peers > 0
            && matches!(self.completeness, FederatedCompletenessV2::Complete | FederatedCompletenessV2::Empty)
        {
            return Err(FederationV3Error::InvalidCompleteness);
        }
        if matches!(self.completeness, FederatedCompletenessV2::Empty) && !self.items.is_empty() {
            return Err(FederationV3Error::InvalidCompleteness);
        }
        if matches!(self.validity, FederatedValidityV2::Revoked | FederatedValidityV2::StaleGeneration)
            && self.coverage.completed_peers == 0
            && !self.items.is_empty()
        {
            return Err(FederationV3Error::StaleEvidenceExposed);
        }
        let mut sorted = self.coverage.peers.clone();
        sorted.sort_by(|left, right| left.peer_id.cmp(&right.peer_id));
        if sorted != self.coverage.peers {
            return Err(FederationV3Error::InvalidAggregateResult);
        }
        let mut identities = BTreeSet::new();
        for item in &self.items {
            validate_evidence_item(item)?;
            if !identities.insert((
                item.source_owner_id.clone(),
                item.record_id.clone(),
                item.record_revision,
            )) {
                return Err(FederationV3Error::DuplicateResultIdentity);
            }
        }
        if self.authority.grants_any() {
            return Err(FederationV3Error::AuthorityGranted);
        }
        if self.result_digest != self.compute_result_digest() {
            return Err(FederationV3Error::DigestMismatch("aggregate_result"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct FederationCacheKeyV3 {
    pub peer_id: StableId,
    pub query_binding_digest: Digest32,
}

#[derive(Clone, Debug)]
struct FederationCacheEntryV3 {
    query: FederatedPeerQueryV3,
    original_grant: SignedFinalUseGrant,
    result: FederatedPeerResultV3,
}

#[derive(Default)]
struct FederationCacheStateV3 {
    entries: BTreeMap<FederationCacheKeyV3, FederationCacheEntryV3>,
    by_grant: BTreeMap<String, BTreeSet<FederationCacheKeyV3>>,
    by_key: BTreeMap<String, BTreeSet<FederationCacheKeyV3>>,
    by_peer: BTreeMap<StableId, BTreeSet<FederationCacheKeyV3>>,
}

pub struct FederationResultCacheV3 {
    maximum_entries: usize,
    state: Mutex<FederationCacheStateV3>,
}

impl fmt::Debug for FederationResultCacheV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("FederationResultCacheV3")
            .field("maximum_entries", &self.maximum_entries)
            .finish_non_exhaustive()
    }
}

impl FederationResultCacheV3 {
    pub fn new(maximum_entries: usize) -> Result<Self, FederationV3Error> {
        if maximum_entries == 0 || maximum_entries > MAX_FEDERATION_CACHE_ENTRIES_V3 {
            return Err(FederationV3Error::InvalidCacheCapacity);
        }
        Ok(Self {
            maximum_entries,
            state: Mutex::new(FederationCacheStateV3::default()),
        })
    }

    fn insert(
        &self,
        query: FederatedPeerQueryV3,
        original_grant: SignedFinalUseGrant,
        result: FederatedPeerResultV3,
        now_unix_ms: u64,
    ) -> Result<(), FederationV3Error> {
        result.validate()?;
        if now_unix_ms >= result.expires_unix_ms
            || !matches!(result.validity, FederatedValidityV2::Valid)
        {
            return Ok(());
        }
        let key = FederationCacheKeyV3 {
            peer_id: result.peer_id.clone(),
            query_binding_digest: result.query_binding_digest,
        };
        let entry = FederationCacheEntryV3 {
            query,
            original_grant,
            result,
        };
        let mut state = self.state.lock().map_err(|_| FederationV3Error::CacheUnavailable)?;
        remove_cache_entry(&mut state, &key);
        if state.entries.len() >= self.maximum_entries {
            let oldest_key = state
                .entries
                .iter()
                .min_by_key(|(_, value)| value.result.expires_unix_ms)
                .map(|(key, _)| key.clone())
                .ok_or(FederationV3Error::CacheUnavailable)?;
            remove_cache_entry(&mut state, &oldest_key);
        }
        state
            .by_grant
            .entry(entry.original_grant.grant.grant_id.clone())
            .or_default()
            .insert(key.clone());
        state
            .by_key
            .entry(entry.result.peer_key_id.clone())
            .or_default()
            .insert(key.clone());
        state
            .by_peer
            .entry(entry.result.peer_id.clone())
            .or_default()
            .insert(key.clone());
        state.entries.insert(key, entry);
        Ok(())
    }

    fn get_entry(
        &self,
        key: &FederationCacheKeyV3,
        now_unix_ms: u64,
    ) -> Result<Option<FederationCacheEntryV3>, FederationV3Error> {
        let mut state = self.state.lock().map_err(|_| FederationV3Error::CacheUnavailable)?;
        if state
            .entries
            .get(key)
            .is_some_and(|entry| now_unix_ms >= entry.result.expires_unix_ms)
        {
            remove_cache_entry(&mut state, key);
            return Ok(None);
        }
        Ok(state.entries.get(key).cloned())
    }

    pub fn purge_grant(&self, grant_id: &str) -> Result<usize, FederationV3Error> {
        let mut state = self.state.lock().map_err(|_| FederationV3Error::CacheUnavailable)?;
        let keys = state.by_grant.get(grant_id).cloned().unwrap_or_default();
        let count = keys.len();
        for key in keys {
            remove_cache_entry(&mut state, &key);
        }
        Ok(count)
    }

    pub fn purge_peer(&self, peer_id: &StableId) -> Result<usize, FederationV3Error> {
        let mut state = self.state.lock().map_err(|_| FederationV3Error::CacheUnavailable)?;
        let keys = state.by_peer.get(peer_id).cloned().unwrap_or_default();
        let count = keys.len();
        for key in keys {
            remove_cache_entry(&mut state, &key);
        }
        Ok(count)
    }

    pub fn purge_key(&self, key_id: &str) -> Result<usize, FederationV3Error> {
        let mut state = self.state.lock().map_err(|_| FederationV3Error::CacheUnavailable)?;
        let keys = state.by_key.get(key_id).cloned().unwrap_or_default();
        let count = keys.len();
        for key in keys {
            remove_cache_entry(&mut state, &key);
        }
        Ok(count)
    }

    pub fn purge_revocations(
        &self,
        head: &FinalUseRevocations,
    ) -> Result<usize, FederationV3Error> {
        let mut state = self.state.lock().map_err(|_| FederationV3Error::CacheUnavailable)?;
        let keys = state
            .entries
            .iter()
            .filter_map(|(key, entry)| {
                let grant = &entry.original_grant.grant;
                (grant.authority_epoch != head.authority_epoch
                    || head.revoked_grant_ids.contains(&grant.grant_id))
                .then(|| key.clone())
            })
            .collect::<Vec<_>>();
        let count = keys.len();
        for key in keys {
            remove_cache_entry(&mut state, &key);
        }
        Ok(count)
    }
}
