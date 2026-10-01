use super::*;
use codex_hepta_infer_core::durable_control::native::NativeCognitivePreparation;

fn native_receipt(read_request_id: u64, receipt: ledger::AppendReceipt) -> NativeCognitivePreparation {
    NativeCognitivePreparation {
        read_request_id,
        sequence: receipt.sequence.get(),
        event_digest: receipt.event_digest.to_string(),
        chain_digest: receipt.chain_digest.to_string(),
    }
}

fn native_dispatch(request: &NativeRequest, receipt: Option<NativeCognitivePreparation>, context: Digest32) -> NativeDispatch {
    NativeDispatch {
        thread_id: "thread".to_string(),
        model_provider: "provider".to_string(),
        context_digest: digest("additional-context").to_string(),
        owner_context_digest: Some(context.to_string()),
        cognitive_preparation: receipt,
        codex_payload_digest: Some(digest("turn-payload").to_string()),
        codex_request_digest: Some(digest("turn-request").to_string()),
        app_server_version: Some("1.2.3".to_string()),
        protocol_id: Some("codex.app-server.v2".to_string()),
        codex_source_admission_digest: Some(request.payload_digest.clone()),
        codex_home_digest: Some(digest("home").to_string()),
        codex_connection_id: Some(7),
        codex_session_id: Some("session".to_string()),
        codex_deadline_ms: Some(10_000),
        codex_authority_epoch: Some(7),
        codex_revocation_revision: Some(1),
        codex_revocation_head_sha256: Some(digest("revocation").to_string()),
        codex_authority_witness_sha256: Some(digest("authority").to_string()),
    }
}

#[test]
fn ordinary_preparation_receipt_joins_exact_native_dispatch_after_reopen() {
    let temp = tempfile::tempdir().unwrap();
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000191").unwrap();
    let generation = 4;
    let read_request_id = 17;
    let mut writer = writer(temp.path());
    let (record_id, episode_id) = assignment_identity(&owner, generation, read_request_id);
    let prepared = assignment(record_id, episode_id);
    let context = prepared.published_context_digest.unwrap();
    let first = native_receipt(read_request_id, writer.append_retrieval_assignment_preparation(prepared.clone()).unwrap());
    let second = native_receipt(read_request_id, writer.append_retrieval_assignment_preparation(prepared).unwrap());
    let (record_id, episode_id) = assignment_identity(&owner, generation, read_request_id + 1);
    let explicit = native_receipt(read_request_id + 1, writer.append_retrieval_assignment_current(assignment(record_id, episode_id)).unwrap());
    let foreign_owner = AgentId::parse("00000000-0000-4000-8000-000000000192").unwrap();
    let (record_id, episode_id) = assignment_identity(&foreign_owner, generation, read_request_id);
    let foreign = native_receipt(read_request_id, writer.append_retrieval_assignment_preparation(assignment(record_id, episode_id)).unwrap());
    let (record_id, episode_id) = assignment_identity(&owner, generation + 1, read_request_id);
    let other_generation = native_receipt(read_request_id, writer.append_retrieval_assignment_preparation(assignment(record_id, episode_id)).unwrap());
    let ledger_before = std::fs::read(temp.path().join("learning.journal")).unwrap();
    let witness_before = std::fs::read(temp.path().join("learning.witness")).unwrap();
    let sink = CognitiveRetrievalLearningSink::new(writer);
    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: temp.path().join("nonexistent-agentd.sock"),
        agent_id: owner,
        generation,
        model: "model".to_string(),
        timeout: std::time::Duration::from_secs(5),
    }).unwrap();
    let request = NativeRequest {
        request_id: "native-request".to_string(),
        principal_id: "00000000-0000-4000-8000-000000000191".to_string(),
        worker_generation: generation,
        model: "model".to_string(),
        payload_digest: digest("source-admission").to_string(),
    };
    let mut cases = vec![("first", Some(first.clone()), true), ("second", Some(second), true), ("explicit", Some(explicit), false), ("missing", None, false), ("foreign-owner", Some(foreign), false), ("other-generation", Some(other_generation), false)];
    let mut wrong = first.clone();
    wrong.read_request_id += 1;
    cases.push(("wrong-rpc", Some(wrong), false));
    let mut wrong = first.clone();
    wrong.sequence += 100;
    cases.push(("wrong-sequence", Some(wrong), false));
    let mut wrong = first.clone();
    wrong.event_digest = digest("wrong-event").to_string();
    cases.push(("wrong-event", Some(wrong), false));
    let mut wrong = first;
    wrong.chain_digest = digest("wrong-chain").to_string();
    cases.push(("wrong-chain", Some(wrong), false));
    let mut good_joins = Vec::new();
    for (label, receipt, expected_success) in cases {
        let native_path = temp.path().join(format!("{label}.native.journal"));
        let mut control = DurableInferenceControl::open(&native_path, /*capacity*/ 8).unwrap();
        control.reserve_native(request.clone(), /*maximum_in_flight*/ 1).unwrap();
        control.dispatch_native(&request.request_id, native_dispatch(&request, receipt, context)).unwrap();
        let inspected = driver.inspect_owner_cognitive_preparation(&control, &sink, &request, context);
        assert_eq!(inspected.is_ok(), expected_success, "{label}");
        if !expected_success { continue; }
        let pending = inspected.unwrap();
        assert_eq!(pending.0, CognitiveContextDeliveryStateV1::AcceptanceUnknown);
        good_joins.push(pending.1);
        let mut changed = request.clone();
        changed.principal_id = "00000000-0000-4000-8000-000000000192".to_string();
        assert!(driver.inspect_owner_cognitive_preparation(&control, &sink, &changed, context).is_err());
        let mut changed = request.clone();
        changed.worker_generation += 1;
        assert!(driver.inspect_owner_cognitive_preparation(&control, &sink, &changed, context).is_err());
        let mut changed = request.clone();
        changed.model = "other-model".to_string();
        assert!(driver.inspect_owner_cognitive_preparation(&control, &sink, &changed, context).is_err());
        let mut changed = request.clone();
        changed.payload_digest = digest("other-source-admission").to_string();
        assert!(driver.inspect_owner_cognitive_preparation(&control, &sink, &changed, context).is_err());
        assert!(driver.inspect_owner_cognitive_preparation(&control, &sink, &request, digest("wrong-context")).is_err());
        let expected_state = if label == "second" {
            control.native_started(&request.request_id, "turn".to_string()).unwrap();
            CognitiveContextDeliveryStateV1::TurnAccepted
        } else {
            CognitiveContextDeliveryStateV1::AcceptanceUnknown
        };
        control.cancel_native(&request.request_id).unwrap();
        let cancelled = driver.inspect_owner_cognitive_preparation(&control, &sink, &request, context).unwrap();
        assert_eq!(cancelled.0, expected_state);
        drop(control);
        let reopened = DurableInferenceControl::open(&native_path, /*capacity*/ 8).unwrap();
        assert_eq!(driver.inspect_owner_cognitive_preparation(&reopened, &sink, &request, context).unwrap(), cancelled);
    }
    assert_ne!(good_joins[0], good_joins[1]);
    assert_eq!(std::fs::read(temp.path().join("learning.journal")).unwrap(), ledger_before);
    assert_eq!(std::fs::read(temp.path().join("learning.witness")).unwrap(), witness_before);
}
