//! Bounded historical-growth measurement over the real durable owner.
//! This is a repository benchmark, not a target-host SLO or physical erasure proof.

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
use codex_hepta_memory::ForgetMemoryDraft;
use codex_hepta_memory::KgFactSetDraft;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::SourceDraft;
use codex_hepta_paths::HeptaFleetRoot;
use serde_json::Value;
use serde_json::json;
use tempfile::TempDir;

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    let heads = bounded_env("HEPTA_COGNITIVE_HISTORY_HEADS", 64, 1, 256)?;
    let revisions = bounded_env("HEPTA_COGNITIVE_HISTORY_REVISIONS", 16, 1, 64)?;
    if heads
        .checked_mul(revisions)
        .ok_or("history size overflow")?
        > 8192
    {
        return Err("historical profile is bounded to 8192 pre-tombstone revisions".into());
    }
    let temp = TempDir::new()?;
    let fleet_path = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet_path)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-00000000c061")?;
    let layout = HeptaFleetRoot::parse(fleet_path)?.layout().agent(&owner);
    let access = CognitiveAccess::agent_private(owner);
    let start = Instant::now();
    let store = CognitiveStore::open(&layout).await?;
    let cold_open_us = elapsed_us(start);
    let mut ids = Vec::with_capacity(heads);
    let mut remember_us = Vec::with_capacity(heads);
    let mut correction_us = Vec::with_capacity(heads * revisions.saturating_sub(1));
    let mut forget_us = Vec::with_capacity(heads / 2);
    let mut waves = Vec::new();
    for index in 0..heads {
        let text = payload(index, 1);
        let draft = MemoryDraft {
            stable_key: format!("historical-memory-{index}"),
            revision: revision(&text, 1),
        };
        let start = Instant::now();
        let receipt = store
            .remember_with_kg(
                &access,
                &source(index, 1, &text),
                &draft,
                &KgFactSetDraft::default(),
            )
            .await?;
        remember_us.push(elapsed_us(start));
        ids.push(receipt.memory.id.memory_id);
    }
    waves.push(wave(&store, heads, "initial").await?);
    for round in 2..=revisions {
        for (index, id) in ids.iter().enumerate() {
            let text = payload(index, round);
            let start = Instant::now();
            let receipt = store
                .correct_with_kg(
                    &access,
                    id,
                    u64::try_from(round - 1)?,
                    &source(index, round, &text),
                    &revision(&text, i64::try_from(round)?),
                    &KgFactSetDraft::default(),
                )
                .await?;
            correction_us.push(elapsed_us(start));
            if receipt.memory.id.revision != u64::try_from(round)? {
                return Err("correction lost its exact predecessor revision".into());
            }
        }
        if round % 8 == 0 || round == revisions {
            waves.push(wave(&store, heads * round, "correction-history").await?);
        }
    }
    for (index, id) in ids.iter().enumerate().take(heads / 2) {
        let reason = format!("historical-profile-forget-{index}");
        let start = Instant::now();
        let receipt = store
            .forget_with_kg(
                &access,
                id,
                u64::try_from(revisions)?,
                &source(index, revisions + 1, &reason),
                &ForgetMemoryDraft {
                    scope: CognitiveScope::AgentPrivate,
                    reason,
                    valid_from_unix_seconds: i64::try_from(revisions + 1)?,
                    citations: Vec::new(),
                },
            )
            .await?;
        forget_us.push(elapsed_us(start));
        if !matches!(
            receipt.memory.lifecycle,
            MemoryLifecycleState::Tombstoned { .. }
        ) {
            return Err("forget failed to return a tombstoned revision".into());
        }
    }
    let committed_revisions = heads * revisions + heads / 2;
    waves.push(wave(&store, committed_revisions, "tombstones").await?);
    let start = Instant::now();
    let now = i64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs())?;
    let snapshot = store
        .lane_c_snapshot(&access, &CognitiveScope::AgentPrivate, now)
        .await?;
    let snapshot_us = elapsed_us(start);
    let snapshot_records = snapshot.snapshot().records.len();
    let start = Instant::now();
    let expected = store.recovery_anchor().await?;
    let anchor_us = elapsed_us(start);
    drop(snapshot);
    drop(store);
    let start = Instant::now();
    let reopened = CognitiveStore::open(&layout).await?;
    let reopen_us = elapsed_us(start);
    let start = Instant::now();
    let observed = reopened.recovery_anchor().await?;
    let reopen_anchor_us = elapsed_us(start);
    if expected != observed {
        return Err("historical/tombstone current cut changed after reopen".into());
    }
    let report = json!({
        "schema": "hepta.perf-durable.cognitive-store-history.v1",
        "sourceSha": std::env::var("SOURCE_SHA").ok(),
        "testedSha": std::env::var("TESTED_SHA").ok(),
        "baseSha": std::env::var("BASE_SHA").ok(),
        "heads": heads, "revisionsPerHeadBeforeForget": revisions,
        "committedRevisions": committed_revisions, "tombstoneReceipts": forget_us.len(),
        "contentBytesPerRevision": 1024,
        "coldOpenUs": cold_open_us, "rememberUs": distribution(remember_us),
        "correctionUs": distribution(correction_us), "forgetUs": distribution(forget_us),
        "growthWaves": waves, "snapshotRecords": snapshot_records, "snapshotUs": snapshot_us,
        "recoveryAnchorUs": anchor_us, "reopenUs": reopen_us, "reopenAnchorUs": reopen_anchor_us,
        "peakResidentKiB": peak_resident_kib(), "exactCutPreserved": true,
        "physicalErasureProved": false, "targetHostQualified": false
    });
    let rendered = serde_json::to_string_pretty(&report)?;
    println!("{rendered}");
    if let Some(path) = std::env::var_os("HEPTA_COGNITIVE_HISTORY_OUTPUT") {
        let path = PathBuf::from(path);
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(path, format!("{rendered}\n"))?;
    }
    Ok(())
}

