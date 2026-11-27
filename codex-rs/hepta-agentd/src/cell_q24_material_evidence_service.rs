//! Read-only production of original Experience/Dataset evidence.
//! The original Material role host keeps its keys and typed source capabilities.
//! This module consumes a pre-connected channel; it never enrolls, signs, trains,
//! opens a pathname, or accepts a caller-provided snapshot or observation.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;

use super::wire;
use crate::AgentdIdentity;
use crate::CircuitTaskSourceReadbackV1;
use crate::LoadedCellQ24ModelV1;
use crate::OriginalCellQ24MaterialCompletionV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCellQ24MaterialReceiptErrorV1;
use crate::OriginalCellQ24MaterialReceiptOwnersV1;
use crate::OriginalCellQ24MaterialReceiptSourcesV1;

#[path = "cell_q24_material_command.rs"]
mod command;
pub use command::OriginalCellQ24DatasetCommandReadbackV1;
pub use command::OriginalCellQ24MaterialCommandClientV1;
pub use command::OriginalCellQ24MaterialCommandErrorV1;
pub use command::OriginalCellQ24MaterialCommandOwnerV1;
pub use command::OriginalCellQ24MaterialCommandReceiptV1;

#[path = "cell_q24_material_source.rs"]
mod source;
pub use source::OriginalCellQ24MaterialSourceConnectionV1;
pub use source::OriginalCellQ24MaterialSourceErrorV1;
pub use source::OriginalCellQ24RemoteMaterialClientV1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellQ24MaterialEvidenceErrorV1 {
    #[error("original material readback request differs from its fixed scope")]
    Request,
    #[error("original material readback owner or ledger is unavailable")]
    Unavailable,
    #[error("original material readback transport: {0}")]
    Transport(#[from] HostIssuerTransportError),
    #[error("original material readback owner: {0}")]
    Material(#[from] OriginalCellQ24MaterialReceiptErrorV1),
    #[error("original material readback iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original material readback evidence: {0}")]
    Evidence(#[from] SignedEvidenceError),
    #[error("original material readback encoding: {0}")]
    Encoding(#[from] serde_json::Error),
}

type Error = OriginalCellQ24MaterialEvidenceErrorV1;

/// Chosen by the original host before accepting a request on this connection.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OriginalCellQ24MaterialEvidenceRoleV1 {
    Experience,
    Dataset,
}

impl OriginalCellQ24MaterialEvidenceRoleV1 {
    fn stage(self) -> LearningIterationStageV1 {
        match self {
            Self::Experience => LearningIterationStageV1::Experience,
            Self::Dataset => LearningIterationStageV1::Dataset,
        }
    }
}

/// One original pair and one original Ledger, shared only in its role host.
/// A cloned Arc preserves the same writer; no second writer is opened. Every
/// request tries owner then Ledger locks, releases both before any socket write,
/// and reads both original Material completions to derive the Dataset cut.
pub struct OriginalCellQ24MaterialEvidenceOwnerV1<
    EW: AnchorWitnessStore,
    DW: AnchorWitnessStore,
    SW: AnchorWitnessStore,
> {
    owners: Mutex<OriginalCellQ24MaterialReceiptOwnersV1<EW, DW>>,
    config: OriginalCellQ24MaterialReceiptConfigV1,
    source: CircuitTaskSourceReadbackV1<SW>,
    identity: AgentdIdentity,
    ledger: Arc<Mutex<LedgerWriter>>,
    baseline: Arc<LoadedCellQ24ModelV1>,
}

impl<EW: AnchorWitnessStore, DW: AnchorWitnessStore, SW: AnchorWitnessStore>
    OriginalCellQ24MaterialEvidenceOwnerV1<EW, DW, SW>
{
    /// Only the consuming original-pair method supplies this private context.
    pub(crate) fn from_original_owners(
        owners: OriginalCellQ24MaterialReceiptOwnersV1<EW, DW>,
        config: OriginalCellQ24MaterialReceiptConfigV1,
        source: CircuitTaskSourceReadbackV1<SW>,
        identity: AgentdIdentity,
        ledger: Arc<Mutex<LedgerWriter>>,
        baseline: Arc<LoadedCellQ24ModelV1>,
    ) -> Result<Self, Error> {
        let initial = LearningIterationCoordinatorV1::new(
            config.initial.request.clone(),
            config.initial.owners.clone(),
        )?;
        if initial.snapshot() != &config.initial {
            return Err(Error::Request);
        }
        config.scope.validate_snapshot(&config.initial)?;
        Ok(Self {
            owners: Mutex::new(owners),
            config,
            source,
            identity,
            ledger,
            baseline,
        })
    }

    /// Serve the existing READBACK purpose, with host-selected role and peer.
    /// The original host transfers the connected socket and already-held pidfd.
    /// A new connection cannot change the pair, source, Ledger, role or scope.
    /// Any uncertainty consumes this channel; this API never reconnects.
    pub fn serve_readback(
        &self,
        role: OriginalCellQ24MaterialEvidenceRoleV1,
        stream: UnixStream,
        mut policy: HostAuthorityPeerPolicy,
        original_consumer_pidfd: OwnedFd,
    ) -> Result<(), Error> {
        // SAFETY: observe only this process's current credentials.
        let same_uid = policy.peer.uid == unsafe { libc::getuid() }
            || policy.peer.uid == unsafe { libc::geteuid() };
        if same_uid
            || policy.peer.pid == std::process::id()
            || policy.timeout.is_zero()
            || policy.timeout > Duration::from_millis(500)
            || policy.lifetime.is_zero()
            || policy.lifetime > Duration::from_secs(300)
        {
            return Err(Error::Request);
        }
        policy.request_bound = 16 * 1024;
        policy.response_bound = 16 * 1024;
        let mut channel =
            HostAuthorityPeerChannel::from_stream(stream, policy, original_consumer_pidfd)?;
        let mut next_request_id = 1_u64;
        loop {
            let mut failure = None;
            let exchanged = channel.exchange(|bytes| {
                self.respond(role, &mut next_request_id, bytes)
                    .map_err(|error| {
                        failure = Some(error);
                        HostIssuerTransportError::Unavailable
                    })
            });
            match exchanged {
                Ok(true) => {}
                Ok(false) => return Ok(()),
                Err(error) => {
                    return Err(match failure {
                        Some(failure) => failure,
                        None => Error::Transport(error),
                    });
                }
            }
        }
    }

    fn respond(
        &self,
        role: OriginalCellQ24MaterialEvidenceRoleV1,
        next_request_id: &mut u64,
        bytes: &[u8],
    ) -> Result<Vec<u8>, Error> {
        let started_at = now()?;
        let request: wire::Request = serde_json::from_slice(bytes)?;
        let initial = &self.config.initial;
        if request.schema != 1
            || request.operation != wire::OPERATION
            || request.request_id != *next_request_id
            || request.binding != initial.head_digest.to_string()
            || request.operation_id != initial.request.operation_id.as_str()
            || request.actor_id != initial.owners.owner(role.stage()).as_str()
        {
            return Err(Error::Request);
        }
        let next = (*next_request_id).checked_add(1).ok_or(Error::Request)?;
        let snapshot_head: Digest32 = request.snapshot_head.parse().map_err(|_| Error::Request)?;
        if snapshot_head.to_string() != request.snapshot_head {
            return Err(Error::Request);
        }
        let completion = self.read_original(role, snapshot_head)?;
        let payload = learning_iteration_receipt_signing_bytes_v1(&completion.receipt)?;
        if completion.receipt.observation.stage() != role.stage()
            || request.predecessor != completion.receipt.predecessor.to_string()
            || request.receipt_digest != Digest32::of_bytes(&payload).to_string()
        {
            return Err(Error::Request);
        }
        let fresh_now = now()?;
        if fresh_now < started_at
            || fresh_now < self.config.freeze_evidence.issued_at
            || fresh_now >= self.config.freeze_evidence.expires_at
        {
            return Err(Error::Request);
        }
        let signed = &completion.attestation;
        let verified = self.config.verifier.verify(
            LearningEvidenceRoleV1::Observer,
            signed,
            &payload,
            fresh_now,
        )?;
        let signer = match role {
            OriginalCellQ24MaterialEvidenceRoleV1::Experience => &self.config.experience_signer,
            OriginalCellQ24MaterialEvidenceRoleV1::Dataset => &self.config.dataset_signer,
        };
        if verified.principal() != &signer.principal
            || verified.controller_id() != &signer.controller_id
            || signed.principal_id != completion.receipt.actor_id
            || signed.issued_at != completion.receipt.observed_unix_seconds
        {
            return Err(Error::Request);
        }
        let response = wire::Response {
            schema: request.schema,
            operation: request.operation,
            request_id: request.request_id,
            binding: request.binding,
            snapshot_head: request.snapshot_head,
            receipt_digest: request.receipt_digest,
            evidence: wire::Evidence::from_original(signed),
        };
        let encoded = serde_json::to_vec(&response)?;
        if encoded.is_empty() || encoded.len() > 16 * 1024 {
            return Err(Error::Request);
        }
        *next_request_id = next;
        Ok(encoded)
    }

    fn read_original(
        &self,
        role: OriginalCellQ24MaterialEvidenceRoleV1,
        requested_head: Digest32,
    ) -> Result<OriginalCellQ24MaterialCompletionV1, Error> {
        let mut owners = self.owners.try_lock().map_err(|_| Error::Unavailable)?;
        let mut ledger = self.ledger.try_lock().map_err(|_| Error::Unavailable)?;
        let original: &mut OriginalCellQ24MaterialReceiptOwnersV1<EW, DW> = &mut owners;
        let experience = original.readback_experience(OriginalCellQ24MaterialReceiptSourcesV1 {
            snapshot: &self.config.initial,
            source: &self.source,
            identity: &self.identity,
            ledger: &mut ledger,
            baseline: &self.baseline,
        })?;
        let mut coordinator =
            LearningIterationCoordinatorV1::from_snapshot(self.config.initial.clone())?;
        coordinator.record(
            experience.receipt.clone(),
            experience.receipt.observed_unix_seconds,
        )?;
        let experience_prefix = coordinator.snapshot().clone();
        let dataset = original.readback_dataset(OriginalCellQ24MaterialReceiptSourcesV1 {
            snapshot: &experience_prefix,
            source: &self.source,
            identity: &self.identity,
            ledger: &mut ledger,
            baseline: &self.baseline,
        })?;
        coordinator.record(
            dataset.receipt.clone(),
            dataset.receipt.observed_unix_seconds,
        )?;
        let dataset_prefix = coordinator.snapshot().clone();
        let valid_head = requested_head == dataset_prefix.head_digest
            || requested_head == experience_prefix.head_digest
            || (role == OriginalCellQ24MaterialEvidenceRoleV1::Experience
                && requested_head == self.config.initial.head_digest);
        if !valid_head {
            return Err(Error::Request);
        }
        let completion = match role {
            OriginalCellQ24MaterialEvidenceRoleV1::Dataset => dataset,
            OriginalCellQ24MaterialEvidenceRoleV1::Experience => {
                let current =
                    original.readback_experience(OriginalCellQ24MaterialReceiptSourcesV1 {
                        snapshot: &dataset_prefix,
                        source: &self.source,
                        identity: &self.identity,
                        ledger: &mut ledger,
                        baseline: &self.baseline,
                    })?;
                if current.receipt != experience.receipt
                    || current.attestation != experience.attestation
                {
                    return Err(Error::Request);
                }
                current
            }
        };
        drop(ledger);
        drop(owners);
        Ok(completion)
    }
}

fn now() -> Result<u64, Error> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|elapsed| elapsed.as_secs())
        .map_err(|_| Error::Unavailable)
}

#[cfg(test)]
#[path = "cell_q24_material_evidence_service_tests.rs"]
mod tests;

#[cfg(test)]
pub(crate) use command::bootstrap_ports;
#[cfg(test)]
pub(crate) use command::retained_version_dataset_fixture;
