use super::*;
use pretty_assertions::assert_eq;

fn fixture(endpoint: &str) -> ModelProviderInfo {
    let mut provider = ModelProviderInfo::create_openai_provider(Some(endpoint.to_string()));
    provider.supports_websockets = false;
    provider
}

#[test]
fn fixture_endpoint_requires_an_exact_literal_loopback_origin() {
    for endpoint in ["http://127.0.0.1:47813/v1", "http://[::1]:47813/v1"] {
        assert!(is_literal_fixture_endpoint(endpoint), "{endpoint}");
    }
    for endpoint in [
        "https://api.openai.com/v1",
        "https://chatgpt.com/backend-api/codex",
        "http://example.com:47813/v1",
        "http://localhost:47813/v1",
        "http://192.0.2.1:47813/v1",
        "http://127.0.0.1/v1",
        "http://127.0.0.1:0/v1",
        "http://127.0.0.1:80/v1",
        "http://127.1:47813/v1",
        "http://2130706433:47813/v1",
        "http://127.0.0.1:47813/v1/",
        "http://127.0.0.1:47813/backend-api/codex",
        "http://127.0.0.1:47813/v1?route=other",
        "http://127.0.0.1:47813/v1#fragment",
        "http://user@127.0.0.1:47813/v1",
        "https://127.0.0.1:47813/v1",
        "ws://127.0.0.1:47813/v1",
    ] {
        assert!(!is_literal_fixture_endpoint(endpoint), "{endpoint}");
        let provider = fixture(endpoint);
        assert!(
            OpenAiFixtureMetadataLease::for_owned_test_provider(
                &provider,
                OPENAI_PROVIDER_ID,
                &provider,
            )
            .is_none(),
            "{endpoint}",
        );
    }
}

#[test]
fn replacement_provider_does_not_inherit_a_fixture_capability() {
    let provider = fixture("http://127.0.0.1:47813/v1");
    let mut replacement = provider.clone();
    replacement.name = "Test Responses".to_string();
    assert!(
        OpenAiFixtureMetadataLease::for_owned_test_provider(
            &provider,
            OPENAI_PROVIDER_ID,
            &replacement,
        )
        .is_none()
    );
    assert!(
        OpenAiFixtureMetadataLease::for_owned_test_provider(&provider, "third-party", &provider)
            .is_none()
    );
    // Supplying the replacement as the alleged origin cannot mint a lease.
    assert!(
        OpenAiFixtureMetadataLease::for_owned_test_provider(
            &replacement,
            OPENAI_PROVIDER_ID,
            &replacement,
        )
        .is_none()
    );
    let mut changed = provider.clone();
    changed.requires_openai_auth = false;
    assert!(
        OpenAiFixtureMetadataLease::for_owned_test_provider(
            &provider,
            OPENAI_PROVIDER_ID,
            &changed,
        )
        .is_none()
    );
    changed = provider.clone();
    changed.env_key = Some("THIRD_PARTY_KEY".to_string());
    assert!(
        OpenAiFixtureMetadataLease::for_owned_test_provider(
            &provider,
            OPENAI_PROVIDER_ID,
            &changed,
        )
        .is_none()
    );
    changed = provider.clone();
    changed.http_headers = None;
    assert!(
        OpenAiFixtureMetadataLease::for_owned_test_provider(
            &provider,
            OPENAI_PROVIDER_ID,
            &changed,
        )
        .is_none()
    );
    changed = provider.clone();
    changed.base_url = Some("http://127.0.0.1:47814/v1".to_string());
    assert!(
        OpenAiFixtureMetadataLease::for_owned_test_provider(
            &provider,
            OPENAI_PROVIDER_ID,
            &changed,
        )
        .is_none()
    );
}

#[test]
fn transport_tuning_is_bound_into_the_final_snapshot() {
    let provider = fixture("http://127.0.0.1:47813/v1");
    let mut configured = provider.clone();
    configured.request_max_retries = Some(1);
    configured.stream_max_retries = Some(0);
    configured.stream_idle_timeout_ms = Some(100);
    configured.websocket_connect_timeout_ms = Some(200);
    configured.supports_websockets = true;
    let lease = OpenAiFixtureMetadataLease::for_owned_test_provider(
        &provider,
        OPENAI_PROVIDER_ID,
        &configured,
    )
    .expect("transport-only tuning keeps the explicit fixture");
    assert!(lease.matches_config(OPENAI_PROVIDER_ID, &configured));
    assert!(!lease.matches_config("third-party", &configured));
    assert!(!lease.matches_provider(&provider));
    configured.stream_idle_timeout_ms = Some(101);
    assert!(!lease.matches_provider(&configured));
}

#[test]
fn fixture_request_uses_exact_endpoint_and_provider_snapshot() {
    let provider = fixture("http://127.0.0.1:47813/v1");
    let lease = OpenAiFixtureMetadataLease::for_owned_test_provider(
        &provider,
        OPENAI_PROVIDER_ID,
        &provider,
    )
    .expect("owned fixture");
    assert!(lease.accepts_request(&provider, "http://127.0.0.1:47813/v1"));
    for endpoint in [
        "http://127.0.0.1:47814/v1",
        "http://127.0.0.1:47813/v1/",
        "http://127.0.0.1:47813/v1?route=other",
        "https://chatgpt.com/backend-api/codex",
        "https://proxy.example.com/v1",
    ] {
        assert!(!lease.accepts_request(&provider, endpoint), "{endpoint}");
    }
    let mut changed = provider;
    changed.name = "Test Responses".to_string();
    assert!(!lease.accepts_request(&changed, "http://127.0.0.1:47813/v1"));
}

#[test]
fn fixture_lease_lifetime_is_owned_by_explicit_clones() {
    let provider = fixture("http://127.0.0.1:47813/v1");
    let lease = OpenAiFixtureMetadataLease::for_owned_test_provider(
        &provider,
        OPENAI_PROVIDER_ID,
        &provider,
    )
    .expect("owned fixture");
    let weak = Arc::downgrade(&lease);
    let clone = Arc::clone(&lease);
    drop(lease);
    assert!(weak.upgrade().is_some());
    assert!(clone.matches_provider(&provider));
    assert_eq!(Arc::strong_count(&clone), 1);
    drop(clone);
    assert!(weak.upgrade().is_none());
}

#[test]
fn fixture_debug_does_not_disclose_provider_values() {
    let provider = fixture("http://127.0.0.1:47813/v1");
    let lease = OpenAiFixtureMetadataLease::for_owned_test_provider(
        &provider,
        OPENAI_PROVIDER_ID,
        &provider,
    )
    .expect("owned fixture");
    let debug = format!("{lease:?}");
    assert!(!debug.contains("127.0.0.1"));
    assert!(!debug.contains("47813"));
    assert!(!debug.contains("OPENAI_ORGANIZATION"));
}
