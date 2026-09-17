pub struct FederationClientV3<T, C = SystemFederationClockV3> {
    authority: Arc<FinalUseAuthority>,
    authority_key_id: Arc<str>,
    registry: FederationPeerRegistryV3,
    transport: Arc<T>,
    clock: Arc<C>,
    cache: Arc<FederationResultCacheV3>,
    active_queries: Arc<Mutex<BTreeMap<StableId, FederationCancellationTokenV3>>>,
}

impl<T, C> Clone for FederationClientV3<T, C> {
    fn clone(&self) -> Self {
        Self {
            authority: Arc::clone(&self.authority),
            authority_key_id: Arc::clone(&self.authority_key_id),
            registry: self.registry.clone(),
            transport: Arc::clone(&self.transport),
            clock: Arc::clone(&self.clock),
            cache: Arc::clone(&self.cache),
            active_queries: Arc::clone(&self.active_queries),
        }
    }
}

impl<T, C> fmt::Debug for FederationClientV3<T, C> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("FederationClientV3")
            .field("authority_key_id", &self.authority_key_id)
            .field("registry", &self.registry)
            .field("cache", &self.cache)
            .finish_non_exhaustive()
    }
}

impl<T, C> FederationClientV3<T, C>
where
    T: FederationTransportV3 + 'static,
    C: FederationClockV3 + 'static,
{
    pub fn new(
        authority: FinalUseAuthority,
        authority_key_id: String,
        registry: FederationPeerRegistryV3,
        transport: T,
        clock: C,
        cache_capacity: usize,
    ) -> Result<Self, FederationV3Error> {
        if !external_identifier(&authority_key_id) {
            return Err(FederationV3Error::InvalidAuthorityReceipt);
        }
        Ok(Self {
            authority: Arc::new(authority),
            authority_key_id: Arc::from(authority_key_id),
            registry,
            transport: Arc::new(transport),
            clock: Arc::new(clock),
            cache: Arc::new(FederationResultCacheV3::new(cache_capacity)?),
            active_queries: Arc::new(Mutex::new(BTreeMap::new())),
        })
    }

    pub async fn query(
        &self,
        plan: FederatedReadPlanV3,
    ) -> Result<FederatedAggregateResultV3, FederationV3Error> {
        let query_id = plan.spec.query_id.clone();
        let cancellation = FederationCancellationTokenV3::default();
        {
            let mut active = self
                .active_queries
                .lock()
                .map_err(|_| FederationV3Error::QueryRegistryUnavailable)?;
            if active.contains_key(&query_id) {
                return Err(FederationV3Error::QueryAlreadyActive);
            }
            active.insert(query_id.clone(), cancellation.clone());
        }
        let result = self.query_inner(plan, cancellation).await;
        if let Ok(mut active) = self.active_queries.lock() {
            active.remove(&query_id);
        }
        result
    }

    pub fn cancel_query(&self, query_id: &StableId) -> Result<bool, FederationV3Error> {
        let active = self
            .active_queries
            .lock()
            .map_err(|_| FederationV3Error::QueryRegistryUnavailable)?;
        let Some(token) = active.get(query_id) else {
            return Ok(false);
        };
        token.cancel();
        Ok(true)
    }

    async fn query_inner(
        &self,
        plan: FederatedReadPlanV3,
        cancellation: FederationCancellationTokenV3,
    ) -> Result<FederatedAggregateResultV3, FederationV3Error> {
        let now = self.clock.now_unix_ms()?;
        plan.validate(now)?;
        for permit in &plan.peers {
            self.registry.resolve(&permit.target.peer_id, now)?;
        }
        let concurrency = usize::from(plan.maximum_concurrency);
        let spec = plan.spec.clone();
        let executions = stream::iter(plan.peers.into_iter().map(|permit| {
            let client = self.clone();
            let spec = spec.clone();
            let cancellation = cancellation.clone();
            async move {
                let peer_id = permit.target.peer_id.clone();
                let result = client.execute_peer(spec, permit, cancellation).await;
                (peer_id, result)
            }
        }))
        .buffer_unordered(concurrency)
        .collect::<Vec<_>>()
        .await;
        let result = aggregate_results(spec, executions)?;
        result.validate()?;
        Ok(result)
    }

    async fn execute_peer(
        &self,
        spec: FederatedReadSpecV3,
        permit: FederatedPeerPermitV3,
        query_cancellation: FederationCancellationTokenV3,
    ) -> Result<FederatedPeerResultV3, FederationV3Error> {
        let before_send = self.clock.now_unix_ms()?;
        spec.validate(before_send)?;
        permit.target.validate()?;
        let query = spec.peer_query(&permit.target);
        query.validate(before_send)?;
        let binding = query.authority_binding();
        if permit.signed_grant.grant.binding != binding {
            return Err(FederationV3Error::AuthorityBindingMismatch);
        }
        if permit.signed_grant.grant.authority_epoch != query.authority_epoch {
            return Err(FederationV3Error::AuthorityEpochMismatch);
        }
        let enrollment = self.registry.resolve(&query.peer_id, before_send)?;
        let verified = self
            .authority
            .claim(&permit.signed_grant, &binding)
            .map_err(FederationV3Error::Authority)?;
        let authority_receipt = VerifiedFederationAuthorityReceiptV3::from_verified_grant(
            &query,
            &permit.signed_grant,
            &self.authority_key_id,
        )?;
        if query_cancellation.is_cancelled() {
            return Err(FederationV3Error::Cancelled);
        }
        let attempt_cancellation = FederationCancellationTokenV3::default();
        let attempt = FederatedAttemptV3 {
            query: query.clone(),
            grant: permit.signed_grant.clone(),
            enrollment: enrollment.clone(),
        };
        let remaining = query.deadline_unix_ms - before_send;
        let transport_result = tokio::select! {
            biased;
            _ = query_cancellation.cancelled() => {
                attempt_cancellation.cancel();
                FederationTransportResultV3::NonTerminal(FederationTransportOutcomeV3::Cancelled)
            }
            _ = tokio::time::sleep(Duration::from_millis(remaining)) => {
                attempt_cancellation.cancel();
                FederationTransportResultV3::NonTerminal(FederationTransportOutcomeV3::TimedOut)
            }
            result = self.transport.send_once(attempt, attempt_cancellation.clone()) => result?,
        };
        let after_send = self.clock.now_unix_ms()?;
        if query_cancellation.is_cancelled() {
            return Err(FederationV3Error::Cancelled);
        }
        if after_send >= query.deadline_unix_ms {
            return Err(FederationV3Error::DeadlineExpired);
        }
        let current_enrollment = self.registry.resolve(&query.peer_id, after_send)?;
        if current_enrollment.enrollment_epoch != enrollment.enrollment_epoch
            || current_enrollment.key_id != enrollment.key_id
            || current_enrollment.verifying_key != enrollment.verifying_key
        {
            return Err(FederationV3Error::PeerEnrollmentChanged);
        }
        let response = match transport_result {
            FederationTransportResultV3::Terminal(response) => response,
            FederationTransportResultV3::NonTerminal(outcome) => {
                return Err(match outcome {
                    FederationTransportOutcomeV3::Unavailable => FederationV3Error::Unavailable,
                    FederationTransportOutcomeV3::TimedOut => FederationV3Error::TimedOut,
                    FederationTransportOutcomeV3::Cancelled => FederationV3Error::Cancelled,
                    FederationTransportOutcomeV3::NoTerminalObservation => {
                        FederationV3Error::MissingTerminalObservation
                    }
                });
            }
        };
        response.validate_and_verify(
            &query,
            &permit.signed_grant,
            &current_enrollment,
            after_send,
        )?;
        let stale_generation = response.generation_vector_digest != query.generation_vector_digest;
        let remote_count = response.items.len();
        let maximum_results = usize::try_from(query.maximum_results)
            .unwrap_or(MAX_FEDERATED_RESULTS_V2);
        let mut items = if stale_generation {
            Vec::new()
        } else {
            response.items.clone()
        };
        items.sort_by(|left, right| {
            left.source_owner_id
                .cmp(&right.source_owner_id)
                .then_with(|| left.record_id.cmp(&right.record_id))
                .then_with(|| left.record_revision.cmp(&right.record_revision))
        });
        items.truncate(maximum_results);
        let truncated_items = if stale_generation {
            0
        } else {
            remote_count.saturating_sub(items.len())
        };
        let completeness = if stale_generation {
            FederatedCompletenessV2::Partial
        } else if truncated_items > 0
            || matches!(response.completeness, FederatedCompletenessV2::Partial)
        {
            FederatedCompletenessV2::Partial
        } else if matches!(response.completeness, FederatedCompletenessV2::Empty) {
            FederatedCompletenessV2::Empty
        } else {
            FederatedCompletenessV2::Complete
        };
        let expires_unix_ms = response
            .expires_unix_ms
            .min(permit.signed_grant.grant.expires_at_unix_ms)
            .min(query.deadline_unix_ms)
            .min(current_enrollment.expires_unix_ms);
        if after_send >= expires_unix_ms {
            return Err(FederationV3Error::ResponseExpired);
        }
        let mut result = FederatedPeerResultV3 {
            query_id: query.query_id.clone(),
            peer_id: query.peer_id.clone(),
            principal_id: query.principal_id.clone(),
            query_binding_digest: query.binding_digest(),
            generation_vector_digest: query.generation_vector_digest,
            authority_receipt,
            grant_id: permit.signed_grant.grant.grant_id.clone(),
            peer_key_id: current_enrollment.key_id,
            enrollment_epoch: current_enrollment.enrollment_epoch,
            observed_frontier: response.observed_frontier,
            expires_unix_ms,
            items,
            completeness,
            validity: if stale_generation {
                FederatedValidityV2::StaleGeneration
            } else {
                FederatedValidityV2::Valid
            },
            truncated_items: u32::try_from(truncated_items).unwrap_or(u32::MAX),
            remote_payload_digest: response.payload_digest,
            result_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        result.result_digest = result.compute_result_digest();
        result.validate()?;
        let release_time = self.clock.now_unix_ms()?;
        if release_time >= result.expires_unix_ms || query_cancellation.is_cancelled() {
            return Err(if query_cancellation.is_cancelled() {
                FederationV3Error::Cancelled
            } else {
                FederationV3Error::ResponseExpired
            });
        }
        let released = self
            .authority
            .with_verified_use(verified, &binding, || result.clone())
            .map_err(FederationV3Error::Authority)?;
        self.cache.insert(
            query,
            permit.signed_grant,
            released.clone(),
            release_time,
        )?;
        Ok(released)
    }

    pub fn revalidate_remote(
        &self,
        key: &FederationCacheKeyV3,
        fresh_grant: &SignedFinalUseGrant,
        expected_generation_vector_digest: Digest32,
    ) -> Result<FederatedPeerResultV3, FederationV3Error> {
        let now = self.clock.now_unix_ms()?;
        let entry = self
            .cache
            .get_entry(key, now)?
            .ok_or(FederationV3Error::CacheMiss)?;
        if entry.result.generation_vector_digest != expected_generation_vector_digest {
            return Err(FederationV3Error::StaleGeneration);
        }
        if fresh_grant.grant.grant_id != entry.original_grant.grant.grant_id
            || fresh_grant.grant.authority_epoch != entry.original_grant.grant.authority_epoch
        {
            return Err(FederationV3Error::AuthorityGrantMismatch);
        }
        let binding = entry.query.authority_binding();
        if fresh_grant.grant.binding != binding {
            return Err(FederationV3Error::AuthorityBindingMismatch);
        }
        let current_enrollment = self.registry.resolve(&entry.result.peer_id, now)?;
        if current_enrollment.key_id != entry.result.peer_key_id
            || current_enrollment.enrollment_epoch != entry.result.enrollment_epoch
            || current_enrollment.verifying_key
                != self
                    .registry
                    .resolve(&entry.result.peer_id, now)?
                    .verifying_key
        {
            self.cache.purge_peer(&entry.result.peer_id)?;
            return Err(FederationV3Error::PeerEnrollmentChanged);
        }
        let verified = self
            .authority
            .claim(fresh_grant, &binding)
            .map_err(FederationV3Error::Authority)?;
        let mut refreshed = entry.result.clone();
        refreshed.authority_receipt = VerifiedFederationAuthorityReceiptV3::from_verified_grant(
            &entry.query,
            fresh_grant,
            &self.authority_key_id,
        )?;
        refreshed.expires_unix_ms = refreshed
            .expires_unix_ms
            .min(fresh_grant.grant.expires_at_unix_ms)
            .min(current_enrollment.expires_unix_ms)
            .min(entry.query.deadline_unix_ms);
        if now >= refreshed.expires_unix_ms {
            return Err(FederationV3Error::CacheMiss);
        }
        refreshed.result_digest = refreshed.compute_result_digest();
        refreshed.validate()?;
        let released = self
            .authority
            .with_verified_use(verified, &binding, || refreshed.clone())
            .map_err(FederationV3Error::Authority)?;
        self.cache.insert(
            entry.query,
            fresh_grant.clone(),
            released.clone(),
            now,
        )?;
        Ok(released)
    }

    pub fn purge_revocations(
        &self,
        head: &FinalUseRevocations,
    ) -> Result<usize, FederationV3Error> {
        self.cache.purge_revocations(head)
    }

    pub fn purge_peer(&self, peer_id: &StableId) -> Result<usize, FederationV3Error> {
        self.cache.purge_peer(peer_id)
    }

    pub fn purge_peer_key(&self, key_id: &str) -> Result<usize, FederationV3Error> {
        self.cache.purge_key(key_id)
    }
}
