use super::*;
use crate::final_use_authorizer::IssuerProcessIdentityConfig;
use std::os::unix::fs::PermissionsExt;
use tokio::net::UnixListener;

fn route(socket: PathBuf) -> Route {
    Route {
        schema_version: 1,
        socket,
        process_attestation: PathBuf::from("/nonexistent/root-process-identity.json"),
        process_identity: IssuerProcessIdentityConfig {
            executable_sha256: "01".repeat(32),
            cgroup_sha256: "02".repeat(32),
            boot_id_sha256: "03".repeat(32),
        },
        maximum_request_duration_ms: 2000,
    }
}

#[tokio::test]
async fn actual_non_root_kernel_peer_is_rejected_before_any_payload_write() {
    if rustix::process::geteuid().as_raw() == 0 {
        return;
    }
    let root = tempfile::tempdir().unwrap();
    let socket = root.path().join("generator.sock");
    let listener = UnixListener::bind(&socket).unwrap();
    let mut client = UnixStream::connect(&socket).await.unwrap();
    let (mut server, _) = listener.accept().await.unwrap();
    let request = encode_frozen_generator_request_v1(
        &FrozenGeneratorRequestV1::from_payload(b"actual-frozen-source").unwrap(),
    )
    .unwrap();
    let error = exchange_connected(&mut client, &route(socket), &request)
        .await
        .err()
        .unwrap();
    assert!(
        matches!(error, AgentdError::Protocol(ref reason) if reason == "frozen Generator requires actual Root kernel peer")
    );
    drop(client);
    let mut observed = Vec::new();
    server.read_to_end(&mut observed).await.unwrap();
    assert!(observed.is_empty());
}

#[test]
fn refuses_workload_owned_route_and_unprotected_parent_without_contacting_a_service() {
    if rustix::process::geteuid().as_raw() == 0 {
        return;
    }
    let root = tempfile::tempdir().unwrap();
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let path = root.path().join("route.json");
    let bytes = br#"{"schema_version":1}"#;
    std::fs::write(&path, bytes).unwrap();
    let result = CpuNeuronFrozenGeneratorClientV1::from_protected_route(
        path,
        Digest32::of_bytes(bytes),
        StableId::new("installed-generator").unwrap(),
    );
    assert!(
        matches!(result, Err(AgentdError::Protocol(ref reason)) if reason == "frozen Generator routing directory must be Root protected")
    );
}

