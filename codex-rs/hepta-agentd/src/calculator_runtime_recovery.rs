//! Explicit old Calculator recovery on the same original operation runtime.
use super::*;
use crate::AgentdCalculatorPreviousRecoveryLaunch;
use codex_hepta_memory::CalculatorRecoveryChannel;
use codex_hepta_memory::CalculatorTargetIdentity;

pub(super) struct CalculatorRuntimeRecovery {
    current: CalculatorTargetIdentity,
    launch: AgentdCalculatorPreviousRecoveryLaunch,
}

impl AgentdProductionOperationRuntimeConfig {
    pub(crate) fn select_previous_calculator_process(
        &mut self,
        current: &CalculatorTargetIdentity,
        launch: AgentdCalculatorPreviousRecoveryLaunch,
    ) -> Result<(), AgentdError> {
        current.validate().map_err(AgentdError::Invalid)?;
        launch
            .previous_target
            .validate()
            .map_err(AgentdError::Invalid)?;
        codex_hepta_types::StableId::new(&launch.operation_id)
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        let destination = current.destination_id();
        if self.calculator_recovery.is_some()
            || launch.previous_target == *current
            || !launch.helper.is_absolute()
            || !launch.state_directory.is_absolute()
            || (self.target.destination_id() != destination
                && !self
                    .additional_targets
                    .iter()
                    .any(|(_, target)| target.destination_id() == destination))
        {
            return Err(AgentdError::Invalid(
                "old Calculator recovery requires a distinct old target and one actual current destination".into(),
            ));
        }
        self.calculator_recovery = Some(CalculatorRuntimeRecovery {
            current: current.clone(),
            launch,
        });
        Ok(())
    }
}

impl CalculatorRuntimeRecovery {
    pub(super) async fn attach(
        self,
        host: AgentdProductionWriterHost,
    ) -> Result<AgentdProductionWriterHost, AgentdError> {
        let runtime = tokio::runtime::Handle::current();
        tokio::task::spawn_blocking(move || {
            runtime.block_on(
                host.attach_previous_calculator_recovery_process(&self.current, self.launch),
            )
        })
        .await
        .map_err(|_| {
            AgentdError::Invalid("original Calculator startup recovery worker failed".into())
        })?
    }
}

impl AgentdProductionWriterHost {
    /// Attach one exact old receipt without registering an old effect dispatcher.
    pub async fn attach_explicit_previous_calculator_recovery(
        mut self,
        current: &CalculatorTargetIdentity,
        previous: CalculatorTargetIdentity,
        operation_id: &str,
        channel: Arc<dyn CalculatorRecoveryChannel>,
    ) -> Result<Self, AgentdError> {
        current.validate().map_err(AgentdError::Invalid)?;
        if self.previous_calculator.is_some()
            || previous == *current
            || !self.has_destination(&current.destination_id())
        {
            return Err(AgentdError::Invalid(
                "explicit Calculator recovery requires a distinct old target and one fixed current destination".into(),
            ));
        }
        let recovery = self
            .writer
            .calculator_recovery_target_for_retained_operation(previous, operation_id, channel)
            .await?;
        self.previous_calculator = Some((current.destination_id(), Arc::new(recovery)));
        Ok(self)
    }
}
