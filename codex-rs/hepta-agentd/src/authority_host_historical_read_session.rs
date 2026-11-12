//! Install and seal exactly one final historical purpose in the actual
//! registered Root service. No legacy learning owner is opened or upgraded.

use codex_hepta_memory::CognitiveCheckpointPeerLifetime;

use super::*;
use crate::root_historical_task_read_protocol::HistoricalTaskReadBootstrapV1;
use crate::root_historical_task_read_protocol::RootHistoricalTaskReadOfferV1;

impl PreparedHostAuthoritySession {
    pub fn enable_original_historical_task_read_from_deployment(
        &mut self,
        path: &Path,
    ) -> io::Result<()> {
        original_root()?;
        if self.historical_read.is_some() {
            return Err(io::Error::other(
                "original historical route already installed",
            ));
        }
        self.historical_read = Some(HistoricalTaskReadRuntime::open_original(
            path,
            &self.service,
            &self.config,
            &self.registration,
            &self.owner_pidfd,
        )?);
        Ok(())
    }

    pub fn seal_original_historical_task_read(&self) -> io::Result<RootHistoricalTaskReadOfferV1> {
        original_root()?;
        let runtime = self
            .historical_read
            .as_ref()
            .ok_or_else(|| io::Error::other("original complete historical deployment missing"))?;
        runtime
            .phase
            .compare_exchange(PREPARED, SEALED, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| io::Error::other("original historical offer already consumed"))?;
        let result = self.service.with_learning_profile(
            &self.config,
            &self.registration,
            &self.owner_pidfd,
            &runtime.deployment.initial,
            |_, proof| {
                runtime.metadata.require_metadata_unchanged()?;
                runtime.profile.require_original_context(
                    &self.registration.registered_identity.identity()?,
                    &proof,
                    &runtime.deployment.initial,
                )?;
                let stat = std::fs::read_to_string("/proc/self/stat")?;
                let start = stat
                    .rsplit_once(") ")
                    .and_then(|(_, fields)| fields.split_whitespace().nth(19))
                    .and_then(|value| value.parse::<u64>().ok())
                    .filter(|value| *value != 0)
                    .ok_or_else(|| io::Error::other("missing original Root process identity"))?;
                let bundle = HistoricalTaskReadBootstrapV1 {
                    schema: 1,
                    purpose: PURPOSE.into(),
                    root: CognitiveCheckpointPeerLifetime {
                        uid: 0,
                        pid: std::process::id(),
                        boot_id: self.registration.boot_id.clone(),
                        process_start_ticks: start,
                    },
                    consumer: CognitiveCheckpointPeerLifetime {
                        uid: self.config.peer_uid,
                        pid: self.registration.peer_pid,
                        boot_id: self.registration.boot_id.clone(),
                        process_start_ticks: self.registration.process_start_ticks,
                    },
                    identity: self.registration.registered_identity.clone(),
                    initial: runtime.deployment.initial.clone(),
                    profile: runtime.profile.clone(),
                    socket: runtime.socket.clone(),
                };
                let bytes = serde_json::to_vec(&bundle).map_err(io::Error::other)?;
                let bootstrap = crate::authority_host_bootstrap_seal::seal_bytes(&bytes)?;
                runtime.metadata.require_metadata_unchanged()?;
                Ok(RootHistoricalTaskReadOfferV1 { bootstrap })
            },
        );
        if result.is_err() {
            runtime.phase.store(STOPPED, Ordering::Release);
        }
        result
    }
}
