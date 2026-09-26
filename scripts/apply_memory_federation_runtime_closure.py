#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace(path: str, old: str, new: str, expected: int = 1) -> None:
    text = read(path)
    found = text.count(old)
    if found != expected:
        raise RuntimeError(f"{path}: expected {expected} exact matches, found {found}: {old[:120]!r}")
    write(path, text.replace(old, new))


def replace_re(path: str, pattern: str, replacement: str, expected: int = 1) -> None:
    text = read(path)
    updated, count = re.subn(pattern, replacement, text, flags=re.MULTILINE | re.DOTALL)
    if count != expected:
        raise RuntimeError(f"{path}: expected {expected} regex matches, found {count}: {pattern[:120]!r}")
    write(path, updated)


def append_once(path: str, marker: str, content: str) -> None:
    text = read(path)
    if marker in text:
        return
    if not text.endswith("\n"):
        text += "\n"
    write(path, text + "\n" + content.strip() + "\n")


runtime = "codex-rs/hepta-memory/src/cognitive_runtime.rs"
replace(
    runtime,
    "use futures::future::join_all;\n",
    "use futures::StreamExt;\nuse futures::stream;\n",
)
replace(
    runtime,
    "const PRODUCT_FEDERATION_TOTAL_BUDGET: Duration = Duration::from_secs(2);\n"
    "const MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS: usize = 128;\n"
    "const PRODUCT_FEDERATION_PURPOSE: &[u8] = b\"hepta.cognitive.federated-recall.product.v2\";\n",
    r'''pub const MAX_PRODUCT_FEDERATION_TOTAL_BUDGET: Duration = Duration::from_secs(30);
pub const MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS: usize = 128;
pub const MAX_PRODUCT_FEDERATION_DISCOVERY_CONCURRENCY: usize = 32;
pub const MAX_PRODUCT_FEDERATION_ATTEMPT_CONCURRENCY: usize = 16;
pub const MAX_PRODUCT_FEDERATION_REVALIDATION_CONCURRENCY: usize = 16;
const PRODUCT_FEDERATION_PURPOSE: &[u8] = b"hepta.cognitive.federated-recall.product.v2";

/// Target-host limits for one product federation composition.
///
/// Every value is validated against an architecture ceiling before it can be
/// installed. A host may reduce limits without changing the canonical V2
/// contract, but it cannot widen the product beyond reviewed bounds.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct MemoryFederationHostProfile {
    total_budget: Duration,
    max_owner_candidates: usize,
    max_admitted_peers: usize,
    discovery_concurrency: usize,
    attempt_concurrency: usize,
    revalidation_concurrency: usize,
}

impl MemoryFederationHostProfile {
    pub fn try_new(
        total_budget: Duration,
        max_owner_candidates: usize,
        max_admitted_peers: usize,
        discovery_concurrency: usize,
        attempt_concurrency: usize,
        revalidation_concurrency: usize,
    ) -> Result<Self, CognitiveStoreError> {
        if total_budget.is_zero() || total_budget > MAX_PRODUCT_FEDERATION_TOTAL_BUDGET {
            return Err(CognitiveStoreError::Invalid(format!(
                "memory federation total budget must be 1ms..={}ms",
                MAX_PRODUCT_FEDERATION_TOTAL_BUDGET.as_millis()
            )));
        }
        if !(1..=MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS).contains(&max_owner_candidates) {
            return Err(CognitiveStoreError::Invalid(format!(
                "memory federation owner candidates must be 1..={MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS}"
            )));
        }
        if !(1..=MAX_FEDERATION_SOURCES_PER_AGENT).contains(&max_admitted_peers) {
            return Err(CognitiveStoreError::Invalid(format!(
                "memory federation admitted peers must be 1..={MAX_FEDERATION_SOURCES_PER_AGENT}"
            )));
        }
        if !(1..=MAX_PRODUCT_FEDERATION_DISCOVERY_CONCURRENCY)
            .contains(&discovery_concurrency)
            || discovery_concurrency > max_owner_candidates
        {
            return Err(CognitiveStoreError::Invalid(format!(
                "memory federation discovery concurrency must be 1..={} and no larger than owner candidates",
                MAX_PRODUCT_FEDERATION_DISCOVERY_CONCURRENCY
            )));
        }
        if !(1..=MAX_PRODUCT_FEDERATION_ATTEMPT_CONCURRENCY).contains(&attempt_concurrency)
            || attempt_concurrency > max_admitted_peers
        {
            return Err(CognitiveStoreError::Invalid(format!(
                "memory federation attempt concurrency must be 1..={} and no larger than admitted peers",
                MAX_PRODUCT_FEDERATION_ATTEMPT_CONCURRENCY
            )));
        }
        if !(1..=MAX_PRODUCT_FEDERATION_REVALIDATION_CONCURRENCY)
            .contains(&revalidation_concurrency)
            || revalidation_concurrency > max_admitted_peers
        {
            return Err(CognitiveStoreError::Invalid(format!(
                "memory federation revalidation concurrency must be 1..={} and no larger than admitted peers",
                MAX_PRODUCT_FEDERATION_REVALIDATION_CONCURRENCY
            )));
        }
        Ok(Self {
            total_budget,
            max_owner_candidates,
            max_admitted_peers,
            discovery_concurrency,
            attempt_concurrency,
            revalidation_concurrency,
        })
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

impl Default for MemoryFederationHostProfile {
    fn default() -> Self {
        Self {
            total_budget: Duration::from_secs(2),
            max_owner_candidates: MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS,
            max_admitted_peers: MAX_FEDERATION_SOURCES_PER_AGENT,
            discovery_concurrency: 8,
            attempt_concurrency: MAX_FEDERATION_SOURCES_PER_AGENT,
            revalidation_concurrency: 8,
        }
    }
}
''',
)
replace(
    runtime,
    "        owner_layouts: Arc<Vec<HeptaAgentLayout>>,\n"
    "        omitted_owner_candidates: u32,\n",
    "        owner_layouts: Arc<Vec<HeptaAgentLayout>>,\n"
    "        omitted_owner_candidates: u32,\n"
    "        host_profile: MemoryFederationHostProfile,\n",
)

