//! Same-process peer admission only. Responses come from the actual Published
//! owner. Invalid response injection is confined to negative mechanism cases.
use super::*;
use crate::OriginalCircuitEvaluatedReadinessChannelV1;
use crate::OriginalCircuitLearningReadOwnerV1;
use crate::learning_iteration_evidence_client::command_test_support;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_neuron::AnchorWitnessStore;
use std::os::unix::net::UnixStream;
use std::time::Duration;

fn channel(stream: UnixStream) -> anyhow::Result<HostAuthorityPeerChannel> {
    Ok(HostAuthorityPeerChannel::from_stream(
        stream,
        HostAuthorityPeerPolicy {
            // SAFETY: this fixture admits only its own live UID/process.
            peer: HostIssuerPeer {
                uid: unsafe { libc::geteuid() },
                pid: std::process::id(),
            },
            timeout: Duration::from_millis(500),
            lifetime: Duration::from_secs(300),
            request_bound: 16_384,
            response_bound: 16_384,
        },
        command_test_support::pidfd()?,
    )?)
}

pub(crate) fn client(
    material: &OriginalCellQ24MaterialReceiptConfigV1,
    dataset: &OriginalCellQ24MaterialCommandReceiptV1,
    selection: &OriginalCircuitEvaluatedSelectionReceiptV1,
) -> anyhow::Result<(
    OriginalCircuitEvaluatedCompletionReadinessClientV1,
    HostAuthorityPeerChannel,
)> {
    let (stream, server) = UnixStream::pair()?;
    Ok((
        OriginalCircuitEvaluatedCompletionReadinessClientV1::bind_original_stage_channel(
            channel(stream)?,
            material,
            dataset,
            selection,
        )?,
        channel(server)?,
    ))
}

pub(crate) fn version_client(
    material: &OriginalCellQ24MaterialReceiptConfigV1,
    dataset: &OriginalCellQ24MaterialCommandReceiptV1,
    selection: &OriginalCircuitEvaluatedSelectionReceiptV1,
) -> anyhow::Result<(
    OriginalCircuitEvaluatedCompletionReadinessClientV1,
    OriginalCircuitEvaluatedReadinessChannelV1,
)> {
    let (stream, server) = UnixStream::pair()?;
    Ok((
        OriginalCircuitEvaluatedCompletionReadinessClientV1::bind_original_stage_channel(
            channel(stream)?,
            material,
            dataset,
            selection,
        )?,
        OriginalCircuitEvaluatedReadinessChannelV1::fixture_original_stream(server)?,
    ))
}

pub(crate) fn serve<
    C: AnchorWitnessStore + Send + 'static,
    S: AnchorWitnessStore + Send + 'static,
>(
    owner: Arc<OriginalCircuitLearningReadOwnerV1<C, S>>,
    mut channel: HostAuthorityPeerChannel,
) -> std::thread::JoinHandle<Result<u64, Error>> {
    std::thread::spawn(move || owner.serve_evaluated_readiness_channel(&mut channel))
}

pub(crate) fn reject_legacy_and_changed_requests<C: AnchorWitnessStore, S: AnchorWitnessStore>(
    owner: &OriginalCircuitLearningReadOwnerV1<C, S>,
    client: &OriginalCircuitEvaluatedCompletionReadinessClientV1,
) -> anyhow::Result<()> {
    let request = Request::new(&client.context, client.binding, 1)?;
    let encoded = serde_json::to_vec(&request)?;
    anyhow::ensure!(
        owner.readiness_response(&encoded, 1).is_err(),
        "legacy readiness stays strict"
    );
    for field in [
        "purpose",
        "operation",
        "binding",
        "prefix_head",
        "operation_id",
        "mode",
        "request_id",
    ] {
        let mut changed = serde_json::to_value(&request)?;
        let slot = if field == "purpose" {
            &mut changed[field]
        } else {
            &mut changed["original"][field]
        };
        *slot = match field {
            "request_id" => serde_json::json!(2),
            "mode" => serde_json::json!("selection"),
            _ => serde_json::json!("wrong-original-evaluated-readiness"),
        };
        anyhow::ensure!(
            owner
                .evaluated_readiness_response(&serde_json::to_vec(&changed)?, 1)
                .is_err(),
            "{field} substitution"
        );
    }
    Ok(())
}

pub(crate) fn changed_ready_to_pending<
    C: AnchorWitnessStore + Send + 'static,
    S: AnchorWitnessStore + Send + 'static,
>(
    owner: Arc<OriginalCircuitLearningReadOwnerV1<C, S>>,
    mut channel: HostAuthorityPeerChannel,
) -> std::thread::JoinHandle<anyhow::Result<()>> {
    std::thread::spawn(move || {
        for request_id in 1..=2 {
            anyhow::ensure!(
                channel.exchange(|bytes| {
                    let actual = owner
                        .evaluated_readiness_response(bytes, request_id)
                        .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                    if request_id == 1 {
                        return Ok(actual);
                    }
                    let mut response: Response = serde_json::from_slice(&actual)
                        .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                    if !matches!(response.result, Readiness::Ready { .. }) {
                        return Err(HostIssuerTransportError::InvalidRequest);
                    }
                    response.result = Readiness::NotReady;
                    serde_json::to_vec(&response)
                        .map_err(|_| HostIssuerTransportError::InvalidRequest)
                })?,
                "actual original readiness frame"
            );
        }
        Ok(())
    })
}

pub(crate) fn cancel_queued(
    client: OriginalCircuitEvaluatedCompletionReadinessClientV1,
) -> anyhow::Result<()> {
    std::thread::spawn(move || -> anyhow::Result<()> {
        let runtime = tokio::runtime::Builder::new_current_thread()
            .max_blocking_threads(/*val*/ 1)
            .enable_all()
            .build()?;
        runtime.block_on(async move {
            let (occupied, ready) = tokio::sync::oneshot::channel();
            let (release, blocked) = std::sync::mpsc::channel();
            let blocker = tokio::task::spawn_blocking(move || {
                let _ = occupied.send(());
                blocked.recv()
            });
            ready.await?;
            let mut request = Box::pin(client.read_current());
            let pending = std::future::poll_fn(|cx| {
                std::task::Poll::Ready(std::future::Future::poll(request.as_mut(), cx).is_pending())
            })
            .await;
            assert!(pending, "actual readiness request queued before drop");
            drop(request);
            release.send(())?;
            blocker.await??;
            tokio::task::spawn_blocking(|| {}).await?;
            assert!(matches!(
                client.read_current().await,
                Err(Error::Unavailable)
            ));
            drop(client);
            Ok(())
        })
    })
    .join()
    .map_err(|_| anyhow::anyhow!("cancelled readiness runtime"))?
}
