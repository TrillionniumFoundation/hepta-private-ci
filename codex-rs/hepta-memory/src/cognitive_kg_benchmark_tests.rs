use std::fs;
use std::sync::Arc;
use std::time::Instant;

use codex_hepta_kg::KnowledgeRelationQueryV2;
use codex_hepta_kg::query_relations_with_work;
use codex_hepta_types::StableId;
use serde_json::json;
use tempfile::TempDir;
use tokio::sync::Barrier;

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
use crate::RetrievalRequest;
use crate::SourceDraft;
use crate::cognitive_intelligence_writer::canonical_entity_id;
use crate::cognitive_kg_store::load_canonical_generation_tx;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;

const DEFAULT_WRITES: usize = 256;
const ENTITIES_PER_WRITE: usize = 16;
const RELATIONS_PER_WRITE: usize = 128;
const DEFAULT_QUERY_SAMPLES: usize = 20;
const DEFAULT_REOPEN_SAMPLES: usize = 5;
const DEFAULT_CONTENTION_READERS: usize = 4;
const DEFAULT_CONTENTION_ROUNDS: usize = 10;

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
fn linux_peak_rss_kib() -> Option<u64> {
    let status = fs::read_to_string("/proc/self/status").ok()?;
    status.lines().find_map(|line| {
        let rest = line.strip_prefix("VmHWM:")?;
        rest.split_whitespace().next()?.parse().ok()
    })
}