replace_re(
    runtime,
    r'''    pub fn with_federation_sources\(
        self,
        consumer_agent_id: AgentId,
        mut owner_layouts: Vec<HeptaAgentLayout>,
    \) -> Self \{
.*?
    \}

    /// Legacy accessor retained for compatibility-only tests and callers\.''',
    r'''    pub fn with_federation_sources(
        self,
        consumer_agent_id: AgentId,
        owner_layouts: Vec<HeptaAgentLayout>,
    ) -> Self {
        self.with_federation_sources_profile(
            consumer_agent_id,
            owner_layouts,
            MemoryFederationHostProfile::default(),
        )
    }

    /// Product composition with an explicitly validated target-host profile.
    pub fn with_federation_sources_profile(
        self,
        consumer_agent_id: AgentId,
        mut owner_layouts: Vec<HeptaAgentLayout>,
        host_profile: MemoryFederationHostProfile,
    ) -> Self {
        owner_layouts.sort_by(|left, right| left.agent_id().cmp(right.agent_id()));
        owner_layouts.dedup_by(|left, right| left.agent_id() == right.agent_id());
        let omitted_owner_candidates = u32::try_from(
            owner_layouts
                .len()
                .saturating_sub(host_profile.max_owner_candidates()),
        )
        .unwrap_or(u32::MAX);
        owner_layouts.truncate(host_profile.max_owner_candidates());
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
                host_profile,
            },
            Self::Absent | Self::Unavailable(_) => self,
        }
    }

    /// Legacy accessor retained for compatibility-only tests and callers.''',
)

replace(
    runtime,
    "                omitted_owner_candidates,\n"
    "                ..\n"
    "            } => {\n"
    "                retrieve_federated_product(\n"
    "                    consumer_agent_id,\n"
    "                    owner_layouts.as_slice(),\n"
    "                    *omitted_owner_candidates,\n",
    "                omitted_owner_candidates,\n"
    "                host_profile,\n"
    "                ..\n"
    "            } => {\n"
    "                retrieve_federated_product(\n"
    "                    consumer_agent_id,\n"
    "                    owner_layouts.as_slice(),\n"
    "                    *omitted_owner_candidates,\n"
    "                    host_profile,\n",
    expected=2,
)
replace(
    runtime,
    "            Self::AvailableFederatedV2 {\n"
    "                consumer_agent_id,\n"
    "                owner_layouts,\n"
    "                ..\n"
    "            } => {\n"
    "                revalidate_federated_product_batch(\n"
    "                    consumer_agent_id,\n"
    "                    owner_layouts.as_slice(),\n",
    "            Self::AvailableFederatedV2 {\n"
    "                consumer_agent_id,\n"
    "                owner_layouts,\n"
    "                host_profile,\n"
    "                ..\n"
    "            } => {\n"
    "                revalidate_federated_product_batch(\n"
    "                    consumer_agent_id,\n"
    "                    owner_layouts.as_slice(),\n"
    "                    host_profile,\n",
)
replace(
    runtime,
    "            Self::AvailableFederatedV2 {\n"
    "                consumer_agent_id,\n"
    "                owner_layouts,\n"
    "                ..\n"
    "            } => {\n"
    "                revalidate_federated_product(\n"
    "                    consumer_agent_id,\n"
    "                    owner_layouts.as_slice(),\n",
    "            Self::AvailableFederatedV2 {\n"
    "                consumer_agent_id,\n"
    "                owner_layouts,\n"
    "                host_profile,\n"
    "                ..\n"
    "            } => {\n"
    "                revalidate_federated_product(\n"
    "                    consumer_agent_id,\n"
    "                    owner_layouts.as_slice(),\n"
    "                    host_profile,\n",
)

