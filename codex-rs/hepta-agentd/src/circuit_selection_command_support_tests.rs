//! Explicit same-process transport fixtures. Successful Selection responses
//! still come from the actual original owner and Published Circuit read peer.
//! Training metadata below is an enrolled fixture, not a native Training run.

use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_neuron::AnchorWitnessStore;

use super::super::super::Channel as EvidenceChannel;
use super::super::super::LearningIterationEvidenceClientV1;
use super::super::Channel;
use super::super::Error;
use super::super::OriginalCircuitSelectionCommandClientV1;
use super::super::OriginalCircuitSelectionCommandContextV1;
use super::super::OriginalCircuitSelectionCommandReceiptV1;
use super::super::evidence_wire;
use super::super::now;
use super::super::wire;
use super::OriginalCircuitSelectionCommandOwnerV1;
use crate::OriginalCellQ24TrainingCommandContextV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;
use crate::learning_iteration_evidence_client::command_test_support as training_transport;
use crate::root_observation_stream::RootObservationStream;

pub(crate) use training_transport::identity;
pub(crate) use training_transport::pidfd;

fn channel(stream: UnixStream, timeout: Duration) -> anyhow::Result<HostAuthorityPeerChannel> {
    Ok(HostAuthorityPeerChannel::from_stream(
        stream,
        HostAuthorityPeerPolicy {
            peer: HostIssuerPeer {
                // SAFETY: observe this explicit fixture process only.
                uid: unsafe { libc::geteuid() },
                pid: std::process::id(),
            },
            timeout,
            lifetime: Duration::from_secs(300),
            request_bound: 16_384,
            response_bound: 16_384,
        },
        pidfd()?,
    )?)
}

/// Feed the existing actual Trainer client's readback decoder an explicitly
/// signed Training fixture. Only that real decoder constructs its opaque result;
/// this does not claim that the metadata producer performed native training.
pub(crate) async fn training_fixture_result(
    training: LearningIterationSnapshotV1,
    scope: FrozenLearningScopeV2,
    verifier: LearningEvidenceVerifierV1,
    signature: SignedLearningEvidenceV1,
) -> anyhow::Result<(
    LearningIterationSnapshotV1,
    OriginalCellQ24TrainingCommandReceiptV1,
)> {
    let mut dataset = training.clone();
    let original = dataset
        .receipts
        .pop()
        .ok_or_else(|| anyhow::anyhow!("Training fixture"))?;
    dataset.head_digest = original.predecessor;
    let context = OriginalCellQ24TrainingCommandContextV1 {
        dataset: dataset.clone(),
        scope,
        verifier,
    };
    let (client, mut channel) = training_transport::client(context, true, None)?;
    let snapshot = STANDARD_NO_PAD.encode(encode_original_owner_snapshot_v1(&training)?);
    let evidence = evidence_wire::Evidence::from_original(&signature);
    let server = std::thread::spawn(move || -> anyhow::Result<()> {
        anyhow::ensure!(channel.exchange(|bytes| {
            let request: serde_json::Value = serde_json::from_slice(bytes)
                .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
            if request["operation"] != "runtime.learning.original-q24-training.command.v1"
                || request["action"] != "readback" || request["request_id"] != 1
            {
                return Err(HostIssuerTransportError::InvalidRequest);
            }
            let response = serde_json::json!({
                "schema": request["schema"], "operation": request["operation"],
                "request_id": request["request_id"], "binding": request["binding"],
                "operation_id": request["operation_id"], "dataset_head": request["dataset_head"],
                "scope_binding": request["scope_binding"], "actor_id": request["actor_id"],
                "action": request["action"],
                "result": { "state": "completed", "snapshot": snapshot, "evidence": evidence },
            });
            serde_json::to_vec(&response).map_err(|_| HostIssuerTransportError::InvalidRequest)
        })?, "actual fixture Trainer readback frame");
        Ok(())
    });
    let completed = client.readback().await?;
    drop(client);
    server
        .join()
        .map_err(|_| anyhow::anyhow!("Trainer result fixture thread"))??;
    Ok((dataset, completed))
}

pub(crate) fn client(
    context: OriginalCircuitSelectionCommandContextV1,
    readback_only: bool,
    retained: Option<OriginalCircuitSelectionCommandReceiptV1>,
) -> anyhow::Result<(OriginalCircuitSelectionCommandClientV1, HostAuthorityPeerChannel)> {
    let (stream, server) = UnixStream::pair()?;
    let binding = context.binding(now()?)?;
    if let Some(expected) = &retained {
        anyhow::ensure!(
            wire::authenticate_completed(
                &context,
                expected.snapshot.clone(),
                expected.attestation.clone(),
                now()?,
            )? == *expected,
            "original fixture retained Selection"
        );
    }
    Ok((
        OriginalCircuitSelectionCommandClientV1 {
            channel: Mutex::new(Some(Channel {
                peer: channel(stream, Duration::from_secs(30))?,
                next_request_id: 1,
                execution_requested: readback_only,
            })),
            context,
            binding,
            retained: Mutex::new(retained),
        },
        channel(server, Duration::from_secs(30))?,
    ))
}

