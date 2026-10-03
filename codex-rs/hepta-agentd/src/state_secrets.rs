//! Secrets admission shares the actual generation/readiness/drain guard.
use super::*;
use crate::AgentdMethod;
use crate::AgentdPayload;

impl AgentdState {
    pub(crate) fn secrets_capability_available(&self) -> bool {
        #[cfg(target_os = "linux")]
        {
            self.secrets_host.get().is_some_and(|host| !host.closed())
        }
        #[cfg(not(target_os = "linux"))]
        {
            false
        }
    }
    pub(crate) fn pending_secrets_workers(&self) -> u32 {
        #[cfg(target_os = "linux")]
        {
            self.secrets_host
                .get()
                .map_or(0, |host| host.pending_workers())
        }
        #[cfg(not(target_os = "linux"))]
        {
            0
        }
    }
    pub(crate) async fn secrets_original(
        &self,
        method: AgentdMethod,
    ) -> Result<AgentdPayload, AgentdError> {
        #[cfg(target_os = "linux")]
        {
            // Keep the runtime guard through physical worker reservation. Drain
            // cannot publish an empty cut between admission and tracked dispatch.
            let receiver = {
                self.refresh_generation()?;
                let runtime = self.runtime.lock().map_err(poisoned_state)?;
                if runtime.fenced
                    || (matches!(method, AgentdMethod::SecretsConsumeOriginal { .. })
                        && (runtime.lifecycle != AgentLifecycle::Running
                            || !runtime.app_server_ready
                            || !runtime.critical_stores_ready
                            || !runtime.revocation_ready
                            || !runtime.required_ports_ready
                            || !runtime.admission_open))
                {
                    return Err(AgentdError::GenerationFenced(
                        "secrets effect admission is closed for this Agent generation".into(),
                    ));
                }
                self.secrets_host
                    .get()
                    .ok_or_else(|| {
                        AgentdError::Protocol(
                            "this Agent has no Root-enrolled secrets runtime client".into(),
                        )
                    })?
                    .dispatch(method)?
            };
            let observation = receiver.await.map_err(|_| {
                AgentdError::Protocol(
                    "secrets original remains Unknown; only original Status/Recover is permitted"
                        .into(),
                )
            })?;
            Ok(AgentdPayload::SecretsOriginal(observation))
        }
        #[cfg(not(target_os = "linux"))]
        {
            let _ = method;
            Err(AgentdError::Protocol(
                "protected secrets capability is unavailable on this platform".into(),
            ))
        }
    }
}
