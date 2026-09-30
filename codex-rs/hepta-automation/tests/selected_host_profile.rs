#![cfg(unix)]
#![allow(
    clippy::expect_used,
    reason = "selected-host qualification must fail with precise fixture context"
)]

use std::env;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_automation::AutomationCalendarScheduleV2;
use codex_hepta_automation::AutomationDstGapPolicy;
use codex_hepta_automation::AutomationDstOverlapPolicy;
use codex_hepta_automation::AutomationTimeZoneProfileV1;
use codex_hepta_contracts::Sha256Digest;
use serde_json::json;
use sqlx::SqlitePool;

const MAX_PROFILE_BYTES: u64 = 4 * 1024 * 1024;

#[tokio::test]
#[ignore = "requires protected selected-host timezone evidence"]
async fn selected_host_timezone_profile_is_consumed_by_rust_runtime() {
    let profile_path = required_path("AUTOMATION_TIMEZONE_PROFILE_FILE");
    let receipt_path = required_path("AUTOMATION_TIMEZONE_RUST_RECEIPT");
    let expected_profile_sha = required_digest("AUTOMATION_EXPECTED_TIMEZONE_PROFILE_SHA256");
    let expected_tzdb_sha = required_digest("AUTOMATION_EXPECTED_TZDB_SHA256");
    let expected_timezone_id = required_text("AUTOMATION_EXPECTED_TIMEZONE_ID");

    let bytes = read_immutable_file(&profile_path, MAX_PROFILE_BYTES);
    let observed_profile_sha = Sha256Digest::for_bytes(&bytes);
    assert_eq!(observed_profile_sha, expected_profile_sha);

    let profile: AutomationTimeZoneProfileV1 =
        serde_json::from_slice(&bytes).expect("parse exact selected-host timezone profile");
    assert_eq!(profile.timezone_id, expected_timezone_id);
    assert_eq!(profile.tzdb_digest, expected_tzdb_sha);

    let schedule = AutomationCalendarScheduleV2 {
        timezone_id: profile.timezone_id.clone(),
        tzdb_digest: profile.tzdb_digest.clone(),
        start_at_utc_ms: profile.valid_from_utc_ms,
        end_at_utc_ms: None,
        every_days: 1,
        local_time_ms: 0,
        dst_gap_policy: AutomationDstGapPolicy::NextValid,
        dst_overlap_policy: AutomationDstOverlapPolicy::First,
        clock_profile: profile.clone(),
    };
    schedule
        .validate()
        .expect("validate selected-host profile through Calendar V2");
    let schedule_digest = schedule.digest().expect("digest selected-host schedule");
    let _ = schedule
        .first_at_or_after(profile.valid_from_utc_ms)
        .expect("execute selected-host transition profile");

    let pool = SqlitePool::connect("sqlite::memory:")
        .await
        .expect("open SQLx SQLite runtime");
    let sqlite_version: String = sqlx::query_scalar("SELECT sqlite_version()")
        .fetch_one(&pool)
        .await
        .expect("query native SQLite runtime version");
    pool.close().await;

    let receipt = json!({
        "schema": "hepta.automation-taskflow.selected-host-timezone-rust-receipt.v1",
        "profilePath": profile_path,
        "profileSha256": observed_profile_sha.as_str(),
        "timezoneId": profile.timezone_id,
        "tzdbSha256": profile.tzdb_digest.as_str(),
        "scheduleDigest": schedule_digest.as_str(),
        "transitionCount": profile.transitions.len(),
        "validFromUtcMs": profile.valid_from_utc_ms,
        "validUntilUtcMs": profile.valid_until_utc_ms,
        "sqliteRuntimeVersion": sqlite_version,
        "rustConsumed": true,
    });
    write_receipt(&receipt_path, &receipt);
}

fn required_path(name: &str) -> PathBuf {
    PathBuf::from(env::var(name).unwrap_or_else(|_| panic!("missing {name}")))
}

fn required_text(name: &str) -> String {
    let value = env::var(name).unwrap_or_else(|_| panic!("missing {name}"));
    assert!(!value.is_empty() && !value.chars().any(char::is_control));
    value
}

fn required_digest(name: &str) -> Sha256Digest {
    Sha256Digest::parse(required_text(name)).unwrap_or_else(|_| panic!("invalid {name}"))
}

fn read_immutable_file(path: &Path, max_bytes: u64) -> Vec<u8> {
    assert!(
        path.is_absolute(),
        "selected-host profile path must be absolute"
    );
    let canonical = path
        .canonicalize()
        .expect("canonical selected-host profile");
    assert_eq!(
        canonical, path,
        "profile path must be canonical and symlink-free"
    );
    let metadata = fs::symlink_metadata(path).expect("profile metadata");
    assert!(metadata.is_file() && !metadata.file_type().is_symlink());
    assert!(metadata.len() > 0 && metadata.len() <= max_bytes);
    assert_eq!(
        metadata.permissions().mode() & 0o022,
        0,
        "profile must not be writable by group/world"
    );
    fs::read(path).expect("read selected-host profile")
}

fn write_receipt(path: &Path, value: &serde_json::Value) {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).expect("create receipt parent");
    }
    fs::write(
        path,
        serde_json::to_vec_pretty(value).expect("encode receipt"),
    )
    .expect("write receipt");
}
