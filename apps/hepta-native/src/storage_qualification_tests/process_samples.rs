//! Isolated fresh-process observations of persisted qualification fixtures.

use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use serde_json::Value;

use super::QualificationRoot;
use super::compiled_build_profile;
use super::operation_record;
use super::peak_rss_mib;
use super::source_sha;
use crate::backend::LoopbackGatewayBackend;
use crate::journal::OperationJournal;
use crate::journal::OperationPhase;
use crate::model::sha256_hex;
use crate::platform::PlatformPolicy;
use crate::platform::SystemPlatformAdapter;
use crate::retirement::Checkpoint;
use crate::retirement::RetirementStore;
use crate::retirement::directory as retirement_directory;
use crate::retirement::qualification_fixture::MixedAuthority;
use crate::retirement::qualification_fixture::REBUILD_SCOPE;
use crate::retirement::qualification_fixture::derived_assets_before_rebuild;
use crate::retirement::qualification_fixture::inspect_shape;
use crate::runtime::NativeShellRuntime;

pub(super) fn sample_milliseconds(samples: &[Value], field: &str) -> Vec<f64> {
    samples
        .iter()
        .map(|sample| sample[field].as_f64().expect("numeric process observation"))
        .collect()
}

pub(super) fn percentile_samples(values: &[f64], percentile: usize) -> f64 {
    assert!(!values.is_empty(), "cannot calculate an empty percentile");
    let mut ordered = values.to_vec();
    ordered.sort_by(f64::total_cmp);
    let rank = (ordered.len() * percentile).div_ceil(100).saturating_sub(1);
    ordered[rank.min(ordered.len() - 1)]
}

pub(super) fn fresh_process_sample(
    root: &Path,
    label: &str,
    ordinal: usize,
    config: &Value,
) -> Value {
    let output_path = root.join(format!("qualification-{label}-{ordinal}.json"));
    let mut child = Command::new(std::env::current_exe().expect("storage test executable"))
        .args([
            "storage_qualification_tests::process_samples::storage_process_sample_worker",
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
    assert_eq!(sample["buildProfile"], compiled_build_profile());
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
        "buildProfile": compiled_build_profile(),
    });
    if matches!(kind, "active-open" | "combined-open") {
        let started = Instant::now();
        let journal = OperationJournal::open(&path).expect("fresh-process active journal open");
        sample["elapsedMilliseconds"] = (started.elapsed().as_secs_f64() * 1_000.0).into();
        assert_eq!(journal.all().len(), expected);
        if kind == "combined-open" {
            let expected_retired = config["expectedRetiredIdentities"]
                .as_u64()
                .expect("sample expected retired identity count")
                as usize;
            assert_eq!(journal.retired_count(), expected_retired);
            sample["activeRecords"] = journal.all().len().into();
            sample["retiredIdentities"] = journal.retired_count().into();
        }
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
        sample["historyPageIndex"] = page_index.into();
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
        if kind == "retired-rebuild" {
            let before = derived_assets_before_rebuild(&path);
            assert_eq!(
                before, 0,
                "first migration must start without derived assets"
            );
            sample["beforeDerivedIndexAssets"] = before.into();
            sample["rebuildScope"] = REBUILD_SCOPE.into();
        }
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
            let shape = inspect_shape(&path, &checkpoint);
            for (field, expected, actual) in [
                (
                    "authoritySegmentCount",
                    "expectedAuthoritySegments",
                    shape.segment_count,
                ),
                (
                    "mixedPrefixSegments",
                    "expectedMixedPrefixSegments",
                    shape.mixed_prefix_segments,
                ),
                (
                    "minimumPrefixesPerSegment",
                    "expectedMinimumPrefixesPerSegment",
                    shape.minimum_prefixes_per_segment,
                ),
            ] {
                assert_eq!(
                    actual as u64,
                    config[expected].as_u64().expect("expected authority shape")
                );
                sample[field] = actual.into();
            }
            assert_eq!(shape.mixed_prefix_segments, shape.segment_count);
            assert!(shape.minimum_prefixes_per_segment > 1);
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
            sample["rebuiltHeadSha256"] = digest.into();
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

    let retired_path = journal_path;
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
    let combined = fresh_process_sample(
        &root.path,
        "smoke-combined",
        0,
        &serde_json::json!({
            "kind": "combined-open", "journalPath": retired_path, "expectedRecords": 64,
            "expectedRetiredIdentities": 32, "pageIndex": 0,
        }),
    );
    assert_eq!(combined["activeRecords"], 64);
    assert_eq!(combined["retiredIdentities"], 32);
    assert_eq!(combined["historyPageSize"], 64);
    assert_ne!(open["pid"], combined["pid"]);
    let authority_path = root.path.join("mixed-authority.json");
    let authority = MixedAuthority::build(&authority_path, 2048);
    let source = RetirementStore::open(&authority_path, Some(&authority.checkpoint))
        .expect("smoke derive source authority")
        .expect("source authority exists");
    drop(source);
    let expected_head = sha256_hex(
        fs::read(retirement_directory(&authority_path).join("head.json"))
            .expect("smoke indexed authority head"),
    );
    let cold_path = root.path.join("cold-mixed-authority.json");
    authority.clone_cold(&cold_path);
    config = serde_json::json!({
        "kind": "retired-rebuild", "journalPath": cold_path, "expectedRecords": 2048,
        "checkpoint": authority.checkpoint, "firstIdentity": authority.first_identity, "lastIdentity": authority.last_identity,
        "expectedHeadSha256": expected_head, "expectedAuthoritySegments": authority.shape.segment_count,
        "expectedMixedPrefixSegments": authority.shape.mixed_prefix_segments,
        "expectedMinimumPrefixesPerSegment": authority.shape.minimum_prefixes_per_segment,
    });
    let rebuild = fresh_process_sample(&root.path, "smoke-rebuild", 0, &config);
    assert_eq!(rebuild["beforeDerivedIndexAssets"], 0);
    assert_eq!(rebuild["authoritySegmentCount"], 2);
    assert_eq!(rebuild["mixedPrefixSegments"], 2);
    assert_eq!(rebuild["rebuiltHeadSha256"], expected_head);
    assert!(
        rebuild["elapsedMilliseconds"]
            .as_f64()
            .expect("rebuild observation")
            >= 0.0
    );
    assert_ne!(open["pid"], rebuild["pid"]);
}
