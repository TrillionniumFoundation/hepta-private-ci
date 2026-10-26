//! Source-correlation fixtures only. No Root signature, Human authority, Core
//! item or effect is manufactured. Storage/crash coverage lives with the sender.
use super::*;
use codex_hepta_contracts::AgentId;
use pretty_assertions::assert_eq;

#[test]
fn recorded_source_requires_exact_raw_tuple_signed_commitments_and_operation() {
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d18").unwrap();
    let route = crate::text_session::AgentdTextSessionConfig {
        agent_id: agent.clone(),
        spawn_generation: 2,
        control_socket: "/fixture/control".into(),
        codex_home: "/fixture/home".into(),
        thread_id: "original-thread".into(),
        app_server_session_id: "original-session".into(),
    };
    let params = codex_app_server_protocol::DynamicToolCallParams {
        thread_id: route.thread_id.clone(),
        turn_id: "original-turn".into(),
        call_id: "original-call".into(),
        namespace: None,
        tool: "hepta_notes_replace".into(),
        arguments: serde_json::json!({"text":"原笔记","expected_revision":0}),
    };
    let reference = OriginalNotesThreadReference {
        app_server_session_id: route.app_server_session_id.clone(),
        thread_id: params.thread_id.clone(),
        turn_id: params.turn_id.clone(),
        call_id: params.call_id.clone(),
        callback_sha256: Digest32::of_bytes(&serde_json::to_vec(&params).unwrap()).to_string(),
    };
    let digest = Digest32::of_bytes(b"fixture frozen provenance");
    let bindings = AgentdNotesLiteralBindings {
        principal_scope: "fixture.notes".into(),
        principal_scope_digest: digest,
        issuer_id: "fixture-issuer".into(),
        policy_generation: Generation::new(1).unwrap(),
        locale: "zh-CN".into(),
        runtime_body_digest: digest,
        preference_state_digest: digest,
        model_tuple_digest: digest,
        prompt_registry_digest: digest,
        artifact_set_digest: digest,
    };
    let (turn, call) = reference_ids(&reference, agent.as_str()).unwrap();
    let run = format!(
        "notes.thread.{}",
        Digest32::of_bytes(
            &serde_json::to_vec(&(
                "organ.notes.original-turn.run.v1",
                agent.as_str(),
                digest.to_string(),
                &turn,
            ))
            .unwrap()
        )
    );
    let target = codex_hepta_memory::NotesTargetIdentity {
        session_instance: "1".repeat(32),
        task_id: 1,
        incarnation: "2".repeat(32),
    };
    let payload = serde_json::json!({"schema_version":1,"action":"replace_note","operation_id":run,
        "destination_id":target.destination_id(),"target":target,"expected_revision":0,"text":"原笔记"}).to_string();
    let intent = codex_hepta_memory::notes_operation_intent(
        &target,
        &payload,
        codex_hepta_types::StableId::new(agent.as_str()).unwrap(),
        Generation::new(1).unwrap(),
    )
    .unwrap();
    let source = codex_hepta_objective::thread_notes_source_json_v1(LiteralNotesSourceContext {
        client_intent_id: &call,
        source_digest: intent.semantic_digest(),
        principal_scope_digest: digest,
        locale: "zh-CN",
        observed_at: "2026-10-26T12:00:00Z",
        deadline: "2026-10-26T12:00:05Z",
    })
    .unwrap();
    let decoded = decode_source_envelope_json_v1(source.as_bytes()).unwrap();
    let raw = serde_json::json!({"issuer_id":"fixture-issuer","key_epoch":1,"message_id":"fixture-message",
        "sequence":1,"expires_at_ms":4_000_000_000_000_u64,"signature_hex":"ab".repeat(64),
        "body":{"spawn_generation":1,"run_id":run,"objective_revision":1,"source_envelope_json":source,
            "runtime_body_digest":digest.to_string(),"preference_state_digest":digest.to_string(),
            "model_tuple_digest":digest.to_string(),"prompt_registry_digest":digest.to_string(),
            "artifact_set_digest":digest.to_string(),"authority_epoch":1}}).to_string();
    let origin = ObjectiveSenderOrigin {
        agent_id: agent.clone(),
        spawn_generation: 1,
        request_id: 1,
        expected_peer_uid: 1000,
        expected_peer_pid: 1,
        endpoint_identity: "/fixture/control".into(),
        original_notes_thread: Some(reference),
    };
    let operation = ProductionRetainedOperation {
        operation: intent,
        topic: codex_hepta_memory::NOTES_REPLACE_TOPIC_V1.into(),
        payload_json: payload,
        state: codex_hepta_memory::LocalOutcomeState::Indeterminate,
    };
    let check = |origin| {
        let request = ObjectiveSenderRequest::from_original(raw.clone(), origin).unwrap();
        verify_recorded(
            RecordedScope {
                agent_id: &agent,
                spawn_generation: 2,
                bindings: &bindings,
                input_schema_digest: decoded.input_schema_digest,
                normalization_digest: decoded
                    .structured_intent
                    .provenance
                    .normalization_profile_digest,
            },
            &route,
            &request,
            &operation,
        )
    };
    let RecordedNotesLookup::Found(found) = check(origin.clone()).unwrap() else {
        panic!("exact source")
    };
    assert_eq!(
        (
            found.reference().turn_id.as_str(),
            found.reference().call_id.as_str(),
            found.run_id()
        ),
        ("original-turn", "original-call", run.as_str())
    );
    for field in ["thread", "session", "turn", "call", "callback"] {
        let mut changed = origin.clone();
        let value = changed.original_notes_thread.as_mut().unwrap();
        match field {
            "thread" => value.thread_id.push_str("-forged"),
            "session" => value.app_server_session_id.push_str("-forged"),
            "turn" => value.turn_id.push_str("-forged"),
            "call" => value.call_id.push_str("-forged"),
            _ => value.callback_sha256 = Digest32::of_bytes(b"forged").to_string(),
        }
        assert!(check(changed).is_err(), "{field}");
    }
    let scope = RecordedScope {
        agent_id: &agent,
        spawn_generation: 2,
        bindings: &bindings,
        input_schema_digest: decoded.input_schema_digest,
        normalization_digest: decoded
            .structured_intent
            .provenance
            .normalization_profile_digest,
    };
    let original = ObjectiveSenderRequest::from_original(raw.clone(), origin.clone()).unwrap();
    let mut other: serde_json::Value = serde_json::from_str(&raw).unwrap();
    other["message_id"] = serde_json::json!("other-message");
    other["sequence"] = serde_json::json!(2);
    other["body"]["run_id"] = serde_json::json!("notes.thread.other-original");
    let other = ObjectiveSenderRequest::from_original(other.to_string(), origin.clone()).unwrap();
    assert!(matches!(
        latest_matching_request(
            scope,
            vec![original, other],
            tokio::time::Instant::now() + Duration::from_secs(5)
        )
        .unwrap(),
        RecordedChoice::Unknown(RecordedNotesUnknownReason::AmbiguousOriginalOrder)
    ));
    for field in [
        "model_tuple_digest",
        "runtime_body_digest",
        "artifact_set_digest",
    ] {
        let mut changed: serde_json::Value = serde_json::from_str(&raw).unwrap();
        changed["body"][field] =
            serde_json::json!(Digest32::of_bytes(b"forged provenance").to_string());
        let request =
            ObjectiveSenderRequest::from_original(changed.to_string(), origin.clone()).unwrap();
        assert!(
            verify_recorded(scope, &route, &request, &operation).is_err(),
            "{field}"
        );
    }
    let mut legacy = origin;
    legacy.original_notes_thread = None;
    assert!(matches!(
        check(legacy).unwrap(),
        RecordedNotesLookup::Unknown {
            reason: RecordedNotesUnknownReason::LegacyReferenceUnavailable,
            ..
        }
    ));
}
