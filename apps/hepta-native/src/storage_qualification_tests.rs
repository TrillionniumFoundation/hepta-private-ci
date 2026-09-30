//! Full-scale storage qualification. These ignored tests are executed only by
//! the immutable ui.native qualification workflow and emit machine-readable
//! evidence bound to its exact source SHA.

use std::fs;
use std::fs::OpenOptions;
use std::io::Write as _;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use serde_json::Value;

use crate::journal::OperationJournal;
use crate::journal::OperationPhase;
use crate::journal::OperationRecord;
use crate::model::OperationKey;
use crate::model::PlatformAction;
use crate::model::TerminalStatus;
use crate::model::sha256_hex;
use crate::retirement::RetirementStore;
use crate::retirement::directory as retirement_directory;

const STORAGE_BUDGETS: &str = include_str!("../STORAGE_BUDGETS.json");

#[derive(Debug)]
struct QualificationRoot {
    path: PathBuf,
    keep: bool,
}

impl QualificationRoot {
    fn create(label: &str) -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("qualification clock is before the Unix epoch")
            .as_nanos();
        let base = std::env::var_os("HEPTA_UI_NATIVE_STORAGE_ROOT")
            .map(PathBuf::from)
            .unwrap_or_else(std::env::temp_dir);
        let path = base.join(format!(
            "hepta-ui-native-{label}-{}-{nonce}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&path);
        fs::create_dir_all(&path).expect("create storage qualification root");
        Self {
            path,
            keep: std::env::var_os("HEPTA_UI_NATIVE_KEEP_STORAGE_ROOT").is_some(),
        }
    }
}

impl Drop for QualificationRoot {
    fn drop(&mut self) {
        if !self.keep {
            let _ = fs::remove_dir_all(&self.path);
        }
    }
}

fn budgets() -> Value {
    serde_json::from_str(STORAGE_BUDGETS).expect("parse STORAGE_BUDGETS.json")
}

fn budget_u64(value: &Value, section: &str, key: &str) -> u64 {
    value
        .get(section)
        .and_then(|section| section.get(key))
        .and_then(Value::as_u64)
        .unwrap_or_else(|| panic!("missing integer storage budget {section}.{key}"))
}

fn source_sha() -> String {
    let value = std::env::var("HEPTA_UI_NATIVE_SOURCE_SHA")
        .unwrap_or_else(|_| "local-unpinned-source".to_owned());
    if std::env::var_os("HEPTA_UI_NATIVE_REQUIRE_PINNED").is_some() {
        assert!(
            value.len() == 40 && value.bytes().all(|byte| byte.is_ascii_hexdigit()),
            "qualification evidence requires a 40-character source SHA"
        );
    }
    value
}

fn write_evidence(root: &Path, label: &str, evidence: &Value) {
    let path = std::env::var_os("HEPTA_UI_NATIVE_STORAGE_EVIDENCE")
        .map(PathBuf::from)
        .unwrap_or_else(|| root.join(format!("{label}-evidence.json")));
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).expect("create storage evidence parent");
    }
    fs::write(
        &path,
        serde_json::to_vec_pretty(evidence).expect("serialize storage evidence"),
    )
    .expect("write storage qualification evidence");
    println!("ui.native storage evidence: {}", path.display());
}

fn operation_record(index: usize, phase: OperationPhase) -> OperationRecord {
    let terminal = phase == OperationPhase::Terminal;
    OperationRecord {
        endpoint_id: "runtime.storage.qualification".to_owned(),
        key: OperationKey {
            session_id: "session.storage.qualification".to_owned(),
            session_generation: 1,
            operation_id: format!("storage.operation.{index}"),
        },
        subject_id: "operator.storage.qualification".to_owned(),
        displayed_revision: 1,
        action: PlatformAction::CopyText,
        payload_digest: sha256_hex(format!("storage-payload-{index}")),
        binding_digest: sha256_hex(format!("storage-binding-{index}")),
        grant_digest: sha256_hex(format!("storage-grant-{index}")),
        phase,
        terminal_status: terminal.then_some(TerminalStatus::Succeeded),
        outcome_digest: terminal.then(|| sha256_hex(format!("storage-outcome-{index}"))),
    }
}

fn percentile_milliseconds(values: &[Duration], percentile: usize) -> f64 {
    assert!(!values.is_empty(), "cannot calculate an empty percentile");
    let mut ordered = values.to_vec();
    ordered.sort_unstable();
    let rank = ((ordered.len() * percentile).div_ceil(100))
        .saturating_sub(1)
        .min(ordered.len() - 1);
    ordered[rank].as_secs_f64() * 1_000.0
}

fn file_bytes(path: &Path) -> u64 {
    fs::metadata(path).map_or(0, |metadata| metadata.len())
}

