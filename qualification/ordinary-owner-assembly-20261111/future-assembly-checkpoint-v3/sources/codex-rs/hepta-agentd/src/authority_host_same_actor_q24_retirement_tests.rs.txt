//! Only protocol/configuration data and real thread/socket custody components.
//! No test constructs a Root retirement scope, C completion cap, business
//! receipt, Root publication, daemon join proof or operating-system exit.

use super::*;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::os::unix::net::UnixStream;

use crate::same_actor_q24_deployment_protocol::OriginalDeploymentBinding;
use crate::same_actor_q24_deployment_protocol::PROGRESS_PURPOSE;
use crate::same_actor_q24_root_retirement_protocol::OriginalRootRetirementAcknowledgement;
use crate::same_actor_q24_root_retirement_protocol::OriginalRootRetirementRequest;
use crate::same_actor_q24_root_retirement_protocol::OriginalRootRetirementStage;
use crate::same_actor_q24_root_retirement_protocol::RETIREMENT_PURPOSE;

fn binding() -> OriginalDeploymentBinding {
    OriginalDeploymentBinding {
        phase: Digest32::of_bytes(b"retirement-component-phase-data").to_string(),
        root: codex_hepta_memory::CognitiveCheckpointPeerLifetime {
            uid: 0,
            pid: 91,
            boot_id: "retirement-component-data-only-boot".into(),
            process_start_ticks: 17,
        },
        consumer: codex_hepta_memory::CognitiveCheckpointPeerLifetime {
            uid: 60001,
            pid: 92,
            boot_id: "retirement-component-data-only-boot".into(),
            process_start_ticks: 18,
        },
        identity: Digest32::of_bytes(b"retirement-component-identity-data").to_string(),
        root_end_boottime_ns: 111,
    }
}

fn intent_request() -> OriginalRootRetirementRequest {
    OriginalRootRetirementRequest {
        schema_version: 1,
        purpose: RETIREMENT_PURPOSE.into(),
        binding: binding(),
        sequence: 1,
        stage: OriginalRootRetirementStage::AuthorizeRootRetirement,
        current_registration: Digest32::of_bytes(b"component-current-registration-data").to_string(),
        current_request: Digest32::of_bytes(b"component-current-request-data").to_string(),
        original_intent: None,
    }
}

fn gate() -> io::Result<Arc<SameActorPhaseGate>> {
    // A stop/deadline component only; this creates no issuer or Root scope.
    SameActorPhaseGate::from_original_deadline(
        SameActorPhaseDeadline::at_original_service_start(std::time::Duration::from_secs(30))?,
    )
}

#[test]
fn retirement_data_requires_exact_original_incarnation_and_current() {
    let original = intent_request();
    let raw = original.encode_original().unwrap();
    let exact = OriginalRootRetirementRequest::decode_original(&raw).unwrap();
    assert_eq!(exact.encode_original().unwrap(), raw);
    let require = |changed: OriginalRootRetirementRequest| {
        changed.require_original(
            &original.binding,
            &original.current_registration,
            &original.current_request,
            OriginalRootRetirementStage::AuthorizeRootRetirement,
            None,
        )
    };
    let mut changed = intent_request();
    changed.binding.root.process_start_ticks += 1;
    assert!(require(changed).is_err());
    let mut changed = intent_request();
    changed.binding.consumer.process_start_ticks += 1;
    assert!(require(changed).is_err());
    let mut changed = intent_request();
    changed.binding.root_end_boottime_ns += 1;
    assert!(require(changed).is_err());
    let mut changed = intent_request();
    changed.binding.identity = Digest32::of_bytes(b"other-identity-data").to_string();
    assert!(require(changed).is_err());
    let mut changed = intent_request();
    changed.current_registration = Digest32::of_bytes(b"other-current-registration-data").to_string();
    assert!(require(changed).is_err());
    let mut changed = intent_request();
    changed.current_request = Digest32::of_bytes(b"other-current-request-data").to_string();
    assert!(require(changed).is_err());
}

