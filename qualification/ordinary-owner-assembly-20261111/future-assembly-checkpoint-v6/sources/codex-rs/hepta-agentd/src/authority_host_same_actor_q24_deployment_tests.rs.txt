//! Data-protocol and actual same-Gate stop components only. These tests do not
//! register Initial/Current, execute A/B/C, or produce a business receipt.

use super::*;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::os::unix::net::UnixStream;

use crate::same_actor_q24_deployment_protocol::OriginalDeploymentAcknowledgement;
use crate::same_actor_q24_deployment_protocol::OriginalDeploymentBinding;
use crate::same_actor_q24_deployment_protocol::OriginalDeploymentProgress;
use crate::same_actor_q24_deployment_protocol::OriginalDeploymentRequest;
use crate::same_actor_q24_deployment_protocol::PROGRESS_PURPOSE;

fn binding() -> OriginalDeploymentBinding {
    OriginalDeploymentBinding {
        phase: Digest32::of_bytes(b"component-phase-correlation").to_string(),
        root: codex_hepta_memory::CognitiveCheckpointPeerLifetime {
            uid: 0, pid: 91, boot_id: "component-data-only-boot".into(),
            process_start_ticks: 17,
        },
        consumer: codex_hepta_memory::CognitiveCheckpointPeerLifetime {
            uid: 60001, pid: 92, boot_id: "component-data-only-boot".into(),
            process_start_ticks: 18,
        },
        identity: Digest32::of_bytes(b"component-identity-data").to_string(),
        root_end_boottime_ns: 111,
    }
}

fn initial_request() -> OriginalDeploymentRequest {
    OriginalDeploymentRequest {
        schema_version: 1,
        purpose: PROGRESS_PURPOSE.into(),
        binding: binding(),
        sequence: 1,
        progress: OriginalDeploymentProgress::InputsOpened,
    }
}

fn gate() -> io::Result<Arc<SameActorPhaseGate>> {
    SameActorPhaseGate::from_original_deadline(
        SameActorPhaseDeadline::at_original_service_start(std::time::Duration::from_secs(10))?,
    )
}

#[test]
fn original_progress_requires_exact_phase_incarnation_and_stage() {
    let original = binding();
    let mut request = initial_request();
    assert!(request.require_original_stage(&original, DeploymentStage::Initial).is_ok());
    let raw = request.encode_original().unwrap();
    assert_eq!(
        OriginalDeploymentRequest::decode_original(&raw).unwrap().encode_original().unwrap(),
        raw,
    );
    request.binding.root.process_start_ticks += 1;
    assert!(request.require_original_stage(&original, DeploymentStage::Initial).is_err());
    request.binding = original.clone();
    request.binding.consumer.process_start_ticks += 1;
    assert!(request.require_original_stage(&original, DeploymentStage::Initial).is_err());
    request.binding = original.clone();
    request.binding.phase = Digest32::of_bytes(b"different-phase-data").to_string();
    assert!(request.require_original_stage(&original, DeploymentStage::Initial).is_err());
    request.binding = original.clone();
    request.purpose = "different-purpose".into();
    assert!(request.require_original_stage(&original, DeploymentStage::Initial).is_err());
    request = initial_request();
    assert!(request.require_original_stage(&original, DeploymentStage::Current).is_err());
    request.sequence = 2;
    assert!(request.encode_original().is_err());
}

#[test]
fn original_progress_refuses_noncanonical_unknown_or_oversized_data() {
    let mut request = initial_request();
    let raw = request.encode_original().unwrap();
    let mut changed = raw.clone();
    changed.push(b' ');
    assert!(OriginalDeploymentRequest::decode_original(&changed).is_err());
    let mut value = serde_json::to_value(&request).unwrap();
    value.as_object_mut().unwrap().insert("unknown_authority".into(), serde_json::json!(true));
    assert!(OriginalDeploymentRequest::decode_original(&serde_json::to_vec(&value).unwrap()).is_err());
    request.sequence = 3;
    request.progress = OriginalDeploymentProgress::OriginalSelectionReady {
        canonical_material: String::new(),
    };
    assert!(request.encode_original().is_err());
    request.progress = OriginalDeploymentProgress::OriginalSelectionReady {
        canonical_material: "x".repeat(65_537),
    };
    assert!(request.encode_original().is_err());
    let mut response = OriginalDeploymentAcknowledgement::from_actual_registration(
        &initial_request(), Some(Digest32::of_bytes(b"component-ack-data").to_string()),
    ).unwrap();
    response.original_request = Digest32::of_bytes(b"another-original-request").to_string();
    assert!(response.require_original_request(&initial_request()).is_err());
}

