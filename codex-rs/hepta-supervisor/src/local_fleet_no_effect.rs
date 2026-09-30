//! This proof is limited to a never-admitted Agent, not a missing live PID.
use std::io::ErrorKind;
use std::path::Path;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;

use super::LocalFleetHost;
use super::host_error;
use super::trust;
use crate::ProcessDriverError;

impl LocalFleetHost {
    pub(crate) fn prove_never_spawned(
        &self,
        agent: &AgentId,
    ) -> Result<Option<Sha256Digest>, ProcessDriverError> {
        self.run(async {
            let _launch = self.launch_gate.lock().await;
            let main = agent.to_string();
            let matrix = format!("matrix:{agent}");
            if self
                .store
                .principal_has_execution_history(&main)
                .await
                .map_err(host_error)?
                || self
                    .store
                    .principal_has_execution_history(&matrix)
                    .await
                    .map_err(host_error)?
            {
                return Ok(None);
            }
            let base = Path::new("/sys/fs/cgroup").join(&self.policy.cgroup_root);
            trust::validate_root_directory(&base)?;
            let group = base.join(format!("agent-{agent}"));
            let events = match std::fs::symlink_metadata(&group) {
                Err(error) if error.kind() == ErrorKind::NotFound => "absent".to_string(),
                Err(error) => return Err(error.into()),
                Ok(_) => {
                    trust::validate_root_directory(&group)?;
                    let events = std::fs::read_to_string(group.join("cgroup.events"))?;
                    if !events.lines().any(|line| line == "populated 0") {
                        return Ok(None);
                    }
                    events
                }
            };
            // Same launch lock prevents a new Prepared row between the SQL
            // absence proof and this root-protected physical observation.
            let bytes = serde_json::to_vec(&(
                "hepta.local-fleet.before-spawn.v1",
                main,
                matrix,
                &self.policy.cgroup_root,
                events,
                std::process::id(),
            ))?;
            Ok(Some(Sha256Digest::for_bytes(&bytes)))
        })?
    }
}
