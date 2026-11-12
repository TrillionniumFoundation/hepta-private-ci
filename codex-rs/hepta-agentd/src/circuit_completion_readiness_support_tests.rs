//! Same-process transport fixture. Every reply begins with an actual read
//! through the original Published owner; only named negative replies mutate it.
//! This fixture cannot construct a resident Root gate or grant execution.

use std::sync::Arc;
use std::thread::JoinHandle;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_neuron::AnchorWitnessStore;

use super::super::OriginalCircuitLearningReadClientV1;
use super::super::OriginalCircuitLearningReadOwnerV1;
use super::super::fixture;
use super::*;

pub(crate) fn retained_publication_intent(
    task: &crate::PublishedCircuitFeatureTaskV1,
) -> anyhow::Result<Digest32> {
    let crate::circuit_feature_current::Publication::Update { original, .. } = &task.0.publication
    else {
        anyhow::bail!("actual retained Control publication");
    };
    Ok(original.intent_digest())
}

pub(crate) fn client(
    context: Context,
) -> anyhow::Result<(
    OriginalCircuitCompletionReadinessClientV1,
    HostAuthorityPeerChannel,
)> {
    anyhow::ensure!(original::mode(&context)? == original::Mode::NextUse);
    let (original, server) = fixture::client(context)?;
    let OriginalCircuitLearningReadClientV1 {
        context,
        binding,
        channel,
        retained,
    } = original;
    Ok((
        OriginalCircuitCompletionReadinessClientV1 {
            context: context.legacy()?.clone(),
            binding,
            channel,
            retained,
        },
        server,
    ))
}

pub(crate) fn serve<
    C: AnchorWitnessStore + Send + 'static,
    S: AnchorWitnessStore + Send + 'static,
>(
    owner: Arc<OriginalCircuitLearningReadOwnerV1<C, S>>,
    mut channel: HostAuthorityPeerChannel,
) -> JoinHandle<Result<u64, Error>> {
    std::thread::spawn(move || owner.serve_readiness_channel(&mut channel))
}

#[derive(Clone, Copy)]
pub(crate) enum Change {
    PendingAfterReady,
    PublicationAfterReady,
    WrongPurpose,
}

pub(crate) fn changed_reply<
    C: AnchorWitnessStore + Send + 'static,
    S: AnchorWitnessStore + Send + 'static,
>(
    owner: Arc<OriginalCircuitLearningReadOwnerV1<C, S>>,
    mut channel: HostAuthorityPeerChannel,
    change: Change,
) -> JoinHandle<anyhow::Result<u64>> {
    std::thread::spawn(move || {
        let frames = if matches!(change, Change::WrongPurpose) {
            1
        } else {
            2
        };
        for request_id in 1..=frames {
            let mut original_read = false;
            let result = channel.exchange(|bytes| {
                let actual = owner
                    .readiness_response(bytes, request_id)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                let mut response: Response = serde_json::from_slice(&actual)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                if !matches!(response.result, Readiness::Ready { .. }) {
                    return Err(HostIssuerTransportError::InvalidRequest);
                }
                original_read = true;
                match (change, request_id) {
                    (Change::PendingAfterReady, 2) => response.result = Readiness::NotReady,
                    (Change::PublicationAfterReady, 2) => {
                        let Readiness::Ready { read } = &mut response.result else {
                            return Err(HostIssuerTransportError::InvalidRequest);
                        };
                        read.source_publication = Some(
                            Digest32::of_bytes(b"changed-after-original-current-read").to_string(),
                        );
                    }
                    (Change::WrongPurpose, _) => response.request.purpose = "other-purpose".into(),
                    _ => {}
                }
                serde_json::to_vec(&response).map_err(|_| HostIssuerTransportError::InvalidRequest)
            });
            anyhow::ensure!(
                original_read,
                "actual original C read preceded response mutation"
            );
            anyhow::ensure!(result?, "the changed response was actually sent");
        }
        Ok(frames)
    })
}

pub(crate) fn reject_unknown_request_fields<C: AnchorWitnessStore, S: AnchorWitnessStore>(
    owner: &OriginalCircuitLearningReadOwnerV1<C, S>,
    context: &Context,
) -> anyhow::Result<()> {
    let binding = original::context_binding(context, now()?)?;
    let request = Request::new(context, binding, 1)?;
    for field in ["snapshot", "observation", "signature", "ready", "execute"] {
        let mut value = serde_json::to_value(&request)?;
        value[field] = serde_json::json!({"caller_supplied": true});
        anyhow::ensure!(matches!(
            owner.readiness_response(&serde_json::to_vec(&value)?, 1),
            Err(Error::Encoding(_))
        ));
    }
    Ok(())
}
