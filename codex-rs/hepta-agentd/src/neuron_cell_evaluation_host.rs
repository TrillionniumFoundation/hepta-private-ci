//! One concrete Evaluator host over the original completed B/retention owners.
//! It neither manufactures Product declarations nor executes/labels B. The
//! original Evaluator receipt key stays inside its original receipt owner.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;

use codex_hepta_intelligence_eval::ProductTimingEvidenceV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_types::Digest32;
use tokio::runtime::Handle;
use tokio::sync::Semaphore;

use super::OriginalCellEvaluationPanelOwnerV1;
use super::OriginalCellEvaluationPanelReadbackV1;
use crate::CellEvaluationJournalsV1;
use crate::OriginalCellEvaluationReceiptOwnerV1;
use crate::OriginalCellEvaluationReceiptSourcesV1;

#[path = "neuron_cell_evaluation_host_command.rs"]
mod command;
#[path = "neuron_cell_evaluation_host_contract.rs"]
mod contract;
#[path = "neuron_cell_evaluation_host_service.rs"]
mod service;
#[path = "neuron_cell_evaluation_host_training_readback.rs"]
mod training_readback;
#[path = "neuron_cell_evaluation_training_operation.rs"]
mod training_operation;
#[path = "neuron_cell_evaluation_host_wire.rs"]
mod wire;

pub use command::OriginalCellEvaluationCommandClientV1;
pub use command::OriginalCellEvaluationCommandConnectionV1;
pub use contract::OriginalCellEvaluationCommandErrorV1;
pub use contract::OriginalCellEvaluationCommandReceiptV1;
pub(crate) use training_operation::TrainingOperation;
pub(crate) use training_operation::TrainingRead;

use contract::Context;
type Error = OriginalCellEvaluationCommandErrorV1;
type Receipt = OriginalCellEvaluationCommandReceiptV1;
type Panel = OriginalCellEvaluationPanelOwnerV1<
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
>;

/// The original host transfers these concrete owners once. No writable owner,
/// signer, callback, row or qualification seal is exposed by this host.
pub struct OriginalCellEvaluationHostV1 {
    owners: Mutex<Owners>,
    context: Context,
    binding: Digest32,
    execution_requested: AtomicBool,
    runtime: Handle,
    connections: Arc<Semaphore>,
}

struct Owners {
    panel: Panel,
    evaluator: OriginalCellEvaluationReceiptOwnerV1<FileAnchorWitnessStore>,
    shared_training: Option<Arc<crate::LearningIterationEvidenceClientV1>>,
    retained: Option<Receipt>,
    fenced: bool,
    #[cfg(test)]
    fixture_clock: Option<u64>,
}

impl OriginalCellEvaluationHostV1 {
    /// Only the original receipt owner's consuming factory may call this.
    pub(crate) fn from_original_receipt_owner(
        evaluator: OriginalCellEvaluationReceiptOwnerV1<FileAnchorWitnessStore>,
        panel: Panel,
    ) -> Result<Self, Error> {
        let (receipt, readback_only) =
            OriginalCellEvaluationReceiptOwnerV1::original_host_profile(&evaluator);
        let primary = &panel.primary.qualification.config;
        if panel.fenced
            || receipt.training != primary.training
            || receipt.scope != primary.scope
            || receipt.plan != primary.plan
            || receipt.signing.plan != *primary.plan.product_plan()
            || receipt.signing.execution_namespace != primary.execution_namespace
            || receipt.signing.signer.principal != primary.context.evaluator
            || receipt.signing.verifier.trust_digest() != primary.verifier.trust_digest()
            || receipt.signing.verifier.scope_digest() != primary.verifier.scope_digest()
            || receipt.signing.verifier.objective_digest() != primary.verifier.objective_digest()
        {
            return Err(Error::Binding(
                "same original Evaluator, Candidate, plan and execution custody",
            ));
        }
        let context = Context::from_checkpoint(
            primary.training.clone(),
            primary.scope.clone(),
            panel.registration.clone(),
            primary.training_evidence.clone(),
            primary.verifier.clone(),
        )?;
        let binding = context.binding(now()?)?;
        let runtime = Handle::try_current().map_err(|_| Error::Unavailable)?;
        Ok(Self {
            owners: Mutex::new(Owners {
                panel,
                evaluator,
                shared_training: None,
                retained: None,
                fenced: false,
                #[cfg(test)]
                fixture_clock: None,
            }),
            context,
            binding,
            execution_requested: AtomicBool::new(readback_only),
            runtime,
            connections: Arc::new(Semaphore::new(4)),
        })
    }
}

