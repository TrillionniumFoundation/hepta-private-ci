use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixTransactionId;
use codex_hepta_matrix_store::MatrixDispatchState;
use codex_hepta_matrix_store::OutboxKind;
use codex_hepta_matrix_store::OutboxState;
use pretty_assertions::assert_eq;

#[test]
fn binding_changes_for_attempt_destination_and_payload() {
    let transaction = MatrixTransactionId::parse("txn-one").expect("transaction");
    let room = MatrixRoomId::parse("!room:example.test").expect("room");
    let record = OutboxRecord {
        outbox_id: 1,
        stable_txn_id: transaction.clone(),
        room_id: room.clone(),
        kind: OutboxKind::Final,
        payload: b"payload".to_vec(),
        logical_txn_count: 1,
        binding_revision: 3,
        generation: 4,
        state: OutboxState::InFlight,
        attempts: 1,
        next_attempt_at_ms: 0,
        lease_until_ms: Some(10),
        created_at_ms: 1,
        updated_at_ms: 2,
        sent_event_id: None,
        replaces_event_id: None,
    };
    let dispatch = MatrixDispatchRecord {
        operation_id: format!("matrix.send:{}", transaction.as_str()),
        stable_txn_id: transaction,
        logical_outbox_id: "logical-one".to_string(),
        room_id: room,
        binding_revision: 3,
        generation: 4,
        payload_digest: Sha256Digest::for_bytes(b"payload").as_str().to_string(),
        authority_epoch: None,
        grant_id: None,
        grant_payload_digest: None,
        state: MatrixDispatchState::Dispatched,
        accepted_event_id: None,
        terminal_event_id: None,
        transport_observation_digest: None,
        send_observation_digest: None,
        redaction_observation_digest: None,
        attempts: 1,
        prepared_at_ms: 2,
        updated_at_ms: 2,
        terminal_observed_at_ms: None,
    };
    let identity = MatrixOutboundIdentity {
        homeserver_id: "https://matrix.example.test".to_string(),
        matrix_user_id: "@agent:example.test".to_string(),
        device_id: "DEVICE".to_string(),
        session_generation: 9,
    };
    let subject = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent");
    let first = build_matrix_final_use_request(subject.as_str(), &dispatch, &record, &identity)
        .expect("binding");
    first.validate().expect("self-verifying proposal");
    assert_ne!(first.payload_digest, dispatch.payload_digest);
    let mut retry_record = record.clone();
    retry_record.attempts = 2;
    let mut retry_dispatch = dispatch.clone();
    retry_dispatch.attempts = 2;
    let retry = build_matrix_final_use_request(
        &first.subject_id,
        &retry_dispatch,
        &retry_record,
        &identity,
    )
    .expect("retry binding");
    assert_ne!(first.request_digest, retry.request_digest);
    assert_eq!(first.scope_digest, retry.scope_digest);
    assert_eq!(first.payload_digest, retry.payload_digest);
    let mut other_identity = identity.clone();
    other_identity.device_id = "OTHER".to_string();
    let other =
        build_matrix_final_use_request(&first.subject_id, &dispatch, &record, &other_identity)
            .expect("other binding");
    assert_ne!(first.scope_digest, other.scope_digest);
    assert_ne!(first.destination_id, other.destination_id);
    let mut edit = record.clone();
    edit.replaces_event_id = Some(MatrixEventId::parse("$one").expect("edit target"));
    let edited = build_matrix_final_use_request(subject.as_str(), &dispatch, &edit, &identity)
        .expect("edit proposal");
    assert_ne!(first.payload_digest, edited.payload_digest);
    edit.replaces_event_id = Some(MatrixEventId::parse("$two").expect("different target"));
    let retargeted = build_matrix_final_use_request(subject.as_str(), &dispatch, &edit, &identity)
        .expect("different edit proposal");
    assert_ne!(edited.binding, retargeted.binding);
    let mut forged = first.clone();
    forged.attempt += 1;
    assert_eq!(forged.validate(), Err(MatrixAuthorityError::InvalidBinding));
    forged = first.clone();
    forged.schema_version = 1;
    assert_eq!(forged.validate(), Err(MatrixAuthorityError::InvalidBinding));
    let mut changed_body = record;
    changed_body.payload = b"changed".to_vec();
    assert_eq!(
        build_matrix_final_use_request(subject.as_str(), &dispatch, &changed_body, &identity),
        Err(MatrixAuthorityError::InvalidBinding)
    );
}
