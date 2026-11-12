//! Explicit same-process transport only. Successful responses always come
//! from the actual original C Observer and actual Published/Selector peers.
//! This helper cannot run C or produce a replacement original observation.

use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use pretty_assertions::assert_eq;

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
use super::super::OriginalCircuitNextUseCommandClientV1;
use super::super::OriginalCircuitNextUseCommandContextV1;
use super::super::OriginalCircuitNextUseCommandReceiptV1;
use super::super::evidence_wire;
use super::super::now;
use super::super::wire;
use super::OriginalCircuitNextUseCommandOwnerV1;
use crate::learning_iteration_evidence_client::command_test_support as training_transport;
use crate::root_observation_stream::RootObservationStream;

pub(crate) use training_transport::identity;
pub(crate) use training_transport::pidfd;
pub(crate) use super::evidence::serve_evidence_late_response;

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

pub(crate) fn client(
    context: OriginalCircuitNextUseCommandContextV1,
    readback_only: bool,
    retained: Option<OriginalCircuitNextUseCommandReceiptV1>,
) -> anyhow::Result<(
    OriginalCircuitNextUseCommandClientV1,
    HostAuthorityPeerChannel,
)> {
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
        OriginalCircuitNextUseCommandClientV1 {
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
    selection: LearningIterationSnapshotV1,
    scope: FrozenLearningScopeV2,
    verifier: LearningEvidenceVerifierV1,
    training_evidence: SignedLearningEvidenceV1,
    selection_evidence: SignedLearningEvidenceV1,
    expected: Option<(LearningIterationSnapshotV1, SignedLearningEvidenceV1)>,
) -> anyhow::Result<(
    OriginalCircuitNextUseCommandClientV1,
    HostAuthorityPeerChannel,
)> {
    let context = OriginalCircuitNextUseCommandContextV1::from_checkpoint(
        selection,
        scope,
        verifier,
        training_evidence,
        selection_evidence,
    )?;
    let retained = expected
        .map(|(snapshot, signed)| wire::authenticate_completed(&context, snapshot, signed, now()?))
        .transpose()?;
    client(context, true, retained)
}

pub(crate) fn evidence_client(
    context: &OriginalCircuitNextUseCommandContextV1,
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
            command: None,
            channel: Mutex::new(Some(EvidenceChannel {
                transport,
                next_request_id: 1,
            })),
            initial: context.initial()?,
            actor_id: context.selection.owners.next_use_observer.clone(),
            verifier: context.verifier.clone(),
        },
        channel(server, Duration::from_millis(500))?,
    ))
}

pub(crate) fn serve<W: AnchorWitnessStore + Send + 'static>(
    owner: Arc<OriginalCircuitNextUseCommandOwnerV1<W>>,
    mut channel: HostAuthorityPeerChannel,
) -> std::thread::JoinHandle<Result<u64, Error>> {
    std::thread::spawn(move || owner.serve_command_channel(&mut channel))
}
pub(crate) fn serve_evidence<W: AnchorWitnessStore + Send + 'static>(
    owner: Arc<OriginalCircuitNextUseCommandOwnerV1<W>>,
    mut channel: HostAuthorityPeerChannel,
) -> std::thread::JoinHandle<Result<u64, Error>> {
    std::thread::spawn(move || owner.serve_evidence_channel(&mut channel))
}

pub(crate) fn lose_ack<W: AnchorWitnessStore + Send + 'static>(
    owner: Arc<OriginalCircuitNextUseCommandOwnerV1<W>>,
    mut channel: HostAuthorityPeerChannel,
) -> std::thread::JoinHandle<anyhow::Result<OriginalCircuitNextUseCommandReceiptV1>> {
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
        completed.ok_or_else(|| anyhow::anyhow!("actual C completion before lost ACK"))
    })
}

pub(crate) fn reject_wrong_context<W: AnchorWitnessStore + Send + 'static>(
    owner: &OriginalCircuitNextUseCommandOwnerV1<W>,
) -> anyhow::Result<()> {
    for field in [
        "actor_id",
        "operation_id",
        "selection_head",
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

/// Cancel an actual original-client Execute while its sole worker is occupied.
pub(crate) async fn cancel_queued_execute<W: AnchorWitnessStore + Send + 'static>(
    owner: Arc<OriginalCircuitNextUseCommandOwnerV1<W>>,
) -> anyhow::Result<()> {
    let (client, channel) = client(
        owner.context.clone(),
        /*readback_only*/ false,
        /*retained*/ None,
    )?;
    let peer = serve(owner, channel);
    tokio::task::spawn_blocking(move || -> anyhow::Result<()> {
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .max_blocking_threads(/*val*/ 1)
            .build()?;
        runtime.block_on(async move {
            let (occupied, waiting) = tokio::sync::oneshot::channel();
            let (release, blocked) = std::sync::mpsc::channel();
            let blocker = tokio::task::spawn_blocking(move || -> anyhow::Result<()> {
                let _ = occupied.send(());
                blocked
                    .recv()
                    .map_err(|_| anyhow::anyhow!("queued cancellation release"))?;
                Ok(())
            });
            waiting.await?;
            let mut request = Box::pin(client.attest_completed_task());
            let pending = std::future::poll_fn(|cx| {
                std::task::Poll::Ready(std::future::Future::poll(request.as_mut(), cx).is_pending())
            })
            .await;
            // The only blocking worker is still occupied. Dropping this exact
            // future must fence the queued original Execute before release.
            drop(request);
            release.send(())?;
            blocker.await??;
            assert!(pending, "the actual Execute was queued before cancellation");
            assert!(matches!(client.readback().await, Err(Error::Unavailable)));
            assert!(matches!(
                client.attest_completed_task().await,
                Err(Error::Unavailable)
            ));
            drop(client);
            let frames = peer
                .join()
                .map_err(|_| anyhow::anyhow!("queued original peer"))??;
            assert_eq!(frames, 0);
            Ok(())
        })
    })
    .await
    .map_err(|_| anyhow::anyhow!("queued cancellation runtime"))?
}