new_retrieve = r'''async fn retrieve_federated_product(
    consumer_agent_id: &AgentId,
    owner_layouts: &[HeptaAgentLayout],
    omitted_owner_candidates: u32,
    host_profile: &MemoryFederationHostProfile,
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
        .checked_add(
            u64::try_from(host_profile.total_budget().as_millis()).unwrap_or(u64::MAX),
        )
        .ok_or_else(|| CognitiveStoreError::Invalid("federation deadline overflow".to_string()))?;

    let discovery = stream::iter(owner_layouts.iter().cloned())
        .map(|owner_layout| async move {
            let outcome = FederatedMemoryReader::discover(
                &owner_layout,
                consumer_agent_id,
                request.now_unix_seconds(),
            )
            .await;
            (owner_layout, outcome)
        })
        .buffer_unordered(host_profile.discovery_concurrency())
        .collect::<Vec<_>>();
    let outcomes = tokio::time::timeout(host_profile.total_budget(), discovery)
        .await
        .map_err(|_| {
            CognitiveStoreError::Unavailable("memory federation discovery timed out".to_string())
        })?;
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

    readers.sort_by(|(_, left), (_, right)| {
        left.capability()
            .owner_agent_id()
            .cmp(right.capability().owner_agent_id())
            .then_with(|| left.capability().id().cmp(right.capability().id()))
    });
    readers.dedup_by(|(_, left), (_, right)| left.capability().id() == right.capability().id());
    let observable_peer_slots = readers.len().saturating_add(discovery_failures);
    let truncated_peers =
        observable_peer_slots.saturating_sub(host_profile.max_admitted_peers());
    readers.truncate(host_profile.max_admitted_peers());

    let discovery_failure_slots = discovery_failures.min(
        host_profile
            .max_admitted_peers()
            .saturating_sub(readers.len()),
    );
    let requested_peer_slots = readers.len().saturating_add(discovery_failure_slots);
    let query_sha256 = Sha256Digest::for_bytes(request.query().as_bytes());
    let mut coverage = FederatedCoverageV2 {
        requested_peers: u32::try_from(requested_peer_slots).unwrap_or(u32::MAX),
        completed_peers: 0,
        failed_peers: u32::try_from(discovery_failure_slots).unwrap_or(u32::MAX),
        partial_peers: 0,
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
        .buffer_unordered(host_profile.attempt_concurrency())
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
replace_re(
    runtime,
    r'''async fn retrieve_federated_product\(.*?\n\}\n\nfn merge_product_coverage\(''',
    new_retrieve + "fn merge_product_coverage(",
)

replace(
    runtime,
    "    aggregate.truncated_peers = aggregate\n",
    "    aggregate.partial_peers = aggregate\n"
    "        .partial_peers\n"
    "        .saturating_add(attempt.partial_peers);\n"
    "    aggregate.truncated_peers = aggregate\n",
)

new_revalidation = r'''async fn revalidate_federated_product(
    consumer_agent_id: &AgentId,
    owner_layouts: &[HeptaAgentLayout],
    host_profile: &MemoryFederationHostProfile,
    access: &FederationConsumerAccess,
    binding: &FederatedMemoryRevalidationBinding,
    now_unix_seconds: i64,
) -> Result<FederatedRevalidationStatus, CognitiveStoreError> {
    revalidate_federated_product_batch(
        consumer_agent_id,
        owner_layouts,
        host_profile,
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
    host_profile: &MemoryFederationHostProfile,
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

    let mut groups = Vec::new();
    for owner_layout in owner_layouts {
        let owner_indices = bindings
            .iter()
            .enumerate()
            .filter_map(|(index, binding)| {
                (binding.source_agent_id == *owner_layout.agent_id()).then_some(index)
            })
            .collect::<Vec<_>>();
        if owner_indices.is_empty() {
            continue;
        }
        let capability_ids = owner_indices
            .iter()
            .map(|index| bindings[*index].capability.id().as_str().to_string())
            .collect::<BTreeSet<_>>();
        for capability_id in capability_ids {
            let indexed_bindings = owner_indices
                .iter()
                .copied()
                .filter(|index| bindings[*index].capability.id().as_str() == capability_id)
                .map(|index| (index, bindings[index].clone()))
                .collect::<Vec<_>>();
            groups.push((owner_layout.clone(), capability_id, indexed_bindings));
        }
    }

    let deadline = tokio::time::Instant::now() + host_profile.total_budget();
    let access = access.clone();
    let consumer_agent_id = consumer_agent_id.clone();
    let outcomes = stream::iter(groups)
        .map(|(owner_layout, capability_id, indexed_bindings)| {
            let access = access.clone();
            let consumer_agent_id = consumer_agent_id.clone();
            async move {
                let group_indices = indexed_bindings
                    .iter()
                    .map(|(index, _)| *index)
                    .collect::<Vec<_>>();
                let group_bindings = indexed_bindings
                    .into_iter()
                    .map(|(_, binding)| binding)
                    .collect::<Vec<_>>();
                let operation = async {
                    let readers = FederatedMemoryReader::discover(
                        &owner_layout,
                        &consumer_agent_id,
                        now_unix_seconds,
                    )
                    .await?;
                    let Some(reader) = readers
                        .iter()
                        .find(|reader| reader.capability().id().as_str() == capability_id)
                    else {
                        return Ok(vec![
                            FederatedRevalidationStatus::Stale(
                                FederationRevalidationDrift::CapabilityMissing,
                            );
                            group_bindings.len()
                        ]);
                    };
                    reader
                        .revalidate_many(&access, &group_bindings, now_unix_seconds)
                        .await
                };
                let statuses = match tokio::time::timeout_at(deadline, operation).await {
                    Err(_) => vec![
                        FederatedRevalidationStatus::Stale(
                            FederationRevalidationDrift::TimedOut,
                        );
                        group_indices.len()
                    ],
                    Ok(Err(_)) => vec![
                        FederatedRevalidationStatus::Stale(
                            FederationRevalidationDrift::Unavailable,
                        );
                        group_indices.len()
                    ],
                    Ok(Ok(statuses)) if statuses.len() == group_indices.len() => statuses,
                    Ok(Ok(_)) => vec![
                        FederatedRevalidationStatus::Stale(
                            FederationRevalidationDrift::Unavailable,
                        );
                        group_indices.len()
                    ],
                };
                group_indices.into_iter().zip(statuses).collect::<Vec<_>>()
            }
        })
        .buffer_unordered(host_profile.revalidation_concurrency())
        .collect::<Vec<_>>()
        .await;

    let mut statuses = vec![None; bindings.len()];
    for outcome in outcomes {
        for (index, status) in outcome {
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
        .collect())
}

'''
replace_re(
    runtime,
    r'''async fn revalidate_federated_product\(.*?\n\}\n\nstruct ProductReaderTransport''',
    new_revalidation + "struct ProductReaderTransport",
)

replace(
    runtime,
    "            let completeness = if items.is_empty() {\n"
    "                FederatedCompletenessV2::Empty\n"
    "            } else {\n"
    "                FederatedCompletenessV2::Complete\n"
    "            };\n",
    "            let maximum_results =\n"
    "                usize::try_from(query.maximum_results).unwrap_or(usize::MAX);\n"
    "            let completeness = if items.is_empty() {\n"
    "                FederatedCompletenessV2::Empty\n"
    "            } else if items.len() >= maximum_results {\n"
    "                // Reaching the bounded top-K ceiling does not prove that\n"
    "                // the owner scope has no additional matching evidence.\n"
    "                FederatedCompletenessV2::Partial\n"
    "            } else {\n"
    "                FederatedCompletenessV2::Complete\n"
    "            };\n",
)

replace(
    runtime,
    "                        failed_peers: 0,\n"
    "                        truncated_peers: 0,\n",
    "                        failed_peers: 0,\n"
    "                        partial_peers: 0,\n"
    "                        truncated_peers: 0,\n",
)

replace(
    "codex-rs/hepta-memory/src/lib.rs",
    "pub use cognitive_runtime::CognitiveRuntime;\n"
    "pub use cognitive_runtime::CognitiveUnavailableReason;\n",
    "pub use cognitive_runtime::CognitiveRuntime;\n"
    "pub use cognitive_runtime::CognitiveUnavailableReason;\n"
    "pub use cognitive_runtime::MemoryFederationHostProfile;\n"
    "pub use cognitive_runtime::MAX_PRODUCT_FEDERATION_ATTEMPT_CONCURRENCY;\n"
    "pub use cognitive_runtime::MAX_PRODUCT_FEDERATION_DISCOVERY_CONCURRENCY;\n"
    "pub use cognitive_runtime::MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS;\n"
    "pub use cognitive_runtime::MAX_PRODUCT_FEDERATION_REVALIDATION_CONCURRENCY;\n"
    "pub use cognitive_runtime::MAX_PRODUCT_FEDERATION_TOTAL_BUDGET;\n",
)

replace(
    "codex-rs/hepta-memory/src/cognitive_federation.rs",
    "    Scope,\n"
    "    Memory,\n",
    "    Scope,\n"
    "    Memory,\n"
    "    Unavailable,\n"
    "    TimedOut,\n",
)

identity = "codex-rs/hepta-memory/src/cognitive_runtime_identity.rs"
replace(
    identity,
    "                    omitted_owner_candidates: left_omitted_owner_candidates,\n"
    "                },",
    "                    omitted_owner_candidates: left_omitted_owner_candidates,\n"
    "                    host_profile: left_host_profile,\n"
    "                },",
)
replace(
    identity,
    "                    omitted_owner_candidates: right_omitted_owner_candidates,\n"
    "                },",
    "                    omitted_owner_candidates: right_omitted_owner_candidates,\n"
    "                    host_profile: right_host_profile,\n"
    "                },",
)
replace(
    identity,
    "                    && left_omitted_owner_candidates == right_omitted_owner_candidates\n",
    "                    && left_omitted_owner_candidates == right_omitted_owner_candidates\n"
    "                    && left_host_profile == right_host_profile\n",
)

identity_tests = "codex-rs/hepta-memory/src/cognitive_runtime_identity_tests.rs"
replace(
    identity_tests,
    "use crate::CognitiveUnavailableReason;\n",
    "use crate::CognitiveUnavailableReason;\nuse crate::MemoryFederationHostProfile;\n",
)
replace(
    identity_tests,
    "        omitted_owner_candidates: 1,\n"
    "    };\n",
    "        omitted_owner_candidates: 1,\n"
    "        host_profile: MemoryFederationHostProfile::default(),\n"
    "    };\n",
)
replace(
    identity_tests,
    "    assert_ne!(installed, changed_coverage);\n",
    r'''    assert_ne!(installed, changed_coverage);
    let constrained = MemoryFederationHostProfile::try_new(
        std::time::Duration::from_millis(250),
        2,
        1,
        1,
        1,
        1,
    )
    .expect("profile");
    assert_ne!(
        installed,
        CognitiveRuntime::Available(Arc::clone(
            installed.available_store().expect("store")
        ))
        .with_federation_sources_profile(
            agent_id(1),
            vec![layout(&temp, &agent_id(2)), layout(&temp, &agent_id(3))],
            constrained,
        )
    );
''',
)

agentd = "codex-rs/hepta-agentd/src/runtime.rs"
replace(
    agentd,
    "use codex_hepta_memory::CognitiveRuntime;\n",
    "use codex_hepta_memory::CognitiveRuntime;\n"
    "use codex_hepta_memory::MemoryFederationHostProfile;\n",
)
replace(
    agentd,
    "    let intelligence_invocation = config.intelligence_invocation_provider();\n"
    "    let (identity, registry, writer_lock) = config.into_parts();\n",
    "    let intelligence_invocation = config.intelligence_invocation_provider();\n"
    "    let federation_host_profile = memory_federation_host_profile_from_env()?;\n"
    "    let (identity, registry, writer_lock) = config.into_parts();\n",
)
replace(
    agentd,
    "        federation_owner_layouts,\n"
    "    )\n",
    "        federation_owner_layouts,\n"
    "        federation_host_profile,\n"
    "    )\n",
)
replace(
    agentd,
    "async fn attach_federation_after_generation_fence(\n",
    r'''fn federation_profile_usize(name: &str, default: usize) -> Result<usize, AgentdError> {
    let Some(value) = std::env::var_os(name) else {
        return Ok(default);
    };
    value
        .to_str()
        .and_then(|value| value.parse::<usize>().ok())
        .ok_or_else(|| AgentdError::Invalid(format!("{name} must be a positive integer")))
}

fn federation_profile_u64(name: &str, default: u64) -> Result<u64, AgentdError> {
    let Some(value) = std::env::var_os(name) else {
        return Ok(default);
    };
    value
        .to_str()
        .and_then(|value| value.parse::<u64>().ok())
        .ok_or_else(|| AgentdError::Invalid(format!("{name} must be a positive integer")))
}

fn memory_federation_host_profile_from_env(
) -> Result<MemoryFederationHostProfile, AgentdError> {
    let defaults = MemoryFederationHostProfile::default();
    let total_budget_ms = federation_profile_u64(
        "HEPTA_MEMORY_FEDERATION_TOTAL_BUDGET_MS",
        u64::try_from(defaults.total_budget().as_millis()).unwrap_or(u64::MAX),
    )?;
    let max_owner_candidates = federation_profile_usize(
        "HEPTA_MEMORY_FEDERATION_MAX_OWNER_CANDIDATES",
        defaults.max_owner_candidates(),
    )?;
    let max_admitted_peers = federation_profile_usize(
        "HEPTA_MEMORY_FEDERATION_MAX_ADMITTED_PEERS",
        defaults.max_admitted_peers(),
    )?;
    let discovery_concurrency = federation_profile_usize(
        "HEPTA_MEMORY_FEDERATION_DISCOVERY_CONCURRENCY",
        defaults.discovery_concurrency().min(max_owner_candidates),
    )?;
    let attempt_concurrency = federation_profile_usize(
        "HEPTA_MEMORY_FEDERATION_ATTEMPT_CONCURRENCY",
        defaults.attempt_concurrency().min(max_admitted_peers),
    )?;
    let revalidation_concurrency = federation_profile_usize(
        "HEPTA_MEMORY_FEDERATION_REVALIDATION_CONCURRENCY",
        defaults.revalidation_concurrency().min(max_admitted_peers),
    )?;
    MemoryFederationHostProfile::try_new(
        Duration::from_millis(total_budget_ms),
        max_owner_candidates,
        max_admitted_peers,
        discovery_concurrency,
        attempt_concurrency,
        revalidation_concurrency,
    )
    .map_err(|error| AgentdError::Invalid(error.to_string()))
}

async fn attach_federation_after_generation_fence(
''',
)
replace(
    agentd,
    "    owner_layouts: Vec<codex_hepta_paths::HeptaAgentLayout>,\n"
    ") -> Result<CognitiveRuntime, AgentdError> {\n",
    "    owner_layouts: Vec<codex_hepta_paths::HeptaAgentLayout>,\n"
    "    host_profile: MemoryFederationHostProfile,\n"
    ") -> Result<CognitiveRuntime, AgentdError> {\n",
)
replace(
    agentd,
    "    let runtime = runtime.with_federation_sources(state.identity().agent_id.clone(), owner_layouts);\n",
    "    let runtime = runtime.with_federation_sources_profile(\n"
    "        state.identity().agent_id.clone(),\n"
    "        owner_layouts,\n"
    "        host_profile,\n"
    "    );\n",
)

v2 = "codex-rs/hepta-memory-federation/src/v2.rs"
replace(
    v2,
    "#[derive(Clone, Copy, Debug, Eq, PartialEq)]\n"
    "pub enum FederatedCompletenessV2 {\n"
    "    Complete,\n"
    "    Partial,\n"
    "    Empty,\n"
    "    Indeterminate,\n"
    "}\n",
    r'''/// Completeness of one authenticated peer observation.
///
/// `Complete` means the peer proved a terminal non-empty result within the
/// requested bound without known omission. `Partial` means coverage cannot be
/// proven exhaustive, including an exact top-K ceiling, source-side omission,
/// truncation, or a post-I/O authority invalidation. `Empty` is a terminal,
/// valid zero-result observation at the bound frontier. `Indeterminate` has no
/// admissible terminal observation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederatedCompletenessV2 {
    Complete,
    Partial,
    Empty,
    Indeterminate,
}
''',
)
replace(
    v2,
    "    pub failed_peers: u32,\n"
    "    pub truncated_peers: u32,\n",
    "    pub failed_peers: u32,\n"
    "    /// Terminal peer observations that cannot prove complete coverage.\n"
    "    pub partial_peers: u32,\n"
    "    pub truncated_peers: u32,\n",
)
replace(
    v2,
    "            || self.coverage.truncated_peers != 0\n",
    "            || self.coverage.partial_peers > self.coverage.completed_peers\n"
    "            || self.coverage.truncated_peers != 0\n",
)
replace(
    v2,
    "                || self.coverage.failed_peers != 1\n"
    "                || self.coverage.truncated_items != 0\n",
    "                || self.coverage.failed_peers != 1\n"
    "                || self.coverage.partial_peers != 0\n"
    "                || self.coverage.truncated_items != 0\n",
)
replace(
    v2,
    "        } else {\n"
    "            if self.observed_frontier.is_none()\n",
    "        } else {\n"
    "            if self.coverage.partial_peers\n"
    "                != u32::from(matches!(self.completeness, FederatedCompletenessV2::Partial))\n"
    "            {\n"
    "                return Err(FederationV2Error::InvalidCompleteness);\n"
    "            }\n"
    "            if self.observed_frontier.is_none()\n",
)
replace(
    v2,
    "        push_u64(&mut bytes, u64::from(self.coverage.failed_peers));\n"
    "        push_u64(&mut bytes, u64::from(self.coverage.truncated_peers));\n",
    "        push_u64(&mut bytes, u64::from(self.coverage.failed_peers));\n"
    "        push_u64(&mut bytes, u64::from(self.coverage.partial_peers));\n"
    "        push_u64(&mut bytes, u64::from(self.coverage.truncated_peers));\n",
)
replace(
    v2,
    "                    failed_peers: 1,\n"
    "                    truncated_peers: 0,\n",
    "                    failed_peers: 1,\n"
    "                    partial_peers: 0,\n"
    "                    truncated_peers: 0,\n",
)
replace(
    v2,
    "                    failed_peers: 0,\n"
    "                    truncated_peers: 0,\n"
    "                    omitted_peer_candidates: 0,\n"
    "                    truncated_items: u32::try_from(truncated_items).unwrap_or(u32::MAX),\n",
    "                    failed_peers: 0,\n"
    "                    partial_peers: u32::from(matches!(\n"
    "                        completeness,\n"
    "                        FederatedCompletenessV2::Partial\n"
    "                    )),\n"
    "                    truncated_peers: 0,\n"
    "                    omitted_peer_candidates: 0,\n"
    "                    truncated_items: u32::try_from(truncated_items).unwrap_or(u32::MAX),\n",
)

extension = "codex-rs/ext/hepta-memory/src/cognitive/federation.rs"
replace(
    extension,
    "const FEDERATED_ATTACHMENT_SCHEMA_VERSION: u32 = 3;\n",
    "const FEDERATED_ATTACHMENT_SCHEMA_VERSION: u32 = 4;\n",
)
replace(
    extension,
    "    failed_peers: u32,\n"
    "    truncated_peers: u32,\n",
    "    failed_peers: u32,\n"
    "    partial_peers: u32,\n"
    "    truncated_peers: u32,\n",
)
replace(
    extension,
    "            failed_peers: coverage.failed_peers,\n"
    "            truncated_peers: coverage.truncated_peers,\n",
    "            failed_peers: coverage.failed_peers,\n"
    "            partial_peers: coverage.partial_peers,\n"
    "            truncated_peers: coverage.truncated_peers,\n",
)

write(
    "codex-rs/hepta-memory-federation/src/lib.rs",
    r'''//! Scoped, fail-closed cognitive federation verification.

#![forbid(unsafe_code)]

mod v2;

#[cfg(feature = "legacy-v1")]
#[deprecated(
    since = "0.0.0",
    note = "V1 is compatibility-only; product code must use the canonical V2 surface"
)]
pub mod legacy_v1;

pub use v2::FederatedCompletenessV2;
pub use v2::FederatedCoverageV2;
pub use v2::FederatedEvidenceItemV2;
pub use v2::FederatedFailureCoverageV2;
pub use v2::FederatedLeaseV2;
pub use v2::FederatedQueryV2;
pub use v2::FederatedResultV2;
pub use v2::FederatedValidityV2;
pub use v2::FederationAttemptControlV2;
pub use v2::FederationAuthorityFuture;
pub use v2::FederationAuthorityObservationV2;
pub use v2::FederationAuthorityStateV2;
pub use v2::FederationAuthorityV2;
pub use v2::FederationCancellationReceiptV2;
pub use v2::FederationCancellationRequestV2;
pub use v2::FederationStopFuture;
pub use v2::FederationStopReasonV2;
pub use v2::FederationTransportFuture;
pub use v2::FederationTransportOutcomeV2;
pub use v2::FederationTransportResultV2;
pub use v2::FederationTransportV2;
pub use v2::FederationV2Error;
pub use v2::MAX_FEDERATED_RESULTS_V2;
pub use v2::RemoteFederatedResponseV2;
pub use v2::execute_once;
pub use v2::observe_cancellation;

#[cfg(feature = "legacy-v1")]
#[allow(deprecated)]
pub use legacy_v1::Error;
#[cfg(feature = "legacy-v1")]
#[allow(deprecated)]
pub use legacy_v1::FederatedReadLease;
#[cfg(feature = "legacy-v1")]
#[allow(deprecated)]
pub use legacy_v1::FederatedReadReceipt;
#[cfg(feature = "legacy-v1")]
#[allow(deprecated)]
pub use legacy_v1::FederatedReadRequest;
#[cfg(feature = "legacy-v1")]
#[allow(deprecated)]
pub use legacy_v1::FederatedStatus;
#[cfg(feature = "legacy-v1")]
#[allow(deprecated)]
pub use legacy_v1::RemoteObservation;
#[cfg(feature = "legacy-v1")]
#[allow(deprecated)]
pub use legacy_v1::observe;
''',
)
write(
    "codex-rs/hepta-memory-federation/src/legacy_v1.rs",
    r'''//! Compatibility-only V1 federation receipt contract.
//!
//! This module is excluded from the default product dependency surface. It is
//! compiled only with the `legacy-v1` feature so migrations and historical
//! receipts can be tested without allowing new product callers to select V1.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[deprecated(note = "use FederatedQueryV2 and execute_once")]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedReadRequest {
    pub request_id: StableId,
    pub peer_id: StableId,
    pub scope_digest: Digest32,
    pub source_snapshot_digest: Digest32,
    pub request_digest: Digest32,
    pub deadline_ms: u64,
}

