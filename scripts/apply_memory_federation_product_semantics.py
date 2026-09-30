#!/usr/bin/env python3
from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, found {count}")
    write(path, text.replace(old, new, 1))


def insert_before_once(path: str, marker: str, content: str) -> None:
    text = read(path)
    if content in text:
        return
    count = text.count(marker)
    if count != 1:
        raise SystemExit(f"{path}: expected one insertion marker, found {count}")
    write(path, text.replace(marker, content + marker, 1))


retrieval = "codex-rs/hepta-memory/src/cognitive_retrieval.rs"
observation = "codex-rs/hepta-memory/src/cognitive_retrieval_observation.rs"
federation = "codex-rs/hepta-memory/src/cognitive_federation.rs"
runtime = "codex-rs/hepta-memory/src/cognitive_runtime.rs"
extension = "codex-rs/ext/hepta-memory/src/cognitive/federation.rs"
retrieval_tests = "codex-rs/hepta-memory/src/cognitive_retrieval_tests.rs"

# Thread an exact owner scope through every retrieval channel and final
# candidate resolution. This prevents broader access scopes from consuming
# top-K slots before a federation capability's exact scope is applied.
replace_once(
    observation,
    """pub(super) struct GeneratedRetrieval {
    pub(super) ranked: Vec<(MemoryKey, AggregatedRank)>,
    channels: Vec<RetrievalChannelObservation>,
}
""",
    """pub(super) struct GeneratedRetrieval {
    pub(super) ranked: Vec<(MemoryKey, AggregatedRank)>,
    channels: Vec<RetrievalChannelObservation>,
}

impl GeneratedRetrieval {
    pub(super) fn all_channels_exhausted(&self) -> bool {
        self.channels
            .iter()
            .all(|channel| channel.limit == RetrievalLimitObservation::Exhausted)
    }
}
""",
)
replace_once(
    observation,
    """.generate_retrieval_tx(&mut transaction, access, request, &fts_query)
            .await?;""",
    """.generate_retrieval_tx(&mut transaction, access, request, &fts_query, None)
            .await?;""",
)
replace_once(
    observation,
    """                generated.ranked,
                MAX_RETRIEVAL_OWNER_CHANNELS * MAX_RETRIEVAL_CHANNEL_CANDIDATES,
""",
    """                generated.ranked,
                None,
                MAX_RETRIEVAL_OWNER_CHANNELS * MAX_RETRIEVAL_CHANNEL_CANDIDATES,
""",
)
replace_once(
    observation,
    """        request: &RetrievalRequest,
        fts_query: &str,
    ) -> Result<GeneratedRetrieval, CognitiveStoreError> {
""",
    """        request: &RetrievalRequest,
        fts_query: &str,
        exact_scope: Option<&CognitiveScope>,
    ) -> Result<GeneratedRetrieval, CognitiveStoreError> {
""",
)
replace_once(
    observation,
    """.memory_fts_channel_tx(transaction, access, fts_query, now)
            .await?;""",
    """.memory_fts_channel_tx(transaction, access, fts_query, now, exact_scope)
            .await?;""",
)
replace_once(
    observation,
    """.entity_fts_channel_tx(transaction, access, fts_query, now)
            .await?;""",
    """.entity_fts_channel_tx(transaction, access, fts_query, now, exact_scope)
            .await?;""",
)
replace_once(
    observation,
    """                access.workspace_sha256().map(Sha256Digest::as_str),
                now,
""",
    """                access.workspace_sha256().map(Sha256Digest::as_str),
                now,
                exact_scope,
""",
)
replace_once(
    observation,
    """        request: &RetrievalRequest,
        ranked: Vec<(MemoryKey, AggregatedRank)>,
        maximum_results: usize,
""",
    """        request: &RetrievalRequest,
        ranked: Vec<(MemoryKey, AggregatedRank)>,
        exact_scope: Option<&CognitiveScope>,
        maximum_results: usize,
""",
)
replace_once(
    observation,
    """            let explanation = self
                .explain_memory_head_tx(transaction, access, &memory_id)
                .await?;
            if explanation.memory.id.revision != key.revision
""",
    """            let explanation = self
                .explain_memory_head_tx(transaction, access, &memory_id)
                .await?;
            if exact_scope.is_some_and(|scope| explanation.memory.scope != *scope) {
                continue;
            }
            if explanation.memory.id.revision != key.revision
""",
)

