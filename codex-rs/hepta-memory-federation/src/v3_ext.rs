use std::sync::Arc;

use codex_hepta_types::{AuthorityPosture, Digest32};

use crate::v3::{
    AsyncFederationTransportV3, CapabilityAuthorityEnvelopeV3, CapabilityVerifierV3,
    FederatedCompletenessV3, FederatedCoverageV3, FederatedQueryV3, FederatedResultV3,
    FederatedValidityV3, FederationCancellationTokenV3, FederationClockV3,
    FederationKeyResolverV3, FederationTransportResultV3, FederationV3Error,
    MAX_FEDERATED_RESULTS_V3,
};

impl<T> FederationKeyResolverV3 for &T
where
    T: FederationKeyResolverV3 + ?Sized,
{
    fn verification_key(
        &self,
        issuer_id: &codex_hepta_types::StableId,
        key_id: &codex_hepta_types::StableId,
    ) -> Option<[u8; 32]> {
        (**self).verification_key(issuer_id, key_id)
    }
}

impl<T> FederationKeyResolverV3 for Arc<T>
where
    T: FederationKeyResolverV3 + ?Sized,
{
    fn verification_key(
        &self,
        issuer_id: &codex_hepta_types::StableId,
        key_id: &codex_hepta_types::StableId,
    ) -> Option<[u8; 32]> {
        (**self).verification_key(issuer_id, key_id)
    }
}

impl<T> CapabilityVerifierV3 for Arc<T>
where
    T: CapabilityVerifierV3 + ?Sized,
{
    fn verify_current(
        &self,
        now_unix_ms: u64,
        query: &FederatedQueryV3,
        authority: &CapabilityAuthorityEnvelopeV3,
    ) -> Result<crate::v3::VerifiedCapabilityV3, FederationV3Error> {
        (**self).verify_current(now_unix_ms, query, authority)
    }
}

/// Async counterpart of `execute_once_v3`.
///
/// The async transport owns the in-flight cancellation/deadline behavior. The
/// federation boundary still performs fresh clock and live authority checks
/// after `.await`, so a late, revoked, or replayed response is never exposed.
pub async fn execute_once_v3_async<T, C, V, K>(
    transport: &T,
    clock: &C,
    capability_verifier: &V,
    peer_keys: &K,
    query: FederatedQueryV3,
    authority: &CapabilityAuthorityEnvelopeV3,
    cancellation: &FederationCancellationTokenV3,
) -> Result<FederatedResultV3, FederationV3Error>
where
    T: AsyncFederationTransportV3,
    C: FederationClockV3,
    V: CapabilityVerifierV3,
    K: FederationKeyResolverV3,
{
    let before_send = clock.now_unix_ms();
    query.validate(before_send)?;
    let verified_before = capability_verifier.verify_current(before_send, &query, authority)?;
    if cancellation.is_cancelled() {
        return Ok(async_indeterminate(&query, &verified_before));
    }

    let transport_result = transport
        .send_once_async(&query, query.deadline_unix_ms, cancellation)
        .await?;

    let after_send = clock.now_unix_ms();
    if after_send >= query.deadline_unix_ms {
        return Err(FederationV3Error::DeadlineExpired);
    }
    let verified_after = capability_verifier.verify_current(after_send, &query, authority)?;
    if verified_after.grant_id != verified_before.grant_id
        || verified_after.lease_epoch != verified_before.lease_epoch
        || verified_after.revocation_epoch != verified_before.revocation_epoch
    {
        return Err(FederationV3Error::CapabilityChangedDuringRead);
    }
    if cancellation.is_cancelled() {
        return Ok(async_indeterminate(&query, &verified_after));
    }

    let mut result = match transport_result {
        FederationTransportResultV3::NonTerminal(_) => async_indeterminate(&query, &verified_after),
        FederationTransportResultV3::Terminal(response) => {
            if !response.terminal_observed {
                return Err(FederationV3Error::MissingTerminalObservation);
            }
            if response.peer_id != query.peer_id {
                return Err(FederationV3Error::IdentityMismatch("response_peer"));
            }
            if response.principal_id != query.principal_id {
                return Err(FederationV3Error::IdentityMismatch("response_principal"));
            }
            if response.grant_id != verified_after.grant_id {
                return Err(FederationV3Error::IdentityMismatch("response_grant"));
            }
            if response.query_binding_digest != query.binding_digest() {
                return Err(FederationV3Error::DigestMismatch("response_query_binding"));
            }
            if response.request_nonce_digest != query.request_nonce_digest {
                return Err(FederationV3Error::DigestMismatch("response_request_nonce"));
            }
            if response.scope_digest != query.scope_digest {
                return Err(FederationV3Error::DigestMismatch("response_scope"));
            }
            if response.purpose_digest != query.purpose_digest {
                return Err(FederationV3Error::DigestMismatch("response_purpose"));
            }
            if response.lease_epoch != verified_after.lease_epoch {
                return Err(FederationV3Error::LeaseEpochMismatch);
            }
            if after_send >= response.expires_unix_ms {
                return Err(FederationV3Error::ResponseExpired);
            }
            if response.items.len() > MAX_FEDERATED_RESULTS_V3 {
                return Err(FederationV3Error::ResultLimitExceeded);
            }
            let computed_payload = response.compute_payload_digest();
            if response.payload_digest != computed_payload {
                return Err(FederationV3Error::DigestMismatch("remote_payload"));
            }
            verify_remote_signature(
                peer_keys,
                &response.peer_id,
                &response.key_id,
                response.payload_digest,
                response.signature,
            )?;

            let stale_generation = response.generation_vector_digest != query.generation_vector_digest;
            let maximum_results = usize::try_from(query.maximum_results)
                .unwrap_or(MAX_FEDERATED_RESULTS_V3);
            let remote_item_count = response.items.len();
            let remote_completeness = response.completeness;
            let mut items = if stale_generation { Vec::new() } else { response.items };
            items.truncate(maximum_results);
            let truncated_items = remote_item_count.saturating_sub(items.len());
            let completeness = if stale_generation {
                FederatedCompletenessV3::Partial
            } else if truncated_items > 0
                || matches!(remote_completeness, FederatedCompletenessV3::Partial)
            {
                FederatedCompletenessV3::Partial
            } else if items.is_empty() {
                FederatedCompletenessV3::Empty
            } else {
                remote_completeness
            };
            FederatedResultV3 {
                query_id: query.query_id.clone(),
                peer_id: query.peer_id.clone(),
                grant_id: verified_after.grant_id.clone(),
                authority_key_id: verified_after.key_id.clone(),
                query_binding_digest: query.binding_digest(),
                generation_vector_digest: query.generation_vector_digest,
                observed_frontier: Some(response.observed_frontier),
                expires_unix_ms: response
                    .expires_unix_ms
                    .min(verified_after.expires_unix_ms)
                    .min(query.deadline_unix_ms),
                items,
                coverage: FederatedCoverageV3 {
                    requested_peers: 1,
                    completed_peers: 1,
                    failed_peers: 0,
                    truncated_items: u32::try_from(truncated_items).unwrap_or(u32::MAX),
                },
                completeness,
                validity: if stale_generation {
                    FederatedValidityV3::StaleGeneration
                } else {
                    FederatedValidityV3::Valid
                },
                remote_payload_digest: Some(response.payload_digest),
                result_digest: Digest32::ZERO,
                authority: AuthorityPosture::DENY_ALL,
            }
        }
    };
    result.result_digest = result.compute_result_digest();
    result.validate()?;
    Ok(result)
}

