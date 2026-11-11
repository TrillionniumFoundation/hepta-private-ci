use crate::ModelProviderInfo;
use crate::provider_accepts_internal_chat_message_metadata;
use crate::test_support::allow_internal_metadata_for_mock;
use pretty_assertions::assert_eq;

const MOCK_URL: &str = "http://127.0.0.1:42117/v1?fixture=original";

#[test]
fn ordinary_loopback_and_friendly_names_do_not_grant_metadata() {
    let mut provider = ModelProviderInfo::create_openai_provider(Some(MOCK_URL.to_string()));
    assert!(!provider_accepts_internal_chat_message_metadata(MOCK_URL));
    assert!(!provider.accepts_internal_chat_message_metadata_for_request(MOCK_URL));
    allow_internal_metadata_for_mock(&mut provider).expect("explicit local mock");
    assert!(provider.accepts_internal_chat_message_metadata_for_request(MOCK_URL));
    assert!(
        provider
            .clone()
            .accepts_internal_chat_message_metadata_for_request(MOCK_URL)
    );
    let unrelated = ModelProviderInfo::create_openai_provider(Some(MOCK_URL.to_string()));
    assert!(!unrelated.accepts_internal_chat_message_metadata_for_request(MOCK_URL));
}

#[test]
fn mock_permission_is_bound_to_the_full_current_and_resolved_url() {
    let mut provider = ModelProviderInfo::create_openai_provider(Some(MOCK_URL.to_string()));
    allow_internal_metadata_for_mock(&mut provider).expect("explicit local mock");
    for changed in [
        "ws://127.0.0.1:42117/v1?fixture=original",
        "http://127.0.0.2:42117/v1?fixture=original",
        "http://127.0.0.1:42118/v1?fixture=original",
        "http://127.0.0.1:42117/other?fixture=original",
        "http://127.0.0.1:42117/v1?fixture=rebound",
    ] {
        assert!(!provider.accepts_internal_chat_message_metadata_for_request(changed));
        let mut rebound = provider.clone();
        rebound.base_url = Some(changed.to_string());
        assert!(!rebound.accepts_internal_chat_message_metadata_for_request(MOCK_URL));
        assert!(!rebound.accepts_internal_chat_message_metadata_for_request(changed));
    }
    provider.query_params = Some(Default::default());
    assert!(!provider.accepts_internal_chat_message_metadata_for_request(MOCK_URL));
}

#[test]
fn configuration_roundtrip_and_forged_fields_cannot_recreate_a_mock_permission() {
    let mut provider = ModelProviderInfo::create_openai_provider(Some(MOCK_URL.to_string()));
    allow_internal_metadata_for_mock(&mut provider).expect("explicit local mock");
    let encoded = toml::to_string(&provider).expect("serialize provider");
    assert!(!encoded.contains("mock_internal_chat_metadata"));
    let decoded: ModelProviderInfo = toml::from_str(&encoded).expect("deserialize provider");
    assert_eq!(decoded.mock_internal_chat_metadata, None);
    assert!(!decoded.accepts_internal_chat_message_metadata_for_request(MOCK_URL));
    let forged =
        format!("mock_internal_chat_metadata = {{ base_url = \"{MOCK_URL}\" }}\n{encoded}");
    let decoded: ModelProviderInfo = toml::from_str(&forged).expect("ignored skipped field");
    assert_eq!(decoded.mock_internal_chat_metadata, None);
    assert!(!decoded.accepts_internal_chat_message_metadata_for_request(MOCK_URL));
}

#[test]
fn mock_factory_rejects_remote_ambiguous_and_credentialed_addresses() {
    for base_url in [
        "http://example.com:42117/v1",
        "http://127.0.0.1.example.com:42117/v1",
        "http://localhost:42117/v1",
        "http://0.0.0.0:42117/v1",
        "https://api.openai.com/v1",
        "http://user@127.0.0.1:42117/v1",
        "http://127.0.0.1/v1",
        "http://127.0.0.1:0/v1",
        "http://127.0.0.1:42117/v1#fragment",
    ] {
        let mut provider = ModelProviderInfo::create_openai_provider(Some(base_url.to_string()));
        assert!(
            allow_internal_metadata_for_mock(&mut provider).is_err(),
            "{base_url}"
        );
        assert_eq!(provider.mock_internal_chat_metadata, None);
    }
    for base_url in ["http://[::1]:42117/v1", "ws://127.0.0.1:42117/v1"] {
        let mut provider = ModelProviderInfo::create_openai_provider(Some(base_url.to_string()));
        allow_internal_metadata_for_mock(&mut provider).expect("explicit literal loopback");
        assert!(provider.accepts_internal_chat_message_metadata_for_request(base_url));
    }
}
