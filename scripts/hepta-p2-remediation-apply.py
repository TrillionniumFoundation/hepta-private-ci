#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, found {count}")
    target.write_text(text.replace(old, new, 1))


federation = "codex-rs/hepta-memory/src/cognitive_federation.rs"
replace_once(
    federation,
    "use std::sync::Arc;\nuse std::time::Duration;\nuse std::time::SystemTime;",
    "use std::sync::Arc;\nuse std::sync::Mutex;\nuse std::time::Duration;\nuse std::time::Instant;\nuse std::time::SystemTime;",
)
replace_once(
    federation,
    "use codex_hepta_contracts::AgentId;",
    "use codex_hepta_contracts::AgentId;\nuse futures::StreamExt;\nuse futures::stream;",
)
replace_once(
    federation,
    "const MAX_FEDERATION_OWNER_LAYOUTS_PER_AGENT: usize = 128;\nconst FEDERATION_REFRESH_TIMEOUT: Duration = Duration::from_secs(2);",
    "const MAX_FEDERATION_OWNER_LAYOUTS_PER_AGENT: usize = 128;\nconst MAX_FEDERATION_CONCURRENT_SOURCES: usize = 4;\nconst FEDERATION_SOURCE_TIMEOUT: Duration = Duration::from_millis(500);\nconst FEDERATION_REFRESH_TIMEOUT: Duration = Duration::from_secs(2);\nconst FEDERATION_REFRESH_CACHE_TTL: Duration = Duration::from_secs(5);",
)
replace_once(
    federation,
    '''#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct FederatedRetrievalBatch {
    pub query_sha256: Sha256Digest,
    pub candidates: Vec<FederatedRetrievalCandidate>,
}''',
    '''#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FederatedCoverageStatus {
    Complete,
    Partial,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct FederatedRetrievalBatch {
    pub query_sha256: Sha256Digest,
    pub candidates: Vec<FederatedRetrievalCandidate>,
    pub coverage: FederatedCoverageStatus,
    pub attempted_sources: usize,
    pub completed_sources: usize,
}''',
)
replace_once(
    federation,
    '''        Ok(FederatedRetrievalBatch {
            query_sha256: batch.query_sha256,
            candidates,
        })''',
    '''        Ok(FederatedRetrievalBatch {
            query_sha256: batch.query_sha256,
            candidates,
            coverage: FederatedCoverageStatus::Complete,
            attempted_sources: 1,
            completed_sources: 1,
        })''',
)
replace_once(
    federation,
    '''#[derive(Clone)]
pub struct FederatedRecallSet {
    consumer_agent_id: AgentId,
    readers: Vec<FederatedMemoryReader>,
    owner_layouts: Vec<HeptaAgentLayout>,
}''',
    '''#[derive(Clone, Default)]
struct FederationDiscoveryCache {
    refreshed_at: Option<Instant>,
    readers: Vec<FederatedMemoryReader>,
    discovery_complete: bool,
}

struct CurrentFederationReaders {
    readers: Vec<FederatedMemoryReader>,
    discovery_complete: bool,
}

#[derive(Clone)]
pub struct FederatedRecallSet {
    consumer_agent_id: AgentId,
    readers: Vec<FederatedMemoryReader>,
    owner_layouts: Vec<HeptaAgentLayout>,
    dynamic_cache: Arc<Mutex<FederationDiscoveryCache>>,
}''',
)
replace_once(
    federation,
    '''        Ok(Self {
            consumer_agent_id,
            readers,
            owner_layouts: Vec::new(),
        })''',
    '''        Ok(Self {
            consumer_agent_id,
            readers,
            owner_layouts: Vec::new(),
            dynamic_cache: Arc::new(Mutex::new(FederationDiscoveryCache::default())),
        })''',
)
replace_once(
    federation,
    '''        Self {
            consumer_agent_id,
            readers: Vec::new(),
            owner_layouts,
        }''',
    '''        Self {
            consumer_agent_id,
            readers: Vec::new(),
            owner_layouts,
            dynamic_cache: Arc::new(Mutex::new(FederationDiscoveryCache::default())),
        }''',
)
replace_once(
    federation,
    '''        let readers = self.current_readers(request.now_unix_seconds()).await;
        let mut candidates = Vec::new();
        for reader in &readers {
            let Ok(batch) = reader.retrieve(access, request).await else {
                continue;
            };
            candidates.extend(batch.candidates);
        }
        candidates.sort_by(|left, right| {''',
    '''        let current = self.current_readers(request.now_unix_seconds()).await;
        let attempted_sources = current.readers.len();
        let outcomes = stream::iter(current.readers.iter())
            .map(|reader| async move {
                tokio::time::timeout(
                    FEDERATION_SOURCE_TIMEOUT,
                    reader.retrieve(access, request),
                )
                .await
            })
            .buffer_unordered(MAX_FEDERATION_CONCURRENT_SOURCES)
            .collect::<Vec<_>>()
            .await;
        let mut candidates = Vec::new();
        let mut completed_sources = 0usize;
        for outcome in outcomes {
            if let Ok(Ok(batch)) = outcome {
                completed_sources += 1;
                candidates.extend(batch.candidates);
            }
        }
        candidates.sort_by(|left, right| {''',
)
replace_once(
    federation,
    '''        Ok(FederatedRetrievalBatch {
            query_sha256: Sha256Digest::for_bytes(request.query().as_bytes()),
            candidates,
        })''',
    '''        let coverage = if current.discovery_complete && completed_sources == attempted_sources {
            FederatedCoverageStatus::Complete
        } else {
            FederatedCoverageStatus::Partial
        };
        Ok(FederatedRetrievalBatch {
            query_sha256: Sha256Digest::for_bytes(request.query().as_bytes()),
            candidates,
            coverage,
            attempted_sources,
            completed_sources,
        })''',
)
replace_once(
    federation,
    '''        let readers = self.current_readers(now_unix_seconds).await;
        let Some(reader) = readers.iter().find(|reader| {''',
    '''        let current = self.current_readers(now_unix_seconds).await;
        let Some(reader) = current.readers.iter().find(|reader| {''',
)
replace_once(
    federation,
    '''    async fn current_readers(&self, now_unix_seconds: i64) -> Vec<FederatedMemoryReader> {
        let mut readers = self.readers.clone();
        let dynamic = tokio::time::timeout(
            FEDERATION_REFRESH_TIMEOUT,
            self.discover_dynamic_readers(now_unix_seconds),
        )
        .await
        .unwrap_or_default();
        readers.extend(dynamic);
        readers.sort_by(|left, right| {
            left.capability
                .owner_agent_id
                .cmp(&right.capability.owner_agent_id)
                .then_with(|| left.capability.id.cmp(&right.capability.id))
        });
        readers.dedup_by(|left, right| left.capability.id == right.capability.id);
        readers.truncate(MAX_FEDERATION_SOURCES_PER_AGENT);
        readers
    }

    async fn discover_dynamic_readers(&self, now_unix_seconds: i64) -> Vec<FederatedMemoryReader> {
        let mut readers = Vec::new();
        for owner_layout in &self.owner_layouts {
            if readers.len() == MAX_FEDERATION_SOURCES_PER_AGENT {
                break;
            }
            let Ok(discovered) = FederatedMemoryReader::discover(
                owner_layout,
                &self.consumer_agent_id,
                now_unix_seconds,
            )
            .await
            else {
                continue;
            };
            readers.extend(
                discovered
                    .into_iter()
                    .take(MAX_FEDERATION_SOURCES_PER_AGENT - readers.len()),
            );
        }
        readers
    }''',
    '''    async fn current_readers(&self, now_unix_seconds: i64) -> CurrentFederationReaders {
        let (dynamic, mut discovery_complete) = if let Some(cached) = self.cached_dynamic_readers() {
            cached
        } else {
            let refreshed = self.discover_dynamic_readers(now_unix_seconds).await;
            self.store_dynamic_readers(&refreshed.0, refreshed.1);
            refreshed
        };
        let mut readers = self.readers.clone();
        readers.extend(dynamic);
        readers.sort_by(|left, right| {
            left.capability
                .owner_agent_id
                .cmp(&right.capability.owner_agent_id)
                .then_with(|| left.capability.id.cmp(&right.capability.id))
        });
        readers.dedup_by(|left, right| left.capability.id == right.capability.id);
        if readers.len() > MAX_FEDERATION_SOURCES_PER_AGENT {
            discovery_complete = false;
            readers.truncate(MAX_FEDERATION_SOURCES_PER_AGENT);
        }
        CurrentFederationReaders {
            readers,
            discovery_complete,
        }
    }

    fn cached_dynamic_readers(&self) -> Option<(Vec<FederatedMemoryReader>, bool)> {
        let cache = self.dynamic_cache.lock().ok()?;
        let refreshed_at = cache.refreshed_at?;
        if refreshed_at.elapsed() > FEDERATION_REFRESH_CACHE_TTL {
            return None;
        }
        Some((cache.readers.clone(), cache.discovery_complete))
    }

    fn store_dynamic_readers(&self, readers: &[FederatedMemoryReader], discovery_complete: bool) {
        if let Ok(mut cache) = self.dynamic_cache.lock() {
            cache.refreshed_at = Some(Instant::now());
            cache.readers = readers.to_vec();
            cache.discovery_complete = discovery_complete;
        }
    }

    async fn discover_dynamic_readers(
        &self,
        now_unix_seconds: i64,
    ) -> (Vec<FederatedMemoryReader>, bool) {
        let mut pending = stream::iter(self.owner_layouts.iter().cloned())
            .map(|owner_layout| {
                let consumer_agent_id = self.consumer_agent_id.clone();
                async move {
                    match tokio::time::timeout(
                        FEDERATION_SOURCE_TIMEOUT,
                        FederatedMemoryReader::discover(
                            &owner_layout,
                            &consumer_agent_id,
                            now_unix_seconds,
                        ),
                    )
                    .await
                    {
                        Ok(Ok(readers)) => (true, readers),
                        Ok(Err(_)) | Err(_) => (false, Vec::new()),
                    }
                }
            })
            .buffer_unordered(MAX_FEDERATION_CONCURRENT_SOURCES);
        let started = Instant::now();
        let mut observed_sources = 0usize;
        let mut discovery_complete = true;
        let mut readers = Vec::new();
        loop {
            let remaining = FEDERATION_REFRESH_TIMEOUT.saturating_sub(started.elapsed());
            if remaining.is_zero() {
                discovery_complete = false;
                break;
            }
            match tokio::time::timeout(remaining, pending.next()).await {
                Ok(Some((completed, discovered))) => {
                    observed_sources += 1;
                    discovery_complete &= completed;
                    readers.extend(discovered);
                }
                Ok(None) => break,
                Err(_) => {
                    discovery_complete = false;
                    break;
                }
            }
        }
        discovery_complete &= observed_sources == self.owner_layouts.len();
        readers.sort_by(|left, right| {
            left.capability
                .owner_agent_id
                .cmp(&right.capability.owner_agent_id)
                .then_with(|| left.capability.id.cmp(&right.capability.id))
        });
        readers.dedup_by(|left, right| left.capability.id == right.capability.id);
        if readers.len() > MAX_FEDERATION_SOURCES_PER_AGENT {
            discovery_complete = false;
            readers.truncate(MAX_FEDERATION_SOURCES_PER_AGENT);
        }
        (readers, discovery_complete)
    }''',
)

