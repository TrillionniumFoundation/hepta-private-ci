//! Read existing attestations from an original, separately held evidence owner.
//! This client cannot sign, train, adopt, or reconstruct an owner's history.
//! A different UID is a custody boundary, not proof of scientific independence.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Mutex;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdRootAuthorityPeer;
use crate::LearningIterationRuntimeErrorV1 as Error;
use crate::root_observation_stream::RootObservationStream;

#[path = "learning_iteration_evidence_wire.rs"]
mod wire;

#[path = "cell_q24_no_update_stage_owners.rs"]
mod ordinary_stage_owners;
pub use ordinary_stage_owners::OriginalCellQ24CandidateStageOwnersV1;
pub use ordinary_stage_owners::OriginalCellQ24CandidateStageStreamsV1;
pub use ordinary_stage_owners::OriginalCellQ24NoUpdatePeerStreamV1;
pub use ordinary_stage_owners::OriginalCellQ24NoUpdateStageOwnersV1;
pub use ordinary_stage_owners::OriginalCellQ24NoUpdateStageStreamsV1;
pub use ordinary_stage_owners::OriginalCellQ24NoUpdateTaskStreamV1;

#[path = "cell_q24_training_command.rs"]
mod training_command;
pub use training_command::OriginalCellQ24CandidateReadbackClientV1;
pub use training_command::OriginalCellQ24CandidateReadbackErrorV1;
pub use training_command::OriginalCellQ24ModelCommandClientV1;
pub use training_command::OriginalCellQ24ModelCommandConnectionV1;
pub use training_command::OriginalCellQ24ModelCommandErrorV1;
pub use training_command::OriginalCellQ24ModelCommandHostV1;
pub use training_command::OriginalCellQ24ModelCommandReceiptV1;
pub use training_command::OriginalCellQ24TrainingBootstrapConfigV1;
pub use training_command::OriginalCellQ24TrainingBootstrapCustodyV1;
pub use training_command::OriginalCellQ24TrainingBootstrapErrorV1;
pub use training_command::OriginalCellQ24TrainingBootstrapOwnerV1;
pub use training_command::OriginalCellQ24TrainingCommandClientV1;
pub use training_command::OriginalCellQ24TrainingCommandConnectionErrorV1;
pub use training_command::OriginalCellQ24TrainingCommandConnectionV1;
pub use training_command::OriginalCellQ24TrainingCommandContextV1;
pub use training_command::OriginalCellQ24TrainingCommandErrorV1;
pub use training_command::OriginalCellQ24TrainingCommandOwnerV1;
pub use training_command::OriginalCellQ24TrainingCommandReceiptV1;

#[path = "circuit_selection_command.rs"]
mod selection_command;
pub use selection_command::OriginalCircuitSelectionCommandClientV1;
pub use selection_command::OriginalCircuitSelectionCommandContextV1;
pub use selection_command::OriginalCircuitSelectionCommandErrorV1;
pub use selection_command::OriginalCircuitSelectionCommandOwnerV1;
pub use selection_command::OriginalCircuitSelectionCommandReceiptV1;

#[path = "circuit_next_use_command.rs"]
mod next_use_command;
pub use next_use_command::OriginalCircuitNextUseCommandClientV1;
pub use next_use_command::OriginalCircuitNextUseCommandContextV1;
pub use next_use_command::OriginalCircuitNextUseCommandErrorV1;
pub use next_use_command::OriginalCircuitNextUseCommandOwnerV1;
pub use next_use_command::OriginalCircuitNextUseCommandReceiptV1;

#[path = "cell_q24_material_evidence_service.rs"]
mod material;
pub use material::OriginalCellQ24DatasetCommandReadbackV1;
pub use material::OriginalCellQ24MaterialCommandClientV1;
pub use material::OriginalCellQ24MaterialCommandErrorV1;
pub use material::OriginalCellQ24MaterialCommandOwnerV1;
pub use material::OriginalCellQ24MaterialCommandReceiptV1;
pub use material::OriginalCellQ24MaterialEvidenceErrorV1;
pub use material::OriginalCellQ24MaterialEvidenceOwnerV1;
pub use material::OriginalCellQ24MaterialEvidenceRoleV1;
pub use material::OriginalCellQ24MaterialSourceConnectionV1;
pub use material::OriginalCellQ24MaterialSourceErrorV1;
pub use material::OriginalCellQ24RemoteMaterialClientV1;

