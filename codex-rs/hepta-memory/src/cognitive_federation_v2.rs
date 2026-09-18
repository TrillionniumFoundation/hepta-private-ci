use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_memory_federation::FederatedCompletenessV2;
use codex_hepta_memory_federation::FederatedEvidenceItemV2;
use codex_hepta_memory_federation::FederatedLeaseV2;
use codex_hepta_memory_federation::FederatedQueryV2;
use codex_hepta_memory_federation::FederatedValidityV2;
use codex_hepta_memory_federation::FederationAuthorityFutureV2;
use codex_hepta_memory_federation::FederationAuthorityObservationV2;
use codex_hepta_memory_federation::FederationAuthorityV2;
use codex_hepta_memory_federation::FederationTransportFutureV2;
use codex_hepta_memory_federation::FederationTransportResultV2;
use codex_hepta_memory_federation::FederationTransportV2;
use codex_hepta_memory_federation::FederationV2Error;
use codex_hepta_memory_federation::NeverCancelledV2;
use codex_hepta_memory_federation::RemoteFederatedResponseV2;
use codex_hepta_memory_federation::execute_once as execute_federation_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use sha2::Digest as _;
use sha2::Sha256;

use super::*;

const PRODUCT_FEDERATION_ATTEMPT_TIMEOUT: Duration = Duration::from_secs(2);
const PRODUCT_PURPOSE_DOMAIN: &[u8] = b"hepta.cognitive.federated-recall.product.v2";
const PRODUCT_SCOPE_DOMAIN: &[u8] = b"hepta.cognitive.federated-recall.scope.v2";
const PRODUCT_GENERATION_DOMAIN: &[u8] = b"hepta.cognitive.federated-recall.generation.v2";
const PRODUCT_QUERY_ID_DOMAIN: &[u8] = b"hepta.cognitive.federated-recall.query-id.v2";
const PRODUCT_NONCE_DOMAIN: &[u8] = b"hepta.cognitive.federated-recall.nonce.v2";
const PRODUCT_LEASE_ID_DOMAIN: &[u8] = b"hepta.cognitive.federated-recall.lease-id.v2";

#[derive(Default)]
struct ProductFederationState {
    batch: Option<crate::RetrievalBatch>,
    error: Option<CognitiveStoreError>,
}

struct ProductFederationAuthority<'a> {
    reader: &'a FederatedMemoryReader,
    access: &'a FederationConsumerAccess,
    logical_start_unix_ms: u64,
    started: Instant,
    state: Arc<Mutex<ProductFederationState>>,
}

impl ProductFederationAuthority<'_> {
    fn observed_at_unix_ms(&self) -> u64 {
        self.logical_start_unix_ms
            .saturating_add(u64::try_from(self.started.elapsed().as_millis()).unwrap_or(u64::MAX))
    }
}

impl FederationAuthorityV2 for ProductFederationAuthority<'_> {
    fn observe<'a>(
        &'a self,
        query: &'a FederatedQueryV2,
        lease: &'a FederatedLeaseV2,
    ) -> FederationAuthorityFutureV2<'a> {
        Box::pin(async move {
            match self
                .reader
                .product_authority_observation(
                    self.access,
                    query,
                    lease,
                    self.observed_at_unix_ms(),
                )
                .await
            {
                Ok(observation) => Ok(observation),
                Err(error) => {
                    remember_product_error(&self.state, error);
                    Err(FederationV2Error::AuthorityUnavailable)
                }
            }
        })
    }
}

struct ProductFederationTransport<'a> {
    reader: &'a FederatedMemoryReader,
    request: &'a RetrievalRequest,
    expected_query_binding_digest: Digest32,
    state: Arc<Mutex<ProductFederationState>>,
}