fn recursive_bytes(path: &Path) -> u64 {
    let Ok(metadata) = fs::symlink_metadata(path) else {
        return 0;
    };
    if metadata.is_file() {
        return metadata.len();
    }
    if !metadata.is_dir() {
        return 0;
    }
    fs::read_dir(path)
        .expect("read qualification storage directory")
        .map(|entry| recursive_bytes(&entry.expect("read storage entry").path()))
        .sum()
}

#[cfg(target_os = "linux")]
fn peak_rss_mib() -> Option<u64> {
    let status = fs::read_to_string("/proc/self/status").ok()?;
    let kib = status.lines().find_map(|line| {
        line.strip_prefix("VmHWM:")?
            .split_whitespace()
            .next()?
            .parse::<u64>()
            .ok()
    })?;
    Some(kib.div_ceil(1_024))
}

#[cfg(not(target_os = "linux"))]
fn peak_rss_mib() -> Option<u64> {
    None
}

fn assert_at_most(label: &str, actual: f64, ceiling: u64) {
    assert!(
        actual <= ceiling as f64,
        "{label} exceeded its hard budget: actual={actual:.3}, ceiling={ceiling}"
    );
}

#[test]
#[ignore = "full 4096-active-record storage qualification"]
fn storage_active_scale_qualification() {
    let budgets = budgets();
    let active_records = budget_u64(&budgets, "performance", "activeRecordsSubject") as usize;
    assert_eq!(
        active_records,
        budget_u64(&budgets, "structural", "maxActiveRecords") as usize
    );

    let root = QualificationRoot::create("active");
    let journal_path = root.path.join("operation-journal.json");
    let mut journal = OperationJournal::open(&journal_path).expect("open active-scale journal");
    let mut mutation_latencies = Vec::with_capacity(active_records * 3);

    for phase in [
        OperationPhase::Prepared,
        OperationPhase::Invoking,
        OperationPhase::Terminal,
    ] {
        for index in 0..active_records {
            let started = Instant::now();
            journal
                .upsert(operation_record(index, phase))
                .expect("persist active-scale operation transition");
            mutation_latencies.push(started.elapsed());
        }
    }

    let capacity = journal.capacity();
    assert_eq!(capacity.active_records, active_records);
    assert_eq!(capacity.active_limit, active_records);
    assert_eq!(capacity.pending_records, 0);
    drop(journal);

    let cold_started = Instant::now();
    let reopened = OperationJournal::open(&journal_path).expect("cold reopen active-scale journal");
    let cold_start_ms = cold_started.elapsed().as_secs_f64() * 1_000.0;
    assert_eq!(reopened.all().len(), active_records);
    assert!(
        reopened
            .all()
            .iter()
            .all(|record| record.phase == OperationPhase::Terminal)
    );

    let p50_ms = percentile_milliseconds(&mutation_latencies, 50);
    let p95_ms = percentile_milliseconds(&mutation_latencies, 95);
    let p99_ms = percentile_milliseconds(&mutation_latencies, 99);
    let snapshot_bytes = file_bytes(&journal_path);
    let wal_bytes = file_bytes(&crate::journal_storage::wal_path(&journal_path));
    let previous_bytes = file_bytes(&crate::journal_storage::previous_path(&journal_path));
    let total_bytes = recursive_bytes(&root.path);
    let rss_mib = peak_rss_mib();
    let transitions = mutation_latencies.len();

    let evidence = serde_json::json!({
        "schema": "hepta.ui-native-storage-active-evidence.v1",
        "sourceSha": source_sha(),
        "root": root.path.display().to_string(),
        "activeRecords": active_records,
        "transitions": transitions,
        "coldStartMilliseconds": cold_start_ms,
        "mutationP50Milliseconds": p50_ms,
        "mutationP95Milliseconds": p95_ms,
        "mutationP99Milliseconds": p99_ms,
        "snapshotBytes": snapshot_bytes,
        "walBytes": wal_bytes,
        "previousSnapshotBytes": previous_bytes,
        "totalStorageBytes": total_bytes,
        "peakRssMiB": rss_mib,
    });
    write_evidence(&root.path, "active", &evidence);

    assert!(
        snapshot_bytes <= budget_u64(&budgets, "structural", "maxSnapshotBytes"),
        "active snapshot exceeds its structural budget"
    );
    assert!(
        wal_bytes <= budget_u64(&budgets, "structural", "maxWalBytes"),
        "active WAL exceeds its structural budget"
    );
    assert_at_most(
        "active cold start",
        cold_start_ms,
        budget_u64(&budgets, "performance", "coldStartP95Milliseconds"),
    );
    assert_at_most(
        "mutation p50",
        p50_ms,
        budget_u64(&budgets, "performance", "mutationP50Milliseconds"),
    );
    assert_at_most(
        "mutation p95",
        p95_ms,
        budget_u64(&budgets, "performance", "mutationP95Milliseconds"),
    );
    assert_at_most(
        "mutation p99",
        p99_ms,
        budget_u64(&budgets, "performance", "mutationP99Milliseconds"),
    );
}

