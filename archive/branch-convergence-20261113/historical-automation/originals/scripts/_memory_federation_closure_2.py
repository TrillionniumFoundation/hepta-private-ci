#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def p(rel: str) -> Path:
    return ROOT / rel


def read(rel: str) -> str:
    return p(rel).read_text(encoding="utf-8")


def write(rel: str, value: str) -> None:
    p(rel).write_text(value, encoding="utf-8")


def replace_exact(value: str, old: str, new: str, count: int = 1) -> str:
    actual = value.count(old)
    if actual != count:
        raise RuntimeError(f"expected {count} replacements, found {actual}: {old[:120]!r}")
    return value.replace(old, new, count)


def insert_struct_field_literals(value: str, struct_name: str, before_field: str, field_line: str) -> str:
    marker = f"{struct_name} {{"
    cursor = 0
    changed = 0
    while True:
        start = value.find(marker, cursor)
        if start < 0:
            break
        brace = value.find("{", start)
        depth = 0
        end = None
        for index in range(brace, len(value)):
            if value[index] == "{":
                depth += 1
            elif value[index] == "}":
                depth -= 1
                if depth == 0:
                    end = index
                    break
        if end is None:
            raise RuntimeError(f"unterminated {struct_name} literal")
        block = value[brace:end]
        field_name = field_line.split(":", 1)[0]
        if field_name not in block:
            match = re.search(rf"(?m)^(\s*){re.escape(before_field)}", block)
            if match is None:
                raise RuntimeError(f"{struct_name} literal has no {before_field}")
            insertion = f"{match.group(1)}{field_line}\n"
            absolute = brace + match.start()
            value = value[:absolute] + insertion + value[absolute:]
            end += len(insertion)
            changed += 1
        cursor = end + 1
    if changed == 0:
        raise RuntimeError(f"no {struct_name} literals updated")
    return value


# Exact-scope retrieval publishes omission/limit facts from one SQLite snapshot.
observation_rel = "codex-rs/hepta-memory/src/cognitive_retrieval_observation.rs"
observation = read(observation_rel)
observation = replace_exact(
    observation,
    "    channels: Vec<RetrievalChannelObservation>,\n",
    "    pub(super) channels: Vec<RetrievalChannelObservation>,\n",
)
write(observation_rel, observation)