replace_once(
    retrieval,
    """    pub(crate) async fn retrieve_memory_candidates_for_scope(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        request: &RetrievalRequest,
    ) -> Result<(RetrievalBatch, u64), CognitiveStoreError> {
        self.authorize(access, scope)?;
        let fts_query = self.validate_retrieval_request(access, request)?;
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let mut batch = self
            .retrieve_memory_candidates_tx(&mut transaction, access, request, &fts_query)
            .await?;
        batch
            .candidates
            .retain(|candidate| candidate.memory.scope == *scope);

        let (scope_kind, workspace_sha256) = scope.database_parts();
        let memory_frontier: i64 = sqlx::query_scalar(
            "SELECT count(*) FROM memory_revisions
             WHERE owner_agent_id = ? AND scope_kind = ? AND workspace_sha256 IS ?",
        )
        .bind(self.owner_agent_id.as_str())
        .bind(scope_kind)
        .bind(workspace_sha256)
        .fetch_one(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let memory_frontier = u64::try_from(memory_frontier).map_err(|_| {
            CognitiveStoreError::Corrupt(
                "negative exact-scope memory federation frontier".to_string(),
            )
        })?;
        transaction.commit().await.map_err(unavailable)?;
        Ok((batch, memory_frontier))
    }
""",
    """    pub(crate) async fn retrieve_memory_candidates_for_scope(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        request: &RetrievalRequest,
    ) -> Result<(RetrievalBatch, u64, bool), CognitiveStoreError> {
        self.authorize(access, scope)?;
        let fts_query = self.validate_retrieval_request(access, request)?;
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let generated = self
            .generate_retrieval_tx(
                &mut transaction,
                access,
                request,
                &fts_query,
                Some(scope),
            )
            .await?;
        let all_channels_exhausted = generated.all_channels_exhausted();
        let mut candidates = self
            .resolve_retrieval_tx(
                &mut transaction,
                access,
                request,
                generated.ranked,
                Some(scope),
                MAX_RETRIEVAL_RESULTS + 1,
            )
            .await?;
        let owner_exhausted =
            all_channels_exhausted && candidates.len() <= MAX_RETRIEVAL_RESULTS;
        candidates.truncate(MAX_RETRIEVAL_RESULTS);
        let batch = RetrievalBatch {
            query_sha256: Sha256Digest::for_bytes(request.query.as_bytes()),
            candidates,
        };

        let (scope_kind, workspace_sha256) = scope.database_parts();
        let memory_frontier: i64 = sqlx::query_scalar(
            "SELECT count(*) FROM memory_revisions
             WHERE owner_agent_id = ? AND scope_kind = ? AND workspace_sha256 IS ?",
        )
        .bind(self.owner_agent_id.as_str())
        .bind(scope_kind)
        .bind(workspace_sha256)
        .fetch_one(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let memory_frontier = u64::try_from(memory_frontier).map_err(|_| {
            CognitiveStoreError::Corrupt(
                "negative exact-scope memory federation frontier".to_string(),
            )
        })?;
        transaction.commit().await.map_err(unavailable)?;
        Ok((batch, memory_frontier, owner_exhausted))
    }
""",
)
replace_once(
    retrieval,
    """.generate_retrieval_tx(transaction, access, request, fts_query)
            .await?;""",
    """.generate_retrieval_tx(transaction, access, request, fts_query, None)
            .await?;""",
)
replace_once(
    retrieval,
    """                generated.ranked,
                MAX_RETRIEVAL_RESULTS,
""",
    """                generated.ranked,
                None,
                MAX_RETRIEVAL_RESULTS,
""",
)

