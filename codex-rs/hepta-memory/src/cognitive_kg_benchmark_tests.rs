use std::fs;
use std::time::Instant;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_paths::HeptaFleetRoot;
use serde_json::json;
use sqlx::Row;
use tempfile::TempDir;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::KgEntityFactDraft;
use crate::KgFactSetDraft;
use crate::KgRelationFactDraft;
use crate::LedgerSourceKind;
use crate::MemoryDraft;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionDraft;
use crate::MemoryVerification;
use crate::RetrievalChannel;
use crate::RetrievalRequest;
use crate::SourceDraft;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;

const DEFAULT_WRITES: usize = 256;
const ENTITIES_PER_WRITE: usize = 16;
const RELATIONS_PER_WRITE: usize = 128;
const DEFAULT_QUERY_SAMPLES: usize = 20;
const DEFAULT_REOPEN_SAMPLES: usize = 5;

fn benchmark_retrieval_request() -> RetrievalRequest {
    RetrievalRequest::new("Benchmark Graph", 200)
}

fn configured_count(name: &str, default: usize, maximum: usize) -> usize {
    std::env::var(name)
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|value| *value > 0 && *value <= maximum)
        .unwrap_or(default)
}

fn facts() -> KgFactSetDraft {
    let entities = (0..ENTITIES_PER_WRITE)
        .map(|index| KgEntityFactDraft {
            key: format!("bench-node-{index:02}"),
            entity_type: "benchmark_entity".to_string(),
            label: format!("Benchmark Graph Node {index:02}"),
        })
        .collect::<Vec<_>>();
    let relations = (0..RELATIONS_PER_WRITE)
        .map(|index| KgRelationFactDraft {
            key: format!("bench-relation-{index:03}"),
            from_entity_key: format!("bench-node-{:02}", index % ENTITIES_PER_WRITE),
            to_entity_key: format!(
                "bench-node-{:02}",
                (index.wrapping_mul(7).wrapping_add(1)) % ENTITIES_PER_WRITE
            ),
            relation: format!("benchmark_relation_{index:03}"),
        })
        .collect();
    KgFactSetDraft {
        entities,
        relations,
    }
}

fn percentile_ns(samples: &[u64], percentile: usize) -> u64 {
    assert!(!samples.is_empty());
    let mut ordered = samples.to_vec();
    ordered.sort_unstable();
    let numerator = (ordered.len() - 1).saturating_mul(percentile);
    let index = numerator.saturating_add(99) / 100;
    ordered[index.min(ordered.len() - 1)]
}

fn elapsed_ns(start: Instant) -> u64 {
    u64::try_from(start.elapsed().as_nanos()).unwrap_or(u64::MAX)
}

fn file_size(path: &std::path::Path) -> u64 {
    fs::metadata(path).map(|value| value.len()).unwrap_or(0)
}

#[cfg(target_os = "linux")]
fn linux_rss_kib() -> Option<u64> {
    let status = fs::read_to_string("/proc/self/status").ok()?;
    status.lines().find_map(|line| {
        let rest = line.strip_prefix("VmRSS:")?;
        rest.split_whitespace().next()?.parse().ok()
    })
}

#[cfg(not(target_os = "linux"))]
fn linux_rss_kib() -> Option<u64> {
    None
}

#[cfg(target_os = "linux")]
fn linux_cpu_ticks() -> Option<u64> {
    let stat = fs::read_to_string("/proc/self/stat").ok()?;
    let close = stat.rfind(')')?;
    let fields = stat
        .get(close + 1..)?
        .split_whitespace()
        .collect::<Vec<_>>();
    let user = fields.get(11)?.parse::<u64>().ok()?;
    let system = fields.get(12)?.parse::<u64>().ok()?;
    user.checked_add(system)
}

#[cfg(not(target_os = "linux"))]
fn linux_cpu_ticks() -> Option<u64> {
    None
}