retrieval_rel = "codex-rs/hepta-memory/src/cognitive_retrieval.rs"
retrieval = read(retrieval_rel)
retrieval = replace_exact(
    retrieval,
    """#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct RetrievalBatch {
    pub query_sha256: Sha256Digest,
    pub candidates: Vec<RetrievalCandidate>,
}
""",
    """#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct RetrievalBatch {
    pub query_sha256: Sha256Digest,
    pub candidates: Vec<RetrievalCandidate>,
}

pub(crate) struct ScopedRetrievalSnapshot {
    pub(crate) batch: RetrievalBatch,
    pub(crate) observed_frontier: u64,
    pub(crate) omitted_items: u32,
    pub(crate) limit_reached: bool,
}
""",
)
method_start = retrieval.index(
    "    /// Retrieves one exact scope and its memory frontier from the same SQLite\n"
)
method_end = retrieval.index("    async fn retrieve_memory_candidates_tx(", method_start)
new_scope_methods = r'''    /// Retrieves one exact scope and its memory frontier from the same SQLite
    /// read snapshot. Compatibility callers receive the historical tuple;
    /// product federation uses the observed variant below.
    pub(crate) async fn retrieve_memory_candidates_for_scope(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        request: &RetrievalRequest,
    ) -> Result<(RetrievalBatch, u64), CognitiveStoreError> {
        let observed = self
            .observe_memory_candidates_for_scope(access, scope, request)
            .await?;
        Ok((observed.batch, observed.observed_frontier))
    }

    /// Produces exact top-K omission and bounded-channel saturation facts from
    /// the same transaction as the selected candidates and source frontier.
    pub(crate) async fn observe_memory_candidates_for_scope(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        request: &RetrievalRequest,
    ) -> Result<ScopedRetrievalSnapshot, CognitiveStoreError> {
        self.authorize(access, scope)?;
        let fts_query = self.validate_retrieval_request(access, request)?;
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let generated = self
            .generate_retrieval_tx(&mut transaction, access, request, &fts_query)
            .await?;
        let limit_reached = generated
            .channels
            .iter()
            .any(|channel| matches!(channel.limit, RetrievalLimitObservation::LimitReached));
        let mut candidates = self
            .resolve_retrieval_tx(
                &mut transaction,
                access,
                request,
                generated.ranked,
                MAX_RETRIEVAL_OWNER_CHANNELS * MAX_RETRIEVAL_CHANNEL_CANDIDATES,
            )
            .await?;
        candidates.retain(|candidate| candidate.memory.scope == *scope);
        let omitted_items =
            u32::try_from(candidates.len().saturating_sub(MAX_RETRIEVAL_RESULTS))
                .unwrap_or(u32::MAX);
        candidates.truncate(MAX_RETRIEVAL_RESULTS);
        let batch = RetrievalBatch {
            query_sha256: Sha256Digest::for_bytes(request.query().as_bytes()),
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
        let observed_frontier = u64::try_from(memory_frontier).map_err(|_| {
            CognitiveStoreError::Corrupt(
                "negative exact-scope memory federation frontier".to_string(),
            )
        })?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(ScopedRetrievalSnapshot {
            batch,
            observed_frontier,
            omitted_items,
            limit_reached,
        })
    }

'''
retrieval = retrieval[:method_start] + new_scope_methods + retrieval[method_end:]
write(retrieval_rel, retrieval)

federation_rel = "codex-rs/hepta-memory/src/cognitive_federation.rs"
federation = read(federation_rel)
method_start = federation.index("    pub(crate) async fn retrieve_with_frontier(")
method_end = federation.index("    pub async fn revalidate(", method_start)
new_reader_methods = r'''    pub(crate) async fn retrieve_with_frontier(
        &self,
        access: &FederationConsumerAccess,
        request: &RetrievalRequest,
    ) -> Result<(FederatedRetrievalBatch, u64), CognitiveStoreError> {
        let (batch, observed_frontier, _, _) =
            self.retrieve_with_observation(access, request).await?;
        Ok((batch, observed_frontier))
    }

    pub(crate) async fn retrieve_with_observation(
        &self,
        access: &FederationConsumerAccess,
        request: &RetrievalRequest,
    ) -> Result<(FederatedRetrievalBatch, u64, u32, bool), CognitiveStoreError> {
        require_authorized(
            self.validate_capability(access, request.now_unix_seconds())
                .await?,
        )?;
        let owner_access = owner_access(&self.capability);
        let observed = self
            .owner
            .observe_memory_candidates_for_scope(
                &owner_access,
                self.capability.scope.owner_scope(),
                request,
            )
            .await?;
        require_authorized(
            self.validate_capability(access, request.now_unix_seconds())
                .await?,
        )?;
        let candidates = observed
            .batch
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
        Ok((
            FederatedRetrievalBatch {
                query_sha256: observed.batch.query_sha256,
                candidates,
            },
            observed.observed_frontier,
            observed.omitted_items,
            observed.limit_reached,
        ))
    }

'''
federation = federation[:method_start] + new_reader_methods + federation[method_end:]
write(federation_rel, federation)