replace_once(
    retrieval,
    """        access: &CognitiveAccess,
        fts_query: &str,
        now: i64,
    ) -> Result<ChannelOutput<MemoryKey>, CognitiveStoreError> {
        let rows = sqlx::query(
""",
    """        access: &CognitiveAccess,
        fts_query: &str,
        now: i64,
        exact_scope: Option<&CognitiveScope>,
    ) -> Result<ChannelOutput<MemoryKey>, CognitiveStoreError> {
        let (exact_scope_kind, exact_workspace_sha256) = exact_scope
            .map(CognitiveScope::database_parts)
            .map_or((None, None), |(kind, workspace)| (Some(kind), workspace));
        let rows = sqlx::query(
""",
)
replace_once(
    retrieval,
    """             WHERE memory_fts MATCH ? AND r.owner_agent_id = ?
               AND (r.scope_kind = 'agent_private' OR
                    (r.scope_kind = 'workspace_private' AND r.workspace_sha256 = ?))
               AND r.verification = 'verified' AND r.lifecycle = 'active'
""",
    """             WHERE memory_fts MATCH ? AND r.owner_agent_id = ?
               AND (
                    (? IS NULL AND (
                        r.scope_kind = 'agent_private' OR
                        (r.scope_kind = 'workspace_private' AND r.workspace_sha256 = ?)
                    ))
                    OR (r.scope_kind = ? AND r.workspace_sha256 IS ?)
               )
               AND r.verification = 'verified' AND r.lifecycle = 'active'
""",
)
replace_once(
    retrieval,
    """        .bind(fts_query)
        .bind(self.owner_agent_id.as_str())
        .bind(access.workspace_sha256().map(Sha256Digest::as_str))
        .bind(now)
""",
    """        .bind(fts_query)
        .bind(self.owner_agent_id.as_str())
        .bind(exact_scope_kind)
        .bind(access.workspace_sha256().map(Sha256Digest::as_str))
        .bind(exact_scope_kind)
        .bind(exact_workspace_sha256)
        .bind(now)
""",
)

replace_once(
    retrieval,
    """        access: &CognitiveAccess,
        fts_query: &str,
        now: i64,
    ) -> Result<ChannelOutput<EntitySeed>, CognitiveStoreError> {
        let workspace_scope = access
""",
    """        access: &CognitiveAccess,
        fts_query: &str,
        now: i64,
        exact_scope: Option<&CognitiveScope>,
    ) -> Result<ChannelOutput<EntitySeed>, CognitiveStoreError> {
        let exact_projection_scope = exact_scope.map(CognitiveScope::projection_key);
        let workspace_scope = access
""",
)
replace_once(
    retrieval,
    """             WHERE kg_revision_entity_fts MATCH ?
               AND (p.projection_scope = 'agent_private' OR p.projection_scope = ?)
               AND k.valid_from_unix_seconds <= ?
""",
    """             WHERE kg_revision_entity_fts MATCH ?
               AND (
                    (? IS NULL AND (
                        p.projection_scope = 'agent_private' OR p.projection_scope = ?
                    ))
                    OR p.projection_scope = ?
               )
               AND k.valid_from_unix_seconds <= ?
""",
)
replace_once(
    retrieval,
    """        .bind(fts_query)
        .bind(workspace_scope)
        .bind(now)
""",
    """        .bind(fts_query)
        .bind(exact_projection_scope.as_deref())
        .bind(workspace_scope)
        .bind(exact_projection_scope.as_deref())
        .bind(now)
""",
)

