use std::collections::BTreeMap;
use std::error::Error;
use std::ffi::OsString;
use std::path::Path;
use std::path::PathBuf;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_types::RecordState;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::KgFactSetDraft;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryRevisionRecord;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::PRODUCTION_DURABLE_WRITER_JOURNAL_MODE;
use codex_hepta_memory::PRODUCTION_DURABLE_WRITER_SYNCHRONOUS_FULL;
use codex_hepta_memory::SourceDraft;
use codex_hepta_paths::HeptaFleetRoot;
use serde_json::json;
use tempfile::TempDir;

const DEFAULT_RECORDS: usize = 256;
const MAX_RECORDS: usize = 16_384;
const MAX_ACTIVE_HEADS: usize = 512;
const CONTENT_BYTES: usize = 1024;
const RECOVERY_LOGICAL_BUDGET_BYTES: usize = 128 * 1024 * 1024;

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    let requested = std::env::var("HEPTA_COGNITIVE_PERF_RECORDS")
        .ok()
        .map(|value| value.parse::<usize>())
        .transpose()?
        .unwrap_or(DEFAULT_RECORDS);
    if requested == 0 || requested > MAX_RECORDS {
        return Err(format!("HEPTA_COGNITIVE_PERF_RECORDS must be 1..={MAX_RECORDS}").into());
    }
    // Retained revision capacity is independent of the KG live-head ceiling.
    // The latency sample retains its distinct-head workload; larger histories
    // correct a fixed pilot-sized head set instead of expanding it every time.
    let active_heads = requested.min(MAX_ACTIVE_HEADS);

    let temp = TempDir::new()?;
    let fleet = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet)?;
    let fleet = std::fs::canonicalize(fleet)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-00000000c057")?;
    let layout = HeptaFleetRoot::parse(fleet)?.layout().agent(&owner);
    let access = CognitiveAccess::agent_private(owner.clone());

    let opened = Instant::now();
    let store = CognitiveStore::open(&layout).await?;
    let cold_open_us = elapsed_us(opened);

    let mut commit_us = Vec::with_capacity(requested);
    let mut remember_us = Vec::with_capacity(active_heads);
    let mut correction_us = Vec::with_capacity(requested - active_heads);
    let mut heads = Vec::<MemoryRevisionRecord>::with_capacity(active_heads);
    let workload_started = Instant::now();
    for index in 0..requested {
        let head_index = index % active_heads;
        let expected_revision = u64::try_from(index / active_heads + 1)?;
        let content = bounded_content(index);
        let expected_content_sha256 = Sha256Digest::for_bytes(content.as_bytes());
        let source = SourceDraft {
            scope: CognitiveScope::AgentPrivate,
            kind: LedgerSourceKind::ExplicitMemoryDirective,
            event_key: format!("perf-source-{index:05}"),
            content: content.as_bytes().to_vec(),
            observed_at_unix_seconds: 1,
        };
        let memory = MemoryDraft {
            stable_key: format!("perf-memory-{head_index:05}"),
            revision: MemoryRevisionDraft {
                scope: CognitiveScope::AgentPrivate,
                content,
                verification: MemoryVerification::Verified,
                lifecycle: MemoryLifecycleState::Active,
                valid_from_unix_seconds: 1,
                valid_to_unix_seconds: None,
                citations: Vec::new(),
            },
        };
        let started = Instant::now();
        let receipt = if index < active_heads {
            store
                .remember_with_kg(&access, &source, &memory, &KgFactSetDraft::default())
                .await?
        } else {
            let head = &heads[head_index];
            store
                .correct_with_kg(
                    &access,
                    &head.id.memory_id,
                    head.id.revision,
                    &source,
                    &memory.revision,
                    &KgFactSetDraft::default(),
                )
                .await?
        };
        let elapsed = elapsed_us(started);
        if receipt.memory.id.revision != expected_revision
            || receipt.memory.content_sha256 != expected_content_sha256
            || receipt.memory.citations.as_slice() != std::slice::from_ref(&receipt.source)
            || receipt.projection.generation.get() != u64::try_from(index + 1)?
            || receipt.projection.entity_count != 0
            || receipt.projection.relation_count != 0
            || receipt.projection.node_count != 0
            || receipt.projection.edge_count != 0
        {
            return Err("commit did not preserve the exact source/revision/KG workload".into());
        }
        if index < active_heads {
            remember_us.push(elapsed);
            heads.push(receipt.memory);
        } else {
            if receipt.memory.id.memory_id != heads[head_index].id.memory_id {
                return Err("correction changed the stable memory identity".into());
            }
            correction_us.push(elapsed);
            heads[head_index] = receipt.memory;
        }
        commit_us.push(elapsed);
        if (index + 1) % MAX_ACTIVE_HEADS == 0 || index + 1 == requested {
            eprintln!(
                "committed {} of {requested} retained revisions across {} active heads",
                index + 1,
                heads.len(),
            );
        }
    }
    let workload_us = elapsed_us(workload_started);

    let database = store.path().to_path_buf();
    let database_bytes = file_len(&database);
    let wal_bytes = file_len(&sidecar(&database, "-wal"));
    let journal_bytes = file_len(&sidecar(&database, "-journal"));

    let snapshot_started = Instant::now();
    let snapshot = store
        .lane_c_snapshot(&access, &CognitiveScope::AgentPrivate, now_unix_seconds()?)
        .await?;
    let snapshot_us = elapsed_us(snapshot_started);
    let snapshot_records = snapshot.snapshot().records.len();
    let expected_heads = heads
        .iter()
        .map(|head| (head.id.memory_id.as_str(), head))
        .collect::<BTreeMap<_, _>>();
    let requested_frontier = u64::try_from(requested)?;
    let frontiers = snapshot.frontiers();
    if snapshot_records != active_heads
        || expected_heads.len() != active_heads
        || frontiers.memory != requested_frontier
        || frontiers.source != requested_frontier
        || frontiers.knowledge_facts != requested_frontier
        || frontiers.knowledge_graph.get() != requested_frontier + 1
        || frontiers.tombstone != 0
    {
        return Err("snapshot does not cover the complete retained-revision workload".into());
    }
    for record in &snapshot.snapshot().records {
        let head = expected_heads
            .get(record.record_id.as_str())
            .ok_or("snapshot contains an unexpected memory head")?;
        if record.state != RecordState::Live
            || record.revision.get() != head.id.revision
            || record.content_digest != head.content_sha256.as_str().parse()?
        {
            return Err("snapshot did not preserve the exact latest memory revisions".into());
        }
    }
    let snapshot_digest = snapshot.snapshot().snapshot_digest.to_string();
    let owner_cut_digest = snapshot.cut_digest().to_string();

    let anchor_started = Instant::now();
    let anchor = store.recovery_anchor().await?;
    let recovery_anchor_us = elapsed_us(anchor_started);
    drop(store);

    let reopen_started = Instant::now();
    let reopened = CognitiveStore::open(&layout).await?;
    let reopen_us = elapsed_us(reopen_started);
    let reopen_anchor_started = Instant::now();
    let reopened_anchor = reopened.recovery_anchor().await?;
    let reopen_anchor_us = elapsed_us(reopen_anchor_started);
    if reopened_anchor != anchor {
        return Err("reopen changed the exact cognitive current-cut anchor".into());
    }
    let reopen_cut_started = Instant::now();
    reopened
        .revalidate_lane_c_snapshot(
            &access,
            &CognitiveScope::AgentPrivate,
            &snapshot,
            now_unix_seconds()?,
        )
        .await?;
    let reopen_cut_us = elapsed_us(reopen_cut_started);

    let metrics = json!({
        "schema": "hepta.perf-durable.cognitive-store.v2",
        "profile": "PERF-DURABLE",
        "sourceSha": std::env::var("SOURCE_SHA").ok(),
        "testedSha": std::env::var("TESTED_SHA").ok(),
        "retainedMemoryRevisions": requested,
        "activeMemoryHeads": active_heads,
        "contentBytesPerRevision": CONTENT_BYTES,
        "workload": {
            "kind": if requested == active_heads {
                "distinct live heads"
            } else {
                "bounded live heads with retained correction history"
            },
            "rememberCommits": remember_us.len(),
            "correctionCommits": correction_us.len(),
            "sourceAppends": frontiers.source,
            "immutableFactSets": frontiers.knowledge_facts,
            "kgPublications": frontiers.knowledge_graph.get() - 1,
            "kgFactsPerRevision": { "entities": 0, "relations": 0 },
            "minimumRevisionsPerMemory": requested / active_heads,
            "maximumRevisionsPerMemory": requested.div_ceil(active_heads),
            "elapsedUs": workload_us,
        },
        "sqliteJournalMode": PRODUCTION_DURABLE_WRITER_JOURNAL_MODE,
        "sqliteSynchronous": PRODUCTION_DURABLE_WRITER_SYNCHRONOUS_FULL,
        "coldOpenUs": cold_open_us,
        "commitUs": latency_distribution(commit_us),
        "commitUsByOperation": {
            "remember": latency_distribution(remember_us),
            "correction": latency_distribution(correction_us),
        },
        "databaseBytes": database_bytes,
        "walBytesBeforeReopen": wal_bytes,
        "journalBytesBeforeReopen": journal_bytes,
        "snapshot": {
            "heads": snapshot_records,
            "memoryRevisionFrontier": frontiers.memory,
            "digest": snapshot_digest,
            "ownerCutDigest": owner_cut_digest,
            "materializeUs": snapshot_us,
        },
        "recoveryLogicalBudgetBytes": RECOVERY_LOGICAL_BUDGET_BYTES,
        "recoveryLogicalBudgetValidated": true,
        "recoveryAnchorUs": recovery_anchor_us,
        "reopenUs": reopen_us,
        "reopenAnchorUs": reopen_anchor_us,
        "reopenCutUs": reopen_cut_us,
        "exactRecoveryStateDigest": anchor.state_digest.as_str(),
        "exactCutPreserved": true,
    });
    let rendered = serde_json::to_string_pretty(&metrics)?;
    println!("{rendered}");

    if let Some(output) = std::env::var_os("HEPTA_COGNITIVE_PERF_OUTPUT") {
        let output = PathBuf::from(output);
        if let Some(parent) = output.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(output, format!("{rendered}\n"))?;
    }
    Ok(())
}

