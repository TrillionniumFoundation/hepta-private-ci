//! Resolve sealed previous selections before installing either old helper.
use super::*;

pub(crate) struct ResolvedDesktopRecoveryLaunches {
    pub(crate) notes: Option<crate::AgentdNotesPreviousRecoveryLaunch>,
    pub(crate) calculator: Option<crate::AgentdCalculatorPreviousRecoveryLaunch>,
    pub(crate) current_calculator: codex_hepta_memory::CalculatorTargetIdentity,
}

impl AgentdDesktopThreadToolRuntime {
    pub(crate) async fn resolve_previous_recovery(
        &self,
        notes: crate::AgentdNotesPreviousRecoveryRequest,
        calculator: crate::AgentdCalculatorPreviousRecoveryRequest,
        deadline: crate::calculator_deadline::Deadline,
    ) -> Result<ResolvedDesktopRecoveryLaunches, AgentdError> {
        let end = deadline.capped(Duration::from_secs(5))?;
        notes
            .previous_target
            .validate()
            .map_err(AgentdError::Invalid)?;
        calculator
            .previous_target
            .validate()
            .map_err(AgentdError::Invalid)?;
        if notes.previous_target.session_instance != calculator.previous_target.session_instance
            || notes.previous_target.task_id == calculator.previous_target.task_id
            || notes.previous_target == *self.adapter.observer.target()
            || calculator.previous_target == *self.calculator.target()
            || !notes.helper.is_absolute()
            || !calculator.helper.is_absolute()
            || !notes.state_directory.is_absolute()
            || !calculator.state_directory.is_absolute()
        {
            return Err(invalid(
                "joint recovery requires the exact distinct previous targets and absolute frozen paths",
            ));
        }
        self.seed.verify_persisted()?;
        let session = self
            .session
            .as_ref()
            .ok_or_else(|| invalid("original Session absent during joint recovery"))?;
        session.check_alive()?;
        end.remaining()?;
        let selected = self
            .adapter
            .desktop_previous_operation_ids(&self.route, &notes, &calculator, end)
            .await?;
        self.seed.verify_persisted()?;
        session.check_alive()?;
        self.adapter.check_available()?;
        end.remaining()?;
        Ok(ResolvedDesktopRecoveryLaunches {
            notes: selected
                .notes
                .map(|operation_id| notes.resolved(operation_id)),
            calculator: selected
                .calculator
                .map(|operation_id| calculator.resolved(operation_id)),
            current_calculator: self.calculator.target().clone(),
        })
    }
}
