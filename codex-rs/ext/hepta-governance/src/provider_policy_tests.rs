use std::sync::Arc;

use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION;
use codex_extension_api::ModelProviderInvocationInput;
use codex_extension_api::ModelProviderPolicyDecision;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderSha256Digest;
use codex_extension_api::ModelProviderTerminal;
use codex_extension_api::ModelProviderTransport;
use codex_hepta_contracts::GovernanceMode;
use codex_hepta_contracts::ProviderTerminal as StoredTerminal;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use crate::GovernanceState;
use crate::install_with_mode;
use crate::provider_binding::provider_intent;

struct Digests {
    provider_config: ModelProviderSha256Digest,
    endpoint: ModelProviderSha256Digest,
    logical: ModelProviderSha256Digest,
    wire: ModelProviderSha256Digest,
}

fn sqlite_config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

async fn evidence(temp: &TempDir) -> Arc<HeptaEvidenceStore> {
    Arc::new(
        HeptaEvidenceStore::open(&sqlite_config(temp))
            .await
            .expect("open evidence"),
    )
}

fn stores() -> (ExtensionData, ExtensionData, ExtensionData) {
    (
        ExtensionData::new("session-1"),
        ExtensionData::new("thread-1"),
        ExtensionData::new("turn-1"),
    )
}

fn api_digest(bytes: &[u8]) -> ModelProviderSha256Digest {
    ModelProviderSha256Digest::parse(Sha256Digest::for_bytes(bytes).as_str())
        .expect("fixture digest")
}

fn digests(endpoint: &[u8]) -> Digests {
    Digests {
        provider_config: api_digest(b"provider-config"),
        endpoint: api_digest(endpoint),
        logical: api_digest(b"logical-request"),
        wire: api_digest(b"wire-request"),
    }
}

fn input<'a>(
    session: &'a ExtensionData,
    thread: &'a ExtensionData,
    turn: &'a ExtensionData,
    attempt_id: &'a str,
    request_binding_id: &'a str,
    digests: &'a Digests,
) -> ModelProviderInvocationInput<'a> {
    ModelProviderInvocationInput {
        schema_version: MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION,
        session_store: session,
        thread_store: thread,
        turn_store: turn,
        attempt_id,
        request_binding_id,
        thread_id: "thread-1",
        turn_id: "turn-1",
        request_kind: ModelProviderRequestKind::Turn,
        provider_id: "provider-fixture",
        provider_config_sha256: &digests.provider_config,
        model: "model-fixture",
        transport: ModelProviderTransport::Http,
        endpoint_sha256: &digests.endpoint,
        logical_request_sha256: &digests.logical,
        wire_semantic_sha256: &digests.wire,
        ephemeral_input_sha256: None,
        ephemeral_input_witness_sha256: None,
        previous_response_id_sha256: None,
        generate: true,
    }
}

#[test]
fn provider_binding_requires_an_all_or_none_ephemeral_digest_pair() {
    let (session, thread, turn) = stores();
    let digests = digests(b"https://provider.invalid/responses");
    let ephemeral = api_digest(b"ephemeral-input");
    let mut invocation = input(
        &session,
        &thread,
        &turn,
        "attempt-ephemeral",
        "binding-ephemeral",
        &digests,
    );
    invocation.ephemeral_input_sha256 = Some(&ephemeral);

    let error = provider_intent(&invocation).expect_err("orphaned digest must fail closed");
    assert_eq!(
        error.reason_code(),
        "hepta_provider_ephemeral_input_incomplete"
    );
}

#[test]
fn provider_binding_maps_ephemeral_digests_into_exact_request_identity() {
    let (session, thread, turn) = stores();
    let digests = digests(b"https://provider.invalid/responses");
    let ephemeral = api_digest(b"ephemeral-input");
    let witness = api_digest(b"ephemeral-witness");
    let mut invocation = input(
        &session,
        &thread,
        &turn,
        "attempt-ephemeral",
        "binding-ephemeral",
        &digests,
    );
    invocation.ephemeral_input_sha256 = Some(&ephemeral);
    invocation.ephemeral_input_witness_sha256 = Some(&witness);

    let intent = provider_intent(&invocation).expect("complete pair should bind");
    assert!(
        intent
            .request_binding_id
            .as_str()
            .starts_with("provider-request:v1:")
    );
    assert_eq!(
        intent.binding.ephemeral_input_sha256,
        Some(Sha256Digest::for_bytes(b"ephemeral-input"))
    );
    assert_eq!(
        intent.binding.ephemeral_input_witness_sha256,
        Some(Sha256Digest::for_bytes(b"ephemeral-witness"))
    );
}