#[test]
#[ignore = "full 1000000-retired-identity storage qualification"]
fn storage_retirement_scale_qualification() {
    let budgets = budgets();
    let retired_identities =
        budget_u64(&budgets, "performance", "retiredIdentitiesSubject") as usize;
    let root = QualificationRoot::create("retired");
    let journal_path = root.path.join("operation-journal.json");
    let mut store = RetirementStore::create(&journal_path).expect("create retirement store");

    let approximate_bucket = retired_identities.div_ceil(256);
    let mut buckets = (0..256)
        .map(|_| Vec::with_capacity(approximate_bucket))
        .collect::<Vec<Vec<String>>>();
    let mut first_identity = None;
    let mut last_identity = String::new();
    for index in 0..retired_identities {
        let identity = sha256_hex(format!("hepta-retired-qualification-{index}"));
        if first_identity.is_none() {
            first_identity = Some(identity.clone());
        }
        last_identity.clone_from(&identity);
        let prefix = usize::from_str_radix(&identity[..2], 16)
            .expect("SHA-256 retirement prefix is hexadecimal");
        buckets[prefix].push(identity);
    }

    let append_started = Instant::now();
    for mut bucket in buckets {
        bucket.sort_unstable();
        if !bucket.is_empty() {
            store
                .append(&bucket)
                .expect("append retirement qualification bucket");
        }
    }
    let append_ms = append_started.elapsed().as_secs_f64() * 1_000.0;
    assert_eq!(store.len(), retired_identities);
    let checkpoint = store.checkpoint();
    let segment_count = store.segments();
    let first_identity = first_identity.expect("retirement subject is non-empty");
    let head_path = retirement_directory(&journal_path).join("head.json");
    let original_head = fs::read(&head_path).expect("read indexed retirement head");
    drop(store);

    let indexed_started = Instant::now();
    let indexed = RetirementStore::open(&journal_path, Some(&checkpoint))
        .expect("open indexed retirement store")
        .expect("indexed retirement store exists");
    let indexed_open_ms = indexed_started.elapsed().as_secs_f64() * 1_000.0;
    assert_eq!(indexed.len(), retired_identities);
    assert!(indexed.contains(&first_identity));
    assert!(indexed.contains(&last_identity));
    drop(indexed);

    let legacy_head = serde_json::json!({
        "schema": "hepta.native-retirement.v2",
        "checkpoint": checkpoint,
    });
    let mut head = OpenOptions::new()
        .write(true)
        .truncate(true)
        .open(&head_path)
        .expect("open retirement head for deterministic legacy projection");
    head.write_all(
        &serde_json::to_vec(&legacy_head).expect("serialize legacy retirement head"),
    )
    .expect("write legacy retirement head");
    head.sync_all().expect("sync legacy retirement head");
    drop(head);

    let rebuild_started = Instant::now();
    let rebuilt = RetirementStore::open(&journal_path, Some(&checkpoint))
        .expect("rebuild retirement index")
        .expect("rebuilt retirement store exists");
    let rebuild_ms = rebuild_started.elapsed().as_secs_f64() * 1_000.0;
    assert_eq!(rebuilt.len(), retired_identities);
    assert!(rebuilt.contains(&first_identity));
    assert!(rebuilt.contains(&last_identity));
    assert_eq!(rebuilt.segments(), segment_count);
    drop(rebuilt);

    let rebuilt_head = fs::read(&head_path).expect("read rebuilt retirement head");
    let deterministic_rebuild = rebuilt_head == original_head;
    let total_bytes = recursive_bytes(&root.path);
    let rss_mib = peak_rss_mib();
    let evidence = serde_json::json!({
        "schema": "hepta.ui-native-storage-retirement-evidence.v1",
        "sourceSha": source_sha(),
        "root": root.path.display().to_string(),
        "retiredIdentities": retired_identities,
        "retirementSegments": segment_count,
        "appendMilliseconds": append_ms,
        "indexedColdOpenMilliseconds": indexed_open_ms,
        "indexRebuildMilliseconds": rebuild_ms,
        "deterministicRebuild": deterministic_rebuild,
        "totalStorageBytes": total_bytes,
        "peakRssMiB": rss_mib,
    });
    write_evidence(&root.path, "retired", &evidence);

    assert!(deterministic_rebuild, "retirement index rebuild is not deterministic");
    assert_at_most(
        "million-retired indexed cold open",
        indexed_open_ms,
        budget_u64(&budgets, "performance", "coldStartP95Milliseconds"),
    );
    assert_at_most(
        "million-retired index rebuild",
        rebuild_ms,
        budget_u64(
            &budgets,
            "performance",
            "millionRetiredIndexRebuildP95Milliseconds",
        ),
    );
    let rss_mib = rss_mib.expect("Linux qualification must expose VmHWM");
    assert!(
        rss_mib <= budget_u64(&budgets, "performance", "millionRetiredPeakRssMiB"),
        "million-retired peak RSS exceeded its hard budget"
    );
}
