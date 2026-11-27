use super::*;
use pretty_assertions::assert_eq;

use crate::PROVIDER_EVIDENCE_SCHEMA_VERSION;
use crate::ProviderRequestBinding;
use crate::ProviderRequestKind;
use crate::ProviderTransport;

fn request_binding_id() -> RequestBindingId {
    RequestBindingId::for_request(&ProviderRequestBinding {
        schema_version: PROVIDER_EVIDENCE_SCHEMA_VERSION,
        thread_id: "thread-1".to_string(),
        turn_id: "turn-1".to_string(),
        host_request_binding_id_sha256: Sha256Digest::for_bytes(b"host-request"),
        request_kind: ProviderRequestKind::Turn,
        provider_id: "provider-1".to_string(),
        provider_config_sha256: Sha256Digest::for_bytes(b"config"),
        model: "model-1".to_string(),
        transport: ProviderTransport::Http,
        endpoint_sha256: Sha256Digest::for_bytes(b"/responses"),
        logical_request_sha256: Sha256Digest::for_bytes(b"logical"),
        wire_semantic_sha256: Sha256Digest::for_bytes(b"wire"),
        ephemeral_input_sha256: None,
        ephemeral_input_witness_sha256: None,
        previous_response_id_sha256: None,
        generate: true,
    })
}

fn intent(payload: &[u8]) -> ProviderEffectIntent {
    let key = ProviderEffectKey::for_occurrence(
        "provider-1/config-v1",
        "hepta.automation.v1:agent-a:task-a:1",
        &request_binding_id(),
    )
    .expect("effect key");
    ProviderEffectIntent::new(key, Sha256Digest::for_bytes(payload))
}

#[test]
fn journal_status_acceptance_cannot_replace_the_original_operation() {
    let intent = intent(b"status-accepted-after-unknown");
    let key = intent.key.clone();
    let accepted_before_unknown = ProviderEffectAck::new(
        key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(b"operation-before-unknown"),
        ProviderEffectAckStatus::Accepted,
    );
    let accepted_after_unknown = ProviderEffectStatusObservation::new(
        key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(b"operation-after-unknown"),
        ProviderEffectAckStatus::Accepted,
    );
    let mut journal = ProviderEffectJournal::default();
    journal.record_intent(intent).expect("intent");
    journal
        .record_ack(accepted_before_unknown)
        .expect("accepted ACK");
    journal
        .mark_indeterminate(&key, "provider_dispatch_unknown")
        .expect("quarantine");
    assert_eq!(
        journal.record_status_observation(accepted_after_unknown),
        Err(ProviderEffectBindingError::AckConflict)
    );
    assert_eq!(
        journal.state(&key),
        Some(ProviderEffectState::Indeterminate)
    );
    assert!(journal.validate().is_ok());
}

struct ExactLookupAdapter {
    observed: std::sync::Mutex<Option<Vec<u8>>>,
}

impl ProviderEffectAdapter for ExactLookupAdapter {
    fn capability(&self) -> ProviderEffectIdempotencyCapability {
        ProviderEffectIdempotencyCapability::KeyAndStatusLookup
    }

    fn dispatch<'a>(
        &'a self,
        _intent: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, ProviderEffectDispatch> {
        Box::pin(std::future::ready(ProviderEffectDispatch::Unknown))
    }

    fn lookup<'a>(
        &'a self,
        _key: &'a ProviderEffectKey,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        Box::pin(std::future::ready(ProviderEffectLookup::Unknown))
    }

    fn lookup_for_reconciliation<'a>(
        &'a self,
        _intent: &'a ProviderEffectIntent,
        wire_payload: Option<&'a [u8]>,
    ) -> ProviderEffectFuture<'a, ProviderEffectLookup> {
        *self.observed.lock().expect("lookup capture") = wire_payload.map(ToOwned::to_owned);
        Box::pin(std::future::ready(ProviderEffectLookup::Unknown))
    }
}

#[tokio::test]
async fn reconciliation_lookup_can_consume_exact_durable_wire_without_dispatch() {
    let intent = intent(b"exact-recovery-wire");
    let adapter = ExactLookupAdapter {
        observed: std::sync::Mutex::new(None),
    };
    let wire: &[u8] = b"exact-recovery-wire";
    assert_eq!(
        adapter.lookup_for_reconciliation(&intent, Some(wire)).await,
        ProviderEffectLookup::Unknown
    );
    assert_eq!(
        adapter.observed.lock().expect("lookup capture").as_deref(),
        Some(wire)
    );
}
