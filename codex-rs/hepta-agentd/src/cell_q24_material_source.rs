//! Keyless access to one original Material host through its fixed purpose.
//! The client receives no signing key, Ledger writer, Source pathname or
//! callback. Its only output is material reconstructed by the closed verifier.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::DatasetReceiptError;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_types::Digest32;

use super::super::wire as evidence_wire;
use super::OriginalCellQ24MaterialEvidenceErrorV1;
use crate::AgentdRootAuthorityPeer;
use crate::CellQ24DatasetErrorV1;
use crate::CellQ24TrainingErrorV1;
use crate::LearningIterationEvidencePeerV1;
use crate::LearningIterationRuntimeErrorV1;
use crate::LoadedCellQ24ModelV1;
use crate::OriginalCellQ24DatasetV1;
use crate::OriginalCellQ24TrainingSourceConfigV1;
use crate::root_observation_stream::RootObservationStream;

#[path = "cell_q24_material_source_connection.rs"]
mod connection;
pub use connection::OriginalCellQ24MaterialSourceConnectionV1;

#[path = "cell_q24_material_source_service.rs"]
mod serving;
#[path = "cell_q24_material_source_wire.rs"]
mod wire;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellQ24MaterialSourceErrorV1 {
    #[error("original Material source binding: {0}")]
    Binding(&'static str),
    #[error("original Material source channel is unavailable")]
    Unavailable,
    #[error("original Material owner: {0}")]
    Owner(#[from] OriginalCellQ24MaterialEvidenceErrorV1),
    #[error("original Material peer framing: {0}")]
    Transport(#[from] HostIssuerTransportError),
    #[error("original evidence decoding: {0}")]
    Connection(#[from] LearningIterationRuntimeErrorV1),
    #[error("original Material Dataset: {0}")]
    Dataset(#[from] CellQ24DatasetErrorV1),
    #[error("original Material iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original Material signature: {0}")]
    Evidence(#[from] SignedEvidenceError),
    #[error("original Material receipt: {0}")]
    Receipt(#[from] DatasetReceiptError),
    #[error("original Q24 batch: {0}")]
    Batch(#[from] CellQ24TrainingErrorV1),
    #[error("original Material wire: {0}")]
    Encoding(#[from] serde_json::Error),
}

type Error = OriginalCellQ24MaterialSourceErrorV1;

struct Channel {
    transport: RootObservationStream,
    next_request_id: u64,
}

/// An opaque live connection. Only the original launcher supplies its connected
/// stream, peer identity, held pidfd, original config and loaded baseline.
/// Retaining this object or a returned material value is not a CURRENT lease.
pub struct OriginalCellQ24RemoteMaterialClientV1 {
    channel: Mutex<Option<Channel>>,
    config: OriginalCellQ24TrainingSourceConfigV1,
    baseline: Arc<LoadedCellQ24ModelV1>,
}

impl OriginalCellQ24RemoteMaterialClientV1 {
    pub fn from_original_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        original_owner_pidfd: OwnedFd,
        config: OriginalCellQ24TrainingSourceConfigV1,
        baseline: Arc<LoadedCellQ24ModelV1>,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        let started_at = now()?;
        verify_context(&config, started_at)?;
        // SAFETY: observe only this process's original credentials.
        let same_uid =
            peer.uid == unsafe { libc::getuid() } || peer.uid == unsafe { libc::geteuid() };
        if same_uid
            || peer.pid == std::process::id()
            || peer.actor_id != config.dataset.owners.dataset
            || baseline.components() != &config.dataset.request.selected_bundle.components
        {
            return Err(Error::Binding(
                "original distinct Material host and loaded baseline",
            ));
        }
        let transport = RootObservationStream::from_stream_for_uid(
            stream,
            AgentdRootAuthorityPeer {
                pid: peer.pid,
                boot_id: peer.boot_id,
                process_start_ticks: peer.process_start_ticks,
            },
            original_owner_pidfd,
            timeout,
            lifetime,
            peer.uid,
        )
        .map_err(|_| Error::Unavailable)?;
        let fresh_now = now()?;
        if fresh_now < started_at {
            return Err(Error::Binding("Material channel clock moved backwards"));
        }
        verify_context(&config, fresh_now)?;
        Ok(Self {
            channel: Mutex::new(Some(Channel {
                transport,
                next_request_id: 1,
            })),
            config,
            baseline,
        })
    }

    /// Make a fresh read through the same original host. No request carries a
    /// batch, label, snapshot, receipt, observation or signing payload. Every
    /// failure after taking the channel consumes it; there is no reconnect.
    pub async fn read_current(&self) -> Result<OriginalCellQ24DatasetV1, Error> {
        let started_at = now()?;
        let mut channel = self
            .channel
            .try_lock()
            .map_err(|_| Error::Unavailable)?
            .take()
            .ok_or(Error::Unavailable)?;
        verify_context(&self.config, started_at)?;
        let initial = LearningIterationCoordinatorV1::new(
            self.config.dataset.request.clone(),
            self.config.dataset.owners.clone(),
        )?;
        let request_id = channel.next_request_id;
        let next_request_id = request_id
            .checked_add(1)
            .ok_or(Error::Binding("Material request id overflow"))?;
        let request = wire::Request {
            schema: 1,
            operation: wire::OPERATION.into(),
            request_id,
            binding: initial.snapshot().head_digest.to_string(),
            scope: self.config.scope.binding().to_string(),
            operation_id: self.config.dataset.request.operation_id.to_string(),
            dataset_head: self.config.dataset.head_digest.to_string(),
            experience_receipt: receipt_digest(&self.config, 0)?.to_string(),
            dataset_receipt: receipt_digest(&self.config, 1)?.to_string(),
        };
        let response: wire::Response = channel
            .transport
            .read(&request)
            .await
            .map_err(|_| Error::Unavailable)?;
        if response.schema != request.schema
            || response.operation != request.operation
            || response.request_id != request_id
            || response.binding != request.binding
            || response.scope != request.scope
            || response.operation_id != request.operation_id
            || response.dataset_head != request.dataset_head
            || response.experience_receipt != request.experience_receipt
            || response.dataset_receipt != request.dataset_receipt
        {
            return Err(Error::Binding("same original Material response"));
        }
        let experience = response.experience.decode()?;
        let dataset = response.dataset.decode()?;
        if experience != self.config.experience_evidence || dataset != self.config.dataset_evidence
        {
            return Err(Error::Binding("complete original Material signature bytes"));
        }
        let material = OriginalCellQ24DatasetV1::from_original_material_peer(
            response.material,
            &self.config,
            Arc::clone(&self.baseline),
            &experience,
            &dataset,
        )?;
        let fresh_now = now()?;
        if fresh_now < started_at {
            return Err(Error::Binding("Material read clock moved backwards"));
        }
        verify_context(&self.config, fresh_now)?;
        crate::root_observation_stream::check_lifetime(channel.transport.root_lifetime().get_ref())
            .map_err(|_| Error::Unavailable)?;
        channel.next_request_id = next_request_id;
        *self.channel.try_lock().map_err(|_| Error::Unavailable)? = Some(channel);
        Ok(material)
    }

    /// The closed SourceCapture adapter checks every retained input before it
    /// admits this live client. This exposes no owner, writer or mutable config.
    pub(crate) fn require_source_binding(
        &self,
        config: &OriginalCellQ24TrainingSourceConfigV1,
        baseline: &Arc<LoadedCellQ24ModelV1>,
    ) -> Result<(), Error> {
        if self.config.dataset != config.dataset
            || self.config.scope != config.scope
            || self.config.rule != config.rule
            || self.config.optimizer != config.optimizer
            || self.config.freeze_plan != config.freeze_plan
            || self.config.freeze_evidence != config.freeze_evidence
            || self.config.experience_evidence != config.experience_evidence
            || self.config.dataset_evidence != config.dataset_evidence
            || self.config.verifier.trust_digest() != config.verifier.trust_digest()
            || self.config.verifier.scope_digest() != config.verifier.scope_digest()
            || self.config.verifier.objective_digest() != config.verifier.objective_digest()
            || !Arc::ptr_eq(&self.baseline, baseline)
        {
            return Err(Error::Binding(
                "same original Material source capture context",
            ));
        }
        verify_context(config, now()?)?;
        Ok(())
    }
}

fn verify_context(config: &OriginalCellQ24TrainingSourceConfigV1, at: u64) -> Result<(), Error> {
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(config.dataset.clone())?;
    config.scope.validate_snapshot(&config.dataset)?;
    if coordinator.next_stage() != Some(LearningIterationStageV1::Training)
        || config.dataset.receipts.len() != 2
        || config.dataset.owners.evidence_trust_digest != config.verifier.trust_digest()
        || config.dataset.request.envelope.objective_digest != config.verifier.objective_digest()
        || at < config.freeze_evidence.issued_at
        || at >= config.freeze_evidence.expires_at
    {
        return Err(Error::Binding("original signed Dataset cut"));
    }
    for (receipt, evidence) in config
        .dataset
        .receipts
        .iter()
        .zip([&config.experience_evidence, &config.dataset_evidence])
    {
        let payload = learning_iteration_receipt_signing_bytes_v1(receipt)?;
        let verified =
            config
                .verifier
                .verify(LearningEvidenceRoleV1::Observer, evidence, &payload, at)?;
        if verified.principal().principal_id != receipt.actor_id
            || evidence.issued_at != receipt.observed_unix_seconds
            || evidence.issued_at > at
        {
            return Err(Error::Binding("original Material actors and windows"));
        }
    }
    Ok(())
}

fn receipt_digest(
    config: &OriginalCellQ24TrainingSourceConfigV1,
    index: usize,
) -> Result<Digest32, Error> {
    let receipt = config
        .dataset
        .receipts
        .get(index)
        .ok_or(Error::Binding("complete original Material cut"))?;
    Ok(Digest32::of_bytes(
        &learning_iteration_receipt_signing_bytes_v1(receipt)?,
    ))
}

fn now() -> Result<u64, Error> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_secs())
        .map_err(|_| Error::Binding("Material clock before Unix epoch"))
}

#[cfg(test)]
#[path = "cell_q24_material_source_tests.rs"]
mod tests;