impl FederationTransportV2 for ProductFederationTransport<'_> {
    fn send_once<'a>(
        &'a self,
        query: &'a FederatedQueryV2,
    ) -> FederationTransportFutureV2<'a> {
        Box::pin(async move {
            if query.binding_digest() != self.expected_query_binding_digest {
                return Err(FederationV2Error::DigestMismatch(
                    "product_query_binding",
                ));
            }

            let frontier_before = match self.reader.product_memory_frontier().await {
                Ok(frontier) => frontier,
                Err(error) => {
                    remember_product_error(&self.state, error);
                    return Ok(FederationTransportResultV2::NonTerminal(
                        codex_hepta_memory_federation::FederationTransportOutcomeV2::Unavailable,
                    ));
                }
            };
            let batch = match self.reader.product_owner_retrieval(self.request).await {
                Ok(batch) => batch,
                Err(error) => {
                    remember_product_error(&self.state, error);
                    return Ok(FederationTransportResultV2::NonTerminal(
                        codex_hepta_memory_federation::FederationTransportOutcomeV2::Unavailable,
                    ));
                }
            };
            let frontier_after = match self.reader.product_memory_frontier().await {
                Ok(frontier) => frontier,
                Err(error) => {
                    remember_product_error(&self.state, error);
                    return Ok(FederationTransportResultV2::NonTerminal(
                        codex_hepta_memory_federation::FederationTransportOutcomeV2::Unavailable,
                    ));
                }
            };
            if frontier_before != frontier_after {
                return Ok(FederationTransportResultV2::NonTerminal(
                    codex_hepta_memory_federation::FederationTransportOutcomeV2::Unavailable,
                ));
            }

            let items = match batch
                .candidates
                .iter()
                .map(|candidate| self.reader.product_evidence_item(candidate))
                .collect::<Result<Vec<_>, _>>()
            {
                Ok(items) => items,
                Err(error) => {
                    remember_product_error(&self.state, error);
                    return Err(FederationV2Error::TransportRejected);
                }
            };
            let completeness = if items.is_empty() {
                FederatedCompletenessV2::Empty
            } else {
                FederatedCompletenessV2::Complete
            };
            let response = RemoteFederatedResponseV2 {
                peer_id: product_agent_id(self.reader.capability.owner_agent_id())
                    .map_err(|error| {
                        remember_product_error(&self.state, error);
                        FederationV2Error::TransportRejected
                    })?,
                scope_digest: product_scope_digest(&self.reader.capability),
                purpose_digest: Digest32::of_bytes(PRODUCT_PURPOSE_DOMAIN),
                generation_vector_digest: product_generation_digest(
                    &self.reader.capability,
                    FederationCapabilityState::Granted,
                ),
                response_digest: Digest32::ZERO,
                observed_frontier: frontier_after,
                expires_unix_ms: query.deadline_unix_ms,
                items,
                completeness,
                terminal_observed: true,
            }
            .seal(query.binding_digest())?;

            match self.state.lock() {
                Ok(mut state) => state.batch = Some(batch),
                Err(_) => return Err(FederationV2Error::TransportRejected),
            }
            Ok(FederationTransportResultV2::Terminal(response))
        })
    }
}

