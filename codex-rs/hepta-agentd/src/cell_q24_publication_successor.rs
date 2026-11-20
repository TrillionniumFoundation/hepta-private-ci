//! Root-only installation custody. The common PublishedTask constructor is
//! deliberately not an enrollment input: only this original Root driver can
//! hand its validated owners, scope, decision and live session to the worker.

use super::*;
use crate::learning_iteration::OriginalQ24SuccessorContext;

pub(crate) struct OriginalSuccessorPublication {
    pub(crate) prepared: OriginalCellQ24PreparedPublicationV1,
    pub(crate) proof: OriginalSuccessorProof,
    pub(crate) model: Arc<LoadedCellQ24ModelV1>,
    pub(crate) bundle: codex_hepta_learning_artifacts::CellCompatibilityBundleV1,
}

#[derive(Clone)]
pub(crate) struct OriginalSuccessorProof {
    context: Arc<OriginalQ24SuccessorContext>,
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    decision: LearningIterationSnapshotV1,
    operation: StableId,
    selection: Digest32,
}

impl OriginalSuccessorProof {
    pub(crate) fn require_original_publication_owners(
        &self,
        owners: &OriginalCellQ24LearningStageOwnersV1,
        decision: &LearningIterationSnapshotV1,
    ) -> Result<(), Error> {
        if !std::ptr::eq(owners, self.context.owners().as_ref()) || decision != &self.decision {
            return Err(Error::Binding(
                "successor publication belongs to another original aggregate",
            ));
        }
        Ok(())
    }

    pub(crate) fn has_original_historical_source(&self) -> bool {
        self.context.has_original_historical_source()
    }

    fn require_current_bindings(&self) -> Result<(), AgentdError> {
        let current: &NeuronGenerationCurrentOwnerV1 = self.current.as_ref();
        current.require_original_root_successor(
            self.context.session(),
            self.context.initial(),
            self.context.scope(),
        )?;
        current.require_original_root_selection(&self.decision, &self.operation, self.selection)
    }

    pub(crate) fn require_original_successor_operation(
        &self,
        read: &crate::cell_composed_q24::OriginalPreparedReadV1<'_>,
    ) -> Result<(), AgentdError> {
        self.context.require_original_successor_operation(read)?;
        self.require_current_bindings()?;
        self.context.require_original_successor_operation(read)
    }

    pub(crate) async fn require_current_successor_publication(&self) -> Result<(), Error> {
        let proof = self.clone();
        self.context
            .with_current_successor_operation(move || proof.require_current_bindings())
            .await?;
        Ok(())
    }

    /// The actual channel open is enclosed by this same original source read.
    /// No borrowed read or checked authority result survives the callback.
    pub(crate) async fn with_current_successor_publication<T>(
        &self,
        work: impl FnOnce() -> Result<T, Error> + Send + 'static,
    ) -> Result<T, Error>
    where
        T: Send + 'static,
    {
        use std::sync::atomic::AtomicBool;
        use std::sync::atomic::Ordering;
        let proof = self.clone();
        let started = Arc::new(AtomicBool::new(false));
        let effect_started = Arc::clone(&started);
        let result = self
            .context
            .with_current_successor_operation(move || {
                proof.require_current_bindings()?;
                effect_started.store(true, Ordering::Release);
                let value = work();
                proof.require_current_bindings()?;
                Ok(value)
            })
            .await;
        match result {
            Ok(value) => value,
            Err(_) if started.load(Ordering::Acquire) => Err(Error::CommitUncertain),
            Err(error) => Err(error.into()),
        }
    }
}

impl OriginalCellQ24RootPublicationDriverV1 {
    /// Consume this actual Root path and the one closed pending service. The
    /// supervised service owns preparation and publication, including lost ACK.
    pub async fn prepare_original_successor(
        self,
        handoff: crate::OriginalQ24SuccessorHandoffV1,
        predecessor: AgentdGenerationUpdatePredecessorFilesV1<FileAnchorWitnessStore>,
        target: OriginalCellQ24FeatureTargetV1,
        execution: crate::OriginalQ24SuccessorExecutionInputsV1,
    ) -> Result<crate::OriginalQ24PreparedSuccessorV1, Error> {
        handoff
            .prepare_from_original_root(self, predecessor, target, execution)
            .await
    }

    pub(crate) fn original_successor_decision(&self) -> &LearningIterationSnapshotV1 {
        &self.driver.original.decision.snapshot
    }

    pub(crate) async fn prepare_in_original_successor_worker(
        self,
        context: Arc<OriginalQ24SuccessorContext>,
        predecessor: AgentdGenerationUpdatePredecessorFilesV1<FileAnchorWitnessStore>,
        target: OriginalCellQ24FeatureTargetV1,
        state: Arc<crate::AgentdState>,
        slot: Arc<crate::circuit_q24_successor::SuccessorSlot>,
    ) -> Result<OriginalSuccessorPublication, Error> {
        if !Arc::ptr_eq(context.owners(), &self.driver.original.owners)
            || self.driver.original.decision.snapshot.request != context.initial().request
            || self.driver.original.decision.snapshot.owners != context.initial().owners
        {
            return Err(Error::Binding(
                "successor requires the same original aggregate",
            ));
        }
        context
            .scope()
            .validate_snapshot(&self.driver.original.decision.snapshot)
            .map_err(|_| Error::Binding("successor frozen scope"))?;
        let proof = OriginalSuccessorProof {
            context,
            current: Arc::clone(&self.driver.current),
            decision: self.driver.original.decision.snapshot.clone(),
            operation: self.driver.original.decision.operation.clone(),
            selection: self.selected.observation().digest(),
        };
        let model = Arc::clone(&target.model);
        let bundle = self.driver.original.decision.bundle.clone();
        // All existing model, Artifact, predecessor and task checks still run.
        // Once preparation is attempted its outcome must not be retried here.
        let prepared = self
            .prepare_successor_current(
                predecessor,
                target,
                state,
                proof.context.identity().clone(),
                slot,
                proof.clone(),
            )
            .await?;
        Ok(OriginalSuccessorPublication {
            prepared,
            proof,
            model,
            bundle,
        })
    }
}
