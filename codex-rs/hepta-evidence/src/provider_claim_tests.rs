use codex_hepta_contracts::PROVIDER_EVIDENCE_SCHEMA_VERSION;
use codex_hepta_contracts::ProviderInvocationIntent;
use codex_hepta_contracts::ProviderInvocationReceipt;
use codex_hepta_contracts::ProviderRequestBinding;
use codex_hepta_contracts::ProviderRequestKind;
use codex_hepta_contracts::ProviderTerminal;
use codex_hepta_contracts::ProviderTransport;
use codex_hepta_contracts::Sha256Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use crate::HeptaEvidenceStore;
use crate::ProviderBindingState;
use crate::ProviderIntentClaimDisposition;

fn sqlite_config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn binding(wire: &[u8]) -> ProviderRequestBinding {
    ProviderRequestBinding {
        schema_version: PROVIDER_EVIDENCE_SCHEMA_VERSION,
        thread_id: "thread-1".to_string(),
        turn_id: "turn-1".to_string(),
        host_request_binding_id_sha256: Sha256Digest::for_bytes(b"host-request-binding-1"),
        request_kind: ProviderRequestKind::Turn,
        provider_id: "provider-fixture".to_string(),
        provider_config_sha256: Sha256Digest::for_bytes(b"provider-config"),
        model: "model-fixture".to_string(),
        transport: ProviderTransport::Http,
        endpoint_sha256: Sha256Digest::for_bytes(b"/responses"),
        logical_request_sha256: Sha256Digest::for_bytes(b"logical"),
        wire_semantic_sha256: Sha256Digest::for_bytes(wire),
        ephemeral_input_sha256: None,
        ephemeral_input_witness_sha256: None,
        previous_response_id_sha256: None,
        generate: true,
    }
}

fn intent(nonce: u8) -> ProviderInvocationIntent {
    ProviderInvocationIntent::new([nonce; 16], binding(b"wire"))
}

#[tokio::test]
async fn concurrent_enforced_claims_for_one_request_binding_have_one_owner() {
    let temp = TempDir::new().expect("temp dir");
    let sqlite = sqlite_config(&temp);
    let first = HeptaEvidenceStore::open(&sqlite).await.expect("first pool");
    let second = HeptaEvidenceStore::open(&sqlite)
        .await
        .expect("second pool");
    let left_intent = intent(31);
    let right_intent = intent(32);

    let (left, right) = tokio::join!(
        first.claim_provider_intent(&left_intent),
        second.claim_provider_intent(&right_intent)
    );
    let dispositions = [left.expect("left claim"), right.expect("right claim")];
    assert_eq!(
        dispositions
            .iter()
            .filter(|disposition| **disposition == ProviderIntentClaimDisposition::Inserted)
            .count(),
        1
    );
    assert_eq!(
        dispositions
            .iter()
            .filter(|disposition| {
                **disposition
                    == ProviderIntentClaimDisposition::BlockedByBinding(
                        ProviderBindingState::Pending,
                    )
            })
            .count(),
        1
    );
    assert_eq!(
        first
            .pending_provider_attempt_count()
            .await
            .expect("pending count"),
        1
    );
}

#[tokio::test]
async fn enforced_claim_blocks_transport_changes_until_not_dispatched_is_proven() {
    let temp = TempDir::new().expect("temp dir");
    let store = HeptaEvidenceStore::open(&sqlite_config(&temp))
        .await
        .expect("open evidence");
    let first = intent(41);
    let mut retry_binding = binding(b"incremental-wire");
    retry_binding.transport = ProviderTransport::WebSocket;
    retry_binding.previous_response_id_sha256 = Some(Sha256Digest::for_bytes(b"previous-response"));
    let retry = ProviderInvocationIntent::new([42; 16], retry_binding);
    assert_ne!(first.request_binding_id, retry.request_binding_id);
    assert_eq!(
        first.binding.host_request_binding_id_sha256,
        retry.binding.host_request_binding_id_sha256
    );

    assert_eq!(
        store
            .claim_provider_intent(&first)
            .await
            .expect("first claim"),
        ProviderIntentClaimDisposition::Inserted
    );
    assert_eq!(
        store
            .claim_provider_intent(&retry)
            .await
            .expect("retry claim"),
        ProviderIntentClaimDisposition::BlockedByBinding(ProviderBindingState::Pending)
    );

    store
        .append_provider_receipt(&ProviderInvocationReceipt::new(
            first,
            ProviderTerminal::NotDispatched {
                reason_code: "transport_not_entered".to_string(),
            },
        ))
        .await
        .expect("not-dispatched terminal");
    assert_eq!(
        store
            .claim_provider_intent(&retry)
            .await
            .expect("retry after not-dispatched"),
        ProviderIntentClaimDisposition::Inserted
    );
}