impl FederatedMemoryReader {
    pub(super) async fn retrieve_v2_product(
        &self,
        access: &FederationConsumerAccess,
        request: &RetrievalRequest,
    ) -> Result<FederatedRetrievalBatch, CognitiveStoreError> {
        if access.agent_id != self.capability.consumer_agent_id {
            return Err(CognitiveStoreError::AccessDenied(
                "memory federation consumer identity does not match capability".to_string(),
            ));
        }
        if access.workspace_sha256 != *self.capability.scope.consumer_workspace_sha256() {
            return Err(CognitiveStoreError::AccessDenied(
                "memory federation consumer workspace does not match capability".to_string(),
            ));
        }
        let (query, lease, logical_now_unix_ms) = self.product_query_and_lease(request)?;
        let state = Arc::new(Mutex::new(ProductFederationState::default()));
        let authority = ProductFederationAuthority {
            reader: self,
            access,
            logical_start_unix_ms: logical_now_unix_ms,
            started: Instant::now(),
            state: Arc::clone(&state),
        };
        let transport = ProductFederationTransport {
            reader: self,
            request,
            expected_query_binding_digest: query.binding_digest(),
            state: Arc::clone(&state),
        };

        let execution = execute_federation_v2(
            &transport,
            &authority,
            &NeverCancelledV2,
            logical_now_unix_ms,
            query,
            &lease,
        )
        .await;

        let mut product_state = state.lock().map_err(|_| {
            CognitiveStoreError::Corrupt(
                "memory federation product admission state was poisoned".to_string(),
            )
        })?;
        if let Some(error) = product_state.error.take() {
            return Err(error);
        }
        let result = execution.map_err(map_federation_v2_error)?;
        match result.validity {
            FederatedValidityV2::Valid => {}
            FederatedValidityV2::Revoked
            | FederatedValidityV2::StaleGeneration
            | FederatedValidityV2::Expired => {
                return Err(CognitiveStoreError::AccessDenied(format!(
                    "memory federation V2 result is not current ({:?})",
                    result.validity
                )));
            }
            FederatedValidityV2::Indeterminate => {
                return Err(CognitiveStoreError::Unavailable(
                    "memory federation V2 attempt was indeterminate".to_string(),
                ));
            }
        }

        let batch = product_state.batch.take().ok_or_else(|| {
            CognitiveStoreError::Corrupt(
                "memory federation V2 admitted a terminal response without owner payload"
                    .to_string(),
            )
        })?;
        let expected = batch
            .candidates
            .iter()
            .map(|candidate| self.product_evidence_item(candidate))
            .collect::<Result<Vec<_>, _>>()?;
        if expected.len() != result.items.len()
            || expected
                .iter()
                .any(|item| !result.items.iter().any(|admitted| admitted == item))
        {
            return Err(CognitiveStoreError::Corrupt(
                "memory federation V2 admitted evidence does not match owner payload".to_string(),
            ));
        }

        let candidates = batch
            .candidates
            .into_iter()
            .map(|candidate| FederatedRetrievalCandidate {
                source_agent_id: self.capability.owner_agent_id.clone(),
                revalidation: FederatedMemoryRevalidationBinding {
                    source_agent_id: self.capability.owner_agent_id.clone(),
                    capability: self.capability.clone(),
                    memory: candidate.revalidation.clone(),
                },
                candidate,
            })
            .collect();
        Ok(FederatedRetrievalBatch {
            query_sha256: batch.query_sha256,
            candidates,
            coverage: FederatedRetrievalCoverage {
                requested_sources: 1,
                completed_sources: 1,
                failed_sources: 0,
            },
            admission_expires_unix_ms: Some(result.expires_unix_ms),
        })
    }

