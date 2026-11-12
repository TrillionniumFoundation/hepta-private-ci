//! Same-process framing only. Successful results always come from the actual
//! original C/T/B/S/task owners; no response or signature is synthesized.

use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_neuron::AnchorWitnessStore;
use pretty_assertions::assert_eq;

use super::super::super::Channel as EvidenceChannel;
use super::super::super::LearningIterationEvidenceClientV1;
use super::super::Channel;
use super::super::Context;
use super::super::Error;
use super::super::OriginalCircuitEvaluatedNextUseCommandClientV1;
use super::super::Retained;
use super::super::now;
use super::super::wire;
use super::OriginalCircuitEvaluatedNextUseCommandOwnerV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCircuitEvaluatedNextUseReceiptV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;
use crate::OriginalCircuitLearningReadClientV1;
use crate::learning_iteration_evidence_client::command_test_support as training_transport;
use crate::root_observation_stream::RootObservationStream;

fn channel(stream: UnixStream, timeout: Duration) -> anyhow::Result<HostAuthorityPeerChannel> {
    Ok(HostAuthorityPeerChannel::from_stream(
        stream,
        HostAuthorityPeerPolicy {
            peer: HostIssuerPeer {
                // SAFETY: this fixture observes its own process credentials.
                uid: unsafe { libc::geteuid() },
                pid: std::process::id(),
            },
            timeout,
            lifetime: Duration::from_secs(300),
            request_bound: 16_384,
            response_bound: 16_384,
        },
        training_transport::pidfd()?,
    )?)
}

/// Reopen only the C journal in the caller. Both original read clients move out
/// of the stopped fixture host with their unchanged channels and deadlines.
pub(crate) fn release_original_read_peers<W: AnchorWitnessStore + Send + 'static>(
    owner: Arc<OriginalCircuitEvaluatedNextUseCommandOwnerV1<W>>,
) -> anyhow::Result<(
    OriginalCircuitLearningReadClientV1,
    LearningIterationEvidenceClientV1,
)> {
    let original = Arc::try_unwrap(owner)
        .map_err(|_| anyhow::anyhow!("all original C serving fixtures must be stopped"))?;
    drop(original.owner);
    Ok((original.live, original.selector))
}

pub(crate) fn client(
    selection: OriginalCircuitEvaluatedSelectionReceiptV1,
    readback_only: bool,
    retained: Option<OriginalCircuitEvaluatedNextUseReceiptV1>,
) -> anyhow::Result<(
    OriginalCircuitEvaluatedNextUseCommandClientV1,
    HostAuthorityPeerChannel,
)> {
    let context = Context::from_original(if readback_only {
        selection.into_original_receipt_readback()
    } else {
        selection
    })?;
    let retained = retained
        .map(|saved| {
            let checked = wire::authenticate_completed(
                &context,
                saved.snapshot().clone(),
                saved.attestation().clone(),
                now()?,
            )?;
            anyhow::ensure!(
                wire::same_original(&saved, &checked),
                "same original cold C fixture"
            );
            Ok::<_, anyhow::Error>(checked)
        })
        .transpose()?;
    let binding = context.binding(now()?)?;
    let (stream, server) = UnixStream::pair()?;
    Ok((
        OriginalCircuitEvaluatedNextUseCommandClientV1 {
            channel: Mutex::new(Some(Channel {
                peer: channel(stream, Duration::from_secs(30))?,
                next_request_id: 1,
                execution_requested: readback_only,
            })),
            context,
            binding,
            retained: Mutex::new(retained.map(Retained::Readback)),
        },
        channel(server, Duration::from_secs(30))?,
    ))
}

pub(crate) fn stage_client(
    material: &OriginalCellQ24MaterialReceiptConfigV1,
    dataset: &OriginalCellQ24MaterialCommandReceiptV1,
    selection: &OriginalCircuitEvaluatedSelectionReceiptV1,
    readback_only: bool,
) -> anyhow::Result<(
    OriginalCircuitEvaluatedNextUseCommandClientV1,
    HostAuthorityPeerChannel,
)> {
    let (stream, server) = UnixStream::pair()?;
    let peer = channel(stream, Duration::from_secs(30))?;
    let client = if readback_only {
        OriginalCircuitEvaluatedNextUseCommandClientV1::recover_original_stage_channel(
            peer, material, dataset, selection,
        )?
    } else {
        OriginalCircuitEvaluatedNextUseCommandClientV1::bind_original_stage_channel(
            peer, material, dataset, selection,
        )?
    };
    Ok((client, channel(server, Duration::from_secs(30))?))
}