replace_once(
    retrieval,
    """        workspace: Option<&str>,
        now: i64,
    ) -> Result<ChannelOutput<MemoryKey>, CognitiveStoreError> {
        let rows = sqlx::query(
""",
    """        workspace: Option<&str>,
        now: i64,
        exact_scope: Option<&CognitiveScope>,
    ) -> Result<ChannelOutput<MemoryKey>, CognitiveStoreError> {
        let (exact_scope_kind, exact_workspace_sha256) = exact_scope
            .map(CognitiveScope::database_parts)
            .map_or((None, None), |(kind, exact_workspace)| {
                (Some(kind), exact_workspace)
            });
        let rows = sqlx::query(
""",
)
replace_once(
    retrieval,
    """             WHERE r.owner_agent_id = ?
               AND (r.scope_kind = 'agent_private' OR
                    (r.scope_kind = 'workspace_private' AND r.workspace_sha256 = ?))
               AND r.verification = 'verified' AND r.lifecycle = 'active'
""",
    """             WHERE r.owner_agent_id = ?
               AND (
                    (? IS NULL AND (
                        r.scope_kind = 'agent_private' OR
                        (r.scope_kind = 'workspace_private' AND r.workspace_sha256 = ?)
                    ))
                    OR (r.scope_kind = ? AND r.workspace_sha256 IS ?)
               )
               AND r.verification = 'verified' AND r.lifecycle = 'active'
""",
)
replace_once(
    retrieval,
    """        .bind(self.owner_agent_id.as_str())
        .bind(workspace)
        .bind(now)
""",
    """        .bind(self.owner_agent_id.as_str())
        .bind(exact_scope_kind)
        .bind(workspace)
        .bind(exact_scope_kind)
        .bind(exact_workspace_sha256)
        .bind(now)
""",
)

# Preserve the owner exhaustion witness across the local federation reader.
replace_once(
    federation,
    """        let (batch, _observed_frontier) = self.retrieve_with_frontier(access, request).await?;
""",
    """        let (batch, _observed_frontier, _owner_exhausted) =
            self.retrieve_with_frontier(access, request).await?;
""",
)
replace_once(
    federation,
    """    ) -> Result<(FederatedRetrievalBatch, u64), CognitiveStoreError> {
""",
    """    ) -> Result<(FederatedRetrievalBatch, u64, bool), CognitiveStoreError> {
""",
)
replace_once(
    federation,
    """        let (batch, observed_frontier) = self
            .owner
            .retrieve_memory_candidates_for_scope(
""",
    """        let (batch, observed_frontier, owner_exhausted) = self
            .owner
            .retrieve_memory_candidates_for_scope(
""",
)
replace_once(
    federation,
    """            observed_frontier,
        ))
""",
    """            observed_frontier,
            owner_exhausted,
        ))
""",
)

# One malformed peer is a structured peer failure, not a request-wide abort.
replace_once(
    runtime,
    """    for attempt in attempts {
        let (result, captured) = attempt?;
        let result = match result {
""",
    """    for attempt in attempts {
        let (result, captured) = match attempt {
            Ok(attempt) => attempt,
            Err(error) => {
                coverage.failed_peers = coverage.failed_peers.saturating_add(1);
                record_product_setup_failure(&mut coverage.failures, &error);
                continue;
            }
        };
        let result = match result {
""",
)
insert_before_once(
    runtime,
    """fn record_product_failure(failures: &mut FederatedFailureCoverageV2, error: &FederationV2Error) {
""",
    """fn record_product_setup_failure(
    failures: &mut FederatedFailureCoverageV2,
    error: &CognitiveStoreError,
) {
    match error {
        CognitiveStoreError::AccessDenied(_) => {
            failures.authority_rejected = failures.authority_rejected.saturating_add(1);
        }
        CognitiveStoreError::Invalid(_)
        | CognitiveStoreError::Conflict(_)
        | CognitiveStoreError::Corrupt(_) => {
            failures.integrity_rejected = failures.integrity_rejected.saturating_add(1);
        }
        CognitiveStoreError::Unavailable(_) => {
            failures.transport_unavailable = failures.transport_unavailable.saturating_add(1);
        }
    }
}

""",
)

# Derive protocol completeness only from the owner-side exhaustion witness.
replace_once(
    runtime,
    """            let (batch, observed_frontier) = self
                .reader
                .retrieve_with_frontier(self.access, self.request)
""",
    """            let (batch, observed_frontier, owner_exhausted) = self
                .reader
                .retrieve_with_frontier(self.access, self.request)
""",
)
replace_once(
    runtime,
    """            let maximum_results = usize::try_from(query.maximum_results).unwrap_or(usize::MAX);
            let completeness = if items.is_empty() {
                FederatedCompletenessV2::Empty
            } else if items.len() >= maximum_results {
                // Reaching the bounded top-K ceiling does not prove that
                // the owner scope has no additional matching evidence.
                FederatedCompletenessV2::Partial
            } else {
                FederatedCompletenessV2::Complete
            };
""",
    """            let completeness = if owner_exhausted {
                if items.is_empty() {
                    FederatedCompletenessV2::Empty
                } else {
                    FederatedCompletenessV2::Complete
                }
            } else {
                FederatedCompletenessV2::Partial
            };
""",
)

