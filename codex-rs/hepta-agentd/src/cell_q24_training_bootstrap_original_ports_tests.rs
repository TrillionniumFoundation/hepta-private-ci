//! Same-process adapters to the actual deferred Trainer. The initial channels
//! are created before Material/T completion and never return canned evidence.
use super::super::connection;
pub(crate) use super::super::connection::fresh_peer as fresh_candidate_channel;
pub(crate) use super::super::connection::recovered_peer as recovered_candidate_channel;
use super::super::readonly;
use super::*;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use std::thread::JoinHandle;
use std::time::Duration;

pub(crate) fn command<
    TW: AnchorWitnessStore + Send + 'static,
    RW: AnchorWitnessStore + Send + 'static,
>(
    owner: Arc<OriginalCellQ24TrainingBootstrapOwnerV1<TW, RW>>,
    material: OriginalCellQ24MaterialReceiptConfigV1,
) -> anyhow::Result<(
    crate::OriginalCellQ24TrainingCommandConnectionV1,
    JoinHandle<Result<u64, Error>>,
)> {
    let (initial, mut channel) = connection::fresh_peer(material, Duration::from_secs(300))?;
    let thread = std::thread::spawn(move || owner.serve_command_channel(&mut channel));
    Ok((initial, thread))
}

pub(crate) fn readonly<
    TW: AnchorWitnessStore + Send + 'static,
    RW: AnchorWitnessStore + Send + 'static,
>(
    owner: Arc<OriginalCellQ24TrainingBootstrapOwnerV1<TW, RW>>,
    material: OriginalCellQ24MaterialReceiptConfigV1,
) -> anyhow::Result<(
    crate::OriginalCellQ24TrainingReadbackConnectionV1,
    JoinHandle<Result<u64, Error>>,
)> {
    let (initial, mut channel) =
        readonly::test_support::connection(material, Duration::from_secs(300))?;
    let thread =
        std::thread::spawn(move || owner.serve_original_training_readback_channel(&mut channel));
    Ok((initial, thread))
}

pub(crate) fn readonly_channel(
    material: OriginalCellQ24MaterialReceiptConfigV1,
) -> anyhow::Result<(
    crate::OriginalCellQ24TrainingReadbackConnectionV1,
    HostAuthorityPeerChannel,
)> {
    readonly::test_support::connection(material, Duration::from_secs(300))
}

/// A transport fault after the second actual original read. The original
/// Generator never re-signs: only this explicit test peer changes its reply.
pub(crate) fn renew_second_actual_read<
    TW: AnchorWitnessStore + Send + 'static,
    RW: AnchorWitnessStore + Send + 'static,
>(
    owner: Arc<OriginalCellQ24TrainingBootstrapOwnerV1<TW, RW>>,
    mut channel: HostAuthorityPeerChannel,
    expected: crate::OriginalCellQ24TrainingCommandReceiptV1,
) -> JoinHandle<anyhow::Result<u64>> {
    use super::super::wire;
    use crate::learning_iteration_evidence_client::wire as evidence_wire;
    use codex_hepta_contracts::HostIssuerTransportError;
    use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
    use ed25519_dalek::Signer;
    std::thread::spawn(move || {
        for request_id in 1..=128 {
            if !channel.exchange(|bytes| {
                let actual = owner
                    .original_training_readback_response(bytes, request_id)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                let mut response: wire::Response = serde_json::from_slice(&actual)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                if request_id == 2 {
                    let wire::CommandResult::Completed { snapshot, evidence } = response.result
                    else {
                        return Err(HostIssuerTransportError::InvalidRequest);
                    };
                    let mut changed = evidence
                        .decode()
                        .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                    if changed != *expected.attestation() {
                        return Err(HostIssuerTransportError::InvalidRequest);
                    }
                    changed.expires_at = changed
                        .expires_at
                        .checked_add(1)
                        .ok_or(HostIssuerTransportError::InvalidRequest)?;
                    changed.signature = SigningKey::from_bytes(&[41; 32])
                        .sign(&changed.signing_bytes())
                        .to_bytes();
                    let payload = learning_iteration_receipt_signing_bytes_v1(expected.receipt())
                        .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                    owner
                        .config
                        .material
                        .verifier
                        .verify(
                            LearningEvidenceRoleV1::Generator,
                            &changed,
                            &payload,
                            now().map_err(|_| HostIssuerTransportError::InvalidRequest)?,
                        )
                        .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                    response.result = wire::CommandResult::Completed {
                        snapshot,
                        evidence: evidence_wire::Evidence::from_original(&changed),
                    };
                }
                serde_json::to_vec(&response).map_err(|_| HostIssuerTransportError::InvalidRequest)
            })? {
                return Ok(request_id - 1);
            }
        }
        anyhow::bail!("bounded original Trainer renewal fault")
    })
}