#[test]
fn retirement_data_refuses_progress_purpose_skipped_intent_and_noncanonical_frames() {
    let mut changed = intent_request();
    changed.purpose = PROGRESS_PURPOSE.into();
    assert!(changed.encode_original().is_err());
    let mut changed = intent_request();
    changed.sequence = 2;
    changed.stage = OriginalRootRetirementStage::ObserveRootWorkersJoined;
    assert!(changed.encode_original().is_err());
    let mut changed = intent_request();
    changed.original_intent = Some(changed.digest().unwrap());
    assert!(changed.encode_original().is_err());

    let original = intent_request();
    let mut raw = original.encode_original().unwrap();
    raw.push(b' ');
    assert!(OriginalRootRetirementRequest::decode_original(&raw).is_err());
    let mut value = serde_json::to_value(&original).unwrap();
    value.as_object_mut().unwrap().insert("completion_proof".into(), serde_json::json!(true));
    assert!(OriginalRootRetirementRequest::decode_original(
        &serde_json::to_vec(&value).unwrap()
    ).is_err());
    assert!(OriginalRootRetirementRequest::decode_original(&[]).is_err());
    assert!(OriginalRootRetirementRequest::decode_original(&vec![b'x'; 65_537]).is_err());
}

#[test]
fn retirement_acknowledgement_is_bound_to_one_original_intent_and_request() {
    let intent = intent_request();
    let intent_digest = intent.digest().unwrap();
    let mut joined = intent_request();
    joined.sequence = 2;
    joined.stage = OriginalRootRetirementStage::ObserveRootWorkersJoined;
    joined.original_intent = Some(intent_digest.clone());
    let mut acknowledgement = OriginalRootRetirementAcknowledgement {
        schema_version: 1,
        purpose: RETIREMENT_PURPOSE.into(),
        binding: joined.binding.clone(),
        sequence: 2,
        stage: OriginalRootRetirementStage::ObserveRootWorkersJoined,
        original_request: joined.digest().unwrap(),
        original_intent: intent_digest.clone(),
    };
    // This codec roundtrip remains data; it cannot construct any actual owner.
    let raw = acknowledgement.encode_original(&joined, &intent_digest).unwrap();
    assert!(OriginalRootRetirementAcknowledgement::decode_original(
        &raw, &joined, &intent_digest
    ).is_ok());
    assert!(OriginalRootRetirementAcknowledgement::decode_original(
        &raw, &intent, &intent_digest
    ).is_err());
    acknowledgement.original_intent = Digest32::of_bytes(b"other-intent-data").to_string();
    assert!(acknowledgement.require_original_request(&joined, &intent_digest).is_err());
    acknowledgement.original_intent = intent_digest.clone();
    acknowledgement.original_request = intent_digest.clone();
    assert!(acknowledgement.require_original_request(&joined, &intent_digest).is_err());
}