#[tokio::test]
async fn orphaned_ephemeral_digests_are_blocked_without_evidence_in_every_mode() {
    for mode in [GovernanceMode::Shadow, GovernanceMode::Enforce] {
        for input_present in [true, false] {
            let temp = TempDir::new().expect("temp dir");
            let evidence = evidence(&temp).await;
            let state = GovernanceState::enabled(mode, Ok(evidence.clone()));
            let (session, thread, turn) = stores();
            let digests = digests(b"https://provider.invalid/responses");
            let ephemeral = api_digest(b"ephemeral-input");
            let witness = api_digest(b"ephemeral-witness");
            let mut invocation = input(
                &session,
                &thread,
                &turn,
                "attempt-orphaned",
                "binding-orphaned",
                &digests,
            );
            let expected_reason = if input_present {
                invocation.ephemeral_input_sha256 = Some(&ephemeral);
                "hepta_ephemeral_input_witness_missing"
            } else {
                invocation.ephemeral_input_witness_sha256 = Some(&witness);
                "hepta_ephemeral_input_witness_orphaned"
            };

            let decision = state
                .begin_provider(invocation)
                .await
                .expect("orphaned digest should produce a stable block");
            assert!(matches!(
                decision,
                ModelProviderPolicyDecision::Block { ref reason_code, .. }
                    if reason_code == expected_reason
            ));
            assert_eq!(
                evidence
                    .pending_provider_attempt_count()
                    .await
                    .expect("pending count"),
                0
            );
        }
    }
}

#[tokio::test]
async fn complete_ephemeral_binding_is_blocked_when_governance_is_disabled() {
    let state = GovernanceState::disabled();
    let (session, thread, turn) = stores();
    let digests = digests(b"https://provider.invalid/responses");
    let ephemeral = api_digest(b"ephemeral-input");
    let witness = api_digest(b"ephemeral-witness");
    let mut invocation = input(
        &session,
        &thread,
        &turn,
        "attempt-disabled",
        "binding-disabled",
        &digests,
    );
    invocation.ephemeral_input_sha256 = Some(&ephemeral);
    invocation.ephemeral_input_witness_sha256 = Some(&witness);

    let decision = state
        .begin_provider(invocation)
        .await
        .expect("disabled governance should produce a stable block");
    assert!(matches!(
        decision,
        ModelProviderPolicyDecision::Block { ref reason_code, .. }
            if reason_code == "hepta_ephemeral_input_governance_disabled"
    ));
}

fn completed() -> ModelProviderTerminal {
    ModelProviderTerminal::Completed {
        response_id_sha256: api_digest(b"response-id"),
        response_items_sha256: api_digest(b"response-items"),
        token_usage_sha256: api_digest(b"token-usage"),
        end_turn: Some(true),
    }
}

fn unary_completed() -> ModelProviderTerminal {
    ModelProviderTerminal::CompletedUnary {
        response_items_sha256: api_digest(b"compacted-items"),
    }
}

#[test]
fn installing_governance_registers_one_shared_provider_policy_extension() {
    let mut builder = ExtensionRegistryBuilder::<()>::new();
    install_with_mode(&mut builder, None, GovernanceMode::Shadow, |_: &()| true);
    let registry = builder.build();

    assert_eq!(registry.thread_lifecycle_contributors().len(), 1);
    assert_eq!(registry.tool_policy_contributors().len(), 1);
    assert_eq!(registry.model_provider_policy_contributors().len(), 1);
}

#[tokio::test]
async fn inserted_intent_finishes_exact_terminal_without_plaintext_host_ids() {
    const HOST_ATTEMPT: &str = "host-attempt-secret-fixture-701";
    const HOST_BINDING: &str = "host-binding-secret-fixture-702";
    const ENDPOINT: &[u8] = b"https://provider.invalid/responses?secret=703";

    let temp = TempDir::new().expect("temp dir");
    let evidence = evidence(&temp).await;
    let state = GovernanceState::enabled(GovernanceMode::Enforce, Ok(evidence.clone()));
    let (session, thread, turn) = stores();
    let digests = digests(ENDPOINT);
    let invocation = input(
        &session,
        &thread,
        &turn,
        HOST_ATTEMPT,
        HOST_BINDING,
        &digests,
    );
    let expected = provider_intent(&invocation).expect("convert intent");
    let ModelProviderPolicyDecision::Allow { lease } = state
        .begin_provider(invocation)
        .await
        .expect("provider begin")
    else {
        panic!("first durable insert must own an allow lease");
    };

    lease.finish(completed()).await.expect("persist terminal");

    let receipt = evidence
        .get_provider_attempt(&expected.attempt_id)
        .await
        .expect("read attempt")
        .expect("attempt exists")
        .receipt
        .expect("terminal exists")
        .receipt;
    assert!(matches!(receipt.terminal, StoredTerminal::Completed { .. }));
    let json = serde_json::to_string(&receipt).expect("serialize receipt");
    for forbidden in [
        HOST_ATTEMPT,
        HOST_BINDING,
        std::str::from_utf8(ENDPOINT).unwrap(),
    ] {
        assert!(!json.contains(forbidden));
    }
    assert_eq!(
        receipt.intent.attempt_nonce_sha256,
        Sha256Digest::for_bytes(HOST_ATTEMPT.as_bytes())
    );
    assert_eq!(
        receipt.intent.binding.host_request_binding_id_sha256,
        Sha256Digest::for_bytes(HOST_BINDING.as_bytes())
    );
}

