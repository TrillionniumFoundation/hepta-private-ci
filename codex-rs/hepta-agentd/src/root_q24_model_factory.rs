//! Ordinary Model admission through an original Root reservation and original
//! material owner. Public pins never construct a factory or supply provenance.

use std::fs::File;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use crate::AgentdError;
use crate::CellQ24ModelProposalInputsV1;
use crate::CellQ24ModelProposalOwnerV1;
use crate::CellQ24ModelProposalReceiptV1;
use crate::CellQ24TrainingOwnerV1;
use crate::HostAuthorityQ24ModelFactoryProfileV1;
use crate::authority_host_service::q24_model::Command;
use crate::authority_host_service::q24_model::FactoryLease;
use crate::authority_host_service::q24_model::PURPOSE;
use crate::authority_host_service::q24_model::Reply;
use crate::authority_host_service::q24_model::Request;
use crate::authority_host_service::q24_model::Response;
use crate::authority_host_service::q24_model::WITNESS_RECORDS;
use crate::root_observation_stream::RootObservationStream;

/// Non-cloneable original factory. Retains sole writable file rights, the
/// original Root connection/pidfd and its full immutable learning scope.
/// It grants only the existing DENY_ALL Model proposal owner operation.
pub struct AgentdRootQ24ModelFactoryV1 {
    transport: Option<RootObservationStream>,
    next_request_id: u64,
    profile: HostAuthorityQ24ModelFactoryProfileV1,
    initial: LearningIterationSnapshotV1,
    scope: FrozenLearningScopeV2,
    generation: Generation,
    files: Option<(File, File)>,
    owner: Option<CellQ24ModelProposalOwnerV1<FileAnchorWitnessStore>>,
    fenced: bool,
}

#[derive(Clone, Copy)]
enum Operation {
    CommitOrReadback,
    Readback,
}

impl AgentdRootQ24ModelFactoryV1 {
    pub(crate) async fn require_current(&mut self) -> Result<(), AgentdError> {
        if self.fenced {
            return Err(refused(
                "factory acknowledgement uncertain; original reopen required",
            ));
        }
        self.fenced = true;
        let before = self.exchange(Command::Observe).await?;
        let after = self
            .exchange(Command::Confirm {
                expected: before.lease.clone(),
            })
            .await?;
        if after.lease != before.lease || after.newly_bound {
            return Err(refused(
                "factory live enrollment changed during observation",
            ));
        }
        self.fenced = false;
        Ok(())
    }

    pub(crate) async fn from_original_handoff(
        transport: RootObservationStream,
        profile: HostAuthorityQ24ModelFactoryProfileV1,
        initial: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
        spawn_generation: u64,
        journal: File,
        witness: File,
    ) -> Result<Self, AgentdError> {
        profile.require_files(&journal, &witness)?;
        let mut factory = Self {
            transport: Some(transport),
            next_request_id: 1,
            profile,
            initial,
            scope,
            generation: Generation::new(spawn_generation).map_err(refused)?,
            files: Some((journal, witness)),
            owner: None,
            fenced: false,
        };
        // A sealed descriptor alone is insufficient: observe the registered
        // namespace through its live original writer before returning a factory.
        factory.exchange(Command::Observe).await?;
        Ok(factory)
    }

    pub(crate) fn require_successor_session(
        &self,
        original: &crate::root_production_inputs::OriginalQ24SuccessorSession,
    ) -> Result<(), AgentdError> {
        original.require_current_successor_session()?;
        self.profile
            .require_context(
                original.identity(),
                &original.writer_proof()?,
                &self.initial,
                &self.scope,
            )
            .map_err(refused)
    }

    pub(crate) fn require_local_policy(&self, policy: Digest32) -> Result<(), AgentdError> {
        self.profile.require_local_policy(policy).map_err(refused)
    }

    pub(crate) fn require_learning_scope(
        &self,
        initial: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
    ) -> Result<(), AgentdError> {
        if initial != &self.initial || scope != &self.scope {
            return Err(refused(
                "factory original empty initial or frozen scope differs",
            ));
        }
        Ok(())
    }

