//! Full-scale storage qualification. These ignored tests are executed only by
//! the immutable ui.native qualification workflow and emit machine-readable
//! evidence bound to its exact source SHA.

use std::fs;
use std::fs::OpenOptions;
use std::io::Write as _;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use serde_json::Value;

use crate::backend::LoopbackGatewayBackend;
use crate::journal::OperationJournal;
use crate::journal::OperationPhase;
use crate::journal::OperationRecord;
use crate::model::OperationKey;
use crate::model::PlatformAction;
use crate::model::TerminalStatus;
use crate::model::sha256_hex;
use crate::platform::PlatformPolicy;
use crate::platform::SystemPlatformAdapter;
use crate::private_state::PrivateStateRoot;
use crate::retirement::Checkpoint;
use crate::retirement::RetirementStore;
use crate::retirement::directory as retirement_directory;
use crate::runtime::NativeShellRuntime;

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

fn sample_milliseconds(samples: &[Value], field: &str) -> Vec<f64> {
    samples
        .iter()
        .map(|sample| sample[field].as_f64().expect("numeric process observation"))
        .collect()
}

fn percentile_samples(values: &[f64], percentile: usize) -> f64 {
    assert!(!values.is_empty(), "cannot calculate an empty percentile");
    let mut ordered = values.to_vec();
    ordered.sort_by(f64::total_cmp);
    let rank = (ordered.len() * percentile).div_ceil(100).saturating_sub(1);
    ordered[rank.min(ordered.len() - 1)]
}