fn bounded_env(
    name: &str,
    default: usize,
    minimum: usize,
    maximum: usize,
) -> Result<usize, Box<dyn Error>> {
    let value = std::env::var(name)
        .ok()
        .map(|value| value.parse::<usize>())
        .transpose()?
        .unwrap_or(default);
    if !(minimum..=maximum).contains(&value) {
        return Err(format!("{name} must be {minimum}..={maximum}").into());
    }
    Ok(value)
}

fn payload(index: usize, round: usize) -> String {
    let mut text = format!("history-{index}-{round}:");
    text.extend(std::iter::repeat_n('x', 1024 - text.len()));
    text
}

fn revision(text: &str, at: i64) -> MemoryRevisionDraft {
    MemoryRevisionDraft {
        scope: CognitiveScope::AgentPrivate,
        content: text.into(),
        verification: MemoryVerification::Verified,
        lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: at,
        valid_to_unix_seconds: None,
        citations: Vec::new(),
    }
}

fn source(index: usize, round: usize, text: &str) -> SourceDraft {
    SourceDraft {
        scope: CognitiveScope::AgentPrivate,
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: format!("history-source-{index}-{round}"),
        content: text.as_bytes().to_vec(),
        observed_at_unix_seconds: 1,
    }
}

async fn wave(
    store: &CognitiveStore,
    revisions: usize,
    phase: &str,
) -> Result<Value, Box<dyn Error>> {
    let database = store.path();
    let start = Instant::now();
    let _ = store.recovery_anchor().await?;
    Ok(json!({"phase": phase, "committedRevisions": revisions,
              "anchorUs": elapsed_us(start), "databaseBytes": file_len(database)?,
              "walBytes": file_len(&sidecar(database, "-wal"))?,
              "journalBytes": file_len(&sidecar(database, "-journal"))?}))
}

fn file_len(path: &Path) -> Result<u64, std::io::Error> {
    match std::fs::metadata(path) {
        Ok(metadata) => Ok(metadata.len()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(0),
        Err(error) => Err(error),
    }
}

fn sidecar(path: &Path, suffix: &str) -> PathBuf {
    let mut name = OsString::from(path.as_os_str());
    name.push(suffix);
    PathBuf::from(name)
}

fn elapsed_us(start: Instant) -> u64 {
    u64::try_from(start.elapsed().as_micros()).unwrap_or(u64::MAX)
}

fn distribution(mut values: Vec<u64>) -> Value {
    values.sort_unstable();
    let percentile = |p: usize| -> Option<u64> {
        if values.is_empty() {
            return None;
        }
        let index = (values.len() * p).div_ceil(100).saturating_sub(1);
        values.get(index).copied()
    };
    json!({"samples": values.len(), "p50": percentile(50), "p95": percentile(95),
           "p99": percentile(99), "max": values.last()})
}

fn peak_resident_kib() -> Option<u64> {
    std::fs::read_to_string("/proc/self/status")
        .ok()?
        .lines()
        .find_map(|line| {
            line.strip_prefix("VmHWM:")?
                .split_whitespace()
                .next()?
                .parse()
                .ok()
        })
}
