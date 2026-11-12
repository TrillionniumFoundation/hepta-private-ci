//! Private conversion of a response on the original Root factory stream into
//! a borrowed Model material capability. No raw constructor or native B value
//! is available to callers; every write is followed by another actual Root read.

use super::*;
use crate::OriginalRootIndependentBEvaluationReadbackV1;
use crate::cell_q24_model_proposal::RootQ24ModelProjectionDataV1;
use crate::cell_q24_model_proposal::original_root_model_key;
use crate::cell_q24_training_receipt_owner::OriginalQ24TrainingOperationEvidenceV1;
use crate::root_q24_model_b_protocol as wire;

pub(crate) struct OriginalRootModelMaterialV1<'a, 'read> {
    training: &'a OriginalQ24TrainingOperationEvidenceV1<'read>,
    evaluation: &'a OriginalRootIndependentBEvaluationReadbackV1,
    scope: FrozenLearningScopeV2,
    projection: RootQ24ModelProjectionDataV1,
}

impl OriginalRootModelMaterialV1<'_, '_> {
    pub(crate) fn require_current_training_source(
        &self,
    ) -> Result<(), crate::CellQ24ModelProposalErrorV1> {
        OriginalQ24TrainingOperationEvidenceV1::require_current_training_source(self.training)
            .map_err(crate::CellQ24ModelProposalErrorV1::OriginalSource)
    }
    pub(crate) fn scope(&self) -> &FrozenLearningScopeV2 {
        &self.scope
    }
    pub(crate) fn projection(&self) -> &RootQ24ModelProjectionDataV1 {
        &self.projection
    }
    pub(crate) fn training_snapshot(&self) -> &LearningIterationSnapshotV1 {
        self.training.snapshot()
    }
    pub(crate) fn training_receipt(
        &self,
    ) -> &codex_hepta_learning_artifacts::LearningIterationReceiptV1 {
        self.training.receipt()
    }
    pub(crate) fn evaluation_receipt(
        &self,
    ) -> &codex_hepta_learning_artifacts::LearningIterationReceiptV1 {
        self.evaluation.receipt()
    }
}

impl AgentdRootQ24ModelFactoryV1 {
    pub(crate) async fn commit_from_original_b(
        &mut self,
        original: &OriginalQ24TrainingOperationEvidenceV1<'_>,
        evaluation: &OriginalRootIndependentBEvaluationReadbackV1,
    ) -> Result<CellQ24ModelProposalReceiptV1, AgentdError> {
        self.operate_original_b(original, evaluation, Operation::CommitOrReadback)
            .await
    }

    pub(crate) async fn read_from_original_b(
        &mut self,
        original: &OriginalQ24TrainingOperationEvidenceV1<'_>,
        evaluation: &OriginalRootIndependentBEvaluationReadbackV1,
    ) -> Result<CellQ24ModelProposalReceiptV1, AgentdError> {
        self.operate_original_b(original, evaluation, Operation::Readback)
            .await
    }

