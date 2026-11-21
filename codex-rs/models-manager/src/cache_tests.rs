use super::ModelsCacheEntry;
use chrono::Duration as ChronoDuration;
use chrono::Utc;
use pretty_assertions::assert_eq;
use std::time::Duration;

fn entry_with_timestamp(timestamp: &str) -> ModelsCacheEntry {
    serde_json::from_value(serde_json::json!({
        "fetched_at": timestamp,
        "models": []
    }))
    .expect("original model cache timestamp should deserialize")
}

#[test]
fn original_model_cache_timestamp_wire_preserves_utc_offset_and_fraction() {
    for (source, expected_utc) in [
        (
            "2024-01-01T12:34:56.123456+05:30",
            "2024-01-01T07:04:56.123456Z",
        ),
        (
            "1969-12-31T23:59:59.999999999Z",
            "1969-12-31T23:59:59.999999999Z",
        ),
    ] {
        let entry = entry_with_timestamp(source);
        let actual = serde_json::to_value(&entry).expect("cache timestamp should serialize");
        assert_eq!(
            actual,
            serde_json::json!({
                "fetched_at": expected_utc,
                "models": []
            })
        );
    }
    assert!(
        serde_json::from_value::<ModelsCacheEntry>(serde_json::json!({
            "fetched_at": "not-a-date",
            "models": []
        }))
        .is_err()
    );
}

#[test]
fn original_model_cache_ttl_preserves_future_stale_and_overflow_semantics() {
    let mut entry = entry_with_timestamp("1970-01-01T00:00:00Z");

    entry.fetched_at = Utc::now() - ChronoDuration::hours(2);
    assert!(!entry.is_fresh(Duration::from_secs(3600)));

    entry.fetched_at = Utc::now() - ChronoDuration::minutes(30);
    assert!(entry.is_fresh(Duration::from_secs(3600)));

    entry.fetched_at = Utc::now() + ChronoDuration::minutes(2);
    assert!(entry.is_fresh(Duration::from_secs(1)));
    assert!(!entry.is_fresh(Duration::ZERO));
    assert!(!entry.is_fresh(Duration::MAX));
}

#[test]
fn original_model_cache_ttl_rejects_values_beyond_chrono_range() {
    let entry = entry_with_timestamp("1970-01-01T00:00:00Z");
    // Chrono's TimeDelta stops at i64::MAX milliseconds, not i64::MAX seconds.
    let max_chrono_ttl = Duration::from_millis(i64::MAX as u64);
    assert!(entry.is_fresh(max_chrono_ttl));
    assert!(!entry.is_fresh(max_chrono_ttl + Duration::from_millis(1)));
}