/// Capacity receipt for the currently selected durable algorithm.
///
/// This is intentionally ignored in ordinary unit lanes. It executes real
/// CognitiveStore writes, product retrieval and ordinary reopen. It reports
/// measurements rather than inventing a host-independent latency threshold.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "qualification: knowledge.graph PERF-LIBRARY capacity receipt"]
async fn qualification_knowledge_graph_capacity_receipt() {
    let writes = configured_count("HEPTA_KG_BENCH_WRITES", DEFAULT_WRITES, DEFAULT_WRITES);
    let query_samples =
        configured_count("HEPTA_KG_BENCH_QUERY_SAMPLES", DEFAULT_QUERY_SAMPLES, 100);
    let reopen_samples =
        configured_count("HEPTA_KG_BENCH_REOPEN_SAMPLES", DEFAULT_REOPEN_SAMPLES, 20);

    eprintln!("KG_PHASE open writes={writes} queries={query_samples} reopens={reopen_samples}");
    let benchmark_started = Instant::now();
    let temp = TempDir::new().expect("KG benchmark temp dir");
    let owner = agent_id(185);
    let owner_layout = layout(&temp, &owner);
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let store = CognitiveStore::open(&owner_layout)
        .await
        .expect("KG benchmark store");
    eprintln!(
        "KG_PHASE write start elapsed_ms={}",
        benchmark_started.elapsed().as_millis()
    );
    let facts = facts();

    let cpu_before = linux_cpu_ticks();
    let rss_before = linux_rss_kib();
    let total_write_start = Instant::now();
    let mut mutation_ns = Vec::with_capacity(writes);
    for index in 0..writes {
        let content = format!("Benchmark graph memory {index:04}");
        let started = Instant::now();
        store
            .remember_with_kg(
                &access,
                &SourceDraft {
                    scope: scope.clone(),
                    kind: LedgerSourceKind::ExplicitMemoryDirective,
                    event_key: format!("kg-benchmark-source-{index:04}"),
                    content: content.as_bytes().to_vec(),
                    observed_at_unix_seconds: 100,
                },
                &MemoryDraft {
                    stable_key: format!("kg-benchmark-memory-{index:04}"),
                    revision: MemoryRevisionDraft {
                        scope: scope.clone(),
                        content,
                        verification: MemoryVerification::Verified,
                        lifecycle: MemoryLifecycleState::Active,
                        valid_from_unix_seconds: 100,
                        valid_to_unix_seconds: None,
                        citations: Vec::new(),
                    },
                },
                &facts,
            )
            .await
            .expect("KG benchmark mutation");
        mutation_ns.push(elapsed_ns(started));
        if (index + 1).is_power_of_two() || index + 1 == writes {
            eprintln!(
                "KG_PHASE write completed={} total_ms={} last_ns={}",
                index + 1,
                total_write_start.elapsed().as_millis(),
                mutation_ns.last().copied().unwrap_or(0)
            );
        }
    }
    let total_write_ns = elapsed_ns(total_write_start);

    let current_generation: i64 =
        sqlx::query_scalar("SELECT generation FROM kg_projection WHERE projection_scope = ?")
            .bind(scope.projection_key())
            .fetch_one(&store.pool)
            .await
            .expect("KG benchmark current generation");
    let logical_counts: (i64, i64) = sqlx::query_as(
        "SELECT node_count, edge_count
         FROM kg_projection_generation_receipts
         WHERE projection_scope = ? AND generation = ?",
    )
    .bind(scope.projection_key())
    .bind(current_generation)
    .fetch_one(&store.pool)
    .await
    .expect("KG benchmark current-generation logical counts");
    assert_eq!(
        logical_counts,
        (
            i64::try_from(writes * ENTITIES_PER_WRITE).expect("bounded node count"),
            i64::try_from(writes * RELATIONS_PER_WRITE).expect("bounded edge count"),
        ),
    );
    let revision_fact_counts: (i64, i64) = sqlx::query_as(
        "SELECT
            (SELECT COUNT(*) FROM kg_revision_entities),
            (SELECT COUNT(*) FROM kg_revision_relations)",
    )
    .fetch_one(&store.pool)
    .await
    .expect("KG benchmark revision fact counts");
    assert_eq!(revision_fact_counts, logical_counts);
    let compact_generation_rows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM kg_projection_generation_storage
         WHERE projection_scope = ? AND storage_mode = 'revision_facts_v1'",
    )
    .bind(scope.projection_key())
    .fetch_one(&store.pool)
    .await
    .expect("KG benchmark compact generation witnesses");
    assert_eq!(
        compact_generation_rows,
        i64::try_from(writes).expect("bounded compact generation count")
    );
    let legacy_snapshot_counts: (i64, i64) = sqlx::query_as(
        "SELECT
            (SELECT COUNT(*) FROM kg_nodes WHERE projection_scope = ?),
            (SELECT COUNT(*) FROM kg_edges WHERE projection_scope = ?)",
    )
    .bind(scope.projection_key())
    .bind(scope.projection_key())
    .fetch_one(&store.pool)
    .await
    .expect("KG benchmark legacy snapshot counts");
    assert_eq!(
        legacy_snapshot_counts,
        (0, 0),
        "a fresh G14 store must not copy complete graphs per generation"
    );

    eprintln!(
        "KG_PHASE query elapsed_ms={}",
        benchmark_started.elapsed().as_millis()
    );
    let mut query_ns = Vec::with_capacity(query_samples);
    for _ in 0..query_samples {
        let started = Instant::now();
        let result = store
            .retrieve_memory_candidates(&access, &benchmark_retrieval_request())
            .await
            .expect("KG benchmark retrieval");
        assert!(
            !result.candidates.is_empty(),
            "KG benchmark query returned empty"
        );
        query_ns.push(elapsed_ns(started));
    }

    let database_path = store.path().to_path_buf();
    let wal_path = database_path.with_extension("sqlite3-wal");
    let database_bytes = file_size(&database_path);
    let wal_bytes = file_size(&wal_path);
    eprintln!(
        "KG_PHASE close elapsed_ms={}",
        benchmark_started.elapsed().as_millis()
    );
    store.pool.close().await;
    eprintln!(
        "KG_PHASE reopen elapsed_ms={}",
        benchmark_started.elapsed().as_millis()
    );

    let mut reopen_ns = Vec::with_capacity(reopen_samples);
    for _ in 0..reopen_samples {
        let started = Instant::now();
        let reopened = CognitiveStore::open(&owner_layout)
            .await
            .expect("KG benchmark reopen");
        reopen_ns.push(elapsed_ns(started));
        reopened.pool.close().await;
        eprintln!(
            "KG_PHASE reopened={} elapsed_ms={}",
            reopen_ns.len(),
            benchmark_started.elapsed().as_millis()
        );
    }

    let cpu_after = linux_cpu_ticks();
    let rss_after = linux_rss_kib();
    let cpu_ticks_delta = cpu_before
        .zip(cpu_after)
        .and_then(|(before, after)| after.checked_sub(before));

    let receipt = json!({
        "schema": "hepta.knowledge-graph-perf-library.v1",
        "algorithm": "revision_facts_v1_per_trigger_generation",
        "writes": writes,
        "currentGeneration": current_generation,
        "logicalNodes": logical_counts.0,
        "logicalEdges": logical_counts.1,
        "revisionEntityRows": revision_fact_counts.0,
        "revisionRelationRows": revision_fact_counts.1,
        "compactGenerationWitnessRows": compact_generation_rows,
        "legacySnapshotNodeRows": legacy_snapshot_counts.0,
        "legacySnapshotEdgeRows": legacy_snapshot_counts.1,
        "querySamples": query_samples,
        "reopenSamples": reopen_samples,
        "mutationNs": {
            "p50": percentile_ns(&mutation_ns, 50),
            "p95": percentile_ns(&mutation_ns, 95),
            "p99": percentile_ns(&mutation_ns, 99),
            "total": total_write_ns,
            "throughputMilliOpsPerSecond": u64::try_from(writes)
                .unwrap_or(u64::MAX)
                .saturating_mul(1_000_000_000_000)
                / total_write_ns.max(1),
        },
        "queryNs": {
            "p50": percentile_ns(&query_ns, 50),
            "p95": percentile_ns(&query_ns, 95),
            "p99": percentile_ns(&query_ns, 99),
        },
        "reopenNs": {
            "p50": percentile_ns(&reopen_ns, 50),
            "p95": percentile_ns(&reopen_ns, 95),
            "p99": percentile_ns(&reopen_ns, 99),
        },
        "storage": {
            "databaseBytes": database_bytes,
            "walBytes": wal_bytes,
        },
        "process": {
            "rssKiBBefore": rss_before,
            "rssKiBAfter": rss_after,
            "linuxCpuTicksDelta": cpu_ticks_delta,
        },
        "claim": "measurement_only_no_host_independent_latency_threshold",
    });
    println!(
        "HEPTA_KNOWLEDGE_GRAPH_PERF_RECEIPT={}",
        serde_json::to_string(&receipt).expect("serialize KG performance receipt")
    );
}

