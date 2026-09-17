use super::*;

pub fn execute_once<T, A, P, C>(
    transport: &T,
    authority_verifier: &A,
    peer_verifier: &P,
    clock: &C,
    query: FederatedQueryV2,
    lease: &FederatedLeaseV2,
) -> Result<FederatedResultV2, FederationV2Error>
where
    T: FederationTransportV2,
    A: FederationAuthorityVerifierV2,
    P: FederationPeerSignatureVerifierV2,
    C: FederationClockV2,
{
    let started_at = clock.now_unix_ms()?;
    query.validate(started_at).map_err(FederationV2Error::Legacy)?;
    validate_lease_shape(started_at, &query, lease)?;
    let authority_before = authority_verifier.verify(&query, lease, started_at)?;
    authority_before.validate(started_at, &query, lease)?;

    let transport_result = transport.send_once(&FederationTransportRequestV2 {
        query: query.clone(),
        grant_id: authority_before.grant_id.clone(),
        lease_id: lease.lease_id.clone(),
        authority_verification_digest: authority_before.verification_digest(),
    })?;
    let after_io = clock.now_unix_ms()?;
    query.validate(after_io).map_err(FederationV2Error::Legacy)?;
    validate_lease_shape(after_io, &query, lease)?;
    let authority_after = authority_verifier.verify(&query, lease, after_io)?;
    let publish_at = clock.now_unix_ms()?;
    query.validate(publish_at).map_err(FederationV2Error::Legacy)?;
    validate_lease_shape(publish_at, &query, lease)?;
    authority_after.validate(publish_at, &query, lease)?;
    if authority_after.revocation_epoch < authority_before.revocation_epoch
        || authority_after.grant_id != authority_before.grant_id
        || authority_after.lease_id != authority_before.lease_id
        || authority_after.lease_epoch != authority_before.lease_epoch
    {
        return Err(FederationV2Error::AuthorityChangedDuringRead);
    }

    let mut result = match transport_result {
        FederationTransportResultV2::NonTerminal(_) => {
            indeterminate_result(&query, lease, &authority_after)
        }
        FederationTransportResultV2::Terminal(response) => {
            validate_response(&response, &query, lease, &authority_after, publish_at)?;
            let peer_receipt = peer_verifier.verify(&response)?;
            if peer_receipt.peer_id != response.peer_id
                || peer_receipt.key_id != response.signer_key_id
                || peer_receipt.signing_digest != response.signing_digest()
            {
                return Err(FederationV2Error::InvalidSignature);
            }
            ensure_digest("peer_proof", peer_receipt.proof_digest)?;
            let final_publish_at = clock.now_unix_ms()?;
            query.validate(final_publish_at).map_err(FederationV2Error::Legacy)?;
            validate_lease_shape(final_publish_at, &query, lease)?;
            authority_after.validate(final_publish_at, &query, lease)?;
            if final_publish_at >= response.expires_unix_ms {
                return Err(FederationV2Error::ResponseExpired);
            }
            terminal_result(&query, lease, &authority_after, response, peer_receipt)?
        }
    };
    result.result_digest = result.compute_result_digest();
    Ok(result)
}

fn validate_lease_shape(
    now_unix_ms: u64,
    query: &FederatedQueryV2,
    lease: &FederatedLeaseV2,
) -> Result<(), FederationV2Error> {
    if now_unix_ms >= lease.expires_unix_ms {
        return Err(FederationV2Error::LeaseExpired);
    }
    if lease.query_id != query.query_id
        || lease.peer_id != query.peer_id
        || lease.principal_id != query.principal_id
    {
        return Err(FederationV2Error::IdentityMismatch("lease"));
    }
    if lease.lease_epoch == 0 || lease.lease_epoch != query.lease_epoch {
        return Err(FederationV2Error::LeaseEpochMismatch);
    }
    if lease.scope_digest != query.scope_digest
        || lease.purpose_digest != query.purpose_digest
        || lease.generation_vector_digest != query.generation_vector_digest
        || lease.query_binding_digest != query.binding_digest()
    {
        return Err(FederationV2Error::DigestMismatch("lease_binding"));
    }
    Ok(())
}