replace_once(
    "codex-rs/hepta-memory/Cargo.toml",
    'ed25519-dalek = { workspace = true }\nserde = { workspace = true, features = ["derive"] }',
    'ed25519-dalek = { workspace = true }\nfutures = { workspace = true }\nserde = { workspace = true, features = ["derive"] }',
)
replace_once(
    "codex-rs/hepta-memory/src/lib.rs",
    "pub use cognitive_federation::FederatedMemoryRevalidationBinding;\npub use cognitive_federation::FederatedRecallSet;",
    "pub use cognitive_federation::FederatedCoverageStatus;\npub use cognitive_federation::FederatedMemoryRevalidationBinding;\npub use cognitive_federation::FederatedRecallSet;",
)
extension = "codex-rs/ext/hepta-memory/src/cognitive/federation.rs"
replace_once(
    extension,
    "use codex_hepta_memory::FederatedMemoryExplanation;",
    "use codex_hepta_memory::FederatedCoverageStatus;\nuse codex_hepta_memory::FederatedMemoryExplanation;",
)
replace_once(
    extension,
    '''            else {
                return Vec::new();
            };
            let byte_budget = usize::try_from(''',
    '''            else {
                return Vec::new();
            };
            if batch.coverage != FederatedCoverageStatus::Complete {
                return Vec::new();
            }
            let byte_budget = usize::try_from(''',
)