#[test]
fn original_phase_slots_refuse_aliases_and_relative_paths() {
    assert!(require_distinct_deployment_paths(&[
        Path::new("/root/original-a"), Path::new("/root/original-b"),
    ]).is_ok());
    assert!(require_distinct_deployment_paths(&[
        Path::new("/root/original-a"), Path::new("/root/original-a"),
    ]).is_err());
    assert!(require_distinct_deployment_paths(&[
        Path::new("relative-a"), Path::new("/root/original-b"),
    ]).is_err());
}

#[test]
fn actual_acknowledgement_kind_cannot_advance_another_phase_stage() {
    let binding = Digest32::of_bytes(b"component-ack-data").to_string();
    assert!(bridge::require_original_acknowledgement(
        RootSameActorHostAcknowledgementV1::CurrentRegistered { binding: binding.clone() },
        DeploymentStage::Initial,
    ).is_err());
    assert!(bridge::require_original_acknowledgement(
        RootSameActorHostAcknowledgementV1::ScopedRightsSent,
        DeploymentStage::Current,
    ).is_err());
    assert_eq!(
        bridge::require_original_acknowledgement(
            RootSameActorHostAcknowledgementV1::InitialRegistered { binding: binding.clone() },
            DeploymentStage::Initial,
        ).unwrap(),
        Some(binding),
    );
    assert!(bridge::require_original_acknowledgement(
        RootSameActorHostAcknowledgementV1::InitialRegistered { binding: "00".repeat(32) },
        DeploymentStage::Initial,
    ).is_err());
}

#[test]
fn lost_actual_ack_channel_closes_the_same_retained_endpoint() -> io::Result<()> {
    let gate = gate()?;
    let (stream, mut peer) = UnixStream::pair()?;
    let _retained = gate.retain_original_stream(&stream)?;
    let (sender, receiver) = mpsc::sync_channel(1);
    drop(sender);
    assert!(bridge::receive_original_acknowledgement(&receiver, &gate).is_err());
    assert!(gate.require_open().is_err());
    let mut bytes = [0; 1];
    assert_eq!(peer.read(&mut bytes)?, 0);
    Ok(())
}

#[test]
fn queued_ack_cannot_reopen_a_closed_original_gate() -> io::Result<()> {
    let gate = gate()?;
    let (sender, receiver) = mpsc::sync_channel(1);
    sender.try_send(RootSameActorHostAcknowledgementV1::ScopedRightsSent)
        .map_err(io::Error::other)?;
    gate.close();
    assert!(bridge::receive_original_acknowledgement(&receiver, &gate).is_err());
    assert!(gate.require_open().is_err());
    assert!(receiver.try_recv().is_ok());
    Ok(())
}

#[test]
fn waiting_actual_ack_observer_wakes_on_original_gate_close() -> io::Result<()> {
    let gate = gate()?;
    let (sender, receiver) = mpsc::sync_channel(1);
    std::thread::scope(|scope| {
        let waiting_gate = Arc::clone(&gate);
        let waiting = scope.spawn(move || {
            bridge::receive_original_acknowledgement(&receiver, &waiting_gate)
        });
        gate.close();
        assert!(waiting.join().expect("original acknowledgement observer panicked").is_err());
    });
    drop(sender);
    assert!(gate.require_open().is_err());
    Ok(())
}

#[test]
fn post_handoff_uncertainty_retains_the_original_error() {
    let original = io::Error::new(io::ErrorKind::PermissionDenied, "original file pin refused");
    let error = deployment_uncertain("original Initial host command", original);
    let context = error.get_ref()
        .and_then(|source| source.downcast_ref::<DeploymentUncertain>())
        .expect("actual deployment uncertainty context");
    assert_eq!(context.source.kind(), io::ErrorKind::PermissionDenied);
    assert_eq!(context.source.to_string(), "original file pin refused");
}