# Product runtime profile and bounded streaming fan-out.
runtime_rel = "codex-rs/hepta-memory/src/cognitive_runtime.rs"
runtime = read(runtime_rel)
runtime = replace_exact(
    runtime,
    "use futures::future::join_all;\n",
    "use futures::stream;\nuse futures::StreamExt;\n",
)
runtime = replace_exact(
    runtime,
    """const PRODUCT_FEDERATION_TOTAL_BUDGET: Duration = Duration::from_secs(2);
const MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS: usize = 128;
const PRODUCT_FEDERATION_PURPOSE: &[u8] = b"hepta.cognitive.federated-recall.product.v2";
""",
    """const DEFAULT_PRODUCT_FEDERATION_TOTAL_BUDGET: Duration = Duration::from_secs(2);
const MAX_PRODUCT_FEDERATION_TOTAL_BUDGET: Duration = Duration::from_secs(10);
const MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS: usize = 128;
const MAX_PRODUCT_FEDERATION_CONCURRENCY: usize = 32;
const PRODUCT_FEDERATION_PURPOSE: &[u8] = b"hepta.cognitive.federated-recall.product.v2";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FederationRuntimeProfile {
    total_budget: Duration,
    max_owner_candidates: usize,
    max_admitted_peers: usize,
    discovery_concurrency: usize,
    attempt_concurrency: usize,
    revalidation_concurrency: usize,
}

impl Default for FederationRuntimeProfile {
    fn default() -> Self {
        Self {
            total_budget: DEFAULT_PRODUCT_FEDERATION_TOTAL_BUDGET,
            max_owner_candidates: MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS,
            max_admitted_peers: MAX_FEDERATION_SOURCES_PER_AGENT,
            discovery_concurrency: 16,
            attempt_concurrency: 16,
            revalidation_concurrency: 8,
        }
    }
}

impl FederationRuntimeProfile {
    pub fn new(
        total_budget: Duration,
        max_owner_candidates: usize,
        max_admitted_peers: usize,
        discovery_concurrency: usize,
        attempt_concurrency: usize,
        revalidation_concurrency: usize,
    ) -> Result<Self, CognitiveStoreError> {
        let profile = Self {
            total_budget,
            max_owner_candidates,
            max_admitted_peers,
            discovery_concurrency,
            attempt_concurrency,
            revalidation_concurrency,
        };
        profile.validate()?;
        Ok(profile)
    }

    #[must_use]
    pub fn for_host_capacity(max_concurrent_turns: u16, memory_limit_mib: u32) -> Self {
        let turn_width =
            usize::from(max_concurrent_turns).clamp(1, MAX_PRODUCT_FEDERATION_CONCURRENCY);
        let memory_width = usize::try_from((memory_limit_mib / 256).max(1))
            .unwrap_or(MAX_PRODUCT_FEDERATION_CONCURRENCY)
            .min(MAX_PRODUCT_FEDERATION_CONCURRENCY);
        let width = turn_width.min(memory_width).max(1);
        Self {
            discovery_concurrency: width.saturating_mul(2).min(16).max(1),
            attempt_concurrency: width.min(MAX_FEDERATION_SOURCES_PER_AGENT).max(1),
            revalidation_concurrency: width.min(MAX_FEDERATION_SOURCES_PER_AGENT).max(1),
            ..Self::default()
        }
    }

    fn validate(&self) -> Result<(), CognitiveStoreError> {
        if self.total_budget.is_zero()
            || self.total_budget > MAX_PRODUCT_FEDERATION_TOTAL_BUDGET
            || !(1..=MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS).contains(&self.max_owner_candidates)
            || !(1..=MAX_FEDERATION_SOURCES_PER_AGENT).contains(&self.max_admitted_peers)
            || !(1..=MAX_PRODUCT_FEDERATION_CONCURRENCY).contains(&self.discovery_concurrency)
            || !(1..=MAX_PRODUCT_FEDERATION_CONCURRENCY).contains(&self.attempt_concurrency)
            || !(1..=MAX_PRODUCT_FEDERATION_CONCURRENCY).contains(&self.revalidation_concurrency)
        {
            return Err(CognitiveStoreError::Invalid(
                "memory federation runtime profile exceeds architecture bounds".to_string(),
            ));
        }
        Ok(())
    }

    pub const fn total_budget(self) -> Duration {
        self.total_budget
    }

    pub const fn max_owner_candidates(self) -> usize {
        self.max_owner_candidates
    }

    pub const fn max_admitted_peers(self) -> usize {
        self.max_admitted_peers
    }

    pub const fn discovery_concurrency(self) -> usize {
        self.discovery_concurrency
    }

    pub const fn attempt_concurrency(self) -> usize {
        self.attempt_concurrency
    }

    pub const fn revalidation_concurrency(self) -> usize {
        self.revalidation_concurrency
    }
}
""",
)
runtime = replace_exact(
    runtime,
    "        omitted_owner_candidates: u32,\n",
    "        omitted_owner_candidates: u32,\n        profile: FederationRuntimeProfile,\n",
)
with_start = runtime.index("    pub fn with_federation_sources(")
with_end = runtime.index("    /// Legacy accessor retained", with_start)
new_with_sources = r'''    pub fn with_federation_sources(
        self,
        consumer_agent_id: AgentId,
        owner_layouts: Vec<HeptaAgentLayout>,
    ) -> Self {
        self.with_federation_sources_profile(
            consumer_agent_id,
            owner_layouts,
            FederationRuntimeProfile::default(),
        )
    }

    pub fn with_federation_sources_profile(
        self,
        consumer_agent_id: AgentId,
        mut owner_layouts: Vec<HeptaAgentLayout>,
        profile: FederationRuntimeProfile,
    ) -> Self {
        profile
            .validate()
            .expect("FederationRuntimeProfile constructors preserve invariants");
        owner_layouts.sort_by(|left, right| left.agent_id().cmp(right.agent_id()));
        owner_layouts.dedup_by(|left, right| left.agent_id() == right.agent_id());
        let omitted_owner_candidates = u32::try_from(
            owner_layouts
                .len()
                .saturating_sub(profile.max_owner_candidates()),
        )
        .unwrap_or(u32::MAX);
        owner_layouts.truncate(profile.max_owner_candidates());
        if owner_layouts.is_empty() {
            return self;
        }
        match self {
            Self::Available(store)
            | Self::AvailableFederated { store, .. }
            | Self::AvailableFederatedV2 { store, .. } => Self::AvailableFederatedV2 {
                store,
                consumer_agent_id,
                owner_layouts: Arc::new(owner_layouts),
                omitted_owner_candidates,
                profile,
            },
            Self::Absent | Self::Unavailable(_) => self,
        }
    }

'''
runtime = runtime[:with_start] + new_with_sources + runtime[with_end:]