impl Owners {
    async fn completion(
        &mut self,
        context: &Context,
        action: wire::Action,
    ) -> Result<Receipt, Error> {
        if self.fenced {
            return Err(Error::CommitUncertain);
        }
        let result = self.complete_original_operation(context, action).await;
        self.fence_result(result)
    }

    fn fence_result<T>(&mut self, result: Result<T, Error>) -> Result<T, Error> {
        if result.is_err()
            && !matches!(&result,
            Err(Error::Receipt(crate::OriginalCellEvaluationReceiptErrorV1::Owner(
                crate::learning_owner_journal::LearningOriginalOwnerErrorV1::Pending
                | crate::learning_owner_journal::LearningOriginalOwnerErrorV1::Store(
                    codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1::Missing,
                )
            ))))
        {
            self.fenced = true;
        }
        result
    }

    async fn begin_training_operation(
        &self,
        context: &Context,
    ) -> Result<Option<TrainingOperation>, Error> {
        match &self.shared_training {
            Some(trainer) => Ok(Some(
                TrainingOperation::begin(Arc::clone(trainer), context).await?,
            )),
            None => Ok(None),
        }
    }

    async fn complete_original_operation(
        &mut self,
        context: &Context,
        action: wire::Action,
    ) -> Result<Receipt, Error> {
        let started_at = self.current_time()?;
        context.authenticate(started_at)?;
        let operation = self.begin_training_operation(context).await?;
        let training = match operation.as_ref() {
            Some(original) => TrainingRead::Operation(original),
            None => TrainingRead::Independent,
        };
        let (completed, after) = self
            .read_original_completion(context, action, training)
            .await?;
        if let Some(original) = operation {
            TrainingOperation::finish(original).await?;
        }
        self.finish_original_completion(context, action, completed, &after, started_at)
    }

    async fn read_original_completion(
        &mut self,
        context: &Context,
        action: wire::Action,
        training: TrainingRead<'_>,
    ) -> Result<(Receipt, OriginalCellEvaluationPanelReadbackV1), Error> {
        let started_at = self.current_time()?;
        context.authenticate(started_at)?;
        let before = self.read_panel(training).await?;
        if before.training() != &context.training
            || before.training_evidence() != &context.training_evidence
            || before.registration() != &context.registration
        {
            return Err(Error::Binding(
                "exact original panel and Training command context",
            ));
        }
        if action == wire::Action::Execute {
            let current = self.current_time()?;
            require_clock(started_at, current)?;
            if current >= context.training.request.envelope.expiry_unix_seconds {
                return Err(Error::DeadlineExceeded);
            }
        }
        let completed = {
            let primary = &mut self.panel.primary;
            let config = &primary.qualification.config;
            let sources = OriginalCellEvaluationReceiptSourcesV1 {
                snapshot: &context.training,
                runner: &mut primary.runner,
                journals: CellEvaluationJournalsV1 {
                    candidate: &primary.candidate,
                    fixed_expert: &primary.fixed_expert,
                },
                candidate_plan: &primary.candidate_plan,
                baseline_plan: &primary.baseline_plan,
                executions: &mut primary.executions,
                qualification: before.primary().qualification(),
                context: &config.context,
                evidence: &config.product_evidence,
                timing: ProductTimingEvidenceV1::Qualification,
                trainer: primary.trainer.as_ref(),
            };
            match action {
                wire::Action::Execute => {
                    OriginalCellEvaluationReceiptOwnerV1::attest_with_training(
                        &mut self.evaluator,
                        sources,
                        training,
                    )
                    .await?
                }
                wire::Action::Readback => {
                    OriginalCellEvaluationReceiptOwnerV1::readback_with_training(
                        &mut self.evaluator,
                        sources,
                        training,
                    )
                    .await?
                }
            }
        };
        let after = self.read_panel(training).await?;
        if before != after {
            return Err(Error::CommitUncertain);
        }
        let current = self.current_time()?;
        require_clock(started_at, current)?;
        let completed =
            contract::authenticate_receipt(context, completed.0, completed.1, current)?;
        Ok((completed, after))
    }