#[test]
fn root_owned_retirement_mode_has_no_implicit_or_unknown_value() {
    let original = serde_json::json!({
        "schema_version": 1,
        "initial_deployment": "/component/initial.json",
        "publication_deployment": "/component/current.json",
        "q24_model_reservation": "/component/model.json",
        "learning_profile": "/component/learning.json",
    });
    let default: DeploymentData = serde_json::from_value(original.clone()).unwrap();
    assert!(default.root_worker_retirement.is_none());
    let mut enabled = original.clone();
    enabled.as_object_mut().unwrap().insert(
        "root_worker_retirement".into(),
        serde_json::json!("original_root_workers"),
    );
    let enabled: DeploymentData = serde_json::from_value(enabled).unwrap();
    assert!(matches!(
        enabled.root_worker_retirement,
        Some(RootWorkerRetirementMode::OriginalRootWorkers)
    ));
    let encoded = serde_json::to_vec(&enabled).unwrap();
    let default = serde_json::to_vec(&default).unwrap();
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&default).unwrap(),
        original
    );
    assert_eq!(
        default.as_slice(),
        concat!(
            r#"{"schema_version":1,"initial_deployment":"/component/initial.json","#,
            r#""publication_deployment":"/component/current.json","#,
            r#""q24_model_reservation":"/component/model.json","#,
            r#""learning_profile":"/component/learning.json"}"#
        )
        .as_bytes()
    );
    let mut explicitly_disabled = original.clone();
    explicitly_disabled
        .as_object_mut()
        .unwrap()
        .insert("root_worker_retirement".into(), serde_json::Value::Null);
    let explicitly_disabled: DeploymentData =
        serde_json::from_value(explicitly_disabled).unwrap();
    assert!(explicitly_disabled.root_worker_retirement.is_none());
    assert_eq!(serde_json::to_vec(&explicitly_disabled).unwrap(), default);
    assert_ne!(Digest32::of_bytes(&encoded), Digest32::of_bytes(&default));
    let mut rejected = original.clone();
    rejected.as_object_mut().unwrap().insert(
        "root_worker_retirement".into(),
        serde_json::json!("complete_c"),
    );
    assert!(serde_json::from_value::<DeploymentData>(rejected).is_err());
    let mut rejected = original;
    rejected.as_object_mut().unwrap().insert("ordinary_completed".into(), serde_json::json!(true));
    assert!(serde_json::from_value::<DeploymentData>(rejected).is_err());
}

#[test]
fn physical_root_join_retains_its_actual_returned_owner_until_drop() -> io::Result<()> {
    let gate = gate()?;
    let (owned, mut peer) = UnixStream::pair()?;
    peer.set_nonblocking(true)?;
    std::thread::scope(|scope| -> io::Result<()> {
        let worker = scope.spawn(move || Ok::<_, io::Error>(owned));
        let returned = join_original_retirement_thread(
            worker, &gate, "component owned worker panicked",
        )?;
        gate.require_open()?;
        let mut byte = [0; 1];
        assert_eq!(peer.read(&mut byte).unwrap_err().kind(), io::ErrorKind::WouldBlock);
        drop(returned);
        assert_eq!(peer.read(&mut byte)?, 0);
        Ok(())
    })
}

#[test]
fn physical_root_join_error_closes_the_actual_retained_peer_and_preserves_cause() -> io::Result<()> {
    let gate = gate()?;
    let (endpoint, mut peer) = UnixStream::pair()?;
    let _retained = gate.retain_original_stream(&endpoint)?;
    peer.set_read_timeout(Some(std::time::Duration::from_secs(5)))?;
    std::thread::scope(|scope| -> io::Result<()> {
        let reading = scope.spawn(move || {
            let mut byte = [0; 1];
            peer.read(&mut byte)
        });
        let failed = scope.spawn(|| {
            Err::<(), _>(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "component original worker refused",
            ))
        });
        let error = join_original_retirement_thread(
            failed, &gate, "component original worker panicked",
        ).unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::PermissionDenied);
        assert_eq!(error.to_string(), "component original worker refused");
        assert!(gate.require_open().is_err());
        assert_eq!(reading.join().expect("component peer reader panicked")?, 0);
        Ok(())
    })
}

#[test]
fn physical_root_join_panic_cannot_leave_the_final_peer_open() -> io::Result<()> {
    let gate = gate()?;
    let (endpoint, mut peer) = UnixStream::pair()?;
    let _retained = gate.retain_original_stream(&endpoint)?;
    peer.set_read_timeout(Some(std::time::Duration::from_secs(5)))?;
    std::thread::scope(|scope| -> io::Result<()> {
        let panicked = scope.spawn(|| -> io::Result<()> {
            panic!("component actual worker panic");
        });
        let error = join_original_retirement_thread(
            panicked, &gate, "component original worker panicked",
        ).unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::Other);
        assert_eq!(error.to_string(), "component original worker panicked");
        assert!(gate.require_open().is_err());
        let mut byte = [0; 1];
        assert_eq!(peer.read(&mut byte)?, 0);
        Ok(())
    })
}