#[tokio::test]
async fn unary_compaction_completion_maps_without_synthetic_response_fields() {
    let temp = TempDir::new().expect("temp dir");
    let evidence = evidence(&temp).await;
    let state = GovernanceState::enabled(GovernanceMode::Enforce, Ok(evidence.clone()));
    let (session, thread, turn) = stores();
    let digests = digests(b"compact-endpoint");
    let invocation = input(
        &session,
        &thread,
        &turn,
        "compact-attempt",
        "compact-binding",
        &digests,
    );
    let expected = provider_intent(&invocation).expect("convert intent");
    let ModelProviderPolicyDecision::Allow { lease } = state
        .begin_provider(invocation)
        .await
        .expect("provider begin")
    else {
        panic!("unary compaction must own its first attempt");
    };
    lease
        .finish(unary_completed())
        .await
        .expect("persist unary terminal");

    let terminal = evidence
        .get_provider_attempt(&expected.attempt_id)
        .await
        .expect("read attempt")
        .expect("attempt")
        .receipt
        .expect("receipt")
        .receipt
        .terminal;
    assert!(matches!(
        terminal,
        StoredTerminal::CompletedUnary {
            response_items_sha256
        } if response_items_sha256 == Sha256Digest::for_bytes(b"compacted-items")
    ));
}

#[tokio::test]
async fn exact_concurrent_attempt_has_one_owner_and_one_pending_block() {
    let temp = TempDir::new().expect("temp dir");
    let evidence = evidence(&temp).await;
    let state = GovernanceState::enabled(GovernanceMode::Enforce, Ok(evidence));
    let (session, thread, turn) = stores();
    let digests = digests(b"endpoint");

    let (left, right) = tokio::join!(
        state.begin_provider(input(
            &session,
            &thread,
            &turn,
            "attempt-concurrent",
            "binding-concurrent",
            &digests,
        )),
        state.begin_provider(input(
            &session,
            &thread,
            &turn,
            "attempt-concurrent",
            "binding-concurrent",
            &digests,
        ))
    );
    let mut owner = None;
    let mut blocked = 0;
    for decision in [left.expect("left"), right.expect("right")] {
        match decision {
            ModelProviderPolicyDecision::Allow { lease } => owner = Some(lease),
            ModelProviderPolicyDecision::Block { reason_code, .. } => {
                assert_eq!(reason_code, "hepta_provider_attempt_pending");
                blocked += 1;
            }
        }
    }
    assert_eq!(blocked, 1);
    owner
        .expect("one exact owner")
        .finish(ModelProviderTerminal::NotDispatched {
            reason_code: "cancelled_before_send".to_string(),
        })
        .await
        .expect("finish owner");
}

#[tokio::test]
async fn pending_completed_and_indeterminate_bindings_block_fresh_attempts() {
    for (terminal, expected_reason) in [
        (None, "hepta_provider_request_pending"),
        (Some(unary_completed()), "hepta_provider_request_completed"),
        (
            Some(ModelProviderTerminal::Indeterminate {
                reason_code: "stream_eof_before_completed".to_string(),
                partial_response_sha256: None,
            }),
            "hepta_provider_request_indeterminate",
        ),
    ] {
        let temp = TempDir::new().expect("temp dir");
        let evidence = evidence(&temp).await;
        let state = GovernanceState::enabled(GovernanceMode::Enforce, Ok(evidence));
        let (session, thread, turn) = stores();
        let digests = digests(b"endpoint");
        let ModelProviderPolicyDecision::Allow { lease } = state
            .begin_provider(input(
                &session,
                &thread,
                &turn,
                "attempt-first",
                "binding-terminal",
                &digests,
            ))
            .await
            .expect("first begin")
        else {
            panic!("first attempt must own a lease");
        };
        if let Some(terminal) = terminal {
            lease.finish(terminal).await.expect("finish first");
        }
        let retry = state
            .begin_provider(input(
                &session,
                &thread,
                &turn,
                "attempt-retry",
                "binding-terminal",
                &digests,
            ))
            .await
            .expect("typed retry block");
        assert!(matches!(
            retry,
            ModelProviderPolicyDecision::Block { reason_code, .. }
                if reason_code == expected_reason
        ));
    }
}