#[path = "learning_iteration_evaluation_evidence.rs"]
mod evaluation;
pub use evaluation::AuthenticatedCellLearningEvaluationV1;
pub use evaluation::CellLearningEvaluationReadbackErrorV1;
pub use evaluation::CellLearningEvaluationReadbackRequestV1;
pub use evaluation::read_cell_learning_evaluation_v1;

/// Selected by the original host, before transfer of the connected stream and
/// pidfd. Neither a reply nor a model-selected pathname can select this owner.
pub struct LearningIterationEvidencePeerV1 {
    pub pid: u32,
    pub uid: u32,
    pub boot_id: String,
    pub process_start_ticks: u64,
    pub actor_id: StableId,
}

struct Channel {
    transport: RootObservationStream,
    next_request_id: u64,
}

/// One read-only, purpose-bound connection. The external owner must resolve
/// the exact committed result and its current withdrawal/revocation state.
/// A signed reply authenticates its assertion, not the underlying experiment.
/// Trust/controller separation is still checked by the iteration worker.
pub struct LearningIterationEvidenceClientV1 {
    channel: Mutex<Option<Channel>>,
    initial: LearningIterationSnapshotV1,
    actor_id: StableId,
    verifier: LearningEvidenceVerifierV1,
}

impl LearningIterationEvidenceClientV1 {
    /// Consume original capabilities; never connect, open a key or create an
    /// evidence store. Same-UID or same-process ownership is refused. The
    /// inherited transport bounds remain 500 ms per read and 300 s per session.
    pub fn from_owner_stream(
        stream: UnixStream,
        peer: LearningIterationEvidencePeerV1,
        owner_pidfd: OwnedFd,
        initial: LearningIterationSnapshotV1,
        verifier: LearningEvidenceVerifierV1,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Self, Error> {
        let expected =
            LearningIterationCoordinatorV1::new(initial.request.clone(), initial.owners.clone())?;
        // SAFETY: these calls only observe this process's credentials.
        let same_uid =
            peer.uid == unsafe { libc::getuid() } || peer.uid == unsafe { libc::geteuid() };
        if same_uid
            || peer.pid == std::process::id()
            || expected.snapshot() != &initial
            || initial.owners.evidence_trust_digest != verifier.trust_digest()
            || initial.request.envelope.objective_digest != verifier.objective_digest()
            || ![
                &initial.owners.experience,
                &initial.owners.dataset,
                &initial.owners.trainer,
                &initial.owners.evaluator,
                &initial.owners.selector,
                &initial.owners.next_use_observer,
            ]
            .contains(&&peer.actor_id)
        {
            return Err(Error::WrongScope);
        }
        let transport = RootObservationStream::from_stream_for_uid(
            stream,
            AgentdRootAuthorityPeer {
                pid: peer.pid,
                boot_id: peer.boot_id,
                process_start_ticks: peer.process_start_ticks,
            },
            owner_pidfd,
            timeout,
            lifetime,
            peer.uid,
        )
        .map_err(|_| unavailable())?;
        Ok(Self {
            channel: Mutex::new(Some(Channel {
                transport,
                next_request_id: 1,
            })),
            initial,
            actor_id: peer.actor_id,
            verifier,
        })
    }

    /// Look up already issued evidence by exact receipt digest. No arbitrary
    /// signing payload is sent. Recovered receipts may be read after the work
    /// deadline, but the returned signature must be valid at the current clock.
    /// Cancellation, malformed replies and failed authentication permanently
    /// consume this connection; only the original host can supply a new one.
    pub async fn readback(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        receipt: &LearningIterationReceiptV1,
    ) -> Result<SignedLearningEvidenceV1, Error> {
        let stage = receipt.observation.stage();
        let role = evidence_role(stage)?;
        if snapshot.request != self.initial.request
            || snapshot.owners != self.initial.owners
            || receipt.actor_id != self.actor_id
            || &receipt.actor_id != snapshot.owners.owner(stage)
        {
            return Err(Error::WrongScope);
        }
        let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
        if !snapshot.receipts.contains(receipt) {
            coordinator.record(receipt.clone(), receipt.observed_unix_seconds)?;
        }
        let payload = learning_iteration_receipt_signing_bytes_v1(receipt)?;
        let mut channel = self
            .channel
            .try_lock()
            .map_err(|_| unavailable())?
            .take()
            .ok_or_else(unavailable)?;
        let request_id = channel.next_request_id;
        channel.next_request_id = request_id.checked_add(1).ok_or_else(unavailable)?;
        let request = wire::Request {
            schema: 1,
            operation: wire::OPERATION.into(),
            request_id,
            binding: self.initial.head_digest.to_string(),
            snapshot_head: snapshot.head_digest.to_string(),
            operation_id: receipt.operation_id.to_string(),
            actor_id: self.actor_id.to_string(),
            predecessor: receipt.predecessor.to_string(),
            receipt_digest: Digest32::of_bytes(&payload).to_string(),
        };
        let response: wire::Response = channel
            .transport
            .read(&request)
            .await
            .map_err(|_| unavailable())?;
        if response.schema != 1
            || response.operation != request.operation
            || response.request_id != request_id
            || response.binding != request.binding
            || response.snapshot_head != request.snapshot_head
            || response.receipt_digest != request.receipt_digest
        {
            return Err(unavailable());
        }
        let signature = response.evidence.decode()?;
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| unavailable())?
            .as_secs();
        let verified = self
            .verifier
            .verify(role, &signature, &payload, now)
            .map_err(Error::Evidence)?;
        if verified.principal().principal_id != self.actor_id || receipt.observed_unix_seconds > now
        {
            return Err(Error::Evidence(SignedEvidenceError::ContextMismatch));
        }
        crate::root_observation_stream::check_lifetime(channel.transport.root_lifetime().get_ref())
            .map_err(|_| unavailable())?;
        *self.channel.try_lock().map_err(|_| unavailable())? = Some(channel);
        Ok(signature)
    }
}