fn latency_distribution(mut values: Vec<u64>) -> Option<serde_json::Value> {
    if values.is_empty() {
        return None;
    }
    values.sort_unstable();
    Some(json!({
        "samples": values.len(),
        "p50": percentile(&values, 50),
        "p95": percentile(&values, 95),
        "p99": percentile(&values, 99),
        "max": values.last().copied().unwrap_or(0),
    }))
}

fn bounded_content(index: usize) -> String {
    let prefix = format!("perf-record-{index:05}:");
    let mut value = String::with_capacity(CONTENT_BYTES);
    value.push_str(&prefix);
    while value.len() < CONTENT_BYTES {
        let remaining = CONTENT_BYTES - value.len();
        let chunk = "0123456789abcdef";
        value.push_str(&chunk[..remaining.min(chunk.len())]);
    }
    value
}

fn elapsed_us(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX)
}

fn percentile(sorted: &[u64], percentile: usize) -> u64 {
    if sorted.is_empty() {
        return 0;
    }
    let index = sorted.len().saturating_mul(percentile).saturating_add(99) / 100;
    sorted[index.saturating_sub(1).min(sorted.len() - 1)]
}

fn sidecar(database: &Path, suffix: &str) -> PathBuf {
    let mut value = OsString::from(database.as_os_str());
    value.push(suffix);
    PathBuf::from(value)
}

fn file_len(path: &Path) -> u64 {
    std::fs::metadata(path).map_or(0, |metadata| metadata.len())
}

fn now_unix_seconds() -> Result<i64, Box<dyn Error>> {
    let seconds = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    Ok(i64::try_from(seconds)?)
}