# The authority observation timestamp is sampled after the asynchronous owner
# database observation, so queue/read latency cannot reuse an older timestamp.
replace_once(
    runtime,
    """            let observed_unix_ms = elapsed_logical_ms(self.logical_start_ms, self.started_at);
            let now_unix_seconds = i64::try_from(observed_unix_ms / 1_000)
                .map_err(|_| FederationV2Error::AuthorityRevalidationFailed)?;
            let readers = FederatedMemoryReader::discover(
""",
    """            let discovery_unix_ms =
                elapsed_logical_ms(self.logical_start_ms, self.started_at);
            let now_unix_seconds = i64::try_from(discovery_unix_ms / 1_000)
                .map_err(|_| FederationV2Error::AuthorityRevalidationFailed)?;
            let readers = FederatedMemoryReader::discover(
""",
)
replace_once(
    runtime,
    """            .await
            .map_err(|_| FederationV2Error::AuthorityRevalidationFailed)?;
            let current = readers
""",
    """            .await
            .map_err(|_| FederationV2Error::AuthorityRevalidationFailed)?;
            let observed_unix_ms =
                elapsed_logical_ms(self.logical_start_ms, self.started_at);
            let current = readers
""",
)

# Re-check both capability and memory validity at the last local clock sample
# before provider dispatch.
replace_once(
    extension,
    """                FederatedRevalidationStatus::Current(explanation) => {
                    !final_use_capability_window_current(
                        now,
                        final_use_now,
                        explanation.capability.effective_at_unix_seconds(),
                        explanation.capability.expires_at_unix_seconds(),
                    )
                }
""",
    """                FederatedRevalidationStatus::Current(explanation) => {
                    let memory = &explanation.explanation.memory;
                    !final_use_capability_window_current(
                        now,
                        final_use_now,
                        explanation.capability.effective_at_unix_seconds(),
                        explanation.capability.expires_at_unix_seconds(),
                    ) || !final_use_memory_window_current(
                        final_use_now,
                        memory.valid_from_unix_seconds,
                        memory.valid_to_unix_seconds,
                    )
                }
""",
)
replace_once(
    extension,
    """                    "federated memory capability expired or the clock regressed before provider dispatch",
""",
    """                    "federated memory or its capability expired, or the clock regressed before provider dispatch",
""",
)
insert_before_once(
    extension,
    """#[cfg(test)]
mod tests {
""",
    """fn final_use_memory_window_current(
    final_use_now: i64,
    valid_from: i64,
    valid_to: Option<i64>,
) -> bool {
    valid_from <= final_use_now && valid_to.is_none_or(|expires| final_use_now < expires)
}

""",
)
replace_once(
    extension,
    """    use super::final_use_capability_window_current;
""",
    """    use super::final_use_capability_window_current;
    use super::final_use_memory_window_current;
""",
)
insert_before_once(
    extension,
    """    #[test]
    fn federated_source_binding_changes_when_coverage_changes() {
""",
    """    #[test]
    fn final_use_memory_window_rejects_expiry() {
        assert!(final_use_memory_window_current(100, 99, None));
        assert!(final_use_memory_window_current(100, 100, Some(101)));
        assert!(!final_use_memory_window_current(100, 101, None));
        assert!(!final_use_memory_window_current(101, 99, Some(101)));
    }

""",
)

