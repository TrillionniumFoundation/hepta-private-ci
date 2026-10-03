use super::*;
use crate::fleet_lifecycle::FleetLifecycleOperation;

impl HeptaNativeApp {
    pub(super) fn start_fleet_lifecycle(
        &mut self,
        action: Option<(String, FleetLifecycleOperation)>,
    ) {
        if self.runtime_busy() {
            return;
        }
        let revision = self.view_revision;
        self.runtime_overview = None;
        self.status_rendered = None;
        self.ready_view = None;
        self.view_revision = None;
        self.operation_binding = None;
        let runtime = Arc::clone(&self.runtime);
        self.start_task(UiTaskKind::FleetLifecycle, move |admission| {
            let mut runtime = lock_runtime_for_task(&admission, &runtime)?;
            admission
                .begin()
                .map_err(|message| ShellError::State(message.into()))?;
            let result = if let Some((agent, operation)) = action {
                revision
                    .ok_or_else(|| ShellError::State("refresh Agent status before acting".into()))
                    .and_then(|revision| {
                        runtime.execute_fleet_lifecycle(&agent, operation, revision)
                    })
                    .map(|()| "Agent action submitted. Refreshing its actual status.".to_owned())
            } else {
                runtime.inspect_fleet_lifecycle_receipt().map(|terminal| {
                    if terminal {
                        "The original action has a final receipt. Refreshing actual status."
                    } else {
                        "The original action remains unconfirmed; a new action is blocked."
                    }
                    .to_owned()
                })
            };
            Ok(UiTaskOutput::FleetLifecycle {
                message: result.unwrap_or_else(|error| error.to_string()),
                pending: runtime.fleet_lifecycle_pending(),
            })
        });
    }
}
