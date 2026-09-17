#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct FederationWireRequestV3 {
    schema_version: u32,
    query_id: String,
    peer_id: String,
    principal_id: String,
    scope_sha256: [u8; 32],
    purpose_sha256: [u8; 32],
    generation_vector_sha256: [u8; 32],
    query_sha256: [u8; 32],
    query_binding_sha256: [u8; 32],
    request_nonce_sha256: [u8; 32],
    maximum_results: u32,
    deadline_unix_ms: u64,
    authority_epoch: u64,
    signed_grant: SignedFinalUseGrant,
}

impl FederationWireRequestV3 {
    fn from_attempt(attempt: &FederatedAttemptV3) -> Self {
        Self {
            schema_version: 3,
            query_id: attempt.query.query_id.as_str().to_owned(),
            peer_id: attempt.query.peer_id.as_str().to_owned(),
            principal_id: attempt.query.principal_id.as_str().to_owned(),
            scope_sha256: attempt.query.scope_digest.into_array(),
            purpose_sha256: attempt.query.purpose_digest.into_array(),
            generation_vector_sha256: attempt.query.generation_vector_digest.into_array(),
            query_sha256: attempt.query.query_digest.into_array(),
            query_binding_sha256: attempt.query.binding_digest().into_array(),
            request_nonce_sha256: attempt.query.request_nonce_digest.into_array(),
            maximum_results: attempt.query.maximum_results,
            deadline_unix_ms: attempt.query.deadline_unix_ms,
            authority_epoch: attempt.query.authority_epoch,
            signed_grant: attempt.grant.clone(),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RemoteFederatedEnvelopeWireV3 {
    schema_version: u32,
    query_id: String,
    peer_id: String,
    principal_id: String,
    scope_sha256: [u8; 32],
    purpose_sha256: [u8; 32],
    generation_vector_sha256: [u8; 32],
    query_binding_sha256: [u8; 32],
    request_nonce_sha256: [u8; 32],
    authority_epoch: u64,
    grant_id: String,
    response_nonce_sha256: [u8; 32],
    key_id: String,
    observed_frontier: u64,
    expires_unix_ms: u64,
    items: Vec<FederatedEvidenceItemWireV3>,
    completeness: u8,
    terminal_observed: bool,
    payload_sha256: [u8; 32],
    signature: Vec<u8>,
}

impl RemoteFederatedEnvelopeWireV3 {
    #[cfg(test)]
    fn from_domain(value: &RemoteFederatedEnvelopeV3) -> Self {
        Self {
            schema_version: 3,
            query_id: value.query_id.as_str().to_owned(),
            peer_id: value.peer_id.as_str().to_owned(),
            principal_id: value.principal_id.as_str().to_owned(),
            scope_sha256: value.scope_digest.into_array(),
            purpose_sha256: value.purpose_digest.into_array(),
            generation_vector_sha256: value.generation_vector_digest.into_array(),
            query_binding_sha256: value.query_binding_digest.into_array(),
            request_nonce_sha256: value.request_nonce_digest.into_array(),
            authority_epoch: value.authority_epoch,
            grant_id: value.grant_id.clone(),
            response_nonce_sha256: value.response_nonce_digest.into_array(),
            key_id: value.key_id.clone(),
            observed_frontier: value.observed_frontier,
            expires_unix_ms: value.expires_unix_ms,
            items: value
                .items
                .iter()
                .map(FederatedEvidenceItemWireV3::from_domain)
                .collect(),
            completeness: completeness_code(value.completeness),
            terminal_observed: value.terminal_observed,
            payload_sha256: value.payload_digest.into_array(),
            signature: value.signature.clone(),
        }
    }

    fn try_into_domain(self) -> Result<RemoteFederatedEnvelopeV3, FederationV3Error> {
        if self.schema_version != 3 {
            return Err(FederationV3Error::InvalidRemoteEnvelope);
        }
        Ok(RemoteFederatedEnvelopeV3 {
            query_id: parse_id(self.query_id)?,
            peer_id: parse_id(self.peer_id)?,
            principal_id: parse_id(self.principal_id)?,
            scope_digest: Digest32::from_array(self.scope_sha256),
            purpose_digest: Digest32::from_array(self.purpose_sha256),
            generation_vector_digest: Digest32::from_array(self.generation_vector_sha256),
            query_binding_digest: Digest32::from_array(self.query_binding_sha256),
            request_nonce_digest: Digest32::from_array(self.request_nonce_sha256),
            authority_epoch: self.authority_epoch,
            grant_id: self.grant_id,
            response_nonce_digest: Digest32::from_array(self.response_nonce_sha256),
            key_id: self.key_id,
            observed_frontier: self.observed_frontier,
            expires_unix_ms: self.expires_unix_ms,
            items: self
                .items
                .into_iter()
                .map(FederatedEvidenceItemWireV3::try_into_domain)
                .collect::<Result<Vec<_>, _>>()?,
            completeness: completeness_from_code(self.completeness)?,
            terminal_observed: self.terminal_observed,
            payload_digest: Digest32::from_array(self.payload_sha256),
            signature: self.signature,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct FederatedEvidenceItemWireV3 {
    source_owner_id: String,
    record_id: String,
    record_revision: u64,
    record_sha256: [u8; 32],
    support_sha256: [u8; 32],
    validity_sha256: [u8; 32],
}

impl FederatedEvidenceItemWireV3 {
    #[cfg(test)]
    fn from_domain(value: &FederatedEvidenceItemV2) -> Self {
        Self {
            source_owner_id: value.source_owner_id.as_str().to_owned(),
            record_id: value.record_id.as_str().to_owned(),
            record_revision: value.record_revision.get(),
            record_sha256: value.record_digest.into_array(),
            support_sha256: value.support_digest.into_array(),
            validity_sha256: value.validity_digest.into_array(),
        }
    }

    fn try_into_domain(self) -> Result<FederatedEvidenceItemV2, FederationV3Error> {
        Ok(FederatedEvidenceItemV2 {
            source_owner_id: parse_id(self.source_owner_id)?,
            record_id: parse_id(self.record_id)?,
            record_revision: Revision::new(self.record_revision)
                .map_err(|_| FederationV3Error::InvalidRemoteEnvelope)?,
            record_digest: Digest32::from_array(self.record_sha256),
            support_digest: Digest32::from_array(self.support_sha256),
            validity_digest: Digest32::from_array(self.validity_sha256),
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FederationV3Error {
    ZeroValue(&'static str),
    EmptyDigest(&'static str),
    InvalidMaximumResults,
    DeadlineExpired,
    DeadlineTooFar,
    ClockUnavailable,
    InvalidPeerCount,
    InvalidConcurrency,
    DuplicatePeer,
    DuplicateRequestNonce,
    InvalidPeerRegistry,
    InvalidPeerEnrollment,
    PeerNotEnrolled,
    PeerEnrollmentExpired,
    PeerEnrollmentChanged,
    PeerRevoked,
    PeerKeyMismatch,
    Authority(FinalUseError),
    AuthorityBindingMismatch,
    AuthorityEpochMismatch,
    AuthorityGrantMismatch,
    AuthorityExpired,
    MissingTerminalObservation,
    ResponseExpired,
    ResponseTooLarge,
    ResultLimitExceeded,
    DuplicateResultIdentity,
    ConflictingEvidenceIdentity,
    InvalidCompleteness,
    InvalidPeerSignature,
    InvalidRemoteEnvelope,
    InvalidPeerResult,
    InvalidAuthorityReceipt,
    InvalidAggregateResult,
    QueryAlreadyActive,
    QueryRegistryUnavailable,
    IdentityMismatch(&'static str),
    DigestMismatch(&'static str),
    StaleEvidenceExposed,
    StaleGeneration,
    AuthorityGranted,
    TransportRejected,
    Unavailable,
    TimedOut,
    Cancelled,
    InvalidCacheCapacity,
    CacheUnavailable,
    CacheMiss,
}

impl fmt::Display for FederationV3Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for FederationV3Error {}

fn validate_evidence_item(item: &FederatedEvidenceItemV2) -> Result<(), FederationV3Error> {
    ensure_digest("record", item.record_digest)?;
    ensure_digest("support", item.support_digest)?;
    ensure_digest("validity", item.validity_digest)
}

fn ensure_digest(name: &'static str, digest: Digest32) -> Result<(), FederationV3Error> {
    if digest.is_zero() {
        return Err(FederationV3Error::EmptyDigest(name));
    }
    Ok(())
}

fn parse_id(value: String) -> Result<StableId, FederationV3Error> {
    StableId::new(value).map_err(|_| FederationV3Error::InvalidRemoteEnvelope)
}

fn external_identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
}

fn system_now_unix_ms() -> Result<u64, FederationV3Error> {
    SystemFederationClockV3.now_unix_ms()
}

fn transport_error(error: codex_http_client::HttpError) -> FederationV3Error {
    if error.is_timeout() {
        FederationV3Error::TimedOut
    } else {
        FederationV3Error::Unavailable
    }
}

fn push_evidence_item(bytes: &mut Vec<u8>, item: &FederatedEvidenceItemV2) {
    push_id(bytes, &item.source_owner_id);
    push_id(bytes, &item.record_id);
    push_u64(bytes, item.record_revision.get());
    push_digest(bytes, item.record_digest);
    push_digest(bytes, item.support_digest);
    push_digest(bytes, item.validity_digest);
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_text(bytes, value.as_str());
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    push_len(bytes, value.len());
    bytes.extend_from_slice(value.as_bytes());
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    push_u64(bytes, u64::try_from(value).unwrap_or(u64::MAX));
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

const fn completeness_code(value: FederatedCompletenessV2) -> u8 {
    match value {
        FederatedCompletenessV2::Complete => 0,
        FederatedCompletenessV2::Partial => 1,
        FederatedCompletenessV2::Empty => 2,
        FederatedCompletenessV2::Indeterminate => 3,
    }
}

fn completeness_from_code(value: u8) -> Result<FederatedCompletenessV2, FederationV3Error> {
    match value {
        0 => Ok(FederatedCompletenessV2::Complete),
        1 => Ok(FederatedCompletenessV2::Partial),
        2 => Ok(FederatedCompletenessV2::Empty),
        3 => Ok(FederatedCompletenessV2::Indeterminate),
        _ => Err(FederationV3Error::InvalidRemoteEnvelope),
    }
}

const fn validity_code(value: FederatedValidityV2) -> u8 {
    match value {
        FederatedValidityV2::Valid => 0,
        FederatedValidityV2::StaleGeneration => 1,
        FederatedValidityV2::Revoked => 2,
        FederatedValidityV2::Indeterminate => 3,
    }
}