    fn product_query_and_lease(
        &self,
        request: &RetrievalRequest,
    ) -> Result<(FederatedQueryV2, FederatedLeaseV2, u64), CognitiveStoreError> {
        let logical_now_unix_ms = nonnegative_seconds_to_ms(
            request.now_unix_seconds(),
            "federation request time",
        )?;
        let capability_expiry_unix_ms = nonnegative_seconds_to_ms(
            self.capability.expires_at_unix_seconds,
            "federation capability expiry",
        )?;
        if logical_now_unix_ms >= capability_expiry_unix_ms {
            return Err(CognitiveStoreError::AccessDenied(
                "memory federation capability is expired".to_string(),
            ));
        }
        let deadline_unix_ms = logical_now_unix_ms
            .checked_add(
                u64::try_from(PRODUCT_FEDERATION_ATTEMPT_TIMEOUT.as_millis())
                    .unwrap_or(u64::MAX),
            )
            .unwrap_or(u64::MAX)
            .min(capability_expiry_unix_ms);
        if deadline_unix_ms <= logical_now_unix_ms {
            return Err(CognitiveStoreError::Unavailable(
                "memory federation product deadline has no usable window".to_string(),
            ));
        }

        let query_digest = Digest32::of_bytes(request.query().as_bytes());
        let generation_vector_digest = product_generation_digest(
            &self.capability,
            FederationCapabilityState::Granted,
        );
        let scope_digest = product_scope_digest(&self.capability);
        let query_identity = product_query_identity_digest(
            &self.capability,
            query_digest,
            generation_vector_digest,
            logical_now_unix_ms,
        );
        let query = FederatedQueryV2 {
            query_id: StableId::new(format!("federation-query:v2:{query_identity}"))
                .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?,
            peer_id: product_agent_id(self.capability.owner_agent_id())?,
            principal_id: product_agent_id(self.capability.consumer_agent_id())?,
            scope_digest,
            purpose_digest: Digest32::of_bytes(PRODUCT_PURPOSE_DOMAIN),
            generation_vector_digest,
            query_digest,
            maximum_results: u32::try_from(crate::MAX_RETRIEVAL_RESULTS).map_err(|_| {
                CognitiveStoreError::Corrupt(
                    "memory federation result bound cannot fit u32".to_string(),
                )
            })?,
            deadline_unix_ms,
            lease_epoch: self.capability.generation,
            nonce_digest: product_nonce_digest(
                &self.capability,
                query_identity,
                logical_now_unix_ms,
            ),
        };
        let query_binding_digest = query.binding_digest();
        let lease_identity =
            product_lease_identity_digest(&self.capability, query_binding_digest);
        let lease = FederatedLeaseV2 {
            lease_id: StableId::new(format!("federation-lease:v2:{lease_identity}"))
                .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?,
            query_id: query.query_id.clone(),
            peer_id: query.peer_id.clone(),
            principal_id: query.principal_id.clone(),
            scope_digest: query.scope_digest,
            purpose_digest: query.purpose_digest,
            generation_vector_digest: query.generation_vector_digest,
            query_binding_digest,
            lease_epoch: query.lease_epoch,
            expires_unix_ms: capability_expiry_unix_ms,
            revoked: false,
        };
        Ok((query, lease, logical_now_unix_ms))
    }

    async fn product_authority_observation(
        &self,
        access: &FederationConsumerAccess,
        query: &FederatedQueryV2,
        lease: &FederatedLeaseV2,
        observed_at_unix_ms: u64,
    ) -> Result<FederationAuthorityObservationV2, CognitiveStoreError> {
        let status = self
            .owner
            .federation_capability_status(self.capability.id())
            .await?;
        let access_matches = access.agent_id == self.capability.consumer_agent_id
            && access.workspace_sha256 == *self.capability.scope.consumer_workspace_sha256();

        let (principal_id, generation_vector_digest, expires_unix_ms, peer_enrolled, revoked) =
            if let Some(status) = status {
                require_stable_binding(
                    &status.capability,
                    &self.capability.owner_agent_id,
                    &self.capability.consumer_agent_id,
                    &self.capability.scope,
                )?;
                (
                    product_agent_id(status.capability.consumer_agent_id())?,
                    product_generation_digest(&status.capability, status.state),
                    nonnegative_seconds_to_ms(
                        status.capability.expires_at_unix_seconds(),
                        "current federation capability expiry",
                    )?,
                    access_matches,
                    status.state == FederationCapabilityState::Revoked || !access_matches,
                )
            } else {
                (
                    query.principal_id.clone(),
                    query.generation_vector_digest,
                    lease.expires_unix_ms,
                    false,
                    true,
                )
            };

        Ok(FederationAuthorityObservationV2 {
            peer_id: product_agent_id(self.capability.owner_agent_id())?,
            principal_id,
            query_binding_digest: query.binding_digest(),
            generation_vector_digest,
            lease_epoch: query.lease_epoch,
            expires_unix_ms,
            observed_at_unix_ms,
            peer_enrolled,
            revoked,
        })
    }

