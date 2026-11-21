use super::FileModelsCache;
use super::ModelsCache;
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

#[test]
fn original_model_cache_wire_preserves_leap_seconds_and_extended_years() {
    for timestamp in ["2016-12-31T23:59:60Z", "+10000-01-01T00:00:00Z"] {
        let original = entry_with_timestamp(timestamp);
        let encoded = serde_json::to_value(&original).expect("cache serialization succeeds");
        assert_eq!(encoded["fetched_at"], serde_json::json!(timestamp));
        let restored: ModelsCacheEntry =
            serde_json::from_value(encoded).expect("cache timestamp should round trip");
        assert_eq!(restored, original);
    }
}

#[tokio::test]
async fn file_cache_ttl_refresh_rejects_missing_or_mismatched_client_version_without_writing() {
    let temp = tempfile::tempdir().expect("temporary model cache directory");
    let path = temp.path().join("models.json");
    let cache = FileModelsCache::new(path.clone(), Duration::from_secs(3600));

    for cached_version in [None, Some("previous-client")] {
        let entry = ModelsCacheEntry {
            fetched_at: Utc::now() - ChronoDuration::hours(2),
            etag: Some("unchanged-etag".to_owned()),
            client_version: cached_version.map(str::to_owned),
            models: Vec::new(),
        };
        super::save_file(&path, &entry)
            .await
            .expect("write previous client cache");
        let before = tokio::fs::read(&path).await.expect("read original bytes");

        cache
            .refresh_ttl("current-client")
            .await
            .expect_err("a missing or different client version must not be renewed");

        let after = tokio::fs::read(&path).await.expect("read preserved bytes");
        assert_eq!(after, before);
    }
}
#[tokio::test]
async fn file_cache_ttl_refresh_keeps_half_ttl_hit_and_preserves_catalog_on_renewal() {
    let temp = tempfile::tempdir().expect("temporary model cache directory");
    let path = temp.path().join("models.json");
    let cache = FileModelsCache::new(path.clone(), Duration::from_secs(3600));
    let mut entry = ModelsCacheEntry {
        fetched_at: Utc::now(),
        etag: Some("unchanged-etag".to_owned()),
        client_version: Some("current-client".to_owned()),
        models: Vec::new(),
    };
    super::save_file(&path, &entry)
        .await
        .expect("store fresh cache");
    let before = tokio::fs::read(&path).await.expect("read fresh bytes");
    cache
        .refresh_ttl("current-client")
        .await
        .expect("fresh half-TTL hit");
    assert_eq!(
        tokio::fs::read(&path).await.expect("read unchanged bytes"),
        before
    );

    entry.fetched_at = Utc::now() - ChronoDuration::hours(2);
    super::save_file(&path, &entry)
        .await
        .expect("store expired cache");
    let earliest_renewal = Utc::now();
    cache
        .refresh_ttl("current-client")
        .await
        .expect("revalidate expired cache");
    let latest_renewal = Utc::now();
    let renewed = super::load_file(&path)
        .await
        .expect("read renewed cache")
        .expect("renewed cache exists");
    assert!(renewed.fetched_at >= earliest_renewal);
    assert!(renewed.fetched_at <= latest_renewal);
    entry.fetched_at = renewed.fetched_at;
    assert_eq!(renewed, entry);
}

#[tokio::test]
async fn file_cache_corrupt_json_fails_closed_without_replacing_disk_bytes() {
    let temp = tempfile::tempdir().expect("temporary model cache directory");
    let path = temp.path().join("models.json");
    let cache = FileModelsCache::new(path.clone(), Duration::from_secs(3600));
    let corrupted = b"{not valid json";
    tokio::fs::write(&path, corrupted)
        .await
        .expect("write corrupt cache fixture");

    cache
        .load("current-client")
        .await
        .expect_err("corrupted cache must not be a normal miss");
    cache
        .refresh_ttl("current-client")
        .await
        .expect_err("corrupted cache must not be renewed");
    assert_eq!(
        tokio::fs::read(&path).await.expect("read preserved corrupt bytes"),
        corrupted.to_vec()
    );
}
