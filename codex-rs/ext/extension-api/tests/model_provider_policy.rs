#![allow(clippy::expect_used)]

use std::sync::Arc;
use std::sync::Mutex;

use codex_extension_api::ExtensionData;
use codex_extension_api::MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION;
use codex_extension_api::ModelProviderAttemptLease;
use codex_extension_api::ModelProviderInvocationInput;
use codex_extension_api::ModelProviderPolicyContributor;
use codex_extension_api::ModelProviderPolicyDecision;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderSha256Digest;
use codex_extension_api::ModelProviderTerminal;
use codex_extension_api::ModelProviderTransport;
use pretty_assertions::assert_eq;

fn digest(byte: char) -> ModelProviderSha256Digest {
    ModelProviderSha256Digest::parse(byte.to_string().repeat(64))
        .expect("test digest should be valid")
}

fn invocation_input<'a>(
    session_store: &'a ExtensionData,
    thread_store: &'a ExtensionData,
    turn_store: &'a ExtensionData,
    digests: &'a [ModelProviderSha256Digest; 4],
) -> ModelProviderInvocationInput<'a> {
    ModelProviderInvocationInput {
        schema_version: MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION,
        session_store,
        thread_store,
        turn_store,
        attempt_id: "attempt-1",
        request_binding_id: "request-1",
        thread_id: "thread-1",
        turn_id: "turn-1",
        request_kind: ModelProviderRequestKind::Turn,
        provider_id: "provider-1",
        provider_config_sha256: &digests[0],
        model: "model-1",
        transport: ModelProviderTransport::Http,
        endpoint_sha256: &digests[1],
        logical_request_sha256: &digests[2],
        wire_semantic_sha256: &digests[3],
        ephemeral_input_sha256: None,
        ephemeral_input_witness_sha256: None,
        previous_response_id_sha256: None,
        generate: true,
    }
}

#[test]
fn digest_accepts_only_canonical_lowercase_sha256() {
    assert_eq!(digest('a').as_str(), "a".repeat(64));

    for invalid in [
        "a".repeat(63),
        "a".repeat(65),
        "A".repeat(64),
        "g".repeat(64),
    ] {
        let error = ModelProviderSha256Digest::parse(invalid)
            .expect_err("non-canonical digest should be rejected");
        assert_eq!(error.reason_code(), "invalid_sha256_digest");
    }
}

struct DefaultContributor;

impl ModelProviderPolicyContributor for DefaultContributor {}

#[tokio::test]
async fn default_contributor_returns_one_consumable_noop_lease() {
    let session_store = ExtensionData::new("session");
    let thread_store = ExtensionData::new("thread");
    let turn_store = ExtensionData::new("turn");
    let digests = [digest('a'), digest('b'), digest('c'), digest('d')];

    let decision = DefaultContributor
        .begin(invocation_input(
            &session_store,
            &thread_store,
            &turn_store,
            &digests,
        ))
        .await
        .expect("default provider policy should allow");
    let ModelProviderPolicyDecision::Allow { lease } = decision else {
        panic!("default provider policy should return an allow lease");
    };

    lease
        .finish(ModelProviderTerminal::NotDispatched {
            reason_code: "test_only".to_string(),
        })
        .await
        .expect("default lease should finish successfully");
}

struct RecordingLease {
    terminals: Arc<Mutex<Vec<ModelProviderTerminal>>>,
}

impl ModelProviderAttemptLease for RecordingLease {
    fn finish(
        self: Box<Self>,
        terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        Box::pin(async move {
            self.terminals
                .lock()
                .expect("terminal lock should not be poisoned")
                .push(terminal);
            Ok(())
        })
    }
}

struct RecordingContributor {
    terminals: Arc<Mutex<Vec<ModelProviderTerminal>>>,
}

impl ModelProviderPolicyContributor for RecordingContributor {
    fn begin<'a>(
        &'a self,
        input: ModelProviderInvocationInput<'a>,
    ) -> ModelProviderPolicyFuture<'a, ModelProviderPolicyDecision> {
        Box::pin(async move {
            assert_eq!(
                input.schema_version,
                MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION
            );
            assert_eq!(input.thread_id, "thread-1");
            assert_eq!(input.logical_request_sha256.as_str(), "c".repeat(64));
            assert_eq!(input.wire_semantic_sha256.as_str(), "d".repeat(64));
            assert!(input.ephemeral_input_sha256.is_none());
            assert!(input.ephemeral_input_witness_sha256.is_none());
            Ok(ModelProviderPolicyDecision::Allow {
                lease: Box::new(RecordingLease {
                    terminals: Arc::clone(&self.terminals),
                }),
            })
        })
    }
}

#[tokio::test]
async fn allow_lease_delivers_exact_owned_terminal() {
    let terminals = Arc::new(Mutex::new(Vec::new()));
    let contributor = RecordingContributor {
        terminals: Arc::clone(&terminals),
    };
    let session_store = ExtensionData::new("session");
    let thread_store = ExtensionData::new("thread");
    let turn_store = ExtensionData::new("turn");
    let digests = [digest('a'), digest('b'), digest('c'), digest('d')];

    let decision = contributor
        .begin(invocation_input(
            &session_store,
            &thread_store,
            &turn_store,
            &digests,
        ))
        .await
        .expect("recording contributor should allow");
    assert_eq!(format!("{decision:?}"), "Allow { lease: \"<opaque>\" }");
    let ModelProviderPolicyDecision::Allow { lease } = decision else {
        panic!("recording contributor should return an allow lease");
    };
    let terminal = ModelProviderTerminal::Completed {
        response_id_sha256: digest('e'),
        response_items_sha256: digest('f'),
        token_usage_sha256: digest('0'),
        end_turn: Some(true),
    };

    lease
        .finish(terminal.clone())
        .await
        .expect("recording lease should finish");

    assert_eq!(
        terminals
            .lock()
            .expect("terminal lock should not be poisoned")
            .as_slice(),
        [terminal]
    );
}