#[tokio::test]
async fn not_dispatched_binding_can_be_claimed_again() {
    let temp = TempDir::new().expect("temp dir");
    let evidence = evidence(&temp).await;
    let state = GovernanceState::enabled(GovernanceMode::Enforce, Ok(evidence));
    let (session, thread, turn) = stores();
    let digests = digests(b"endpoint");
    let ModelProviderPolicyDecision::Allow { lease } = state
        .begin_provider(input(
            &session,
            &thread,
            &turn,
            "attempt-not-dispatched",
            "binding-retry-safe",
            &digests,
        ))
        .await
        .expect("first begin")
    else {
        panic!("first attempt must own a lease");
    };
    lease
        .finish(ModelProviderTerminal::NotDispatched {
            reason_code: "transport_not_entered".to_string(),
        })
        .await
        .expect("finish safe attempt");

    assert!(matches!(
        state
            .begin_provider(input(
                &session,
                &thread,
                &turn,
                "attempt-retry",
                "binding-retry-safe",
                &digests,
            ))
            .await
            .expect("retry begin"),
        ModelProviderPolicyDecision::Allow { .. }
    ));
}

#[tokio::test]
async fn shadow_exact_replay_lease_cannot_finalize_stale_pending_intent() {
    let temp = TempDir::new().expect("temp dir");
    let evidence = evidence(&temp).await;
    let state = GovernanceState::enabled(GovernanceMode::Shadow, Ok(evidence.clone()));
    let (session, thread, turn) = stores();
    let digests = digests(b"endpoint");
    let first = state
        .begin_provider(input(
            &session,
            &thread,
            &turn,
            "attempt-shadow",
            "binding-shadow",
            &digests,
        ))
        .await
        .expect("first begin");
    drop(first);

    let ModelProviderPolicyDecision::Allow { lease } = state
        .begin_provider(input(
            &session,
            &thread,
            &turn,
            "attempt-shadow",
            "binding-shadow",
            &digests,
        ))
        .await
        .expect("shadow replay")
    else {
        panic!("shadow replay remains observational");
    };
    lease.finish(completed()).await.expect("detached finish");
    assert_eq!(
        evidence
            .pending_provider_attempt_count()
            .await
            .expect("pending count"),
        1
    );
}

#[tokio::test]
async fn unavailable_backend_blocks_enforce_and_detaches_shadow() {
    let (session, thread, turn) = stores();
    let digests = digests(b"endpoint");
    let unavailable = Err(Arc::<str>::from("offline"));
    let enforce = GovernanceState::enabled(GovernanceMode::Enforce, unavailable.clone());
    assert!(matches!(
        enforce
            .begin_provider(input(
                &session,
                &thread,
                &turn,
                "attempt-unavailable",
                "binding-unavailable",
                &digests,
            ))
            .await
            .expect("typed block"),
        ModelProviderPolicyDecision::Block { reason_code, .. }
            if reason_code == "hepta_provider_evidence_unavailable"
    ));

    let shadow = GovernanceState::enabled(GovernanceMode::Shadow, unavailable);
    let ModelProviderPolicyDecision::Allow { lease } = shadow
        .begin_provider(input(
            &session,
            &thread,
            &turn,
            "attempt-unavailable",
            "binding-unavailable",
            &digests,
        ))
        .await
        .expect("shadow allow")
    else {
        panic!("shadow unavailable is observational");
    };
    lease
        .finish(unary_completed())
        .await
        .expect("detached finish");
}

#[tokio::test]
async fn invalid_terminal_reason_keeps_enforced_intent_pending() {
    let temp = TempDir::new().expect("temp dir");
    let evidence = evidence(&temp).await;
    let state = GovernanceState::enabled(GovernanceMode::Enforce, Ok(evidence.clone()));
    let (session, thread, turn) = stores();
    let digests = digests(b"endpoint");
    let ModelProviderPolicyDecision::Allow { lease } = state
        .begin_provider(input(
            &session,
            &thread,
            &turn,
            "attempt-invalid-terminal",
            "binding-invalid-terminal",
            &digests,
        ))
        .await
        .expect("begin")
    else {
        panic!("first attempt must own lease");
    };
    let error = lease
        .finish(ModelProviderTerminal::Rejected {
            reason_code: "contains secret whitespace".to_string(),
        })
        .await
        .expect_err("invalid reason must fail closed");
    assert_eq!(error.reason_code(), "hepta_provider_reason_code_invalid");
    assert_eq!(
        evidence
            .pending_provider_attempt_count()
            .await
            .expect("pending count"),
        1
    );
}