fn evidence_role(stage: LearningIterationStageV1) -> Result<LearningEvidenceRoleV1, Error> {
    Ok(match stage {
        LearningIterationStageV1::Training => LearningEvidenceRoleV1::Generator,
        LearningIterationStageV1::Evaluation => LearningEvidenceRoleV1::Evaluator,
        LearningIterationStageV1::Selection => LearningEvidenceRoleV1::Selector,
        LearningIterationStageV1::Experience
        | LearningIterationStageV1::Dataset
        | LearningIterationStageV1::NextUse => LearningEvidenceRoleV1::Observer,
        LearningIterationStageV1::Proposal => {
            return Err(Error::Evidence(SignedEvidenceError::RoleMismatch));
        }
    })
}

fn unavailable() -> Error {
    Error::OwnerUnavailable("original learning evidence owner")
}

#[cfg(test)]
#[path = "learning_iteration_evidence_tests.rs"]
mod tests;

#[cfg(test)]
pub(crate) use tests::fixture_original_receipt_client;

#[cfg(test)]
pub(crate) use tests::fixture_original_receipt_client_until_close;
#[cfg(test)]
pub(crate) use training_command::command_test_support;

#[cfg(test)]
pub(crate) use selection_command::command_test_support as selection_command_test_support;

#[cfg(test)]
pub(crate) use next_use_command::command_test_support as next_use_command_test_support;

#[cfg(test)]
pub(crate) use ordinary_stage_owners::fresh_material_only;
#[cfg(test)]
pub(crate) use ordinary_stage_owners::recovered_material_only;

#[cfg(test)]
pub(crate) use ordinary_stage_owners::fixture_from_original_clients;
#[cfg(test)]
pub(crate) use ordinary_stage_owners::recovered_candidate_clients;