# Adversarial exact-scope tests: broader agent-private rows cannot crowd a
# workspace capability out, and more than top-K exact rows cannot claim complete.
insert_before_once(
    retrieval_tests,
    """#[tokio::test]
async fn batch_revalidation_is_ordered_and_uses_one_read_snapshot_across_generation_drift() {
""",
    """#[tokio::test]
async fn exact_scope_is_applied_before_ranking_and_top_k() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(61);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let workspace_sha256 = workspace("exact-scope-before-ranking");
    let workspace_scope = CognitiveScope::WorkspacePrivate {
        workspace_sha256: workspace_sha256.clone(),
    };
    let access = CognitiveAccess::workspace_private(owner, workspace_sha256);
    let target_content = "federation exact scope target";
    let target = store
        .remember_with_kg(
            &access,
            &source(workspace_scope.clone(), "exact-scope-target-source", target_content),
            &MemoryDraft {
                stable_key: "exact-scope-target".to_string(),
                revision: revision(workspace_scope.clone(), target_content),
            },
            &KgFactSetDraft::default(),
        )
        .await
        .expect("workspace target")
        .memory;

    for index in 0..MAX_RETRIEVAL_RESULTS {
        let content = format!("federation exact scope competing agent row {index}");
        store
            .remember_with_kg(
                &access,
                &source(
                    CognitiveScope::AgentPrivate,
                    &format!("exact-scope-agent-source-{index}"),
                    &content,
                ),
                &MemoryDraft {
                    stable_key: format!("exact-scope-agent-{index}"),
                    revision: revision(CognitiveScope::AgentPrivate, &content),
                },
                &KgFactSetDraft::default(),
            )
            .await
            .expect("agent competitor");
    }

    let (batch, _frontier, owner_exhausted) = store
        .retrieve_memory_candidates_for_scope(
            &access,
            &workspace_scope,
            &RetrievalRequest::new("federation exact scope", 200),
        )
        .await
        .expect("exact-scope retrieval");
    assert_eq!(batch.candidates.len(), 1);
    assert_eq!(batch.candidates[0].memory.id, target.id);
    assert!(owner_exhausted);
}

#[tokio::test]
async fn exact_scope_requires_an_explicit_exhaustion_witness_for_complete() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(62);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let workspace_sha256 = workspace("exact-scope-exhaustion");
    let workspace_scope = CognitiveScope::WorkspacePrivate {
        workspace_sha256: workspace_sha256.clone(),
    };
    let access = CognitiveAccess::workspace_private(owner, workspace_sha256);

    for index in 0..=MAX_RETRIEVAL_RESULTS {
        let content = format!("federation completion witness row {index}");
        store
            .remember_with_kg(
                &access,
                &source(
                    workspace_scope.clone(),
                    &format!("completion-witness-source-{index}"),
                    &content,
                ),
                &MemoryDraft {
                    stable_key: format!("completion-witness-{index}"),
                    revision: revision(workspace_scope.clone(), &content),
                },
                &KgFactSetDraft::default(),
            )
            .await
            .expect("workspace memory");
    }

    let (batch, _frontier, owner_exhausted) = store
        .retrieve_memory_candidates_for_scope(
            &access,
            &workspace_scope,
            &RetrievalRequest::new("federation completion witness", 200),
        )
        .await
        .expect("exact-scope retrieval");
    assert_eq!(batch.candidates.len(), MAX_RETRIEVAL_RESULTS);
    assert!(!owner_exhausted);
}

""",
)

# Unit regression for peer-local setup failures.
insert_before_once(
    runtime,
    """    #[test]
    fn nonvalid_terminal_attempt_counts_as_failed_product_coverage() {
""",
    """    #[test]
    fn peer_setup_failures_are_structured_by_failure_domain() {
        let mut failures = FederatedFailureCoverageV2::default();
        record_product_setup_failure(
            &mut failures,
            &CognitiveStoreError::Corrupt("bad peer state".to_string()),
        );
        record_product_setup_failure(
            &mut failures,
            &CognitiveStoreError::AccessDenied("revoked".to_string()),
        );
        record_product_setup_failure(
            &mut failures,
            &CognitiveStoreError::Unavailable("offline".to_string()),
        );
        assert_eq!(failures.integrity_rejected, 1);
        assert_eq!(failures.authority_rejected, 1);
        assert_eq!(failures.transport_unavailable, 1);
    }

""",
)

print("memory.federation product semantics patch applied")
