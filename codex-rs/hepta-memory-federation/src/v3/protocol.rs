pub trait FederationClockV3: Send + Sync {
    fn now_unix_ms(&self) -> Result<u64, FederationV3Error>;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct SystemFederationClockV3;

impl FederationClockV3 for SystemFederationClockV3 {
    fn now_unix_ms(&self) -> Result<u64, FederationV3Error> {
        let millis = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| FederationV3Error::ClockUnavailable)?
            .as_millis();
        u64::try_from(millis).map_err(|_| FederationV3Error::ClockUnavailable)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedReadSpecV3 {
    pub query_id: StableId,
    pub principal_id: StableId,
    pub scope_digest: Digest32,
    pub purpose_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub query_digest: Digest32,
    pub maximum_results: u32,
    pub deadline_unix_ms: u64,
}

impl FederatedReadSpecV3 {
    pub fn validate(&self, now_unix_ms: u64) -> Result<(), FederationV3Error> {
        for (name, digest) in [
            ("scope", self.scope_digest),
            ("purpose", self.purpose_digest),
            ("generation_vector", self.generation_vector_digest),
            ("query", self.query_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if now_unix_ms >= self.deadline_unix_ms {
            return Err(FederationV3Error::DeadlineExpired);
        }
        if self.deadline_unix_ms - now_unix_ms > MAX_FEDERATION_QUERY_LIFETIME_MS_V3 {
            return Err(FederationV3Error::DeadlineTooFar);
        }
        let maximum_results = usize::try_from(self.maximum_results).unwrap_or(usize::MAX);
        if maximum_results == 0 || maximum_results > MAX_FEDERATED_RESULTS_V2 {
            return Err(FederationV3Error::InvalidMaximumResults);
        }
        Ok(())
    }

    pub fn peer_query(&self, target: &FederatedPeerTargetV3) -> FederatedPeerQueryV3 {
        FederatedPeerQueryV3 {
            query_id: self.query_id.clone(),
            peer_id: target.peer_id.clone(),
            principal_id: self.principal_id.clone(),
            scope_digest: self.scope_digest,
            purpose_digest: self.purpose_digest,
            generation_vector_digest: self.generation_vector_digest,
            query_digest: self.query_digest,
            maximum_results: self.maximum_results,
            deadline_unix_ms: self.deadline_unix_ms,
            authority_epoch: target.authority_epoch,
            request_nonce_digest: target.request_nonce_digest,
        }
    }

    pub fn authority_binding(
        &self,
        target: &FederatedPeerTargetV3,
    ) -> Result<FinalUseBinding, FederationV3Error> {
        target.validate()?;
        Ok(self.peer_query(target).authority_binding())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedPeerTargetV3 {
    pub peer_id: StableId,
    pub authority_epoch: u64,
    pub request_nonce_digest: Digest32,
}

impl FederatedPeerTargetV3 {
    fn validate(&self) -> Result<(), FederationV3Error> {
        if self.authority_epoch == 0 {
            return Err(FederationV3Error::ZeroValue("authority_epoch"));
        }
        ensure_digest("request_nonce", self.request_nonce_digest)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedPeerPermitV3 {
    pub target: FederatedPeerTargetV3,
    pub signed_grant: SignedFinalUseGrant,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedReadPlanV3 {
    pub spec: FederatedReadSpecV3,
    pub peers: Vec<FederatedPeerPermitV3>,
    pub maximum_concurrency: u8,
}

impl FederatedReadPlanV3 {
    pub fn validate(&self, now_unix_ms: u64) -> Result<(), FederationV3Error> {
        self.spec.validate(now_unix_ms)?;
        if self.peers.is_empty() || self.peers.len() > MAX_FEDERATED_PEERS_V3 {
            return Err(FederationV3Error::InvalidPeerCount);
        }
        let concurrency = usize::from(self.maximum_concurrency);
        if concurrency == 0 || concurrency > MAX_FEDERATED_PEERS_V3 || concurrency > self.peers.len() {
            return Err(FederationV3Error::InvalidConcurrency);
        }
        let mut peer_ids = BTreeSet::new();
        let mut nonces = BTreeSet::new();
        for permit in &self.peers {
            permit.target.validate()?;
            if !peer_ids.insert(permit.target.peer_id.clone()) {
                return Err(FederationV3Error::DuplicatePeer);
            }
            if !nonces.insert(permit.target.request_nonce_digest) {
                return Err(FederationV3Error::DuplicateRequestNonce);
            }
            let binding = self.spec.authority_binding(&permit.target)?;
            let grant = &permit.signed_grant.grant;
            if grant.authority_epoch != permit.target.authority_epoch {
                return Err(FederationV3Error::AuthorityEpochMismatch);
            }
            if grant.binding != binding {
                return Err(FederationV3Error::AuthorityBindingMismatch);
            }
            if grant.expires_at_unix_ms <= now_unix_ms {
                return Err(FederationV3Error::AuthorityExpired);
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedPeerQueryV3 {
    pub query_id: StableId,
    pub peer_id: StableId,
    pub principal_id: StableId,
    pub scope_digest: Digest32,
    pub purpose_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub query_digest: Digest32,
    pub maximum_results: u32,
    pub deadline_unix_ms: u64,
    pub authority_epoch: u64,
    pub request_nonce_digest: Digest32,
}

impl FederatedPeerQueryV3 {
    pub fn validate(&self, now_unix_ms: u64) -> Result<(), FederationV3Error> {
        FederatedReadSpecV3 {
            query_id: self.query_id.clone(),
            principal_id: self.principal_id.clone(),
            scope_digest: self.scope_digest,
            purpose_digest: self.purpose_digest,
            generation_vector_digest: self.generation_vector_digest,
            query_digest: self.query_digest,
            maximum_results: self.maximum_results,
            deadline_unix_ms: self.deadline_unix_ms,
        }
        .validate(now_unix_ms)?;
        if self.authority_epoch == 0 {
            return Err(FederationV3Error::ZeroValue("authority_epoch"));
        }
        ensure_digest("request_nonce", self.request_nonce_digest)
    }

    #[must_use]
    pub fn binding_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(QUERY_DOMAIN_V3);
        push_id(&mut bytes, &self.query_id);
        push_id(&mut bytes, &self.peer_id);
        push_id(&mut bytes, &self.principal_id);
        push_digest(&mut bytes, self.scope_digest);
        push_digest(&mut bytes, self.purpose_digest);
        push_digest(&mut bytes, self.generation_vector_digest);
        push_digest(&mut bytes, self.query_digest);
        push_u64(&mut bytes, u64::from(self.maximum_results));
        push_u64(&mut bytes, self.deadline_unix_ms);
        push_u64(&mut bytes, self.authority_epoch);
        push_digest(&mut bytes, self.request_nonce_digest);
        Digest32::of_bytes(&bytes)
    }

    #[must_use]
    pub fn authority_binding(&self) -> FinalUseBinding {
        FinalUseBinding {
            subject_id: self.principal_id.as_str().to_owned(),
            destination_id: self.peer_id.as_str().to_owned(),
            request_sha256: self.binding_digest().into_array(),
            scope_sha256: self.scope_digest.into_array(),
            payload_sha256: self.query_digest.into_array(),
        }
    }
}

#[derive(Clone, Eq, PartialEq)]
pub struct FederatedPeerEnrollmentV3 {
    pub peer_id: StableId,
    pub endpoint: String,
    pub ca_pem: Vec<u8>,
    pub key_id: String,
    pub verifying_key: [u8; 32],
    pub enrollment_epoch: u64,
    pub expires_unix_ms: u64,
    pub revoked: bool,
}

impl fmt::Debug for FederatedPeerEnrollmentV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("FederatedPeerEnrollmentV3")
            .field("peer_id", &self.peer_id)
            .field("endpoint", &self.endpoint)
            .field("ca_sha256", &Digest32::of_bytes(&self.ca_pem))
            .field("key_id", &self.key_id)
            .field("enrollment_epoch", &self.enrollment_epoch)
            .field("expires_unix_ms", &self.expires_unix_ms)
            .field("revoked", &self.revoked)
            .finish_non_exhaustive()
    }
}

impl FederatedPeerEnrollmentV3 {
    fn validate(&self, now_unix_ms: u64) -> Result<(), FederationV3Error> {
        if self.revoked {
            return Err(FederationV3Error::PeerRevoked);
        }
        if self.enrollment_epoch == 0 {
            return Err(FederationV3Error::ZeroValue("enrollment_epoch"));
        }
        if now_unix_ms >= self.expires_unix_ms {
            return Err(FederationV3Error::PeerEnrollmentExpired);
        }
        if self.endpoint.len() > 2048 || self.ca_pem.is_empty() || self.ca_pem.len() > 128 * 1024 {
            return Err(FederationV3Error::InvalidPeerEnrollment);
        }
        if !external_identifier(&self.key_id) {
            return Err(FederationV3Error::InvalidPeerEnrollment);
        }
        let endpoint = Url::parse(&self.endpoint)
            .map_err(|_| FederationV3Error::InvalidPeerEnrollment)?;
        if endpoint.scheme() != "https"
            || endpoint.host_str().is_none()
            || !endpoint.username().is_empty()
            || endpoint.password().is_some()
            || endpoint.query().is_some()
            || endpoint.fragment().is_some()
            || endpoint.path() != "/"
        {
            return Err(FederationV3Error::InvalidPeerEnrollment);
        }
        let key = VerifyingKey::from_bytes(&self.verifying_key)
            .map_err(|_| FederationV3Error::InvalidPeerEnrollment)?;
        if key.is_weak() {
            return Err(FederationV3Error::InvalidPeerEnrollment);
        }
        Ok(())
    }
}

#[derive(Clone)]
pub struct FederationPeerRegistryV3 {
    peers: Arc<BTreeMap<StableId, FederatedPeerEnrollmentV3>>,
}

impl fmt::Debug for FederationPeerRegistryV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("FederationPeerRegistryV3")
            .field("peer_count", &self.peers.len())
            .finish()
    }
}

impl FederationPeerRegistryV3 {
    pub fn new(
        peers: Vec<FederatedPeerEnrollmentV3>,
        now_unix_ms: u64,
    ) -> Result<Self, FederationV3Error> {
        if peers.is_empty() || peers.len() > 1024 {
            return Err(FederationV3Error::InvalidPeerRegistry);
        }
        let mut entries = BTreeMap::new();
        for peer in peers {
            peer.validate(now_unix_ms)?;
            if entries.insert(peer.peer_id.clone(), peer).is_some() {
                return Err(FederationV3Error::DuplicatePeer);
            }
        }
        Ok(Self {
            peers: Arc::new(entries),
        })
    }

    pub fn resolve(
        &self,
        peer_id: &StableId,
        now_unix_ms: u64,
    ) -> Result<FederatedPeerEnrollmentV3, FederationV3Error> {
        let peer = self
            .peers
            .get(peer_id)
            .cloned()
            .ok_or(FederationV3Error::PeerNotEnrolled)?;
        peer.validate(now_unix_ms)?;
        Ok(peer)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RemoteFederatedEnvelopeV3 {
    pub query_id: StableId,
    pub peer_id: StableId,
    pub principal_id: StableId,
    pub scope_digest: Digest32,
    pub purpose_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub query_binding_digest: Digest32,
    pub request_nonce_digest: Digest32,
    pub authority_epoch: u64,
    pub grant_id: String,
    pub response_nonce_digest: Digest32,
    pub key_id: String,
    pub observed_frontier: u64,
    pub expires_unix_ms: u64,
    pub items: Vec<FederatedEvidenceItemV2>,
    pub completeness: FederatedCompletenessV2,
    pub terminal_observed: bool,
    pub payload_digest: Digest32,
    pub signature: Vec<u8>,
}

impl RemoteFederatedEnvelopeV3 {
    #[must_use]
    pub fn compute_payload_digest(&self) -> Digest32 {
        let mut items = self.items.iter().collect::<Vec<_>>();
        items.sort_by(|left, right| {
            left.source_owner_id
                .cmp(&right.source_owner_id)
                .then_with(|| left.record_id.cmp(&right.record_id))
                .then_with(|| left.record_revision.cmp(&right.record_revision))
        });
        let mut bytes = Vec::new();
        bytes.extend_from_slice(RESPONSE_PAYLOAD_DOMAIN_V3);
        push_id(&mut bytes, &self.query_id);
        push_id(&mut bytes, &self.peer_id);
        push_id(&mut bytes, &self.principal_id);
        push_digest(&mut bytes, self.scope_digest);
        push_digest(&mut bytes, self.purpose_digest);
        push_digest(&mut bytes, self.generation_vector_digest);
        push_digest(&mut bytes, self.query_binding_digest);
        push_digest(&mut bytes, self.request_nonce_digest);
        push_u64(&mut bytes, self.authority_epoch);
        push_text(&mut bytes, &self.grant_id);
        push_digest(&mut bytes, self.response_nonce_digest);
        push_text(&mut bytes, &self.key_id);
        push_u64(&mut bytes, self.observed_frontier);
        push_u64(&mut bytes, self.expires_unix_ms);
        push_len(&mut bytes, items.len());
        for item in items {
            push_evidence_item(&mut bytes, item);
        }
        bytes.push(completeness_code(self.completeness));
        bytes.push(u8::from(self.terminal_observed));
        Digest32::of_bytes(&bytes)
    }

    #[must_use]
    pub fn signature_message(&self) -> Vec<u8> {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(RESPONSE_SIGNATURE_DOMAIN_V3);
        push_digest(&mut bytes, self.compute_payload_digest());
        bytes
    }

    fn validate_and_verify(
        &self,
        query: &FederatedPeerQueryV3,
        grant: &SignedFinalUseGrant,
        enrollment: &FederatedPeerEnrollmentV3,
        now_unix_ms: u64,
    ) -> Result<(), FederationV3Error> {
        if !self.terminal_observed {
            return Err(FederationV3Error::MissingTerminalObservation);
        }
        if self.observed_frontier == 0 {
            return Err(FederationV3Error::ZeroValue("observed_frontier"));
        }
        if now_unix_ms >= self.expires_unix_ms {
            return Err(FederationV3Error::ResponseExpired);
        }
        if self.items.len() > MAX_FEDERATED_RESULTS_V2 {
            return Err(FederationV3Error::ResultLimitExceeded);
        }
        if !external_identifier(&self.grant_id) || !external_identifier(&self.key_id) {
            return Err(FederationV3Error::InvalidRemoteEnvelope);
        }
        for (name, digest) in [
            ("response_scope", self.scope_digest),
            ("response_purpose", self.purpose_digest),
            ("response_generation", self.generation_vector_digest),
            ("query_binding", self.query_binding_digest),
            ("request_nonce", self.request_nonce_digest),
            ("response_nonce", self.response_nonce_digest),
            ("payload", self.payload_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.query_id != query.query_id {
            return Err(FederationV3Error::IdentityMismatch("response_query"));
        }
        if self.peer_id != query.peer_id || self.peer_id != enrollment.peer_id {
            return Err(FederationV3Error::IdentityMismatch("response_peer"));
        }
        if self.principal_id != query.principal_id {
            return Err(FederationV3Error::IdentityMismatch("response_principal"));
        }
        if self.scope_digest != query.scope_digest {
            return Err(FederationV3Error::DigestMismatch("response_scope"));
        }
        if self.purpose_digest != query.purpose_digest {
            return Err(FederationV3Error::DigestMismatch("response_purpose"));
        }
        if self.query_binding_digest != query.binding_digest() {
            return Err(FederationV3Error::DigestMismatch("query_binding"));
        }
        if self.request_nonce_digest != query.request_nonce_digest {
            return Err(FederationV3Error::DigestMismatch("request_nonce"));
        }
        if self.authority_epoch != query.authority_epoch
            || self.authority_epoch != grant.grant.authority_epoch
        {
            return Err(FederationV3Error::AuthorityEpochMismatch);
        }
        if self.grant_id != grant.grant.grant_id {
            return Err(FederationV3Error::AuthorityGrantMismatch);
        }
        if self.key_id != enrollment.key_id {
            return Err(FederationV3Error::PeerKeyMismatch);
        }
        match self.completeness {
            FederatedCompletenessV2::Empty if !self.items.is_empty() => {
                return Err(FederationV3Error::InvalidCompleteness);
            }
            FederatedCompletenessV2::Complete if self.items.is_empty() => {
                return Err(FederationV3Error::InvalidCompleteness);
            }
            FederatedCompletenessV2::Indeterminate => {
                return Err(FederationV3Error::InvalidCompleteness);
            }
            _ => {}
        }
        let mut identities = BTreeSet::new();
        for item in &self.items {
            validate_evidence_item(item)?;
            let identity = (
                item.source_owner_id.clone(),
                item.record_id.clone(),
                item.record_revision,
            );
            if !identities.insert(identity) {
                return Err(FederationV3Error::DuplicateResultIdentity);
            }
        }
        let expected = self.compute_payload_digest();
        if self.payload_digest != expected {
            return Err(FederationV3Error::DigestMismatch("remote_payload"));
        }
        let key = VerifyingKey::from_bytes(&enrollment.verifying_key)
            .map_err(|_| FederationV3Error::InvalidPeerEnrollment)?;
        let signature = Signature::from_slice(&self.signature)
            .map_err(|_| FederationV3Error::InvalidPeerSignature)?;
        key.verify_strict(&self.signature_message(), &signature)
            .map_err(|_| FederationV3Error::InvalidPeerSignature)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedAttemptV3 {
    pub query: FederatedPeerQueryV3,
    pub grant: SignedFinalUseGrant,
    pub enrollment: FederatedPeerEnrollmentV3,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederationTransportOutcomeV3 {
    Unavailable,
    TimedOut,
    Cancelled,
    NoTerminalObservation,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FederationTransportResultV3 {
    Terminal(RemoteFederatedEnvelopeV3),
    NonTerminal(FederationTransportOutcomeV3),
}