fn fresh_process_sample(root: &Path, label: &str, ordinal: usize, config: &Value) -> Value {
    let output_path = root.join(format!("qualification-{label}-{ordinal}.json"));
    let mut child = Command::new(std::env::current_exe().expect("storage test executable"))
        .args([
            "storage_qualification_tests::storage_process_sample_worker",
            "--ignored",
            "--exact",
            "--nocapture",
            "--test-threads=1",
        ])
        .env("HEPTA_UI_NATIVE_PROCESS_SAMPLE", config.to_string())
        .env("HEPTA_UI_NATIVE_PROCESS_SAMPLE_OUTPUT", &output_path)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn fresh storage sample process");
    let deadline = Instant::now() + Duration::from_secs(120);
    loop {
        if child
            .try_wait()
            .expect("observe storage sample process")
            .is_some()
        {
            break;
        }
        if Instant::now() >= deadline {
            child
                .kill()
                .expect("terminate over-deadline storage sample");
            let _ = child.wait();
            panic!("fresh storage sample exceeded the observation deadline");
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    let output = child
        .wait_with_output()
        .expect("join storage sample process");
    assert!(
        output.status.success(),
        "fresh storage sample failed: stdout={} stderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let sample: Value =
        serde_json::from_slice(&fs::read(&output_path).expect("read process sample"))
            .expect("parse process sample");
    fs::remove_file(output_path).expect("remove consumed process observation");
    assert_eq!(sample["sourceSha"], source_sha());
    sample
}

/// An isolated child owns no effect capability and observes only the already
/// persisted qualification fixture. The OS page cache is deliberately not
/// controlled, so this proves fresh-process store opening, not cold-disk startup.
#[test]
#[ignore = "child of storage scale qualification only"]
fn storage_process_sample_worker() {
    let config: Value = serde_json::from_str(
        &std::env::var("HEPTA_UI_NATIVE_PROCESS_SAMPLE").expect("storage sample configuration"),
    )
    .expect("parse storage sample configuration");
    let path = PathBuf::from(config["journalPath"].as_str().expect("sample journal path"));
    let expected = config["expectedRecords"]
        .as_u64()
        .expect("sample expected count") as usize;
    let kind = config["kind"].as_str().expect("sample kind");
    let mut sample = serde_json::json!({
        "schema": "hepta.ui-native-storage-process-sample.v1",
        "sourceSha": source_sha(), "kind": kind, "pid": std::process::id(),
    });
    if kind == "active-open" {
        let started = Instant::now();
        let journal = OperationJournal::open(&path).expect("fresh-process active journal open");
        sample["elapsedMilliseconds"] = (started.elapsed().as_secs_f64() * 1_000.0).into();
        assert_eq!(journal.all().len(), expected);
        assert!(
            journal
                .all()
                .iter()
                .all(|record| record.phase == OperationPhase::Terminal)
        );
        let backend = LoopbackGatewayBackend::new(
            "127.0.0.1:1".parse().expect("inert loopback endpoint"),
            "q".repeat(32),
        )
        .expect("inert backend construction");
        let policy =
            PlatformPolicy::new(Vec::new(), false, false).expect("deny-all platform policy");
        let runtime = NativeShellRuntime::new(
            Box::new(backend),
            Box::new(SystemPlatformAdapter::new(policy)),
            None,
            journal,
        );
        let page_index = config["pageIndex"].as_u64().expect("sample page index") as usize;
        let started = Instant::now();
        let page = runtime
            .operation_history_page(page_index, 64)
            .expect("real durable history page");
        sample["historyPageMilliseconds"] = (started.elapsed().as_secs_f64() * 1_000.0).into();
        assert_eq!(page.total, expected);
        assert_eq!(page.receipts.len(), expected.min(64));
        // Exact bytes retained by receipt serialization; this is not allocator
        // accounting and does not include Vec capacity or temporary allocations.
        sample["historyPageRetainedJsonBytes"] = serde_json::to_vec(&page.receipts)
            .expect("serialize retained history receipts")
            .len()
            .into();
        sample["historyPageSize"] = page.receipts.len().into();
    } else {
        assert!(matches!(kind, "retired-open" | "retired-rebuild"));
        let checkpoint: Checkpoint = serde_json::from_value(config["checkpoint"].clone())
            .expect("sample retirement checkpoint");
        let started = Instant::now();
        let store = RetirementStore::open(&path, Some(&checkpoint))
            .expect("fresh-process retirement open")
            .expect("retirement fixture exists");
        sample["elapsedMilliseconds"] = (started.elapsed().as_secs_f64() * 1_000.0).into();
        assert_eq!(store.len(), expected);
        assert!(
            store.contains(
                config["firstIdentity"]
                    .as_str()
                    .expect("first retired identity")
            )
        );
        assert!(
            store.contains(
                config["lastIdentity"]
                    .as_str()
                    .expect("last retired identity")
            )
        );
        drop(store);
        if kind == "retired-rebuild" {
            let digest = sha256_hex(
                fs::read(retirement_directory(&path).join("head.json"))
                    .expect("rebuilt retirement head"),
            );
            assert_eq!(
                digest,
                config["expectedHeadSha256"]
                    .as_str()
                    .expect("expected rebuilt head digest")
            );
        }
    }
    sample["peakRssMiB"] = serde_json::json!(peak_rss_mib());
    let output = PathBuf::from(
        std::env::var_os("HEPTA_UI_NATIVE_PROCESS_SAMPLE_OUTPUT")
            .expect("process sample output path"),
    );
    fs::write(
        output,
        serde_json::to_vec(&sample).expect("encode process sample"),
    )
    .expect("persist process sample");
}

#[test]
fn storage_process_observations_smoke_real_persisted_fixtures() {
    let root = QualificationRoot::create("sample-smoke");
    let journal_path = root.path.join("active-journal.json");
    let mut journal = OperationJournal::open(&journal_path).expect("smoke active journal");
    for phase in [
        OperationPhase::Prepared,
        OperationPhase::Invoking,
        OperationPhase::Terminal,
    ] {
        for index in 0..64 {
            journal
                .upsert(operation_record(index, phase))
                .expect("smoke durable mutation");
        }
    }
    drop(journal);
    let sample = fresh_process_sample(
        &root.path,
        "smoke-active",
        0,
        &serde_json::json!({
            "kind": "active-open", "journalPath": journal_path, "expectedRecords": 64, "pageIndex": 0,
        }),
    );
    assert_ne!(
        sample["pid"].as_u64().expect("child pid"),
        u64::from(std::process::id())
    );
    assert_eq!(sample["historyPageSize"], 64);
    assert!(
        sample["historyPageRetainedJsonBytes"]
            .as_u64()
            .expect("retained bytes")
            > 0
    );

    let retired_path = root.path.join("retired-journal.json");
    let mut store = RetirementStore::create(&retired_path).expect("smoke retirement store");
    let mut identities = (0..32)
        .map(|index| sha256_hex(format!("sample-retired-{index}")))
        .collect::<Vec<_>>();
    identities.sort_unstable();
    store
        .append(&identities)
        .expect("smoke retired fixture append");
    let checkpoint = store.checkpoint();
    drop(store);
    let head_path = retirement_directory(&retired_path).join("head.json");
    let head_digest = sha256_hex(fs::read(&head_path).expect("smoke retirement head"));
    let mut config = serde_json::json!({
        "kind": "retired-open", "journalPath": retired_path, "expectedRecords": 32,
        "checkpoint": checkpoint, "firstIdentity": identities[0], "lastIdentity": identities[31],
        "expectedHeadSha256": head_digest,
    });
    let open = fresh_process_sample(&root.path, "smoke-retired", 0, &config);
    assert!(
        open["elapsedMilliseconds"]
            .as_f64()
            .expect("elapsed observation")
            >= 0.0
    );
    let legacy_head =
        serde_json::json!({"schema": "hepta.native-retirement.v2", "checkpoint": checkpoint});
    let mut head = OpenOptions::new()
        .write(true)
        .truncate(true)
        .open(&head_path)
        .expect("smoke legacy retirement head");
    head.write_all(&serde_json::to_vec(&legacy_head).expect("smoke legacy projection"))
        .expect("write smoke legacy head");
    head.sync_all().expect("sync smoke legacy head");
    drop(head);
    config["kind"] = "retired-rebuild".into();
    let rebuild = fresh_process_sample(&root.path, "smoke-rebuild", 0, &config);
    assert!(
        rebuild["elapsedMilliseconds"]
            .as_f64()
            .expect("rebuild observation")
            >= 0.0
    );
    assert_ne!(open["pid"], rebuild["pid"]);
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
        .max();
    let evidence = serde_json::json!({
        "schema": "hepta.ui-native-storage-retirement-evidence.v1",
        "sourceSha": source_sha(),
        "root": root.path.display().to_string(),
        "retiredIdentities": retired_identities,
        "retirementSegments": segment_count,
        "appendMilliseconds": append_ms,
        "measurementScope": {"open": "fresh-process-os-page-cache-uncontrolled"},
        "processSampleCount": sample_count,
        "openProcessSamples": open_process_samples,
        "indexRebuildProcessSamples": index_rebuild_process_samples,
        "freshProcessOpenSamplesMilliseconds": open_samples_ms,
        "freshProcessOpenP95Milliseconds": open_p95_ms,
        "freshProcessIndexRebuildSamplesMilliseconds": rebuild_samples_ms,
        "freshProcessIndexRebuildP95Milliseconds": rebuild_p95_ms,
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
    let rss_mib = rss_mib.expect("Linux qualification must expose VmHWM");
    assert!(
        rss_mib <= budget_u64(&budgets, "performance", "millionRetiredPeakRssMiB"),
        "million-retired peak RSS exceeded its hard budget"
    );
}