old_product_call = """                omitted_owner_candidates,
                ..
            } => {
                retrieve_federated_product(
                    consumer_agent_id,
                    owner_layouts.as_slice(),
                    *omitted_owner_candidates,
                    access,
                    request,
                )
"""
new_product_call = """                omitted_owner_candidates,
                profile,
                ..
            } => {
                retrieve_federated_product(
                    consumer_agent_id,
                    owner_layouts.as_slice(),
                    *omitted_owner_candidates,
                    *profile,
                    access,
                    request,
                )
"""
runtime = replace_exact(runtime, old_product_call, new_product_call, 2)

runtime = replace_exact(
    runtime,
    """            Self::AvailableFederatedV2 {
                consumer_agent_id,
                owner_layouts,
                ..
            } => {
                revalidate_federated_product_batch(
                    consumer_agent_id,
                    owner_layouts.as_slice(),
                    access,
                    bindings,
                    now_unix_seconds,
                )
""",
    """            Self::AvailableFederatedV2 {
                consumer_agent_id,
                owner_layouts,
                profile,
                ..
            } => {
                revalidate_federated_product_batch(
                    consumer_agent_id,
                    owner_layouts.as_slice(),
                    *profile,
                    access,
                    bindings,
                    now_unix_seconds,
                )
""",
)
runtime = replace_exact(
    runtime,
    """            Self::AvailableFederatedV2 {
                consumer_agent_id,
                owner_layouts,
                ..
            } => {
                revalidate_federated_product(
                    consumer_agent_id,
                    owner_layouts.as_slice(),
                    access,
                    binding,
                    now_unix_seconds,
                )
""",
    """            Self::AvailableFederatedV2 {
                consumer_agent_id,
                owner_layouts,
                profile,
                ..
            } => {
                revalidate_federated_product(
                    consumer_agent_id,
                    owner_layouts.as_slice(),
                    *profile,
                    access,
                    binding,
                    now_unix_seconds,
                )
""",
)