tests = "codex-rs/hepta-memory/src/cognitive_federation_tests.rs"
replace_once(
    tests,
    "use crate::FederatedMemoryReader;\nuse crate::FederatedRecallSet;",
    "use crate::FederatedCoverageStatus;\nuse crate::FederatedMemoryReader;\nuse crate::FederatedRecallSet;",
)
replace_once(
    tests,
    '''    assert_eq!(batch.candidates.len(), 1);
    assert_eq!(batch.candidates[0].source_agent_id, owner_id);''',
    '''    assert_eq!(batch.coverage, FederatedCoverageStatus::Complete);
    assert_eq!(batch.attempted_sources, 1);
    assert_eq!(batch.completed_sources, 1);
    assert_eq!(batch.candidates.len(), 1);
    assert_eq!(batch.candidates[0].source_agent_id, owner_id);''',
)
target = Path(tests)
text = target.read_text()
marker = "partial_discovery_preserves_healthy_results_and_reports_incomplete_coverage"
if marker not in text:
    text += r'''

#[tokio::test]
async fn partial_discovery_preserves_healthy_results_and_reports_incomplete_coverage() {
    let temp = TempDir::new().expect("temp dir");
    let owner_id = agent_id(70);
    let consumer_id = agent_id(71);
    let missing_owner_id = agent_id(72);
    let owner_layout = layout(&temp, &owner_id);
    let missing_layout = layout(&temp, &missing_owner_id);
    let owner = CognitiveStore::open(&owner_layout)
        .await
        .expect("owner store");
    let owner_access = CognitiveAccess::agent_private(owner_id.clone());
    let citation = owner
        .append_source(
            &owner_access,
            &source(
                CognitiveScope::AgentPrivate,
                "partial-source",
                "healthy federated source survives another unavailable owner",
            ),
        )
        .await
        .expect("source");
    owner
        .remember_memory(
            &owner_access,
            &MemoryDraft {
                stable_key: "partial-memory".to_string(),
                revision: memory_revision(
                    CognitiveScope::AgentPrivate,
                    "healthy federated source survives another unavailable owner",
                    citation,
                ),
            },
        )
        .await
        .expect("memory");
    let consumer_workspace = workspace("partial-consumer");
    owner
        .grant_federated_recall(
            &owner_access,
            &FederationGrantRequest {
                consumer_agent_id: consumer_id.clone(),
                scope: FederationGrantScope::new(
                    CognitiveScope::AgentPrivate,
                    consumer_workspace.clone(),
                ),
                effective_at_unix_seconds: 100,
                expires_at_unix_seconds: 1_000,
            },
        )
        .await
        .expect("grant");

    let set = FederatedRecallSet::discover(
        consumer_id.clone(),
        vec![owner_layout, missing_layout],
        150,
    )
    .await;
    let batch = set
        .retrieve(
            &FederationConsumerAccess::new(consumer_id, consumer_workspace),
            &RetrievalRequest::new("healthy federated", 150),
        )
        .await
        .expect("partial retrieval");

    assert_eq!(batch.coverage, FederatedCoverageStatus::Partial);
    assert_eq!(batch.attempted_sources, 1);
    assert_eq!(batch.completed_sources, 1);
    assert_eq!(batch.candidates.len(), 1);
    assert_eq!(batch.candidates[0].source_agent_id, owner_id);
}
'''
    target.write_text(text)