    async fn product_owner_retrieval(
        &self,
        request: &RetrievalRequest,
    ) -> Result<crate::RetrievalBatch, CognitiveStoreError> {
        let owner_access = owner_access(&self.capability);
        let mut batch = self
            .owner
            .retrieve_memory_candidates(&owner_access, request)
            .await?;
        batch
            .candidates
            .retain(|candidate| candidate.memory.scope == *self.capability.scope.owner_scope());
        Ok(batch)
    }

    async fn product_memory_frontier(&self) -> Result<u64, CognitiveStoreError> {
        let (scope_kind, workspace) = self.capability.scope.owner_scope().database_parts();
        let count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM memory_revisions
             WHERE owner_agent_id = ? AND scope_kind = ? AND workspace_sha256 IS ?",
        )
        .bind(self.capability.owner_agent_id.as_str())
        .bind(scope_kind)
        .bind(workspace)
        .fetch_one(&self.owner.pool)
        .await
        .map_err(unavailable)?;
        u64::try_from(count).map_err(|_| {
            CognitiveStoreError::Corrupt(
                "memory federation owner frontier is negative".to_string(),
            )
        })
    }

    fn product_evidence_item(
        &self,
        candidate: &RetrievalCandidate,
    ) -> Result<FederatedEvidenceItemV2, CognitiveStoreError> {
        let support_bytes = serde_json::to_vec(&(
            &candidate.revalidation.citations,
            candidate.revalidation.kg_projection_generation,
        ))
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
        let validity_bytes = serde_json::to_vec(&candidate.revalidation)
            .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
        Ok(FederatedEvidenceItemV2 {
            source_owner_id: product_agent_id(self.capability.owner_agent_id())?,
            record_id: StableId::new(candidate.memory.id.memory_id.as_str().to_string())
                .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?,
            record_revision: Revision::new(candidate.memory.id.revision)
                .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?,
            record_digest: candidate
                .memory
                .content_sha256
                .as_str()
                .parse()
                .map_err(|error: codex_hepta_types::DigestParseError| {
                    CognitiveStoreError::Corrupt(error.to_string())
                })?,
            support_digest: Digest32::of_bytes(&support_bytes),
            validity_digest: Digest32::of_bytes(&validity_bytes),
        })
    }
}

fn product_agent_id(agent_id: &AgentId) -> Result<StableId, CognitiveStoreError> {
    StableId::new(format!("agent:{}", agent_id.as_str()))
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))
}

fn product_scope_digest(capability: &FederationCapability) -> Digest32 {
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, PRODUCT_SCOPE_DOMAIN);
    frame_part(&mut hasher, capability.owner_agent_id.as_str().as_bytes());
    frame_part(&mut hasher, capability.consumer_agent_id.as_str().as_bytes());
    let (scope_kind, owner_workspace) = capability.scope.owner_scope().database_parts();
    frame_part(&mut hasher, scope_kind.as_bytes());
    frame_part(
        &mut hasher,
        owner_workspace.unwrap_or_default().as_bytes(),
    );
    frame_part(
        &mut hasher,
        capability.scope.consumer_workspace_sha256().as_str().as_bytes(),
    );
    digest_from_sha256(hasher)
}

fn product_generation_digest(
    capability: &FederationCapability,
    state: FederationCapabilityState,
) -> Digest32 {
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, PRODUCT_GENERATION_DOMAIN);
    frame_part(&mut hasher, capability.id.as_str().as_bytes());
    frame_part(&mut hasher, &capability.generation.to_be_bytes());
    frame_part(&mut hasher, &capability.revision.to_be_bytes());
    frame_part(
        &mut hasher,
        &capability.effective_at_unix_seconds.to_be_bytes(),
    );
    frame_part(
        &mut hasher,
        &capability.expires_at_unix_seconds.to_be_bytes(),
    );
    frame_part(
        &mut hasher,
        match state {
            FederationCapabilityState::Granted => b"granted",
            FederationCapabilityState::Revoked => b"revoked",
        },
    );
    digest_from_sha256(hasher)
}

