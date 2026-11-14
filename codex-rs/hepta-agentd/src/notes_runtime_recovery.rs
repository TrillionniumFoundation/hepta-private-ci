//! Explicit startup recovery attached to the same original operation runtime.
//! A previous target receives only its existing read/retirement capability.

use super::*;
use crate::AgentdNotesDocumentObserver;
use crate::AgentdNotesPreviousRecoveryLaunch;
use codex_hepta_memory::NotesTargetIdentity;

pub(super) enum NotesRuntimeRecovery {
    Session(AgentdNotesDocumentObserver),
    PreviousProcess {
        current: NotesTargetIdentity,
        launch: AgentdNotesPreviousRecoveryLaunch,
    },
}

impl AgentdProductionOperationRuntimeConfig {
    pub(crate) fn with_notes_receipt_recovery(
        mut self,
        observer: AgentdNotesDocumentObserver,
    ) -> Result<Self, AgentdError> {
        let destination = observer.target().destination_id();
        if self.notes_recovery.is_some()
            || (self.target.destination_id() != destination
                && !self
                    .additional_targets
                    .iter()
                    .any(|(_, target)| target.destination_id() == destination))
        {
            return Err(AgentdError::Invalid(
                "Notes recovery requires its actual fixed runtime destination exactly once".into(),
            ));
        }
        self.notes_recovery = Some(NotesRuntimeRecovery::Session(observer));
        Ok(self)
    }

    /// A trusted sealed startup manifest may select one exact old independent
    /// store. This does not scan documents or import an old effect capability.
    pub(crate) fn select_previous_notes_process(
        &mut self,
        launch: AgentdNotesPreviousRecoveryLaunch,
    ) -> Result<(), AgentdError> {
        let Some(NotesRuntimeRecovery::Session(observer)) = &self.notes_recovery else {
            return Err(AgentdError::Invalid(
                "explicit old Notes recovery requires the original Session attachment once".into(),
            ));
        };
        launch
            .previous_target
            .validate()
            .map_err(AgentdError::Invalid)?;
        codex_hepta_types::StableId::new(&launch.operation_id)
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        if launch.previous_target == *observer.target()
            || !launch.helper.is_absolute()
            || !launch.state_directory.is_absolute()
        {
            return Err(AgentdError::Invalid("explicit old Notes recovery requires distinct original identity and absolute frozen paths".into()));
        }
        self.notes_recovery = Some(NotesRuntimeRecovery::PreviousProcess {
            current: observer.target().clone(),
            launch,
        });
        Ok(())
    }
}

impl NotesRuntimeRecovery {
    pub(super) async fn attach(
        self,
        host: AgentdProductionWriterHost,
    ) -> Result<AgentdProductionWriterHost, AgentdError> {
        // Existing recovery APIs include bounded synchronous channel/helper I/O.
        // Keep those on one startup blocking worker while the original runtime
        // continues driving the same Root feed and protected checkpoint lanes.
        let runtime = tokio::runtime::Handle::current();
        tokio::task::spawn_blocking(move || {
            runtime.block_on(async move {
                match self {
                    Self::Session(observer) => host.attach_previous_notes_recovery(&observer).await,
                    Self::PreviousProcess { current, launch } => {
                        host.attach_previous_notes_recovery_process(&current, launch)
                            .await
                    }
                }
            })
        })
        .await
        .map_err(|_| AgentdError::Invalid("original Notes startup recovery worker failed".into()))?
    }
}
