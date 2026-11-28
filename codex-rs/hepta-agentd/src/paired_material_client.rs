//! A single original Root connection, consumed by the private continuation.
//! Cancellation closes that exact stream, including an in-flight blocking call.
use super::*;
use base64::Engine as _;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use std::net::Shutdown;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Mutex;

use super::material_protocol::FRAME_BOUND;
use super::material_protocol::PairedTrainingReadResponse;

#[path = "paired_record_identity.rs"]
mod record_identity;
pub use record_identity::PairedOpaqueEvidenceV1;
pub use record_identity::PairedOpaqueFinalAnswerObservationV1;
pub use record_identity::PairedRecordIdentityV1;
pub use record_identity::PairedRecordMetadataV1;
pub use record_identity::PairedRecordPinsV1;
pub use record_identity::identify_original_paired_records_v1;
#[cfg(test)]
pub(crate) use record_identity::tests::fresh as record_fixture_materials;

/// Material bytes are returned only after both Root and the native recipient
/// validate their fixed commitment. They are not an adoption or FinalUse receipt.
pub struct PairedTrainingMaterials {
    failure: Vec<u8>,
    correction: Vec<u8>,
}

impl PairedTrainingMaterials {
    pub fn failure(&self) -> &[u8] {
        &self.failure
    }
    pub fn correction(&self) -> &[u8] {
        &self.correction
    }
}

/// Trusted startup input for this exact registered original owner. No path,
/// reconnect callback, key or serialized grant is accepted.
pub struct AgentdPairedMaterialClient {
    pub(super) registration: PairedPreparationRegistration,
    manifest: crate::PairedTrainingMaterialManifestV1,
    channel: Mutex<Option<HostAuthorityPeerChannel>>,
    shutdown: UnixStream,
}

struct ShutdownOriginal<'a>(&'a UnixStream);
impl Drop for ShutdownOriginal<'_> {
    fn drop(&mut self) {
        let _ = self.0.shutdown(Shutdown::Both);
    }
}

impl AgentdPairedMaterialClient {
    pub fn from_original_root(
        registration: PairedPreparationRegistration,
        manifest: crate::PairedTrainingMaterialManifestV1,
        stream: UnixStream,
        mut policy: HostAuthorityPeerPolicy,
        original_root_pidfd: OwnedFd,
    ) -> Result<Self, AgentdError> {
        if policy.peer.uid != 0
            || policy.timeout.is_zero()
            || policy.timeout > Duration::from_secs(1)
            || manifest.commitment().map_err(|e| invalid(&e.to_string()))?
                != registration.frozen_materials
        {
            return Err(invalid(
                "paired material client requires the original Root and frozen commitment",
            ));
        }
        policy.request_bound = FRAME_BOUND;
        policy.response_bound = FRAME_BOUND;
        let shutdown = stream.try_clone()?;
        let channel = HostAuthorityPeerChannel::from_stream(stream, policy, original_root_pidfd)
            .map_err(|_| invalid("original paired Root peer is unavailable"))?;
        Ok(Self {
            registration,
            manifest,
            channel: Mutex::new(Some(channel)),
            shutdown,
        })
    }

    pub(super) async fn read_original(
        &self,
        continuation: OriginalPairedContinuation<'_>,
    ) -> Result<PairedTrainingReadResult, AgentdError> {
        // Keep the same original receipt through the real journal readback.
        // Merely creating this future does not consume a Root read entry.
        let (request, delivery) = continuation.into_training_request().await?;
        let raw = request.encode()?;
        self.exchange_original(raw, delivery).await
    }

    // This private transport continuation is called only after the actual
    // journal result above. Wire bytes alone are never a Root authorization.
    async fn exchange_original(
        &self,
        raw: Vec<u8>,
        delivery: Digest32,
    ) -> Result<PairedTrainingReadResult, AgentdError> {
        let mut channel = self
            .channel
            .lock()
            .map_err(|_| invalid("original paired client fenced"))?
            .take()
            .ok_or_else(|| invalid("original paired channel already consumed"))?;
        let shutdown = ShutdownOriginal(&self.shutdown);
        // The synchronous request owns the one channel. If this future is
        // dropped, shutdown acts on that original socket and never reconnects.
        let response = tokio::task::spawn_blocking(move || channel.request(&raw))
            .await
            .map_err(|_| invalid("original paired material reply is unknown"))?
            .map_err(|_| invalid("original paired material reply is unknown"))?;
        drop(shutdown);
        self.decode_complete(&response, delivery)
    }

    fn decode_complete(
        &self,
        raw: &[u8],
        delivery: Digest32,
    ) -> Result<PairedTrainingReadResult, AgentdError> {
        if raw.is_empty() || raw.len() > FRAME_BOUND {
            return Err(invalid("paired material response exceeds its fixed bound"));
        }
        let value: PairedTrainingReadResponse = serde_json::from_slice(raw)?;
        match value {
            PairedTrainingReadResponse::RetainedReadOnly { original_delivery }
                if original_delivery == delivery.to_string() =>
            {
                Ok(PairedTrainingReadResult::RetainedReadOnly {
                    original_delivery: delivery,
                })
            }
            PairedTrainingReadResponse::FreshRead {
                original_delivery,
                materials_sha256,
                failure_base64,
                correction_base64,
            } => {
                let failure = base64::engine::general_purpose::STANDARD
                    .decode(failure_base64)
                    .map_err(|_| invalid("paired failure encoding is invalid"))?;
                let correction = base64::engine::general_purpose::STANDARD
                    .decode(correction_base64)
                    .map_err(|_| invalid("paired correction encoding is invalid"))?;
                if original_delivery != delivery.to_string()
                    || materials_sha256 != self.registration.frozen_materials.to_string()
                    || failure.len() as u64 != self.manifest.failure_bytes
                    || correction.len() as u64 != self.manifest.correction_bytes
                    || Digest32::of_bytes(&failure) != self.manifest.failure_sha256
                    || Digest32::of_bytes(&correction) != self.manifest.correction_sha256
                {
                    return Err(invalid(
                        "original paired material response differs from its fixed commitment",
                    ));
                }
                Ok(PairedTrainingReadResult::FreshRead(
                    PairedTrainingMaterials {
                        failure,
                        correction,
                    },
                ))
            }
            _ => Err(invalid(
                "retained paired material response changed original delivery",
            )),
        }
    }
}

pub enum PairedTrainingReadResult {
    FreshRead(PairedTrainingMaterials),
    RetainedReadOnly { original_delivery: Digest32 },
    Unknown { original_delivery: Digest32 },
}

#[cfg(test)]
#[path = "paired_material_client_tests.rs"]
mod tests;
