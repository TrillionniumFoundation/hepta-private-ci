use super::*;
use codex_config::AbsolutePathBuf;
use codex_config::CloudConfigFragment;
use codex_config::CloudConfigTomlBundle;
use codex_config::CloudRequirementsFragment;
use codex_config::CloudRequirementsTomlBundle;
use pretty_assertions::assert_eq;
use std::path::Path;
use tempfile::tempdir;

fn test_bundle() -> CloudConfigBundle {
    CloudConfigBundle {
        config_toml: CloudConfigTomlBundle {
            enterprise_managed: vec![CloudConfigFragment {
                id: "cfg_1".to_string(),
                name: "Base config".to_string(),
                contents: "model = \"gpt-5\"".to_string(),
            }],
        },
        requirements_toml: CloudRequirementsTomlBundle {
            enterprise_managed: vec![CloudRequirementsFragment {
                id: "req_1".to_string(),
                name: "Base requirements".to_string(),
                contents: "allowed_approval_policies = [\"never\"]".to_string(),
            }],
        },
    }
}

fn signed_cache_file(
    signed_payload: CloudConfigBundleCacheSignedPayload,
) -> CloudConfigBundleCacheFile {
    let payload_bytes = cache_payload_bytes(&signed_payload).expect("payload bytes");
    CloudConfigBundleCacheFile {
        signature: sign_cache_payload(&payload_bytes).expect("signature"),
        signed_payload,
    }
}

fn valid_signed_payload() -> CloudConfigBundleCacheSignedPayload {
    let cached_at = Timestamp::now();
    CloudConfigBundleCacheSignedPayload {
        version: CLOUD_CONFIG_BUNDLE_CACHE_VERSION,
        cached_at,
        expires_at: cached_at
            .expires_after(Duration::from_secs(30 * 60))
            .expect("expiry"),
        chatgpt_user_id: Some("user-12345".to_string()),
        account_id: Some("account-12345".to_string()),
        bundle: test_bundle(),
    }
}

fn write_cache_file(cache: &CloudConfigBundleCache, cache_file: &CloudConfigBundleCacheFile) {
    std::fs::write(
        cache.path(),
        serde_json::to_vec_pretty(cache_file).expect("serialize cache"),
    )
    .expect("write cache");
}

fn create_test_cache(codex_home: &Path) -> CloudConfigBundleCache {
    CloudConfigBundleCache::new(AbsolutePathBuf::resolve_path_against_base(codex_home, "/"))
}

#[tokio::test]
async fn save_writes_signed_payload_and_loads_for_matching_identity() {
    let codex_home = tempdir().expect("tempdir");
    let cache = create_test_cache(codex_home.path());
    let bundle = test_bundle();

    cache
        .save(
            Some("user-12345".to_string()),
            Some("account-12345".to_string()),
            bundle.clone(),
        )
        .await
        .expect("save cache");

    let cache_file: CloudConfigBundleCacheFile =
        serde_json::from_slice(&std::fs::read(cache.path()).expect("read cache"))
            .expect("parse cache");
    assert!(
        cache_file.signed_payload.expires_at
            <= cache_file
                .signed_payload
                .cached_at
                .expires_after(Duration::from_secs(60 * 60))
                .expect("expiry")
    );
    assert!(cache_file.signed_payload.expires_at > cache_file.signed_payload.cached_at);
    assert_eq!(
        cache_file,
        signed_cache_file(CloudConfigBundleCacheSignedPayload {
            version: CLOUD_CONFIG_BUNDLE_CACHE_VERSION,
            cached_at: cache_file.signed_payload.cached_at,
            expires_at: cache_file.signed_payload.expires_at,
            chatgpt_user_id: Some("user-12345".to_string()),
            account_id: Some("account-12345".to_string()),
            bundle,
        })
    );

    assert_eq!(
        cache.load(Some("user-12345"), Some("account-12345")).await,
        Ok(cache_file.signed_payload)
    );
}

#[tokio::test]
async fn load_rejects_missing_request_identity_before_reading_cache_file() {
    let codex_home = tempdir().expect("tempdir");
    let cache = create_test_cache(codex_home.path());

    assert_eq!(
        cache
            .load(/*chatgpt_user_id*/ None, Some("account-12345"))
            .await,
        Err(CacheLoadStatus::AuthIdentityIncomplete)
    );
    assert_eq!(
        cache.load(Some("user-12345"), /*account_id*/ None).await,
        Err(CacheLoadStatus::AuthIdentityIncomplete)
    );
}

#[tokio::test]
async fn load_reports_missing_and_malformed_cache_files() {
    let codex_home = tempdir().expect("tempdir");
    let cache = create_test_cache(codex_home.path());

    assert_eq!(
        cache.load(Some("user-12345"), Some("account-12345")).await,
        Err(CacheLoadStatus::CacheFileNotFound)
    );

    std::fs::write(cache.path(), "{").expect("write malformed cache");
    assert!(matches!(
        cache.load(Some("user-12345"), Some("account-12345")).await,
        Err(CacheLoadStatus::CacheParseFailed(_))
    ));
}