    async fn operate_original_b(
        &mut self,
        original: &OriginalQ24TrainingOperationEvidenceV1<'_>,
        evaluation: &OriginalRootIndependentBEvaluationReadbackV1,
        operation: Operation,
    ) -> Result<CellQ24ModelProposalReceiptV1, AgentdError> {
        if self.fenced {
            return Err(refused("original Root Model attempt is fenced"));
        }
        self.fenced = true;
        original
            .require_current_training_source()
            .map_err(refused)?;
        self.require_snapshot(original.snapshot())?;
        let before = self.exchange(Command::Observe).await?.lease;
        let action = match operation {
            Operation::CommitOrReadback => wire::Action::Bind {},
            Operation::Readback => wire::Action::Read {},
        };
        let (material, bound) = self
            .exchange_original_b(original, evaluation, before, action)
            .await?;
        if self.owner.is_none() {
            let (journal, witness_file) = self
                .files
                .take()
                .ok_or_else(|| refused("original Model writer rights already consumed"))?;
            self.profile.require_files(&journal, &witness_file)?;
            let witness = FileAnchorWitnessStore::open(
                witness_file,
                JournalScope {
                    scope_digest: LiveFactoryProfile::witness_binding(&self.profile)
                        .parse()
                        .map_err(refused)?,
                    objective_digest: self.initial.request.envelope.objective_digest,
                },
                self.generation,
                WITNESS_RECORDS,
            )
            .map_err(refused)?;
            self.owner = Some(
                if bound.newly_bound {
                    if SystemTime::now()
                        .duration_since(UNIX_EPOCH)
                        .map_err(refused)?
                        .as_secs()
                        >= self.profile.expiry()
                    {
                        return Err(refused("original work expired before Model creation"));
                    }
                    CellQ24ModelProposalOwnerV1::create_from_original_root(
                        journal, witness, &material,
                    )
                } else {
                    CellQ24ModelProposalOwnerV1::recover_from_original_root(
                        journal, witness, &material,
                    )
                }
                .map_err(original_model_error)?,
            );
        } else if bound.newly_bound {
            return Err(refused("original Model writer cannot be rebound"));
        }
        let owner: &mut CellQ24ModelProposalOwnerV1<FileAnchorWitnessStore> =
            self.owner
                .as_mut()
                .ok_or_else(|| refused("original Model writer absent"))?;
        let result = match operation {
            Operation::CommitOrReadback => owner.commit_original_root(&material),
            Operation::Readback => owner.read_original_root(&material),
        };
        // An owner error does not skip the actual B/Root postcheck. A dropped
        // future still leaves this factory permanently fenced.
        let (after, current) = self
            .exchange_original_b(
                original,
                evaluation,
                bound.lease.clone(),
                wire::Action::Read {},
            )
            .await?;
        if after.projection != material.projection
            || current.lease != bound.lease
            || current.newly_bound
        {
            return Err(refused(
                "original Root Model material changed across the writer",
            ));
        }
        original
            .require_current_training_source()
            .map_err(refused)?;
        let receipt = result.map_err(original_model_error)?;
        self.fenced = false;
        Ok(receipt)
    }

    async fn exchange_original_b<'a, 'read>(
        &mut self,
        original: &'a OriginalQ24TrainingOperationEvidenceV1<'read>,
        evaluation: &'a OriginalRootIndependentBEvaluationReadbackV1,
        expected: FactoryLease,
        action: wire::Action,
    ) -> Result<(OriginalRootModelMaterialV1<'a, 'read>, Reply), AgentdError> {
        if self.profile.wire_schema() != 2 {
            return Err(refused("original Root B requires V2 factory"));
        }
        original
            .require_current_training_source()
            .map_err(refused)?;
        let transport = self
            .transport
            .take()
            .ok_or_else(|| refused("original factory lane consumed"))?;
        let request_id = self.next_request_id;
        self.next_request_id = request_id
            .checked_add(1)
            .ok_or_else(|| refused("original factory sequence exhausted"))?;
        let request = wire::Request {
            schema: 2,
            operation: wire::PURPOSE.into(),
            request_id,
            binding: self.profile.binding().into(),
            original_b: evaluation.original_binding().to_string(),
            training_head: original.snapshot().head_digest.to_string(),
            expected,
            action,
        };
        let response: wire::Response = transport.read(&request).await.map_err(refused)?;
        if response.schema != 2
            || response.operation != wire::PURPOSE
            || response.request_id != request_id
            || response.binding != self.profile.binding()
            || response.original_b != request.original_b
        {
            return Err(refused("original Root Model reply differs"));
        }
        let material = OriginalRootModelMaterialV1 {
            training: original,
            evaluation,
            scope: self.scope.clone(),
            projection: response.projection,
        };
        let binding = original_root_model_key(&material)
            .map_err(original_model_error)?
            .to_string();
        let command = match request.action {
            wire::Action::Bind {} => Command::Bind {
                expected: request.expected,
                material: binding,
            },
            wire::Action::Read {} => {
                if request.expected.material.as_ref() != Some(&binding) {
                    return Err(refused("original bound Model required"));
                }
                Command::Confirm {
                    expected: request.expected,
                }
            }
        };
        validate_reply(&command, &response.reply)?;
        original
            .require_current_training_source()
            .map_err(refused)?;
        self.transport = Some(transport);
        Ok((material, response.reply))
    }
}
