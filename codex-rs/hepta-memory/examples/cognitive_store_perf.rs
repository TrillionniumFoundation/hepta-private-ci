use std::error::Error;
use std::ffi::OsString;
use std::path::Path;
use std::path::PathBuf;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::KgFactSetDraft;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::PRODUCTION_DURABLE_WRITER_JOURNAL_MODE;
use codex_hepta_memory::PRODUCTION_DURABLE_WRITER_SYNCHRONOUS_FULL;
use codex_hepta_memory::SourceDraft;
use codex_hepta_paths::HeptaFleetRoot;
use serde_json::json;
use tempfile::TempDir;

const DEFAULT_RECORDS: usize = 256;
const MAX_RECORDS: usize = 16_384;
const CONTENT_BYTES: usize = 1024;

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

    let temp = TempDir::new()?;
    let fleet = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-00000000c057")?;
    let layout = HeptaFleetRoot::parse(fleet)?.layout().agent(&owner);
    let access = CognitiveAccess::agent_private(owner.clone());

    let opened = Instant::now();
    let store = CognitiveStore::open(&layout).await?;
    let cold_open_us = elapsed_us(opened);

    let mut commit_us = Vec::with_capacity(requested);
    for index in 0..requested {
        let content = bounded_content(index);
        let source = SourceDraft {
            scope: CognitiveScope::AgentPrivate,
            kind: LedgerSourceKind::ExplicitMemoryDirective,
            event_key: format!("perf-source-{index:05}"),
            content: content.as_bytes().to_vec(),
            observed_at_unix_seconds: 1,
        };
        let memory = MemoryDraft {
            stable_key: format!("perf-memory-{index:05}"),
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
        store
            .remember_with_kg(&access, &source, &memory, &KgFactSetDraft::default())
            .await?;
        commit_us.push(elapsed_us(started));
    }

    let database = store.path().to_path_buf();
    let database_bytes = file_len(&database);
    let wal_bytes = file_len(&sidecar(&database, "-wal"));
    let journal_bytes = file_len(&sidecar(&database, "-journal"));

    let snapshot_started = Instant::now();
    let snapshot = store
        .lane_c_snapshot(
            &access,
            &CognitiveScope::AgentPrivate,
            now_unix_seconds()?,
        )
        .await?;
    let snapshot_us = elapsed_us(snapshot_started);
    let snapshot_records = snapshot.snapshot().records.len();

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

    commit_us.sort_unstable();
    let metrics = json!({
        "schema": "hepta.perf-durable.cognitive-store.v1",
        "profile": "PERF-DURABLE",
        "sourceSha": std::env::var("SOURCE_SHA").ok(),
        "records": requested,
        "contentBytesPerRecord": CONTENT_BYTES,
        "sqliteJournalMode": PRODUCTION_DURABLE_WRITER_JOURNAL_MODE,
        "sqliteSynchronous": PRODUCTION_DURABLE_WRITER_SYNCHRONOUS_FULL,
        "coldOpenUs": cold_open_us,
        "commitUs": {
            "p50": percentile(&commit_us, 50),
            "p95": percentile(&commit_us, 95),
            "p99": percentile(&commit_us, 99),
            "max": *commit_us.last().unwrap_or(&0),
        },
        "databaseBytes": database_bytes,
        "walBytesBeforeReopen": wal_bytes,
        "journalBytesBeforeReopen": journal_bytes,
        "snapshot": {
            "records": snapshot_records,
            "materializeUs": snapshot_us,
        },
        "recoveryAnchorUs": recovery_anchor_us,
        "reopenUs": reopen_us,
        "reopenAnchorUs": reopen_anchor_us,
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
    let index = sorted
        .len()
        .saturating_mul(percentile)
        .saturating_add(99)
        / 100;
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