/// Measures reads against an existing full-capacity source cut, without writes.
///
/// Manually select this ignored test and provide HEPTA_KG_BENCH_READ_FLEET_ROOT.
/// Ordinary owner validation remains enabled. This separate receipt cannot stand
/// in for successful completion of the full write/query/reopen qualification.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "qualification: existing 256-write KG snapshot; requires HEPTA_KG_BENCH_READ_FLEET_ROOT"]
async fn qualification_knowledge_graph_existing_read_capacity_receipt() {
    let fleet_path = std::env::var_os("HEPTA_KG_BENCH_READ_FLEET_ROOT")
        .expect("manual read-capacity qualification requires an explicit existing fleet root");
    let fleet = HeptaFleetRoot::parse(std::path::PathBuf::from(fleet_path))
        .expect("absolute non-root benchmark fleet path");
    let owner = agent_id(185);
    let owner_layout = fleet.layout().agent(&owner);
    assert!(
        fs::read_dir(owner_layout.cognitive_root())
            .expect("existing benchmark cognitive owner root")
            .any(|entry| entry.is_ok_and(|entry| {
                entry.path().is_file()
                    && entry
                        .path()
                        .extension()
                        .is_some_and(|extension| extension == "sqlite3")
            })),
        "read capacity requires an existing owner database, not a new empty store"
    );
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let store = CognitiveStore::open(&owner_layout)
        .await
        .expect("ordinary validated benchmark owner open");
    assert_eq!(store.owner_agent_id(), &owner);
    let current = sqlx::query(
        "SELECT p.generation, r.node_count, r.edge_count,
                r.input_heads_sha256, r.output_sha256,
                s.source_snapshot_sha256, s.generation_vector_sha256,
                s.graph_profile_sha256, s.generation_sha256, s.publication_sha256
         FROM kg_projection p
         JOIN kg_projection_generation_receipts r
           ON r.projection_scope = p.projection_scope AND r.generation = p.generation
         JOIN kg_projection_generation_semantics s
           ON s.projection_scope = p.projection_scope AND s.generation = p.generation
         WHERE p.projection_scope = ?",
    )
    .bind(scope.projection_key())
    .fetch_one(&store.pool)
    .await
    .expect("exact current projection and semantic receipt");
    let generation: i64 = current.try_get("generation").expect("generation");
    let node_count: i64 = current.try_get("node_count").expect("node count");
    let edge_count: i64 = current.try_get("edge_count").expect("edge count");
    assert_eq!(generation, i64::try_from(DEFAULT_WRITES).expect("writes"));
    assert_eq!(
        node_count,
        i64::try_from(DEFAULT_WRITES * ENTITIES_PER_WRITE).expect("nodes")
    );
    assert_eq!(
        edge_count,
        i64::try_from(DEFAULT_WRITES * RELATIONS_PER_WRITE).expect("edges")
    );
    let input_heads: String = current
        .try_get("input_heads_sha256")
        .expect("input heads cut");
    let source_snapshot: String = current
        .try_get("source_snapshot_sha256")
        .expect("source snapshot");
    let generation_digest: String = current
        .try_get("generation_sha256")
        .expect("generation digest");
    let publication_digest: String = current
        .try_get("publication_sha256")
        .expect("publication digest");
    let generation_digest =
        Sha256Digest::parse(generation_digest).expect("canonical generation digest");
    assert_eq!(
        input_heads, source_snapshot,
        "semantic receipt must bind exact source cut"
    );
    Sha256Digest::parse(input_heads.clone()).expect("source cut digest");
    Sha256Digest::parse(publication_digest.clone()).expect("publication receipt digest");
    let source_counts: (i64, i64, i64, i64) = sqlx::query_as(
        "SELECT (SELECT COUNT(*) FROM memory_heads),
                (SELECT COUNT(*) FROM kg_revision_entities),
                (SELECT COUNT(*) FROM kg_revision_relations),
                (SELECT COUNT(*) FROM kg_projection_generation_storage
                 WHERE projection_scope = ? AND storage_mode = 'revision_facts_v1')",
    )
    .bind(scope.projection_key())
    .fetch_one(&store.pool)
    .await
    .expect("existing source fact and storage witness counts");
    assert_eq!(
        source_counts,
        (generation, node_count, edge_count, generation)
    );
    eprintln!(
        "KG_READ_PHASE query generation={generation} heads={} nodes={node_count} edges={edge_count}",
        source_counts.0
    );
    let mut query_ns = Vec::with_capacity(DEFAULT_QUERY_SAMPLES);
    for _ in 0..DEFAULT_QUERY_SAMPLES {
        let started = Instant::now();
        let result = store
            .retrieve_memory_candidates(&access, &benchmark_retrieval_request())
            .await
            .expect("full-capacity product retrieval");
        query_ns.push(elapsed_ns(started));
        assert!(
            !result.candidates.is_empty(),
            "benchmark product query returned empty"
        );
        assert!(
            result
                .candidates
                .iter()
                .any(|candidate| candidate.channels.contains(&RetrievalChannel::GraphOneHop)),
            "benchmark did not execute graph product channel"
        );
        for candidate in &result.candidates {
            assert_eq!(
                candidate
                    .revalidation
                    .kg_projection_generation
                    .map(crate::ProjectionGeneration::get),
                Some(u64::try_from(generation).expect("generation"))
            );
            assert_eq!(
                candidate
                    .revalidation
                    .kg_projection_generation_sha256
                    .as_ref(),
                Some(&generation_digest)
            );
        }
    }
    let database_path = store.path().to_path_buf();
    let database_bytes = file_size(&database_path);
    let wal_bytes = file_size(&database_path.with_extension("sqlite3-wal"));
    store.pool.close().await;
    let mut reopen_ns = Vec::with_capacity(DEFAULT_REOPEN_SAMPLES);
    for _ in 0..DEFAULT_REOPEN_SAMPLES {
        let started = Instant::now();
        let reopened = CognitiveStore::open(&owner_layout)
            .await
            .expect("ordinary full-capacity reopen");
        reopen_ns.push(elapsed_ns(started));
        assert_eq!(reopened.owner_agent_id(), &owner);
        assert_eq!(reopened.path(), database_path.as_path());
        let reopened_cut: (i64, String, String) = sqlx::query_as(
            "SELECT p.generation, r.input_heads_sha256, s.generation_sha256
             FROM kg_projection p
             JOIN kg_projection_generation_receipts r
               ON r.projection_scope = p.projection_scope AND r.generation = p.generation
             JOIN kg_projection_generation_semantics s
               ON s.projection_scope = p.projection_scope AND s.generation = p.generation
             WHERE p.projection_scope = ?",
        )
        .bind(scope.projection_key())
        .fetch_one(&reopened.pool)
        .await
        .expect("reopen source cut receipt");
        assert_eq!(
            reopened_cut,
            (
                generation,
                input_heads.clone(),
                generation_digest.as_str().to_owned()
            )
        );
        reopened.pool.close().await;
    }
    let receipt = json!({
        "schema": "hepta.knowledge-graph-read-capacity.v1",
        "algorithm": "revision_facts_v1_immutable_generation_query_cache",
        "existingFleetRoot": fleet.as_path(),
        "ownerAgentId": owner.as_str(),
        "sourceCut": {
            "generation": generation,
            "heads": source_counts.0,
            "physicalNodes": node_count,
            "physicalEdges": edge_count,
            "inputHeadsSha256": input_heads,
            "sourceSnapshotSha256": source_snapshot,
            "generationVectorSha256": current.try_get::<String, _>("generation_vector_sha256").expect("vector digest"),
            "graphProfileSha256": current.try_get::<String, _>("graph_profile_sha256").expect("profile digest"),
            "generationSha256": generation_digest.as_str(),
            "publicationSha256": publication_digest,
            "physicalOutputSha256": current.try_get::<String, _>("output_sha256").expect("physical output digest"),
        },
        "querySamples": DEFAULT_QUERY_SAMPLES,
        "reopenSamples": DEFAULT_REOPEN_SAMPLES,
        "queryNs": {
            "p50": percentile_ns(&query_ns, 50),
            "p95": percentile_ns(&query_ns, 95),
            "p99": percentile_ns(&query_ns, 99),
        },
        "reopenNs": {
            "p50": percentile_ns(&reopen_ns, 50),
            "p95": percentile_ns(&reopen_ns, 95),
            "p99": percentile_ns(&reopen_ns, 99),
        },
        "storage": { "databaseBytes": database_bytes, "walBytes": wal_bytes },
        "claim": "read_and_reopen_measurements_only_not_full_write_capacity_completion",
    });
    println!(
        "HEPTA_KNOWLEDGE_GRAPH_READ_CAPACITY_RECEIPT={}",
        serde_json::to_string(&receipt).expect("serialize separate read-capacity receipt")
    );
}