/// This exercises real UID0 credentials and protected files, rather than a
/// caller-provided Root flag. The parent runs this exact test ELF as UID0.
#[tokio::test]
#[ignore = "requires actual UID0 and a protected /run temporary directory"]
async fn actual_root_process_and_route_binding_returns_only_original_evidence() {
    assert_eq!(rustix::process::geteuid().as_raw(), 0);
    use codex_hepta_contracts::ModelIssuerProcessIdentity;
    use sha2::Digest;
    use sha2::Sha256;

    let root = tempfile::Builder::new()
        .prefix("hepta-frozen-generator-fixture-")
        .tempdir_in("/run")
        .unwrap();
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let socket = root.path().join("generator.sock");
    let listener = UnixListener::bind(&socket).unwrap();
    std::fs::set_permissions(&socket, std::fs::Permissions::from_mode(0o660)).unwrap();
    let canonical = |mut bytes: Vec<u8>| {
        while bytes.last().is_some_and(u8::is_ascii_whitespace) {
            bytes.pop();
        }
        format!("{:x}", Sha256::digest(bytes))
    };
    let pid = std::process::id();
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat")).unwrap();
    let start_time_ticks = stat
        .rsplit_once(')')
        .unwrap()
        .1
        .split_whitespace()
        .nth(19)
        .unwrap()
        .parse()
        .unwrap();
    let process = ModelIssuerProcessIdentity {
        schema_version: 1,
        pid,
        start_time_ticks,
        executable_sha256: format!(
            "{:x}",
            Sha256::digest(std::fs::read(format!("/proc/{pid}/exe")).unwrap())
        ),
        cgroup_sha256: canonical(std::fs::read(format!("/proc/{pid}/cgroup")).unwrap()),
        boot_id_sha256: canonical(std::fs::read("/proc/sys/kernel/random/boot_id").unwrap()),
    };
    let attestation = root.path().join("identity.json");
    std::fs::write(&attestation, serde_json::to_vec(&process).unwrap()).unwrap();
    let route_path = root.path().join("route.json");
    let route_bytes = serde_json::to_vec(&serde_json::json!({
        "schema_version":1,"socket":socket,"process_attestation":attestation,
        "process_identity":{
            "executable_sha256":process.executable_sha256,
            "cgroup_sha256":process.cgroup_sha256,
            "boot_id_sha256":process.boot_id_sha256
        },"maximum_request_duration_ms":2000
    }))
    .unwrap();
    std::fs::write(&route_path, &route_bytes).unwrap();
    let client = CpuNeuronFrozenGeneratorClientV1::from_protected_route(
        route_path.clone(),
        Digest32::of_bytes(&route_bytes),
        StableId::new("installed-generator").unwrap(),
    )
    .unwrap();
    let payload = b"whole-original-frozen-candidate";
    let evidence = SignedLearningEvidenceV1 {
        evidence_id: StableId::new("original-evidence").unwrap(),
        principal_id: StableId::new("installed-generator").unwrap(),
        role: LearningEvidenceRoleV1::Generator,
        trust_digest: Digest32::of_bytes(b"trust"),
        scope_digest: Digest32::of_bytes(b"scope"),
        objective_digest: Digest32::of_bytes(b"objective"),
        authority_epoch: 1,
        issued_at: 1,
        expires_at: 2,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    let granted = || {
        FrozenGeneratorResponseV1::Granted(Box::new(
            codex_hepta_agent_components::learning_ledger::ReviewEvidenceWireV1::from_native(
                &evidence,
            ),
        ))
    };
    // Raw whole transport is distinct from the joined terminal verifier. A
    // Reserved record here deliberately cannot establish model failure.
    let failure_facts = raw_failure_transport_facts();
    let request_identity = failure_facts.request.clone();
    let whole = |facts: &codex_hepta_infer_core::SelfIterationModelFailureFactsV1| {
        encode_self_iteration_model_failure_observation_response_v1(
            &SelfIterationModelFailureObservationResponseV1::Facts(
                SelfIterationModelFailureObservationFactsV1::from_facts(facts).unwrap(),
            ),
        )
        .unwrap()
    };
    let original_whole = whole(&failure_facts);
    assert!(original_whole.len() > MAX_FROZEN_GENERATOR_RESPONSE_BYTES_V1);
    let mut foreign = failure_facts.clone();
    foreign.request.request_id = StableId::new("different.failure.request").unwrap();
    let mut partial = original_whole.clone();
    partial.pop();
    let responses = [
        encode_frozen_generator_response_v1(&granted()).unwrap(),
        encode_frozen_generator_response_v1(&granted()).unwrap(),
        encode_frozen_generator_response_v1(&FrozenGeneratorResponseV1::Refused(
            FrozenGeneratorFailureV1 {
                error: FrozenGeneratorErrorCodeV1::Pending,
            },
        ))
        .unwrap(),
        original_whole,
        whole(&foreign),
        encode_self_iteration_model_failure_observation_response_v1(
            &SelfIterationModelFailureObservationResponseV1::Refused(FrozenGeneratorFailureV1 {
                error: FrozenGeneratorErrorCodeV1::Pending,
            }),
        )
        .unwrap(),
        partial,
    ];
    let server = tokio::spawn(async move {
        for (index, response) in responses.into_iter().enumerate() {
            let (mut stream, _) = listener.accept().await.unwrap();
            let mut request = Vec::new();
            stream.read_to_end(&mut request).await.unwrap();
            let decoded = match decode_frozen_generator_operation_v1(&request).unwrap() {
                FrozenGeneratorOperationV1::Issue(request) => {
                    assert_eq!(index, 0);
                    request.payload().unwrap()
                }
                FrozenGeneratorOperationV1::Observe(request) => {
                    assert!(index > 0);
                    request.payload().unwrap()
                }
                FrozenGeneratorOperationV1::ObserveModelFailure(request) => {
                    assert!(index >= 3);
                    assert_eq!(request.request().unwrap(), request_identity);
                    payload.to_vec()
                }
            };
            assert_eq!(decoded, payload);
            stream.write_all(&response).await.unwrap();
            stream.write_all(b"\n").await.unwrap();
        }
    });
    assert_eq!(client.exchange(payload).await.unwrap(), evidence);
    assert_eq!(
        client.observe_payload(payload).await.unwrap(),
        Some(evidence)
    );
    assert!(client.observe_payload(payload).await.unwrap().is_none());
    assert_eq!(
        client
            .observe_model_failure_facts(&failure_facts.request)
            .await
            .unwrap(),
        Some(failure_facts.clone())
    );
    assert!(
        client
            .observe_model_failure_facts(&failure_facts.request)
            .await
            .is_err()
    );
    assert!(
        client
            .observe_model_failure_facts(&failure_facts.request)
            .await
            .unwrap()
            .is_none()
    );
    assert!(
        client
            .observe_model_failure_facts(&failure_facts.request)
            .await
            .is_err()
    );
    server.await.unwrap();
    // The transport cannot reinterpret a changed Root route as the old pin.
    std::fs::write(&route_path, b"{}").unwrap();
    assert!(client.exchange(payload).await.is_err());
}

fn raw_failure_transport_facts() -> codex_hepta_infer_core::SelfIterationModelFailureFactsV1 {
    use codex_hepta_infer_core::durable_control::native::NativeRequest;
    use codex_hepta_infer_core::durable_control::native::NativeReservationState;
    use codex_hepta_infer_core::durable_control::native::NativeRunRecord;
    let request = codex_hepta_infer_core::SelfIterationModelRequestV1 {
        request_id: StableId::new("original.failure.request").unwrap(),
        role: codex_hepta_infer_core::SelfIterationModelRoleV1::Generator,
        envelope_digest: Digest32::of_bytes(b"policy"),
        candidate_digest: None,
        prompt: "original \n🙂 prompt".into(),
        deadline_ms: 10000,
        maximum_response_bytes: 8192,
    };
    codex_hepta_infer_core::SelfIterationModelFailureFactsV1 {
        native_record: NativeRunRecord {
            request: NativeRequest {
                request_id: request.request_id.to_string(),
                principal_id: "original-agent".into(),
                worker_generation: 7,
                model: "original-model".into(),
                payload_digest: Digest32::of_bytes(b"source").to_string(),
            },
            revision: 1,
            state: NativeReservationState::Reserved,
            dispatch: None,
            turn_id: None,
            cancel_requested: false,
            pre_dispatch_stop: None,
            pre_effect_abort: None,
            dispatch_rejection: None,
            terminal_owner: None,
            terminal_publication: None,
            observation: None,
        },
        request,
        root_outcome_bytes: vec![b'x'; 24 * 1024],
        observed_at_ms: 11000,
    }
}