pub(crate) fn recover_client(
    training: LearningIterationSnapshotV1,
    scope: FrozenLearningScopeV2,
    verifier: LearningEvidenceVerifierV1,
    training_evidence: SignedLearningEvidenceV1,
    expected: Option<(LearningIterationSnapshotV1, SignedLearningEvidenceV1)>,
) -> anyhow::Result<(OriginalCircuitSelectionCommandClientV1, HostAuthorityPeerChannel)> {
    let context = OriginalCircuitSelectionCommandContextV1::from_checkpoint(training, scope, verifier, training_evidence)?;
    let retained = expected
        .map(|(snapshot, signed)| wire::authenticate_completed(&context, snapshot, signed, now()?))
        .transpose()?;
    client(context, true, retained)
}

pub(crate) fn evidence_client(
    context: &OriginalCircuitSelectionCommandContextV1,
) -> anyhow::Result<(LearningIterationEvidenceClientV1, HostAuthorityPeerChannel)> {
    let (stream, server) = UnixStream::pair()?;
    // SAFETY: the public custody constructors still refuse this same process.
    let uid = unsafe { libc::geteuid() };
    let transport = RootObservationStream::from_stream_for_uid(
        stream,
        identity()?,
        pidfd()?,
        Duration::from_millis(500),
        Duration::from_secs(300),
        uid,
    )?;
    Ok((
        LearningIterationEvidenceClientV1 {
            channel: Mutex::new(Some(EvidenceChannel {
                transport,
                next_request_id: 1,
            })),
            initial: context.initial()?,
            actor_id: context.training.owners.selector.clone(),
            verifier: context.verifier.clone(),
        },
        channel(server, Duration::from_millis(500))?,
    ))
}

pub(crate) fn serve<W: AnchorWitnessStore + Send + 'static>(
    owner: Arc<OriginalCircuitSelectionCommandOwnerV1<W>>,
    mut channel: HostAuthorityPeerChannel,
) -> std::thread::JoinHandle<Result<u64, Error>> {
    std::thread::spawn(move || owner.serve_command_channel(&mut channel))
}
pub(crate) fn serve_evidence<W: AnchorWitnessStore + Send + 'static>(
    owner: Arc<OriginalCircuitSelectionCommandOwnerV1<W>>,
    mut channel: HostAuthorityPeerChannel,
) -> std::thread::JoinHandle<Result<u64, Error>> {
    std::thread::spawn(move || owner.serve_evidence_channel(&mut channel))
}

pub(crate) fn lose_ack<W: AnchorWitnessStore + Send + 'static>(
    owner: Arc<OriginalCircuitSelectionCommandOwnerV1<W>>,
    mut channel: HostAuthorityPeerChannel,
) -> std::thread::JoinHandle<anyhow::Result<OriginalCircuitSelectionCommandReceiptV1>> {
    std::thread::spawn(move || {
        let mut completed = None;
        let result = channel.exchange(|bytes| {
            let actual = owner
                .command_response(bytes, 1)
                .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
            let response: wire::Response = serde_json::from_slice(&actual)
                .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
            let wire::CommandResult::Completed { snapshot, evidence } = response.result else {
                return Err(HostIssuerTransportError::InvalidRequest);
            };
            completed = Some(
                wire::decode_completed(
                    &owner.context,
                    snapshot,
                    evidence,
                    now().map_err(|_| HostIssuerTransportError::InvalidRequest)?,
                )
                .map_err(|_| HostIssuerTransportError::InvalidRequest)?,
            );
            // Original completed bytes and signature already exist. Only the
            // response ACK is lost; this creates no replacement observation.
            Err(HostIssuerTransportError::Unavailable)
        });
        anyhow::ensure!(result.is_err(), "lost ACK closes this connection");
        completed.ok_or_else(|| anyhow::anyhow!("actual Selection before lost ACK"))
    })
}

pub(crate) fn reject_wrong_context<W: AnchorWitnessStore + Send + 'static>(
    owner: &OriginalCircuitSelectionCommandOwnerV1<W>,
) -> anyhow::Result<()> {
    for field in [
        "actor_id",
        "operation_id",
        "training_head",
        "scope_binding",
        "binding",
    ] {
        let request = wire::Request::new(&owner.context, owner.binding, 1, wire::Action::Execute);
        let mut value = serde_json::to_value(request)?;
        value[field] = serde_json::Value::String("changed-original-context".into());
        anyhow::ensure!(
            owner
                .command_response(&serde_json::to_vec(&value)?, 1)
                .is_err()
        );
        anyhow::ensure!(
            !owner
                .execution_requested
                .load(std::sync::atomic::Ordering::Acquire)
        );
    }
    let request = wire::Request::new(&owner.context, owner.binding, 1, wire::Action::Execute);
    anyhow::ensure!(
        owner
            .command_response(&serde_json::to_vec(&request)?, 2)
            .is_err()
    );
    for field in ["snapshot", "observation", "signature", "payload"] {
        let mut value = serde_json::to_value(&request)?;
        value[field] = serde_json::json!({"caller_supplied": true});
        anyhow::ensure!(
            owner
                .command_response(&serde_json::to_vec(&value)?, 1)
                .is_err()
        );
    }
    anyhow::ensure!(
        !owner
            .execution_requested
            .load(std::sync::atomic::Ordering::Acquire)
    );
    Ok(())
}