fn async_indeterminate(
    query: &FederatedQueryV3,
    capability: &crate::v3::VerifiedCapabilityV3,
) -> FederatedResultV3 {
    let mut result = FederatedResultV3 {
        query_id: query.query_id.clone(),
        peer_id: query.peer_id.clone(),
        grant_id: capability.grant_id.clone(),
        authority_key_id: capability.key_id.clone(),
        query_binding_digest: query.binding_digest(),
        generation_vector_digest: query.generation_vector_digest,
        observed_frontier: None,
        expires_unix_ms: query.deadline_unix_ms.min(capability.expires_unix_ms),
        items: Vec::new(),
        coverage: FederatedCoverageV3 {
            requested_peers: 1,
            completed_peers: 0,
            failed_peers: 1,
            truncated_items: 0,
        },
        completeness: FederatedCompletenessV3::Indeterminate,
        validity: FederatedValidityV3::Indeterminate,
        remote_payload_digest: None,
        result_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    result.result_digest = result.compute_result_digest();
    result
}

fn verify_remote_signature<K: FederationKeyResolverV3>(
    keys: &K,
    issuer_id: &codex_hepta_types::StableId,
    key_id: &codex_hepta_types::StableId,
    digest: Digest32,
    signature_bytes: [u8; 64],
) -> Result<(), FederationV3Error> {
    use ed25519_dalek::{Signature, Verifier, VerifyingKey};

    let key_bytes = keys
        .verification_key(issuer_id, key_id)
        .ok_or(FederationV3Error::UnknownVerificationKey)?;
    let key = VerifyingKey::from_bytes(&key_bytes)
        .map_err(|_| FederationV3Error::InvalidVerificationKey)?;
    let signature = Signature::from_bytes(&signature_bytes);
    key.verify(digest.as_array(), &signature)
        .map_err(|_| FederationV3Error::InvalidSignature)
}