    fn finish_original_completion(
        &mut self,
        context: &Context,
        action: wire::Action,
        completed: Receipt,
        after: &OriginalCellEvaluationPanelReadbackV1,
        started_at: u64,
    ) -> Result<Receipt, Error> {
        // All panel and operation Trainer I/O finishes before this final actual
        // receipt journal read. The operation observation is already consumed.
        OriginalCellEvaluationReceiptOwnerV1::require_original_host_completed(
            &mut self.evaluator,
            completed.receipt(),
            completed.attestation(),
        )?;
        let current = self.current_time()?;
        require_clock(started_at, current)?;
        if action == wire::Action::Execute
            && current >= context.training.request.envelope.expiry_unix_seconds
        {
            // A durable signature may exist; never report a known no-effect expiry.
            return Err(Error::CommitUncertain);
        }
        self.authenticate_panel(after, current)?;
        let (config, _) =
            OriginalCellEvaluationReceiptOwnerV1::original_host_profile(&self.evaluator);
        config.signing.verifier.require_signer_binding(
            LearningEvidenceRoleV1::Evaluator,
            &config.signing.signer,
            current,
        )?;
        let original = contract::authenticate_receipt(
            context,
            completed.receipt,
            completed.attestation,
            current,
        )?;
        if self
            .retained
            .as_ref()
            .is_some_and(|previous| previous != &original)
        {
            return Err(Error::CommitUncertain);
        }
        self.retained = Some(original.clone());
        // No Source, Cell, witness, file or peer I/O follows fresh authentication.
        Ok(original)
    }

    async fn read_panel(
        &mut self,
        training: TrainingRead<'_>,
    ) -> Result<OriginalCellEvaluationPanelReadbackV1, Error> {
        #[cfg(test)]
        if let Some(current) = self.fixture_clock {
            return self
                .panel
                .read_current_with_clock(|| Ok(current), training)
                .await
                .map_err(Error::from);
        }
        OriginalCellEvaluationPanelOwnerV1::read_current_with_clock(
            &mut self.panel,
            super::original::now,
            training,
        )
            .await
            .map_err(Error::from)
    }

    fn authenticate_panel(
        &mut self,
        observed: &OriginalCellEvaluationPanelReadbackV1,
        current: u64,
    ) -> Result<(), Error> {
        if self.panel.retained.as_ref() != Some(observed)
            || observed.retention().len() != self.panel.retention.len()
        {
            return Err(Error::CommitUncertain);
        }
        self.panel
            .primary
            .authenticate(observed.primary(), current)?;
        for (owner, member) in self.panel.retention.iter_mut().zip(observed.retention()) {
            owner.authenticate(member, current)?;
        }
        Ok(())
    }

    fn current_time(&self) -> Result<u64, Error> {
        #[cfg(test)]
        if let Some(current) = self.fixture_clock {
            return Ok(current);
        }
        now()
    }
}

fn now() -> Result<u64, Error> {
    super::original::now().map_err(Error::from)
}

fn require_clock(started_at: u64, current: u64) -> Result<(), Error> {
    if current < started_at {
        return Err(Error::Binding("original Evaluation clock moved backwards"));
    }
    Ok(())
}

#[path = "neuron_cell_evaluation_model_material.rs"]
mod model_material;
pub(crate) use model_material::OriginalCellEvaluationModelInputV1;
pub use model_material::OriginalCellEvaluationModelMaterialClientV1;
pub use model_material::OriginalCellEvaluationModelMaterialConnectionV1;
pub use model_material::OriginalCellEvaluationModelMaterialV1;
pub(crate) use model_material::OriginalCellEvaluationModelReadV1;
