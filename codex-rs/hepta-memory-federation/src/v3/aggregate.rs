fn aggregate_results(
    spec: FederatedReadSpecV3,
    executions: Vec<(StableId, Result<FederatedPeerResultV3, FederationV3Error>)>,
) -> Result<FederatedAggregateResultV3, FederationV3Error> {
    let mut coverage = Vec::with_capacity(executions.len());
    let mut completed_peers = 0u32;
    let mut failed_peers = 0u32;
    let mut truncated_items = 0u32;
    let mut expires = spec.deadline_unix_ms;
    let mut saw_partial = false;
    let mut saw_stale = false;
    let mut saw_revoked = false;
    let mut evidence = BTreeMap::<(StableId, StableId, Revision), FederatedEvidenceItemV2>::new();

    for (peer_id, execution) in executions {
        match execution {
            Ok(result) => {
                completed_peers = completed_peers.saturating_add(1);
                truncated_items = truncated_items.saturating_add(result.truncated_items);
                expires = expires.min(result.expires_unix_ms);
                saw_partial |= matches!(result.completeness, FederatedCompletenessV2::Partial);
                saw_stale |= matches!(result.validity, FederatedValidityV2::StaleGeneration);
                for item in &result.items {
                    let key = (
                        item.source_owner_id.clone(),
                        item.record_id.clone(),
                        item.record_revision,
                    );
                    if let Some(existing) = evidence.get(&key) {
                        if existing != item {
                            return Err(FederationV3Error::ConflictingEvidenceIdentity);
                        }
                    } else {
                        evidence.insert(key, item.clone());
                    }
                }
                coverage.push(FederatedPeerCoverageV3 {
                    peer_id,
                    completeness: result.completeness,
                    validity: result.validity,
                    returned_items: u32::try_from(result.items.len()).unwrap_or(u32::MAX),
                    truncated_items: result.truncated_items,
                    failure: None,
                });
            }
            Err(error) => {
                failed_peers = failed_peers.saturating_add(1);
                let revoked = matches!(
                    error,
                    FederationV3Error::Authority(FinalUseError::Revoked)
                        | FederationV3Error::Authority(FinalUseError::EpochMismatch)
                );
                saw_revoked |= revoked;
                coverage.push(FederatedPeerCoverageV3 {
                    peer_id,
                    completeness: FederatedCompletenessV2::Indeterminate,
                    validity: if revoked {
                        FederatedValidityV2::Revoked
                    } else {
                        FederatedValidityV2::Indeterminate
                    },
                    returned_items: 0,
                    truncated_items: 0,
                    failure: Some(peer_failure(&error)),
                });
            }
        }
    }
    coverage.sort_by(|left, right| left.peer_id.cmp(&right.peer_id));
    let maximum_results = usize::try_from(spec.maximum_results).unwrap_or(MAX_FEDERATED_RESULTS_V2);
    let mut items = evidence.into_values().collect::<Vec<_>>();
    let before_truncation = items.len();
    items.truncate(maximum_results);
    let aggregate_truncation = before_truncation.saturating_sub(items.len());
    truncated_items = truncated_items
        .saturating_add(u32::try_from(aggregate_truncation).unwrap_or(u32::MAX));
    if aggregate_truncation > 0 {
        saw_partial = true;
    }
    let completeness = if completed_peers == 0 {
        FederatedCompletenessV2::Indeterminate
    } else if failed_peers > 0 || saw_partial || saw_stale {
        FederatedCompletenessV2::Partial
    } else if items.is_empty() {
        FederatedCompletenessV2::Empty
    } else {
        FederatedCompletenessV2::Complete
    };
    let validity = if saw_revoked {
        FederatedValidityV2::Revoked
    } else if completed_peers == 0 {
        FederatedValidityV2::Indeterminate
    } else if saw_stale {
        FederatedValidityV2::StaleGeneration
    } else {
        FederatedValidityV2::Valid
    };
    let mut result = FederatedAggregateResultV3 {
        query_id: spec.query_id,
        principal_id: spec.principal_id,
        scope_digest: spec.scope_digest,
        purpose_digest: spec.purpose_digest,
        generation_vector_digest: spec.generation_vector_digest,
        expires_unix_ms: expires,
        items,
        coverage: FederatedCoverageV3 {
            requested_peers: completed_peers.saturating_add(failed_peers),
            completed_peers,
            failed_peers,
            truncated_items,
            peers: coverage,
        },
        completeness,
        validity,
        result_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    result.result_digest = result.compute_result_digest();
    Ok(result)
}

fn remove_cache_entry(state: &mut FederationCacheStateV3, key: &FederationCacheKeyV3) {
    let Some(entry) = state.entries.remove(key) else {
        return;
    };
    remove_reverse_index(
        &mut state.by_grant,
        &entry.original_grant.grant.grant_id,
        key,
    );
    remove_reverse_index(&mut state.by_key, &entry.result.peer_key_id, key);
    remove_reverse_index(&mut state.by_peer, &entry.result.peer_id, key);
}

fn remove_reverse_index<K: Ord>(
    index: &mut BTreeMap<K, BTreeSet<FederationCacheKeyV3>>,
    owner: &K,
    key: &FederationCacheKeyV3,
) {
    let empty = if let Some(keys) = index.get_mut(owner) {
        keys.remove(key);
        keys.is_empty()
    } else {
        false
    };
    if empty {
        index.remove(owner);
    }
}

fn peer_failure(error: &FederationV3Error) -> FederationPeerFailureV3 {
    match error {
        FederationV3Error::Unavailable => FederationPeerFailureV3::Unavailable,
        FederationV3Error::TimedOut | FederationV3Error::DeadlineExpired => {
            FederationPeerFailureV3::TimedOut
        }
        FederationV3Error::Cancelled => FederationPeerFailureV3::Cancelled,
        FederationV3Error::Authority(FinalUseError::Revoked | FinalUseError::EpochMismatch) => {
            FederationPeerFailureV3::Revoked
        }
        FederationV3Error::Authority(FinalUseError::Expired | FinalUseError::NotYetValid)
        | FederationV3Error::AuthorityExpired => FederationPeerFailureV3::Expired,
        FederationV3Error::PeerEnrollmentChanged
        | FederationV3Error::PeerEnrollmentExpired
        | FederationV3Error::PeerRevoked
        | FederationV3Error::PeerNotEnrolled => FederationPeerFailureV3::StaleEnrollment,
        FederationV3Error::TransportRejected => FederationPeerFailureV3::Rejected,
        FederationV3Error::InvalidPeerSignature
        | FederationV3Error::InvalidRemoteEnvelope
        | FederationV3Error::DigestMismatch(_)
        | FederationV3Error::IdentityMismatch(_)
        | FederationV3Error::MissingTerminalObservation => FederationPeerFailureV3::InvalidResponse,
        _ => FederationPeerFailureV3::Internal,
    }
}

const fn failure_code(value: FederationPeerFailureV3) -> u8 {
    match value {
        FederationPeerFailureV3::Unavailable => 0,
        FederationPeerFailureV3::TimedOut => 1,
        FederationPeerFailureV3::Cancelled => 2,
        FederationPeerFailureV3::Revoked => 3,
        FederationPeerFailureV3::Expired => 4,
        FederationPeerFailureV3::StaleEnrollment => 5,
        FederationPeerFailureV3::InvalidResponse => 6,
        FederationPeerFailureV3::Rejected => 7,
        FederationPeerFailureV3::Internal => 8,
    }
}