retrieve_start = runtime.index("async fn retrieve_federated_product(")
merge_start = runtime.index("\nfn merge_product_coverage(", retrieve_start)
new_retrieve = r'''async fn retrieve_federated_product(
    consumer_agent_id: &AgentId,
    owner_layouts: &[HeptaAgentLayout],
    omitted_owner_candidates: u32,
    profile: FederationRuntimeProfile,
    access: &FederationConsumerAccess,
    request: &RetrievalRequest,
) -> Result<(FederatedRetrievalBatch, FederatedCoverageV2), CognitiveStoreError> {
    if access.agent_id() != consumer_agent_id {
        return Err(CognitiveStoreError::AccessDenied(
            "memory federation caller does not match the product consumer".to_string(),
        ));
    }

    let logical_start_ms = seconds_to_ms(request.now_unix_seconds())?;
    let started_at = Instant::now();
    let global_deadline_ms = logical_start_ms
        .checked_add(u64::try_from(profile.total_budget().as_millis()).unwrap_or(u64::MAX))
        .ok_or_else(|| CognitiveStoreError::Invalid("federation deadline overflow".to_string()))?;

    let discovery = async {
        let outcomes = stream::iter(owner_layouts.iter().cloned())
            .map(|owner_layout| async move {
                let outcome = FederatedMemoryReader::discover(
                    &owner_layout,
                    consumer_agent_id,
                    request.now_unix_seconds(),
                )
                .await;
                (owner_layout, outcome)
            })
            .buffer_unordered(profile.discovery_concurrency())
            .collect::<Vec<_>>()
            .await;
        let mut readers = Vec::new();
        let mut discovery_failures = 0usize;
        for (owner_layout, outcome) in outcomes {
            match outcome {
                Ok(discovered) => {
                    for reader in discovered {
                        if reader.capability().scope().consumer_workspace_sha256()
                            != access.workspace_sha256()
                        {
                            continue;
                        }
                        readers.push((owner_layout.clone(), reader));
                    }
                }
                Err(_) => {
                    discovery_failures = discovery_failures.saturating_add(1);
                }
            }
        }
        (readers, discovery_failures)
    };
    let (mut readers, discovery_failures) =
        tokio::time::timeout(profile.total_budget(), discovery)
            .await
            .map_err(|_| {
                CognitiveStoreError::Unavailable(
                    "memory federation discovery timed out".to_string(),
                )
            })?;
    readers.sort_by(|(_, left), (_, right)| {
        left.capability()
            .owner_agent_id()
            .cmp(right.capability().owner_agent_id())
            .then_with(|| left.capability().id().cmp(right.capability().id()))
    });
    readers.dedup_by(|(_, left), (_, right)| left.capability().id() == right.capability().id());
    let observable_peer_slots = readers.len().saturating_add(discovery_failures);
    let admitted_peer_limit = profile.max_admitted_peers();
    let truncated_peers = observable_peer_slots.saturating_sub(admitted_peer_limit);
    readers.truncate(admitted_peer_limit);

    let discovery_failure_slots =
        discovery_failures.min(admitted_peer_limit.saturating_sub(readers.len()));
    let requested_peer_slots = readers.len().saturating_add(discovery_failure_slots);
    let query_sha256 = Sha256Digest::for_bytes(request.query().as_bytes());
    let mut coverage = FederatedCoverageV2 {
        requested_peers: u32::try_from(requested_peer_slots).unwrap_or(u32::MAX),
        completed_peers: 0,
        failed_peers: u32::try_from(discovery_failure_slots).unwrap_or(u32::MAX),
        truncated_peers: u32::try_from(truncated_peers).unwrap_or(u32::MAX),
        omitted_peer_candidates: omitted_owner_candidates,
        truncated_items: 0,
        failures: FederatedFailureCoverageV2 {
            discovery_unavailable: u32::try_from(discovery_failure_slots).unwrap_or(u32::MAX),
            ..FederatedFailureCoverageV2::default()
        },
    };
    let mut candidates = Vec::new();

    let attempts = stream::iter(readers.iter())
        .map(|(owner_layout, reader)| async move {
            if elapsed_logical_ms(logical_start_ms, started_at) >= global_deadline_ms {
                return Ok((
                    Err(FederationV2Error::DeadlineExpired),
                    Arc::new(Mutex::new(None)),
                ));
            }
            let (query, lease) = build_product_query_and_lease(
                reader,
                access,
                request,
                logical_start_ms,
                global_deadline_ms,
            )?;
            let captured = Arc::new(Mutex::new(None));
            let transport = ProductReaderTransport {
                reader,
                access,
                request,
                captured: Arc::clone(&captured),
            };
            let authority = ProductReaderAuthority {
                owner_layout,
                consumer_agent_id,
                expected_capability: reader.capability(),
                logical_start_ms,
                started_at,
            };
            let control = ProductAttemptControl {
                logical_start_ms,
                started_at,
            };
            let result = execute_once(
                &transport,
                &authority,
                &control,
                logical_start_ms,
                query,
                &lease,
            )
            .await;
            Ok::<_, CognitiveStoreError>((result, captured))
        })
        .buffer_unordered(profile.attempt_concurrency())
        .collect::<Vec<_>>()
        .await;

    for attempt in attempts {
        let (result, captured) = attempt?;
        let result = match result {
            Ok(result) => result,
            Err(error) => {
                coverage.failed_peers = coverage.failed_peers.saturating_add(1);
                record_product_failure(&mut coverage.failures, &error);
                continue;
            }
        };
        merge_product_coverage(&mut coverage, &result.coverage, result.validity);
        if result.validity != FederatedValidityV2::Valid {
            continue;
        }
        let selected = result
            .items
            .iter()
            .map(|item| {
                (
                    item.source_owner_id.as_str().to_string(),
                    item.record_id.as_str().to_string(),
                    item.record_revision.get(),
                )
            })
            .collect::<BTreeSet<_>>();
        let mut guard = captured.lock().map_err(|_| {
            CognitiveStoreError::Unavailable("memory federation capture lock poisoned".to_string())
        })?;
        if let Some(batch) = guard.take() {
            candidates.extend(batch.candidates.into_iter().filter(|candidate| {
                selected.contains(&(
                    candidate.source_agent_id.as_str().to_string(),
                    candidate.candidate.memory.id.memory_id.as_str().to_string(),
                    candidate.candidate.memory.id.revision,
                ))
            }));
        }
    }

    candidates.sort_by(|left, right| {
        right
            .candidate
            .reciprocal_rank_score
            .cmp(&left.candidate.reciprocal_rank_score)
            .then_with(|| left.source_agent_id.cmp(&right.source_agent_id))
            .then_with(|| {
                left.candidate
                    .memory
                    .id
                    .memory_id
                    .cmp(&right.candidate.memory.id.memory_id)
            })
            .then_with(|| {
                left.candidate
                    .memory
                    .id
                    .revision
                    .cmp(&right.candidate.memory.id.revision)
            })
    });
    candidates.dedup_by(|left, right| {
        left.source_agent_id == right.source_agent_id
            && left.candidate.memory.id == right.candidate.memory.id
    });
    let before_truncation = candidates.len();
    candidates.truncate(MAX_RETRIEVAL_RESULTS);
    coverage.truncated_items = coverage.truncated_items.saturating_add(
        u32::try_from(before_truncation.saturating_sub(candidates.len())).unwrap_or(u32::MAX),
    );

    Ok((
        FederatedRetrievalBatch {
            query_sha256,
            candidates,
        },
        coverage,
    ))
}
'''
runtime = runtime[:retrieve_start] + new_retrieve + runtime[merge_start:]