#[tokio::test]
async fn load_rejects_tampered_payload() {
    let codex_home = tempdir().expect("tempdir");
    let cache = create_test_cache(codex_home.path());
    let mut cache_file = signed_cache_file(valid_signed_payload());
    cache_file
        .signed_payload
        .bundle
        .requirements_toml
        .enterprise_managed[0]
        .contents = "allowed_approval_policies = [\"on-request\"]".to_string();
    write_cache_file(&cache, &cache_file);

    assert_eq!(
        cache.load(Some("user-12345"), Some("account-12345")).await,
        Err(CacheLoadStatus::CacheSignatureInvalid)
    );
}

#[tokio::test]
async fn load_rejects_cache_for_incomplete_or_different_identity() {
    let codex_home = tempdir().expect("tempdir");
    let cache = create_test_cache(codex_home.path());
    let cache_file = signed_cache_file(valid_signed_payload());
    write_cache_file(&cache, &cache_file);

    assert_eq!(
        cache.load(Some("user-99999"), Some("account-12345")).await,
        Err(CacheLoadStatus::CacheIdentityMismatch)
    );

    let mut signed_payload = valid_signed_payload();
    signed_payload.chatgpt_user_id = None;
    write_cache_file(&cache, &signed_cache_file(signed_payload));

    assert_eq!(
        cache.load(Some("user-12345"), Some("account-12345")).await,
        Err(CacheLoadStatus::CacheIdentityIncomplete)
    );
}

#[tokio::test]
async fn load_rejects_expired_cache() {
    let codex_home = tempdir().expect("tempdir");
    let cache = create_test_cache(codex_home.path());
    let mut signed_payload = valid_signed_payload();
    signed_payload.expires_at = Timestamp::now() - time::Duration::seconds(1);
    write_cache_file(&cache, &signed_cache_file(signed_payload));

    assert_eq!(
        cache.load(Some("user-12345"), Some("account-12345")).await,
        Err(CacheLoadStatus::CacheExpired)
    );
}

#[tokio::test]
async fn load_rejects_unsupported_cache_version() {
    let codex_home = tempdir().expect("tempdir");
    let cache = create_test_cache(codex_home.path());
    let mut signed_payload = valid_signed_payload();
    signed_payload.version = 2;
    write_cache_file(&cache, &signed_cache_file(signed_payload));

    assert_eq!(
        cache.load(Some("user-12345"), Some("account-12345")).await,
        Err(CacheLoadStatus::CacheVersionUnsupported(2))
    );
}

#[tokio::test]
async fn original_signed_timestamp_bytes_survive_normalization_and_reject_tampering() {
    // Version-one canonical payload and HMAC were calculated independently with
    // Python's json/hmac/hashlib, using the original fixed field order.
    let original_payload = br#"{"version":1,"cached_at":"2026-11-19T12:34:56.100000001Z","expires_at":"2036-11-19T12:34:56.123400Z","chatgpt_user_id":"user-12345","account_id":"account-12345","bundle":{"config_toml":{"enterprise_managed":[]},"requirements_toml":{"enterprise_managed":[]}}}"#;
    let original_signature = "4if0RROVNa6Mh4PEa/WNt9q1eB39Wa+pM7bpHShCe5o=";
    let mut stored_payload: serde_json::Value =
        serde_json::from_slice(original_payload).expect("original JSON");
    stored_payload["cached_at"] = "2026-11-19T13:34:56.100000001+01:00".into();
    stored_payload["expires_at"] = "2036-11-19T12:34:56.1234UTC".into();
    let stored =
        serde_json::json!({"signed_payload":stored_payload,"signature":original_signature});
    let cache_file: CloudConfigBundleCacheFile =
        serde_json::from_value(stored.clone()).expect("legacy cache");
    assert_eq!(
        cache_payload_bytes(&cache_file.signed_payload).expect("payload"),
        original_payload
    );
    assert_eq!(
        sign_cache_payload(original_payload).expect("HMAC"),
        original_signature
    );

    let codex_home = tempdir().expect("tempdir");
    let cache = create_test_cache(codex_home.path());
    std::fs::write(
        cache.path(),
        serde_json::to_vec(&stored).expect("stored bytes"),
    )
    .expect("write cache");
    assert_eq!(
        cache.load(Some("user-12345"), Some("account-12345")).await,
        Ok(cache_file.signed_payload),
    );

    let mut tampered = stored;
    tampered["signed_payload"]["cached_at"] = "2026-11-19T13:34:56.100000002+01:00".into();
    std::fs::write(
        cache.path(),
        serde_json::to_vec(&tampered).expect("tampered bytes"),
    )
    .expect("write cache");
    assert_eq!(
        cache.load(Some("user-12345"), Some("account-12345")).await,
        Err(CacheLoadStatus::CacheSignatureInvalid),
    );
}
