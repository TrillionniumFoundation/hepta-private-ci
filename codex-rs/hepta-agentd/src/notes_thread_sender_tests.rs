//! Source-correlation protocol fixture. The signature below is deliberately
//! test data; no Root sign, sender delivery or application effect is performed.
use super::*;

#[test]
fn a_retained_original_turn_source_cannot_be_attributed_to_a_new_call() {
    let source = codex_hepta_objective::thread_notes_source_json_v1(LiteralNotesSourceContext {
        client_intent_id: "original-call-digest",
        source_digest: Digest32::of_bytes(b"fixture operation"),
        principal_scope_digest: Digest32::of_bytes(b"fixture principal"),
        locale: "zh-CN",
        observed_at: "2026-09-08T10:00:00Z",
        deadline: "2026-09-08T10:00:05Z",
    })
    .unwrap();
    let digest = Digest32::of_bytes(b"fixture frozen input").to_string();
    let ingress = AuthBusObjectiveIngress {
        issuer_id: "fixture-notes-thread".into(),
        key_epoch: 1,
        message_id: "fixture-original-message".into(),
        sequence: 1,
        expires_at_ms: 1_788_861_605_000,
        signature_hex: "ab".repeat(64),
        body: AuthBusObjectiveBody {
            spawn_generation: 1,
            run_id: "notes.thread.fixture-original-turn".into(),
            objective_revision: 1,
            source_envelope_json: source,
            runtime_body_digest: digest.clone(),
            preference_state_digest: digest.clone(),
            model_tuple_digest: digest.clone(),
            prompt_registry_digest: digest.clone(),
            artifact_set_digest: digest,
            authority_epoch: 1,
        },
    };
    let request = ObjectiveSenderRequest::from_original(
        serde_json::to_string(&ingress).unwrap(),
        ObjectiveSenderOrigin {
            agent_id: codex_hepta_contracts::AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d18")
                .unwrap(),
            spawn_generation: 1,
            request_id: 1,
            expected_peer_uid: 1,
            expected_peer_pid: 1,
            endpoint_identity: "/fixture/original-agentd.sock".into(),
        },
    )
    .unwrap();
    assert!(require_original_thread_call(&request, "original-call-digest").is_ok());
    assert!(require_original_thread_call(&request, "new-call-after-unknown").is_err());
}
