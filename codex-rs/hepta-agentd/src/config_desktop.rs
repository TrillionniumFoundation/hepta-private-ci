//! Explicit configuration for the new finite Desktop catalog and original owners.
use super::*;

impl AgentdConfig {
    pub(crate) fn with_desktop_objective(
        mut self,
        config: crate::AgentdDesktopObjectiveConfig,
    ) -> Result<Self, AgentdError> {
        config.validate()?;
        if self.notes_objective.is_some() || self.desktop_objective.is_some() {
            return Err(AgentdError::Invalid(
                "finite Objective profile already configured".into(),
            ));
        }
        self.desktop_objective = Some(config);
        Ok(self)
    }

    pub(crate) fn desktop_objective(&self) -> Option<crate::AgentdDesktopObjectiveConfig> {
        self.desktop_objective.clone()
    }

    #[cfg(target_os = "linux")]
    pub(crate) fn install_original_desktop_thread_tools(
        mut self,
        runtime: crate::AgentdDesktopThreadToolRuntime,
    ) -> Result<Self, AgentdError> {
        if self.notes_ui.is_some()
            || self.notes_thread_tools.is_some()
            || self.desktop_thread_tools.is_some()
        {
            return Err(AgentdError::Invalid(
                "original application interaction profile already selected".into(),
            ));
        }
        runtime.validate_for(&self)?;
        self.desktop_thread_tools = Some(runtime);
        Ok(self)
    }

    #[cfg(target_os = "linux")]
    pub(crate) fn take_original_desktop_thread_tools(
        &mut self,
    ) -> Option<crate::AgentdDesktopThreadToolRuntime> {
        self.desktop_thread_tools.take()
    }

    /// Resolve both applications before selecting either original recovery
    /// process. An absent selection requires a complete validated original cut.
    #[cfg(target_os = "linux")]
    pub(crate) async fn with_original_desktop_previous_recovery_requests(
        self,
        notes: crate::AgentdNotesPreviousRecoveryRequest,
        calculator: crate::AgentdCalculatorPreviousRecoveryRequest,
        deadline: crate::calculator_deadline::Deadline,
    ) -> Result<Self, AgentdError> {
        let selected = self
            .desktop_thread_tools
            .as_ref()
            .ok_or_else(|| {
                AgentdError::Invalid("joint recovery requires original Desktop thread mode".into())
            })?
            .resolve_previous_recovery(notes, calculator, deadline)
            .await?;
        let mut configured = self;
        if let Some(notes) = selected.notes {
            configured = configured.with_original_notes_previous_recovery(notes)?;
        }
        if let Some(calculator) = selected.calculator {
            configured = configured.with_original_calculator_previous_recovery(
                &selected.current_calculator,
                calculator,
            )?;
        }
        deadline.remaining()?;
        Ok(configured)
    }
}
