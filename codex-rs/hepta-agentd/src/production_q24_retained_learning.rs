//! Finite host adapter: retain actual A provenance beside the original Root
//! learning assembly before startup consumes its owners. No file is opened here.

use std::sync::Arc;

use codex_hepta_automation::AutomationStore;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdProductionLaunch;
use crate::AgentdProductionStartup;
use crate::LearningIterationHandleV1;
use crate::LearningIterationRuntimeBootstrapV1;
use crate::OriginalCellQ24LearningInputsV1;
use crate::OriginalCellQ24LearningStageOwnersV1;
use crate::OriginalCellQ24RetainedLearningSourceV1;
use crate::OriginalCellQ24TaskLedgerProducerV1;

impl AgentdProductionStartup {
    /// The original database and producer are retained capabilities. The new
    /// daemon need not own A's Objective journal or copy A into its task store.
    pub async fn receive_q24_learning_from_retained_source(
        self,
        inputs: OriginalCellQ24LearningInputsV1,
        producer: Arc<OriginalCellQ24TaskLedgerProducerV1>,
        original_store: AutomationStore,
    ) -> Result<(AgentdConfig, AgentdProductionLaunch, LearningIterationHandleV1,
        Arc<OriginalCellQ24LearningStageOwnersV1>), AgentdError> {
        let source: OriginalCellQ24RetainedLearningSourceV1 = producer.retained_learning_source(Arc::clone(&inputs.prepared), original_store).await?;
        // The new read side has no old Task/Cell/FinalUse owner. Release this
        // transferred active producer before opening the next Root consumers.
        drop(producer);
        self.receive_q24_learning_with_retained_capability(inputs, source).await
    }

    /// Capture and drain A before ending its original runtime, then release
    /// every remaining active Task, Cell, producer and original Root consumer.
    /// This entry accepts only the retained in-process source capability.
    /// The normal Root receive and exact scoped registry join still apply.
    pub async fn receive_q24_learning_with_retained_capability(
        self,
        inputs: OriginalCellQ24LearningInputsV1,
        source: OriginalCellQ24RetainedLearningSourceV1,
    ) -> Result<(AgentdConfig, AgentdProductionLaunch, LearningIterationHandleV1,
        Arc<OriginalCellQ24LearningStageOwnersV1>), AgentdError> {
        let (config, launch, handle, owners) = self.receive_q24_learning(inputs).await?;
        Ok((retain_in_config(config, source)?, launch, handle, owners))
    }
}

impl AgentdProductionLaunch {
    pub async fn assemble_q24_learning_from_retained_source(
        self,
        config: AgentdConfig,
        inputs: OriginalCellQ24LearningInputsV1,
        producer: Arc<OriginalCellQ24TaskLedgerProducerV1>,
        original_store: AutomationStore,
    ) -> Result<(Self, AgentdConfig, LearningIterationHandleV1,
        Arc<OriginalCellQ24LearningStageOwnersV1>), AgentdError> {
        let source: OriginalCellQ24RetainedLearningSourceV1 = producer.retained_learning_source(Arc::clone(&inputs.prepared), original_store).await?;
        drop(producer);
        self.assemble_q24_learning_with_retained_capability(config, inputs, source).await
    }

    /// The host has already released the original active A owners before
    /// receiving this new Root launch. No old producer is kept alive here.
    /// The capability is neither serialized nor recreated from a run ID.
    pub async fn assemble_q24_learning_with_retained_capability(
        self,
        config: AgentdConfig,
        inputs: OriginalCellQ24LearningInputsV1,
        source: OriginalCellQ24RetainedLearningSourceV1,
    ) -> Result<(Self, AgentdConfig, LearningIterationHandleV1,
        Arc<OriginalCellQ24LearningStageOwnersV1>), AgentdError> {
        let (launch, config, handle, owners) = self.assemble_q24_learning(config, inputs).await?;
        Ok((launch, retain_in_config(config, source)?, handle, owners))
    }
}

fn retain_in_config(
    mut config: AgentdConfig,
    source: OriginalCellQ24RetainedLearningSourceV1,
) -> Result<AgentdConfig, AgentdError> {
    let bootstrap: LearningIterationRuntimeBootstrapV1 = config.take_learning_iteration_bootstrap()
        .ok_or_else(|| AgentdError::GenerationFenced("original learning worker is missing".into()))?;
    let bootstrap = bootstrap.with_retained_q24_source(source, config.identity())?;
    config.with_learning_iteration_bootstrap(bootstrap)
}