reval_start = runtime.index("async fn revalidate_federated_product(")
transport_start = runtime.index("\nstruct ProductReaderTransport", reval_start)
new_revalidation = r'''async fn revalidate_federated_product(
    consumer_agent_id: &AgentId,
    owner_layouts: &[HeptaAgentLayout],
    profile: FederationRuntimeProfile,
    access: &FederationConsumerAccess,
    binding: &FederatedMemoryRevalidationBinding,
    now_unix_seconds: i64,
) -> Result<FederatedRevalidationStatus, CognitiveStoreError> {
    revalidate_federated_product_batch(
        consumer_agent_id,
        owner_layouts,
        profile,
        access,
        std::slice::from_ref(binding),
        now_unix_seconds,
    )
    .await?
    .pop()
    .ok_or_else(|| {
        CognitiveStoreError::Corrupt(
            "single federated product revalidation returned no status".to_string(),
        )
    })
}

async fn revalidate_federated_product_batch(
    consumer_agent_id: &AgentId,
    owner_layouts: &[HeptaAgentLayout],
    profile: FederationRuntimeProfile,
    access: &FederationConsumerAccess,
    bindings: &[FederatedMemoryRevalidationBinding],
    now_unix_seconds: i64,
) -> Result<Vec<FederatedRevalidationStatus>, CognitiveStoreError> {
    if bindings.is_empty() {
        return Ok(Vec::new());
    }
    if access.agent_id() != consumer_agent_id {
        return Ok(vec![
            FederatedRevalidationStatus::Stale(
                FederationRevalidationDrift::Consumer
            );
            bindings.len()
        ]);
    }
    let revalidation = async {
        let mut statuses = vec![None; bindings.len()];
        let relevant_layouts = owner_layouts
            .iter()
            .filter(|owner_layout| {
                bindings
                    .iter()
                    .any(|binding| binding.source_agent_id == *owner_layout.agent_id())
            })
            .cloned()
            .collect::<Vec<_>>();

        let discoveries = stream::iter(relevant_layouts)
            .map(|owner_layout| async move {
                let readers = FederatedMemoryReader::discover(
                    &owner_layout,
                    consumer_agent_id,
                    now_unix_seconds,
                )
                .await?;
                Ok::<_, CognitiveStoreError>((owner_layout, readers))
            })
            .buffer_unordered(profile.revalidation_concurrency())
            .collect::<Vec<_>>()
            .await;

        let mut jobs = Vec::new();
        for discovery in discoveries {
            let (owner_layout, readers) = discovery?;
            let owner_indices = bindings
                .iter()
                .enumerate()
                .filter_map(|(index, binding)| {
                    (binding.source_agent_id == *owner_layout.agent_id()).then_some(index)
                })
                .collect::<Vec<_>>();
            let capability_ids = owner_indices
                .iter()
                .map(|index| bindings[*index].capability.id().as_str())
                .collect::<BTreeSet<_>>();
            for capability_id in capability_ids {
                let group_indices = owner_indices
                    .iter()
                    .copied()
                    .filter(|index| bindings[*index].capability.id().as_str() == capability_id)
                    .collect::<Vec<_>>();
                let Some(reader) = readers
                    .iter()
                    .find(|reader| reader.capability().id().as_str() == capability_id)
                    .cloned()
                else {
                    for index in group_indices {
                        statuses[index] = Some(FederatedRevalidationStatus::Stale(
                            FederationRevalidationDrift::CapabilityMissing,
                        ));
                    }
                    continue;
                };
                let group_bindings = group_indices
                    .iter()
                    .map(|index| bindings[*index].clone())
                    .collect::<Vec<_>>();
                jobs.push((reader, group_indices, group_bindings));
            }
        }

        let results = stream::iter(jobs)
            .map(|(reader, group_indices, group_bindings)| async move {
                let group_statuses = reader
                    .revalidate_many(access, &group_bindings, now_unix_seconds)
                    .await?;
                Ok::<_, CognitiveStoreError>((group_indices, group_statuses))
            })
            .buffer_unordered(profile.revalidation_concurrency())
            .collect::<Vec<_>>()
            .await;

        // Retrieval may degrade per peer before a payload exists. Final-use
        // revalidation is deliberately all-or-nothing for the exact approved
        // payload: an unavailable owner aborts rather than changing bytes.
        for result in results {
            let (group_indices, group_statuses) = result?;
            if group_statuses.len() != group_indices.len() {
                return Err(CognitiveStoreError::Corrupt(
                    "product federation batch revalidation changed result cardinality"
                        .to_string(),
                ));
            }
            for (index, status) in group_indices.into_iter().zip(group_statuses) {
                statuses[index] = Some(status);
            }
        }

        Ok(statuses
            .into_iter()
            .map(|status| {
                status.unwrap_or(FederatedRevalidationStatus::Stale(
                    FederationRevalidationDrift::CapabilityMissing,
                ))
            })
            .collect::<Vec<_>>())
    };

    tokio::time::timeout(profile.total_budget(), revalidation)
        .await
        .map_err(|_| {
            CognitiveStoreError::Unavailable(
                "memory federation final batch revalidation timed out".to_string(),
            )
        })?
}
'''
runtime = runtime[:reval_start] + new_revalidation + runtime[transport_start:]

