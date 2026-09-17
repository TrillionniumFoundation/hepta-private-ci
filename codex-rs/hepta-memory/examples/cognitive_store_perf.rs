//! PERF-DURABLE measurement harness for the canonical cognitive SQLite owner.
//!
//! This is intentionally an executable measurement source, not a checked-in
//! performance claim. Run it on the target host and retain stdout together with
//! the exact source/binary identity. It exercises real durable transactions,
//! reopen and Lane-C snapshot materialization through the existing owner.

use std::fs;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

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
use codex_hepta_memory::SourceDraft;
use codex_hepta_paths::HeptaFleetRoot;
use serde_json::json;
use tempfile::TempDir;

const DEFAULT_RECORDS: usize = 1_000;
const MAX_MEASURED_RECORDS: usize = 16_000;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let records = parse_records()?;
    let temp = TempDir::new()?;
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000901")?;
    let fleet = temp.path().join("fleet");
    fs::create_dir_all(&fleet)?;
    let layout = HeptaFleetRoot::parse(fleet)?.layout().agent(&owner);
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;

    let open_started = Instant::now();
    let store = CognitiveStore::open(&layout).await?;
    let cold_open = open_started.elapsed();
    let database_path = store.path().to_path_buf();

    let mut commits = Vec::with_capacity(records);
    for index in 0..records {
        let content = format!("PERF-DURABLE cognitive record {index:08}");
        let source = SourceDraft {
            scope: scope.clone(),
            kind: LedgerSourceKind::ExplicitMemoryDirective,
            event_key: format!("perf:source:{index:08}"),
            content: content.as_bytes().to_vec(),
            observed_at_unix_seconds: 1_700_000_000 + i64::try_from(index)?,
        };
        let draft = MemoryDraft {
            stable_key: format!("perf:memory:{index:08}"),
            revision: MemoryRevisionDraft {
                scope: scope.clone(),
                content,
                verification: MemoryVerification::Verified,
                lifecycle: MemoryLifecycleState::Active,
                valid_from_unix_seconds: 1_700_000_000,
                valid_to_unix_seconds: None,
                citations: Vec::new(),
            },
        };
        let started = Instant::now();
        store
            .remember_with_kg(&access, &source, &draft, &KgFactSetDraft::default())
            .await?;
        commits.push(started.elapsed());
    }

    let snapshot_started = Instant::now();
    let snapshot = store
        .lane_c_snapshot(&access, &scope, 1_800_000_000)
        .await?;
    let snapshot_duration = snapshot_started.elapsed();
    let cut_digest = snapshot.cut_digest().to_string();
    let frontiers = snapshot.frontiers().clone();
    let pre_reopen_bytes = sqlite_family_bytes(&database_path)?;

    drop(store);

    let reopen_started = Instant::now();
    let reopened = CognitiveStore::open(&layout).await?;
    let reopen_duration = reopen_started.elapsed();
    let revalidate_started = Instant::now();
    reopened
        .revalidate_lane_c_cut(&access, &scope, snapshot.cut_digest(), 1_800_000_000)
        .await?;
    let revalidate_duration = revalidate_started.elapsed();
    let post_reopen_bytes = sqlite_family_bytes(&database_path)?;

    commits.sort_unstable();
    let total_commit_nanos = commits.iter().map(Duration::as_nanos).sum::<u128>();
    let commit_count = u128::from(u64::try_from(commits.len())?);
    let mean_commit_nanos = total_commit_nanos / commit_count;
    let commit_min = commits[0];
    let commit_max = commits[commits.len() - 1];

    println!(
        "{}",
        serde_json::to_string_pretty(&json!({
            "schema": "hepta.perf-durable.cognitive-store.v1",
            "records": records,
            "target": {
                "os": std::env::consts::OS,
                "arch": std::env::consts::ARCH
            },
            "durations_us": {
                "cold_open": micros(cold_open),
                "commit_min": micros(commit_min),
                "commit_p50": micros(percentile(&commits, 50)),
                "commit_p95": micros(percentile(&commits, 95)),
                "commit_p99": micros(percentile(&commits, 99)),
                "commit_max": micros(commit_max),
                "commit_mean": mean_commit_nanos / 1_000,
                "snapshot": micros(snapshot_duration),
                "reopen": micros(reopen_duration),
                "revalidate_exact_cut": micros(revalidate_duration)
            },
            "sqlite_family_bytes": {
                "before_reopen": pre_reopen_bytes,
                "after_reopen": post_reopen_bytes
            },
            "frontiers": {
                "memory": frontiers.memory,
                "source": frontiers.source,
                "tombstone": frontiers.tombstone,
                "knowledge_facts": frontiers.knowledge_facts,
                "knowledge_graph": frontiers.knowledge_graph.get()
            },
            "cut_digest": cut_digest,
            "claim": "measurement only; retain exact source/binary identity and target-host metadata separately"
        }))?
    );
    Ok(())
}

fn parse_records() -> Result<usize, Box<dyn std::error::Error>> {
    let value = std::env::args()
        .nth(1)
        .map(|value| value.parse::<usize>())
        .transpose()?
        .unwrap_or(DEFAULT_RECORDS);
    if !(1..=MAX_MEASURED_RECORDS).contains(&value) {
        return Err(format!("records must be in 1..={MAX_MEASURED_RECORDS}").into());
    }
    Ok(value)
}

fn percentile(values: &[Duration], percentile: usize) -> Duration {
    let last = values.len().saturating_sub(1);
    let index = last.saturating_mul(percentile).div_ceil(100);
    values[index.min(last)]
}

fn micros(value: Duration) -> u128 {
    value.as_nanos() / 1_000
}

fn sqlite_family_bytes(path: &Path) -> Result<u64, std::io::Error> {
    let mut total = fs::metadata(path)?.len();
    for suffix in ["-wal", "-shm"] {
        let sidecar = std::path::PathBuf::from(format!("{}{}", path.display(), suffix));
        if let Ok(metadata) = fs::metadata(sidecar) {
            total = total.saturating_add(metadata.len());
        }
    }
    Ok(total)
}