fn validate_response(
    response: &RemoteFederatedResponseV2,
    query: &FederatedQueryV2,
    lease: &FederatedLeaseV2,
    authority: &VerifiedFederationAuthorityV2,
    now_unix_ms: u64,
) -> Result<(), FederationV2Error> {
    response.validate_shape()?;
    if response.peer_id != query.peer_id
        || response.grant_id != authority.grant_id
        || response.lease_id != lease.lease_id
    {
        return Err(FederationV2Error::IdentityMismatch("response_binding"));
    }
    if response.lease_epoch != query.lease_epoch {
        return Err(FederationV2Error::LeaseEpochMismatch);
    }
    for (name, left, right) in [
        (
            "response_query_binding",
            response.query_binding_digest,
            query.binding_digest(),
        ),
        (
            "response_request_nonce",
            response.request_nonce_digest,
            query.nonce_digest,
        ),
        ("response_scope", response.scope_digest, query.scope_digest),
        ("response_purpose", response.purpose_digest, query.purpose_digest),
    ] {
        if left != right {
            return Err(FederationV2Error::DigestMismatch(name));
        }
    }
    if response.payload_digest != response.compute_payload_digest() {
        return Err(FederationV2Error::DigestMismatch("response_payload"));
    }
    if now_unix_ms >= response.expires_unix_ms {
        return Err(FederationV2Error::ResponseExpired);
    }
    Ok(())
}

fn terminal_result(
    query: &FederatedQueryV2,
    lease: &FederatedLeaseV2,
    authority: &VerifiedFederationAuthorityV2,
    response: RemoteFederatedResponseV2,
    peer_receipt: PeerAuthenticationReceiptV2,
) -> Result<FederatedResultV2, FederationV2Error> {
    let stale = response.generation_vector_digest != query.generation_vector_digest;
    let remote_len = response.items.len();
    let mut items = if stale {
        Vec::new()
    } else {
        response.items.clone()
    };
    items.truncate(usize::try_from(query.maximum_results).unwrap_or(MAX_FEDERATED_RESULTS_V2));
    let truncated = remote_len.saturating_sub(items.len());
    let completeness = if stale || truncated > 0 {
        FederatedCompletenessV2::Partial
    } else {
        response.completeness
    };
    Ok(FederatedResultV2 {
        query_id: query.query_id.clone(),
        peer_id: query.peer_id.clone(),
        grant_id: authority.grant_id.clone(),
        lease_id: lease.lease_id.clone(),
        query_binding_digest: query.binding_digest(),
        generation_vector_digest: query.generation_vector_digest,
        observed_frontier: Some(response.observed_frontier),
        expires_unix_ms: bounded_expiry(response.expires_unix_ms, query, lease, authority),
        revocation_epoch: authority.revocation_epoch,
        items,
        coverage: FederatedCoverageV2 {
            requested_peers: 1,
            completed_peers: 1,
            failed_peers: 0,
            truncated_items: u32::try_from(truncated).unwrap_or(u32::MAX),
        },
        completeness,
        validity: if stale {
            FederatedValidityV2::StaleGeneration
        } else {
            FederatedValidityV2::Valid
        },
        authority_verification_digest: authority.verification_digest(),
        peer_authentication_digest: Some(peer_receipt.proof_digest),
        remote_response_digest: Some(response.envelope_digest()),
        result_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn indeterminate_result(
    query: &FederatedQueryV2,
    lease: &FederatedLeaseV2,
    authority: &VerifiedFederationAuthorityV2,
) -> FederatedResultV2 {
    FederatedResultV2 {
        query_id: query.query_id.clone(),
        peer_id: query.peer_id.clone(),
        grant_id: authority.grant_id.clone(),
        lease_id: lease.lease_id.clone(),
        query_binding_digest: query.binding_digest(),
        generation_vector_digest: query.generation_vector_digest,
        observed_frontier: None,
        expires_unix_ms: bounded_expiry(query.deadline_unix_ms, query, lease, authority),
        revocation_epoch: authority.revocation_epoch,
        items: Vec::new(),
        coverage: FederatedCoverageV2 {
            requested_peers: 1,
            completed_peers: 0,
            failed_peers: 1,
            truncated_items: 0,
        },
        completeness: FederatedCompletenessV2::Indeterminate,
        validity: FederatedValidityV2::Indeterminate,
        authority_verification_digest: authority.verification_digest(),
        peer_authentication_digest: None,
        remote_response_digest: None,
        result_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    }
}

fn bounded_expiry(
    response_expiry: u64,
    query: &FederatedQueryV2,
    lease: &FederatedLeaseV2,
    authority: &VerifiedFederationAuthorityV2,
) -> u64 {
    response_expiry
        .min(query.deadline_unix_ms)
        .min(lease.expires_unix_ms)
        .min(authority.expires_unix_ms)
        .min(authority.revocation_fresh_until_unix_ms)
}