runtime = replace_exact(
    runtime,
    """            let (batch, observed_frontier) = self
                .reader
                .retrieve_with_frontier(self.access, self.request)
""",
    """            let (batch, observed_frontier, omitted_items, limit_reached) = self
                .reader
                .retrieve_with_observation(self.access, self.request)
""",
)
runtime = replace_exact(
    runtime,
    """            let completeness = if items.is_empty() {
                FederatedCompletenessV2::Empty
            } else {
                FederatedCompletenessV2::Complete
            };
""",
    """            let completeness = if omitted_items != 0 || limit_reached {
                FederatedCompletenessV2::Partial
            } else if items.is_empty() {
                FederatedCompletenessV2::Empty
            } else {
                FederatedCompletenessV2::Complete
            };
""",
)
runtime = insert_struct_field_literals(
    runtime,
    "RemoteFederatedResponseV2",
    "completeness:",
    "omitted_items,",
)
write(runtime_rel, runtime)

memory_lib_rel = "codex-rs/hepta-memory/src/lib.rs"
memory_lib = read(memory_lib_rel)
memory_lib = replace_exact(
    memory_lib,
    "pub use cognitive_runtime::CognitiveRuntime;\n",
    "pub use cognitive_runtime::CognitiveRuntime;\npub use cognitive_runtime::FederationRuntimeProfile;\n",
)
write(memory_lib_rel, memory_lib)

# Agentd derives the immutable product profile from registered Fleet resources.
agentd_rel = "codex-rs/hepta-agentd/src/runtime.rs"
agentd = read(agentd_rel)
agentd = replace_exact(
    agentd,
    "use codex_hepta_memory::CognitiveRuntime;\n",
    "use codex_hepta_memory::CognitiveRuntime;\nuse codex_hepta_memory::FederationRuntimeProfile;\n",
)
agentd = replace_exact(
    agentd,
    """    let runtime = runtime.with_federation_sources(state.identity().agent_id.clone(), owner_layouts);
""",
    """    let profile = FederationRuntimeProfile::for_host_capacity(
        state.identity().resources.max_concurrent_turns,
        state.identity().resources.memory_limit_mib,
    );
    let runtime = runtime.with_federation_sources_profile(
        state.identity().agent_id.clone(),
        owner_layouts,
        profile,
    );
""",
)
write(agentd_rel, agentd)

print("stage 2 applied")