fn product_query_identity_digest(
    capability: &FederationCapability,
    query_digest: Digest32,
    generation_vector_digest: Digest32,
    logical_now_unix_ms: u64,
) -> Digest32 {
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, PRODUCT_QUERY_ID_DOMAIN);
    frame_part(&mut hasher, capability.id.as_str().as_bytes());
    frame_part(&mut hasher, query_digest.as_array());
    frame_part(&mut hasher, generation_vector_digest.as_array());
    frame_part(&mut hasher, &logical_now_unix_ms.to_be_bytes());
    digest_from_sha256(hasher)
}

fn product_nonce_digest(
    capability: &FederationCapability,
    query_identity: Digest32,
    logical_now_unix_ms: u64,
) -> Digest32 {
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, PRODUCT_NONCE_DOMAIN);
    frame_part(&mut hasher, capability.id.as_str().as_bytes());
    frame_part(&mut hasher, query_identity.as_array());
    frame_part(&mut hasher, &logical_now_unix_ms.to_be_bytes());
    digest_from_sha256(hasher)
}

fn product_lease_identity_digest(
    capability: &FederationCapability,
    query_binding_digest: Digest32,
) -> Digest32 {
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, PRODUCT_LEASE_ID_DOMAIN);
    frame_part(&mut hasher, capability.id.as_str().as_bytes());
    frame_part(&mut hasher, query_binding_digest.as_array());
    digest_from_sha256(hasher)
}

fn digest_from_sha256(hasher: Sha256) -> Digest32 {
    let output = hasher.finalize();
    let mut bytes = [0_u8; 32];
    bytes.copy_from_slice(&output);
    Digest32::from_array(bytes)
}

fn nonnegative_seconds_to_ms(
    seconds: i64,
    label: &str,
) -> Result<u64, CognitiveStoreError> {
    let seconds = u64::try_from(seconds)
        .map_err(|_| CognitiveStoreError::Invalid(format!("{label} must be non-negative")))?;
    seconds
        .checked_mul(1_000)
        .ok_or_else(|| CognitiveStoreError::Invalid(format!("{label} overflows milliseconds")))
}

fn remember_product_error(
    state: &Arc<Mutex<ProductFederationState>>,
    error: CognitiveStoreError,
) {
    if let Ok(mut state) = state.lock() {
        if state.error.is_none() {
            state.error = Some(error);
        }
    }
}

fn map_federation_v2_error(error: FederationV2Error) -> CognitiveStoreError {
    match error {
        FederationV2Error::LeaseExpired
        | FederationV2Error::LeaseRevoked
        | FederationV2Error::LeaseEpochMismatch
        | FederationV2Error::PeerNotEnrolled
        | FederationV2Error::AuthorityRevoked
        | FederationV2Error::AuthorityExpired => CognitiveStoreError::AccessDenied(format!(
            "memory federation V2 authority rejected the read ({error})"
        )),
        FederationV2Error::IdentityMismatch(_)
        | FederationV2Error::DigestMismatch(_)
        | FederationV2Error::DuplicateResultIdentity
        | FederationV2Error::InvalidCompleteness
        | FederationV2Error::InvalidCoverage
        | FederationV2Error::StaleEvidenceExposed
        | FederationV2Error::AuthorityGranted => CognitiveStoreError::Corrupt(format!(
            "memory federation V2 integrity check failed ({error})"
        )),
        _ => CognitiveStoreError::Unavailable(format!(
            "memory federation V2 read is unavailable ({error})"
        )),
    }
}