pub(crate) fn evidence_client<W: AnchorWitnessStore + Send + 'static>(
    owner: &OriginalCircuitEvaluatedNextUseCommandOwnerV1<W>,
) -> anyhow::Result<(LearningIterationEvidenceClientV1, HostAuthorityPeerChannel)> {
    let (stream, server) = UnixStream::pair()?;
    // SAFETY: production constructors still reject same-process custody.
    let uid = unsafe { libc::geteuid() };
    let transport = RootObservationStream::from_stream_for_uid(
        stream,
        training_transport::identity()?,
        training_transport::pidfd()?,
        Duration::from_millis(500),
        Duration::from_secs(300),
        uid,
    )?;
    let (_, verifier, _) = owner
        .context
        .selection
        .original_context()
        .receipt_configuration();
    Ok((
        LearningIterationEvidenceClientV1 {
            command: None,
            channel: Mutex::new(Some(EvidenceChannel {
                transport,
                next_request_id: 1,
            })),
            initial: owner.context.initial()?,
            actor_id: owner
                .context
                .selection
                .snapshot()
                .owners
                .next_use_observer
                .clone(),
            verifier,
        },
        channel(server, Duration::from_millis(500))?,
    ))
}

pub(crate) fn serve<W: AnchorWitnessStore + Send + 'static>(
    owner: Arc<OriginalCircuitEvaluatedNextUseCommandOwnerV1<W>>,
    mut channel: HostAuthorityPeerChannel,
) -> std::thread::JoinHandle<Result<u64, Error>> {
    std::thread::spawn(move || owner.serve_command_channel(&mut channel))
}

pub(crate) fn serve_evidence<W: AnchorWitnessStore + Send + 'static>(
    owner: Arc<OriginalCircuitEvaluatedNextUseCommandOwnerV1<W>>,
    mut channel: HostAuthorityPeerChannel,
) -> std::thread::JoinHandle<Result<u64, Error>> {
    std::thread::spawn(move || owner.serve_evidence_channel(&mut channel))
}

pub(crate) fn lose_ack<W: AnchorWitnessStore + Send + 'static>(
    owner: Arc<OriginalCircuitEvaluatedNextUseCommandOwnerV1<W>>,
    mut channel: HostAuthorityPeerChannel,
) -> std::thread::JoinHandle<anyhow::Result<OriginalCircuitEvaluatedNextUseReceiptV1>> {
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
            // The original journal has committed. Only its response ACK is lost.
            Err(HostIssuerTransportError::Unavailable)
        });
        anyhow::ensure!(result.is_err(), "original lost ACK must close the channel");
        completed.ok_or_else(|| anyhow::anyhow!("actual original C before lost ACK"))
    })
}

pub(crate) fn reject_wrong_context<W: AnchorWitnessStore + Send + 'static>(
    owner: &OriginalCircuitEvaluatedNextUseCommandOwnerV1<W>,
) -> anyhow::Result<()> {
    for field in [
        "operation",
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
    }
    let request = wire::Request::new(&owner.context, owner.binding, 1, wire::Action::Execute);
    anyhow::ensure!(
        owner
            .command_response(&serde_json::to_vec(&request)?, 2)
            .is_err()
    );
    for field in ["snapshot", "observation", "signature", "payload", "grant"] {
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
    anyhow::ensure!(owner.retained.lock().unwrap().is_none());
    Ok(())
}

pub(crate) fn refuse_evidence_without_pin<W: AnchorWitnessStore + Send + 'static>(
    owner: &OriginalCircuitEvaluatedNextUseCommandOwnerV1<W>,
) -> anyhow::Result<()> {
    let before = owner
        .execution_requested
        .load(std::sync::atomic::Ordering::Acquire);
    assert!(matches!(
        owner.evidence_response(b"{}", 1),
        Err(Error::Missing)
    ));
    assert_eq!(
        owner
            .execution_requested
            .load(std::sync::atomic::Ordering::Acquire),
        before
    );
    anyhow::ensure!(owner.retained.lock().unwrap().is_none());
    Ok(())
}

pub(crate) async fn cancel_queued_execute<W: AnchorWitnessStore + Send + 'static>(
    owner: Arc<OriginalCircuitEvaluatedNextUseCommandOwnerV1<W>>,
) -> anyhow::Result<()> {
    let (client, channel) = client(owner.context.selection.clone(), false, None)?;
    let peer = serve(owner, channel);
    tokio::task::spawn_blocking(move || -> anyhow::Result<()> {
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .max_blocking_threads(1)
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
            drop(request);
            release.send(())?;
            blocker.await??;
            assert!(
                pending,
                "the actual C command was queued before cancellation"
            );
            assert!(matches!(client.readback().await, Err(Error::Unavailable)));
            assert!(matches!(
                client.attest_completed_task().await,
                Err(Error::Unavailable)
            ));
            drop(client);
            assert_eq!(
                peer.join()
                    .map_err(|_| anyhow::anyhow!("queued original C peer"))??,
                0
            );
            Ok(())
        })
    })
    .await
    .map_err(|_| anyhow::anyhow!("queued cancellation runtime"))?
}
