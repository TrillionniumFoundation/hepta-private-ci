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
use crate::private_state::PrivateStateRoot;
use crate::retirement::RetirementStore;
use crate::retirement::directory as retirement_directory;

mod process_samples;

use self::process_samples::fresh_process_sample;
use self::process_samples::percentile_samples;
use self::process_samples::sample_milliseconds;

const STORAGE_BUDGETS: &str = include_str!("../STORAGE_BUDGETS.json");

fn compiled_build_profile() -> &'static str {
    if cfg!(debug_assertions) {
        "debug"
    } else {
        "release"
    }
}

fn require_release_qualification() {
    assert_eq!(
        compiled_build_profile(),
        "release",
        "blocking storage performance qualification requires the optimized --release profile"
    );
}

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
        fs::create_dir_all(&base).expect("create qualification root parent");
        PrivateStateRoot::open(path.clone()).expect("create private storage qualification root");
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
    require_release_qualification();
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

    let sample_count = budget_u64(&budgets, "performance", "freshProcessSamples") as usize;
    assert!(
        sample_count >= 20,
        "fresh-process p95 requires at least 20 observations"
    );
    let open_process_samples = (0..sample_count)
        .map(|ordinal| fresh_process_sample(&root.path, "active", ordinal, &serde_json::json!({
            "kind": "active-open", "journalPath": journal_path,
            "expectedRecords": active_records, "pageIndex": ordinal % active_records.div_ceil(64),
        })))
        .collect::<Vec<_>>();
    let open_samples_ms = sample_milliseconds(&open_process_samples, "elapsedMilliseconds");
    let open_p95_ms = percentile_samples(&open_samples_ms, 95);
    let page_samples_ms = sample_milliseconds(&open_process_samples, "historyPageMilliseconds");
    let page_p95_ms = percentile_samples(&page_samples_ms, 95);
    let page_max_retained_bytes = open_process_samples
        .iter()
        .map(|sample| {
            sample["historyPageRetainedJsonBytes"]
                .as_u64()
                .expect("retained history bytes")
        })
        .max()
        .expect("history page population");

    let p50_ms = percentile_milliseconds(&mutation_latencies, 50);
    let p95_ms = percentile_milliseconds(&mutation_latencies, 95);
    let p99_ms = percentile_milliseconds(&mutation_latencies, 99);
    let snapshot_bytes = file_bytes(&journal_path);
    let wal_bytes = file_bytes(&crate::journal_storage::wal_path(&journal_path));
    let previous_bytes = file_bytes(&crate::journal_storage::previous_path(&journal_path));
    let total_bytes = recursive_bytes(&root.path);
    let rss_mib = open_process_samples
        .iter()
        .filter_map(|sample| sample["peakRssMiB"].as_u64())
        .chain(peak_rss_mib())
        .max();
    let transitions = mutation_latencies.len();

    let evidence = serde_json::json!({
        "schema": "hepta.ui-native-storage-active-evidence.v1",
        "sourceSha": source_sha(),
        "root": root.path.display().to_string(),
        "activeRecords": active_records,
        "transitions": transitions,
        "mutationSamplesMilliseconds": mutation_latencies.iter()
            .map(|duration| duration.as_secs_f64() * 1_000.0).collect::<Vec<_>>(),
        "measurementScope": {
            "buildProfile": compiled_build_profile(),
            "open": "fresh-process-os-page-cache-uncontrolled",
            "historyPageBytes": "serialized-retained-receipts-not-allocator-accounting",
        },
        "processSampleCount": sample_count,
        "openProcessSamples": open_process_samples,
        "freshProcessOpenSamplesMilliseconds": open_samples_ms,
        "freshProcessOpenP95Milliseconds": open_p95_ms,
        "historyPageSize": 64,
        "historyPageSamplesMilliseconds": page_samples_ms,
        "historyPageP95Milliseconds": page_p95_ms,
        "historyPageMaxRetainedJsonBytes": page_max_retained_bytes,
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
        "active fresh-process open p95",
        open_p95_ms,
        budget_u64(&budgets, "performance", "coldStartP95Milliseconds"),
    );
    assert_at_most(
        "64-receipt history page p95",
        page_p95_ms,
        budget_u64(&budgets, "performance", "historyPageP95Milliseconds"),
    );
    assert!(
        page_max_retained_bytes
            <= budget_u64(
                &budgets,
                "performance",
                "historyPageRetainedSerializedBytes"
            ),
        "retained history-page serialization exceeded its hard budget"
    );
    assert!(
        rss_mib.expect("Linux qualification must expose VmHWM")
            <= budget_u64(&budgets, "performance", "activePeakRssMiB"),
        "active peak RSS exceeded its hard budget"
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
    require_release_qualification();
    let budgets = budgets();
    let retired_identities =
        budget_u64(&budgets, "performance", "retiredIdentitiesSubject") as usize;
    let root = QualificationRoot::create("retired");
    let journal_path = root.path.join("operation-journal.json");
    let active_records = budget_u64(&budgets, "performance", "activeRecordsSubject") as usize;
    let mut journal = OperationJournal::open(&journal_path).expect("create combined journal");
    // Persist the real live population before publishing the retirement fixture.
    // Closing these operations afterward checkpoints the published retirement
    // frontier through the journal's ordinary WAL and snapshot implementation.
    for phase in [OperationPhase::Prepared, OperationPhase::Invoking] {
        for index in 0..active_records {
            journal
                .upsert(operation_record(index, phase))
                .expect("persist combined live population");
        }
    }
    drop(journal);
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
    let mut journal = OperationJournal::open(&journal_path).expect("open combined live population");
    assert_eq!(journal.retired_count(), retired_identities);
    for index in 0..active_records {
        journal
            .upsert(operation_record(index, OperationPhase::Terminal))
            .expect("close combined population with durable retirement checkpoint");
    }
    assert_eq!(journal.all().len(), active_records);
    drop(journal);

    let sample_count = budget_u64(&budgets, "performance", "freshProcessSamples") as usize;
    assert!(
        sample_count >= 20,
        "fresh-process p95 requires at least 20 observations"
    );
    let mut config = serde_json::json!({
        "kind": "retired-open", "journalPath": journal_path,
        "expectedRecords": retired_identities, "checkpoint": checkpoint,
        "firstIdentity": first_identity, "lastIdentity": last_identity,
        "expectedHeadSha256": sha256_hex(&original_head),
    });
    let open_process_samples = (0..sample_count)
        .map(|ordinal| fresh_process_sample(&root.path, "retired-open", ordinal, &config))
        .collect::<Vec<_>>();
    let open_samples_ms = sample_milliseconds(&open_process_samples, "elapsedMilliseconds");
    let open_p95_ms = percentile_samples(&open_samples_ms, 95);
    let combined_journal = measure_combined_journal(
        &root.path,
        &journal_path,
        active_records,
        retired_identities,
        sample_count,
    );

    let legacy_head = serde_json::json!({
        "schema": "hepta.native-retirement.v2",
        "checkpoint": checkpoint,
    });
    config["kind"] = "retired-rebuild".into();
    let legacy_head_bytes =
        serde_json::to_vec(&legacy_head).expect("serialize legacy retirement head");
    let mut index_rebuild_process_samples = Vec::with_capacity(sample_count);
    for ordinal in 0..sample_count {
        // Reset only this private qualification fixture to an authenticated
        // legacy checkpoint. Every child must perform and verify a full rebuild.
        let mut head = OpenOptions::new()
            .write(true)
            .truncate(true)
            .open(&head_path)
            .expect("open retirement head for deterministic legacy projection");
        head.write_all(&legacy_head_bytes)
            .expect("write legacy retirement head");
        head.sync_all().expect("sync legacy retirement head");
        drop(head);
        index_rebuild_process_samples.push(fresh_process_sample(
            &root.path,
            "retired-rebuild",
            ordinal,
            &config,
        ));
    }
    let rebuild_samples_ms =
        sample_milliseconds(&index_rebuild_process_samples, "elapsedMilliseconds");
    let rebuild_p95_ms = percentile_samples(&rebuild_samples_ms, 95);
    let deterministic_rebuild =
        fs::read(&head_path).expect("read rebuilt retirement head") == original_head;
    let total_bytes = recursive_bytes(&root.path);
    let rss_mib = open_process_samples
        .iter()
        .chain(&index_rebuild_process_samples)
        .filter_map(|sample| sample["peakRssMiB"].as_u64())
        .chain(peak_rss_mib())
        .chain(combined_journal["peakRssMiB"].as_u64())
        .max();
    let evidence = serde_json::json!({
        "schema": "hepta.ui-native-storage-retirement-evidence.v1",
        "sourceSha": source_sha(),
        "root": root.path.display().to_string(),
        "retiredIdentities": retired_identities,
        "retirementSegments": segment_count,
        "appendMilliseconds": append_ms,
        "measurementScope": {
            "buildProfile": compiled_build_profile(),
            "open": "fresh-process-os-page-cache-uncontrolled",
        },
        "processSampleCount": sample_count,
        "openProcessSamples": open_process_samples,
        "indexRebuildProcessSamples": index_rebuild_process_samples,
        "freshProcessOpenSamplesMilliseconds": open_samples_ms,
        "freshProcessOpenP95Milliseconds": open_p95_ms,
        "freshProcessIndexRebuildSamplesMilliseconds": rebuild_samples_ms,
        "freshProcessIndexRebuildP95Milliseconds": rebuild_p95_ms,
        "combinedJournal": combined_journal,
        "deterministicRebuild": deterministic_rebuild,
        "totalStorageBytes": total_bytes,
        "peakRssMiB": rss_mib,
    });
    write_evidence(&root.path, "retired", &evidence);

    assert!(
        deterministic_rebuild,
        "retirement index rebuild is not deterministic"
    );
    assert_at_most(
        "million-retired fresh-process indexed open p95",
        open_p95_ms,
        budget_u64(&budgets, "performance", "coldStartP95Milliseconds"),
    );
    assert_at_most(
        "million-retired fresh-process index rebuild p95",
        rebuild_p95_ms,
        budget_u64(
            &budgets,
            "performance",
            "millionRetiredIndexRebuildP95Milliseconds",
        ),
    );
    assert_combined_journal_budgets(&evidence["combinedJournal"], &budgets);
    let rss_mib = rss_mib.expect("Linux qualification must expose VmHWM");
    assert!(
        rss_mib <= budget_u64(&budgets, "performance", "millionRetiredPeakRssMiB"),
        "million-retired peak RSS exceeded its hard budget"
    );
}

fn measure_combined_journal(
    root: &Path,
    journal_path: &Path,
    active_records: usize,
    retired_identities: usize,
    sample_count: usize,
) -> Value {
    let page_count = active_records.div_ceil(64);
    let observations = (0..sample_count)
        .map(|ordinal| {
            fresh_process_sample(root, "combined-open", ordinal, &serde_json::json!({
                "kind": "combined-open", "journalPath": journal_path,
                "expectedRecords": active_records, "expectedRetiredIdentities": retired_identities,
                "pageIndex": ordinal * (page_count - 1) / (sample_count - 1),
            }))
        })
        .collect::<Vec<_>>();
    let open_samples = sample_milliseconds(&observations, "elapsedMilliseconds");
    let page_samples = sample_milliseconds(&observations, "historyPageMilliseconds");
    let retained_bytes = observations
        .iter()
        .map(|sample| {
            sample["historyPageRetainedJsonBytes"]
                .as_u64()
                .expect("combined history bytes")
        })
        .max()
        .expect("combined sample population");
    let rss_mib = observations
        .iter()
        .filter_map(|sample| sample["peakRssMiB"].as_u64())
        .chain(peak_rss_mib())
        .max();
    serde_json::json!({
        "schema": "hepta.ui-native-storage-combined-evidence.v1", "sourceSha": source_sha(),
        "activeRecords": active_records, "retiredIdentities": retired_identities,
        "measurementScope": {
            "buildProfile": compiled_build_profile(),
            "open": "fresh-process-os-page-cache-uncontrolled",
            "historyPageBytes": "serialized-retained-receipts-not-allocator-accounting",
        },
        "processSampleCount": sample_count, "openProcessSamples": observations,
        "freshProcessOpenP95Milliseconds": percentile_samples(&open_samples, 95),
        "freshProcessOpenSamplesMilliseconds": open_samples,
        "historyPageSize": 64, "historyPageP95Milliseconds": percentile_samples(&page_samples, 95),
        "historyPageSamplesMilliseconds": page_samples,
        "historyPageMaxRetainedJsonBytes": retained_bytes, "peakRssMiB": rss_mib,
    })
}

fn assert_combined_journal_budgets(evidence: &Value, budgets: &Value) {
    for (field, ceiling) in [
        (
            "freshProcessOpenP95Milliseconds",
            "coldStartP95Milliseconds",
        ),
        ("historyPageP95Milliseconds", "historyPageP95Milliseconds"),
        (
            "historyPageMaxRetainedJsonBytes",
            "historyPageRetainedSerializedBytes",
        ),
    ] {
        assert_at_most(
            field,
            evidence[field].as_f64().expect("combined measurement"),
            budget_u64(budgets, "performance", ceiling),
        );
    }
    let rss_mib = evidence["peakRssMiB"]
        .as_u64()
        .expect("Linux combined peak RSS");
    for ceiling in ["activePeakRssMiB", "millionRetiredPeakRssMiB"] {
        assert!(
            rss_mib <= budget_u64(budgets, "performance", ceiling),
            "combined active-and-retired peak RSS exceeded its hard budget"
        );
    }
}