#[deprecated(note = "use FederatedLeaseV2")]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedReadLease {
    pub lease_id: StableId,
    pub request_id: StableId,
    pub peer_id: StableId,
    pub scope_digest: Digest32,
    pub source_snapshot_digest: Digest32,
    pub request_digest: Digest32,
    pub expires_at_ms: u64,
    pub revoked: bool,
}

#[deprecated(note = "use RemoteFederatedResponseV2")]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RemoteObservation {
    pub response_digest: Digest32,
    pub terminal_observed: bool,
}

#[deprecated(note = "use FederatedValidityV2")]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederatedStatus {
    Succeeded,
    Indeterminate,
}

#[deprecated(note = "use FederatedResultV2")]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederatedReadReceipt {
    pub request_id: StableId,
    pub lease_id: StableId,
    pub status: FederatedStatus,
    pub response_digest: Option<Digest32>,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[deprecated(note = "use FederationV2Error")]
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptyDigest(&'static str),
    DeadlineExpired,
    LeaseExpired,
    LeaseRevoked,
    IdentityMismatch(&'static str),
    DigestMismatch(&'static str),
    MissingTerminalResponse,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

#[deprecated(note = "use execute_once")]
#[allow(deprecated)]
pub fn observe(
    now_ms: u64,
    request: FederatedReadRequest,
    lease: FederatedReadLease,
    observation: Option<RemoteObservation>,
) -> Result<FederatedReadReceipt, Error> {
    for (name, digest) in [
        ("scope", request.scope_digest),
        ("snapshot", request.source_snapshot_digest),
        ("request", request.request_digest),
    ] {
        if digest.is_zero() {
            return Err(Error::EmptyDigest(name));
        }
    }
    if now_ms >= request.deadline_ms {
        return Err(Error::DeadlineExpired);
    }
    if lease.revoked {
        return Err(Error::LeaseRevoked);
    }
    if now_ms >= lease.expires_at_ms {
        return Err(Error::LeaseExpired);
    }
    if lease.request_id != request.request_id {
        return Err(Error::IdentityMismatch("request"));
    }
    if lease.peer_id != request.peer_id {
        return Err(Error::IdentityMismatch("peer"));
    }
    for (name, left, right) in [
        ("scope", lease.scope_digest, request.scope_digest),
        (
            "snapshot",
            lease.source_snapshot_digest,
            request.source_snapshot_digest,
        ),
        ("request", lease.request_digest, request.request_digest),
    ] {
        if left != right {
            return Err(Error::DigestMismatch(name));
        }
    }

    let (status, response_digest) = match observation {
        None => (FederatedStatus::Indeterminate, None),
        Some(value) if !value.terminal_observed => (FederatedStatus::Indeterminate, None),
        Some(value) => {
            if value.response_digest.is_zero() {
                return Err(Error::MissingTerminalResponse);
            }
            (FederatedStatus::Succeeded, Some(value.response_digest))
        }
    };
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.memory.federation.receipt.v1");
    push_id(&mut bytes, &request.request_id);
    push_id(&mut bytes, &lease.lease_id);
    bytes.push(match status {
        FederatedStatus::Succeeded => 0,
        FederatedStatus::Indeterminate => 1,
    });
    if let Some(digest) = response_digest {
        bytes.extend_from_slice(digest.as_array());
    }

    Ok(FederatedReadReceipt {
        request_id: request.request_id,
        lease_id: lease.lease_id,
        status,
        response_digest,
        receipt_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
#[allow(deprecated)]
mod tests;
''',
)

cargo = "codex-rs/hepta-memory-federation/Cargo.toml"
replace(
    cargo,
    "[lints]\nworkspace = true\n\n[dependencies]\n",
    "[lints]\nworkspace = true\n\n[features]\ndefault = []\nlegacy-v1 = []\n\n[dependencies]\n",
)

workflow = ".github/workflows/memory-federation-v2-final-verify.yml"
replace(
    workflow,
    "      - name: Test canonical federation contract\n"
    "        working-directory: codex-rs\n"
    "        run: cargo test -p codex-hepta-memory-federation --lib\n\n",
    "      - name: Test canonical federation contract\n"
    "        working-directory: codex-rs\n"
    "        run: cargo test -p codex-hepta-memory-federation --lib\n\n"
    "      - name: Test opt-in legacy V1 compatibility\n"
    "        working-directory: codex-rs\n"
    "        run: cargo test -p codex-hepta-memory-federation --features legacy-v1 --lib\n\n",
    expected=2,
)
replace(
    "scripts/memory_federation_attestation.py",
    '    "cargo test -p codex-hepta-memory-federation --lib",\n',
    '    "cargo test -p codex-hepta-memory-federation --lib",\n'
    '    "cargo test -p codex-hepta-memory-federation --features legacy-v1 --lib",\n',
)

append_once(
    "docs/modules/memory.federation/TECHNICAL.md",
    "## 14. Product host profile and partial-degradation boundary",
    r'''
## 14. Product host profile and partial-degradation boundary

`AvailableFederatedV2` now carries an immutable `MemoryFederationHostProfile`.
Agentd resolves the profile before runtime composition and rejects invalid or
architecture-widening values. The supported environment fields are:

- `HEPTA_MEMORY_FEDERATION_TOTAL_BUDGET_MS`;
- `HEPTA_MEMORY_FEDERATION_MAX_OWNER_CANDIDATES`;
- `HEPTA_MEMORY_FEDERATION_MAX_ADMITTED_PEERS`;
- `HEPTA_MEMORY_FEDERATION_DISCOVERY_CONCURRENCY`;
- `HEPTA_MEMORY_FEDERATION_ATTEMPT_CONCURRENCY`;
- `HEPTA_MEMORY_FEDERATION_REVALIDATION_CONCURRENCY`.

Discovery, admitted peer attempts and owner/capability revalidation use separate
bounded streaming concurrency. One unavailable owner contributes typed failed
coverage during retrieval and does not erase evidence from other owners.
Revalidation likewise returns owner-local `Unavailable` or `TimedOut` stale
statuses instead of aborting unrelated groups.

This partial degradation stops at the physical-send boundary. A prepared
attachment may contain only the bindings selected from successful peers, and
the final-use guard still requires every one of those exact bindings to be
`Current`. It never silently deletes a stale binding from an already approved
payload because doing so would change the content and source-binding digests.

Completeness and truncation are distinct:

- `Empty` is a valid terminal zero-result observation;
- `Complete` is a non-empty observation below the requested top-K ceiling with
  no known omission;
- `Partial` includes an exact top-K ceiling, source-side incomplete coverage,
  post-I/O invalidation, or known truncation;
- `partial_peers` counts terminal peers that cannot prove complete coverage;
- `truncated_items` counts items known to have been dropped by a bound.

The legacy V1 receipt API is no longer in the default crate surface. It is
available only through the explicit `legacy-v1` Cargo feature for migrations
and regression tests; product composition remains V2-only.
''',
)

append_once(
    "docs/modules/memory.federation/V2_HARDENING.md",
    "### Target-host profile and degradation contract",
    r'''
### Target-host profile and degradation contract

The V2 product runtime binds a validated target-host profile into runtime
identity. Owner discovery, peer attempts, and final revalidation have separate
bounded concurrency. Retrieval may degrade per failed peer with explicit
coverage, while provider dispatch remains all-current for the exact selected
binding set. `partial_peers` records unproven peer completeness separately from
known `truncated_items`. Reaching the top-K ceiling is conservatively partial,
not an assertion that no additional matching evidence exists.

V1 compatibility is feature-gated behind `legacy-v1` and is absent from the
default product dependency surface.
''',
)

print("memory.federation runtime closure patch applied")