    pub(crate) fn require_snapshot(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<(), AgentdError> {
        if snapshot.request != self.initial.request || snapshot.owners != self.initial.owners {
            return Err(refused(
                "Model factory belongs to another operation or owner set",
            ));
        }
        self.scope.validate_snapshot(snapshot).map_err(refused)
    }

    /// Create only after the original qualified cut has been bound once at
    /// Root. Existing bindings always recover/read the same original owner.
    pub async fn commit_or_readback<T: AnchorWitnessStore, S: FinalHoldoutCasStoreV1>(
        &mut self,
        trainer: &mut CellQ24TrainingOwnerV1<T>,
        dataset_cut: &LearningIterationSnapshotV1,
        inputs: &CellQ24ModelProposalInputsV1<'_, S>,
    ) -> Result<CellQ24ModelProposalReceiptV1, AgentdError> {
        self.operate(trainer, dataset_cut, inputs, Operation::CommitOrReadback)
            .await
    }

    /// Read-only recovery cannot bind Reserved state or initialize a missing
    /// journal. Original receipt bytes and time are returned without restamping.
    pub async fn readback<T: AnchorWitnessStore, S: FinalHoldoutCasStoreV1>(
        &mut self,
        trainer: &mut CellQ24TrainingOwnerV1<T>,
        dataset_cut: &LearningIterationSnapshotV1,
        inputs: &CellQ24ModelProposalInputsV1<'_, S>,
    ) -> Result<CellQ24ModelProposalReceiptV1, AgentdError> {
        self.operate(trainer, dataset_cut, inputs, Operation::Readback)
            .await
    }

    async fn operate<T: AnchorWitnessStore, S: FinalHoldoutCasStoreV1>(
        &mut self,
        trainer: &mut CellQ24TrainingOwnerV1<T>,
        dataset_cut: &LearningIterationSnapshotV1,
        inputs: &CellQ24ModelProposalInputsV1<'_, S>,
        operation: Operation,
    ) -> Result<CellQ24ModelProposalReceiptV1, AgentdError> {
        if self.fenced {
            return Err(refused(
                "factory acknowledgement uncertain; original reopen required",
            ));
        }
        // Cancellation at any await permanently fences this instance. Neither
        // a late reply nor partially created files can become a fresh attempt.
        self.fenced = true;
        self.require_snapshot(dataset_cut)?;
        self.require_snapshot(inputs.training_cut)?;
        trainer
            .require_original_dataset_provenance()
            .map_err(refused)?;
        let before = self.exchange(Command::Observe).await?.lease;
        let material = crate::cell_q24_model_proposal::prepare_original_q24_model_material(
            trainer,
            dataset_cut,
            inputs,
            &self.scope,
        )
        .map_err(original_model_error)?
        .to_string();
        let bound = match operation {
            Operation::CommitOrReadback => {
                self.exchange(Command::Bind {
                    expected: before,
                    material: material.clone(),
                })
                .await?
            }
            Operation::Readback => {
                if before.material.as_ref() != Some(&material) {
                    return Err(refused(
                        "readback requires the original already bound model material",
                    ));
                }
                self.exchange(Command::Confirm { expected: before }).await?
            }
        };
        if bound.lease.material.as_ref() != Some(&material) {
            return Err(refused("Root factory material reply differs"));
        }
        if self.owner.is_none() {
            let (journal, witness_file) = self
                .files
                .take()
                .ok_or_else(|| refused("factory original owner rights already consumed"))?;
            self.profile.require_files(&journal, &witness_file)?;
            let witness = FileAnchorWitnessStore::open(
                witness_file,
                JournalScope {
                    scope_digest: self.profile.binding().parse().map_err(refused)?,
                    objective_digest: self.initial.request.envelope.objective_digest,
                },
                self.generation,
                WITNESS_RECORDS,
            )
            .map_err(refused)?;
            self.owner = Some(
                if bound.newly_bound {
                    // This clock gates fresh owner creation only; it never replaces
                    // an original proposal receipt's persisted timestamp.
                    if SystemTime::now()
                        .duration_since(UNIX_EPOCH)
                        .map_err(refused)?
                        .as_secs()
                        >= self.profile.expiry()
                    {
                        return Err(refused("original work expired before Model owner creation"));
                    }
                    CellQ24ModelProposalOwnerV1::create(
                        journal,
                        witness,
                        trainer,
                        dataset_cut.clone(),
                    )
                } else {
                    CellQ24ModelProposalOwnerV1::recover(
                        journal,
                        witness,
                        trainer,
                        dataset_cut.clone(),
                    )
                }
                .map_err(original_model_error)?,
            );
        } else if bound.newly_bound {
            return Err(refused("existing factory owner cannot be rebound"));
        }
        let owner: &mut CellQ24ModelProposalOwnerV1<FileAnchorWitnessStore> =
            self.owner
                .as_mut()
                .ok_or_else(|| refused("original Model owner missing"))?;
        let receipt = match operation {
            Operation::CommitOrReadback => owner.commit_or_readback(trainer, inputs),
            Operation::Readback => owner.readback(trainer, inputs),
        }
        .map_err(original_model_error)?;
        trainer
            .require_original_dataset_provenance()
            .map_err(refused)?;
        let after = self
            .exchange(Command::Confirm {
                expected: bound.lease.clone(),
            })
            .await?;
        if after.lease != bound.lease || after.newly_bound {
            return Err(refused(
                "factory original authority changed during owner action",
            ));
        }
        self.fenced = false;
        Ok(receipt)
    }

    async fn exchange(&mut self, command: Command) -> Result<Reply, AgentdError> {
        let transport = self
            .transport
            .take()
            .ok_or_else(|| refused("original factory lane consumed"))?;
        let request_id = self.next_request_id;
        self.next_request_id = request_id
            .checked_add(1)
            .ok_or_else(|| refused("factory request sequence exhausted"))?;
        let request = Request {
            schema: 1,
            operation: PURPOSE.into(),
            request_id,
            binding: self.profile.binding().into(),
            command,
        };
        let response: Response = transport.read(&request).await.map_err(refused)?;
        if response.schema != 1
            || response.operation != PURPOSE
            || response.request_id != request_id
            || response.binding != self.profile.binding()
        {
            return Err(refused("factory original reply scope differs"));
        }
        validate_reply(&request.command, &response.reply)?;
        self.transport = Some(transport);
        Ok(response.reply)
    }
}

fn validate_reply(command: &Command, reply: &Reply) -> Result<(), AgentdError> {
    let FactoryLease {
        epoch,
        material,
        revocations,
    } = &reply.lease;
    let canonical = |value: &str| {
        value
            .parse::<Digest32>()
            .is_ok_and(|digest| !digest.is_zero() && digest.to_string() == value)
    };
    if !canonical(revocations)
        || !matches!((epoch, material), (1, None) | (2, Some(_)))
        || material.as_ref().is_some_and(|value| !canonical(value))
    {
        return Err(refused("invalid original factory lease"));
    }
    let expected = match command {
        Command::Observe => !reply.newly_bound,
        Command::Confirm { expected } => &reply.lease == expected && !reply.newly_bound,
        Command::Bind { expected, material } => {
            reply.lease.revocations == expected.revocations
                && reply.lease.material.as_ref() == Some(material)
                && match (&expected.material, reply.newly_bound) {
                    (None, true) => expected.epoch == 1 && reply.lease.epoch == 2,
                    (Some(before), false) => {
                        before == material && reply.lease.epoch == expected.epoch
                    }
                    _ => false,
                }
        }
    };
    if !expected {
        return Err(refused("factory transition acknowledgement differs"));
    }
    Ok(())
}

fn refused(message: impl std::fmt::Display) -> AgentdError {
    AgentdError::GenerationFenced(format!("original Root Model factory: {message}"))
}

fn original_model_error(error: crate::CellQ24ModelProposalErrorV1) -> AgentdError {
    // Keep the original typed Pending/CommitUncertain/store error as a source;
    // it is never converted into a successful NoUpdate or a new proposal.
    AgentdError::Io(std::io::Error::other(error))
}

#[cfg(test)]
#[path = "root_q24_model_factory_tests.rs"]
mod tests;