#[cfg(not(target_os = "linux"))]
fn linux_peak_rss_kib() -> Option<u64> {
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
    let contention_readers = configured_count(
        "HEPTA_KG_BENCH_CONTENTION_READERS",
        DEFAULT_CONTENTION_READERS,
        16,
    );
    let contention_rounds = configured_count(
        "HEPTA_KG_BENCH_CONTENTION_ROUNDS",
        DEFAULT_CONTENTION_ROUNDS,
        50,
    );
    let host_profile_id = std::env::var("HEPTA_KG_TARGET_PROFILE_ID")
        .unwrap_or_else(|_| "unidentified-host".to_string());

    eprintln!(
        "KG_PHASE open writes={writes} queries={query_samples} reopens={reopen_samples} \
         contention_readers={contention_readers} contention_rounds={contention_rounds}"
    );
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
    let base_facts = facts();

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
                &base_facts,
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
            .retrieve_memory_candidates(&access, &RetrievalRequest::new("Benchmark Graph", 200))
            .await
            .expect("KG benchmark retrieval");
        assert!(
            !result.candidates.is_empty(),
            "KG benchmark query returned empty"
        );
        query_ns.push(elapsed_ns(started));
    }

    let mut generation_transaction = store.pool.begin().await.expect("KG work transaction");
    let canonical_generation = load_canonical_generation_tx(
        &mut generation_transaction,
        &scope.projection_key(),
        current_generation,
    )
    .await
    .expect("KG benchmark canonical generation");
    generation_transaction
        .rollback()
        .await
        .expect("rollback KG work transaction");
    let seed_node_id = StableId::new(canonical_entity_id(&owner, &scope, "bench-node-00"))
        .expect("KG benchmark seed identity");
    let (bounded_query_result, bounded_query_work) = query_relations_with_work(
        &canonical_generation,
        KnowledgeRelationQueryV2 {
            query_id: StableId::new("query:knowledge-graph-capacity-work-v2")
                .expect("KG benchmark query identity"),
            generation_digest: canonical_generation.generation_digest,
            seed_node_ids: vec![seed_node_id],
            relation_kinds: Vec::new(),
            valid_at_unix_seconds: Some(200),
            maximum_edges: 1,
        },
    )
    .expect("KG benchmark bounded relation query");
    assert_eq!(bounded_query_result.edges.len(), 1);
    assert!(bounded_query_result.omitted_count > 0);
    assert_eq!(bounded_query_work.selected_edges_cloned, 1);
    assert_eq!(
        bounded_query_work.omitted_edges,
        u64::from(bounded_query_result.omitted_count)
    );

    eprintln!(
        "KG_PHASE contention elapsed_ms={}",
        benchmark_started.elapsed().as_millis()
    );
    let mut contention_writer_ns = Vec::with_capacity(contention_rounds);
    let mut contention_reader_ns = Vec::with_capacity(contention_rounds * contention_readers);
    let mut contention_round_ns = Vec::with_capacity(contention_rounds);
    for round in 0..contention_rounds {
        let barrier = Arc::new(Barrier::new(contention_readers + 2));
        let writer_store = store.clone();
        let writer_access = access.clone();
        let writer_scope = scope.clone();
        let writer_barrier = Arc::clone(&barrier);
        let writer = tokio::spawn(async move {
            writer_barrier.wait().await;
            let started = Instant::now();
            let content = format!("Benchmark graph contention memory {round:04}");
            writer_store
                .remember_with_kg(
                    &writer_access,
                    &SourceDraft {
                        scope: writer_scope.clone(),
                        kind: LedgerSourceKind::ExplicitMemoryDirective,
                        event_key: format!("kg-benchmark-contention-source-{round:04}"),
                        content: content.as_bytes().to_vec(),
                        observed_at_unix_seconds: 100,
                    },
                    &MemoryDraft {
                        stable_key: format!("kg-benchmark-contention-memory-{round:04}"),
                        revision: MemoryRevisionDraft {
                            scope: writer_scope,
                            content,
                            verification: MemoryVerification::Verified,
                            lifecycle: MemoryLifecycleState::Active,
                            valid_from_unix_seconds: 100,
                            valid_to_unix_seconds: None,
                            citations: Vec::new(),
                        },
                    },
                    &facts(),
                )
                .await
                .expect("KG contention writer");
            elapsed_ns(started)
        });
        let mut readers = Vec::with_capacity(contention_readers);
        for reader_index in 0..contention_readers {
            let reader_store = store.clone();
            let reader_access = access.clone();
            let reader_barrier = Arc::clone(&barrier);
            readers.push(tokio::spawn(async move {
                reader_barrier.wait().await;
                let started = Instant::now();
                let result = reader_store
                    .retrieve_memory_candidates(
                        &reader_access,
                        &RetrievalRequest::new(
                            format!("Benchmark Graph contention {round} reader {reader_index}"),
                            200,
                        ),
                    )
                    .await
                    .expect("KG contention reader");
                assert!(!result.candidates.is_empty(), "KG contention query empty");
                elapsed_ns(started)
            }));
        }
        let round_started = Instant::now();
        barrier.wait().await;
        contention_writer_ns.push(writer.await.expect("join KG contention writer"));
        for reader in readers {
            contention_reader_ns.push(reader.await.expect("join KG contention reader"));
        }
        contention_round_ns.push(elapsed_ns(round_started));
    }
    let post_contention_generation: i64 =
        sqlx::query_scalar("SELECT generation FROM kg_projection WHERE projection_scope = ?")
            .bind(scope.projection_key())
            .fetch_one(&store.pool)
            .await
            .expect("KG post-contention generation");
    assert_eq!(
        post_contention_generation,
        current_generation + i64::try_from(contention_rounds).expect("bounded contention rounds")
    );

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
    let peak_rss = linux_peak_rss_kib();
    let cpu_ticks_delta = cpu_before
        .zip(cpu_after)
        .and_then(|(before, after)| after.checked_sub(before));

    let receipt = json!({
        "schema": "hepta.knowledge-graph-perf-library.v2",
        "algorithm": "revision_facts_v1_per_trigger_generation",
        "hostProfileId": host_profile_id,
        "writes": writes,
        "currentGeneration": current_generation,
        "postContentionGeneration": post_contention_generation,
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
        "boundedQueryWork": {
            "returnedEdges": bounded_query_result.edges.len(),
            "omittedEdges": bounded_query_result.omitted_count,
            "validatedNodes": bounded_query_work.validated_nodes,
            "validatedEdges": bounded_query_work.validated_edges,
            "validatedSupports": bounded_query_work.validated_supports,
            "visibilityNodesScanned": bounded_query_work.visibility_nodes_scanned,
            "visibilitySupportsInspected": bounded_query_work.visibility_supports_inspected,
            "relationEdgesScanned": bounded_query_work.relation_edges_scanned,
            "relationSupportsInspected": bounded_query_work.relation_supports_inspected,
            "matchingEdges": bounded_query_work.matching_edges,
            "selectedEdgesCloned": bounded_query_work.selected_edges_cloned,
            "selectedSupportsCloned": bounded_query_work.selected_supports_cloned,
        },
        "contention": {
            "rounds": contention_rounds,
            "readersPerRound": contention_readers,
            "writerNs": {
                "p50": percentile_ns(&contention_writer_ns, 50),
                "p95": percentile_ns(&contention_writer_ns, 95),
                "p99": percentile_ns(&contention_writer_ns, 99),
            },
            "readerNs": {
                "p50": percentile_ns(&contention_reader_ns, 50),
                "p95": percentile_ns(&contention_reader_ns, 95),
                "p99": percentile_ns(&contention_reader_ns, 99),
            },
            "roundNs": {
                "p50": percentile_ns(&contention_round_ns, 50),
                "p95": percentile_ns(&contention_round_ns, 95),
                "p99": percentile_ns(&contention_round_ns, 99),
            },
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
            "peakRssKiB": peak_rss,
            "linuxCpuTicksDelta": cpu_ticks_delta,
        },
        "claim": "measurement_only_no_host_independent_latency_threshold",
    });
    println!(
        "HEPTA_KNOWLEDGE_GRAPH_PERF_RECEIPT={}",
        serde_json::to_string(&receipt).expect("serialize KG performance receipt")
    );
}
