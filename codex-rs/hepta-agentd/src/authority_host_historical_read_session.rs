//! Install and seal exactly one final historical purpose in the actual
//! registered Root service. No legacy learning owner is opened or upgraded.

use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use std::os::unix::net::UnixDatagram;

use super::*;
use crate::root_historical_task_read_protocol::HistoricalTaskReadBootstrapV1;
use crate::root_historical_task_read_protocol::RootHistoricalTaskReadOfferV1;

impl PreparedHostAuthoritySession {
    /// Retain the protected post-A plan and two original anonymous handoffs
    /// before sealing the historical route. Registration remains a late action.
    pub fn enable_original_post_a_learning_from_deployment(
        &mut self,
        path: &Path,
        learning_handoff: UnixDatagram,
        model_handoff: UnixDatagram,
        root_pidfd: OwnedFd,
        publication: Option<(&Path, UnixDatagram)>,
    ) -> io::Result<()> {
        Self::enable_original_post_a_learning_with_independent_b(
            self,
            path,
            learning_handoff,
            model_handoff,
            root_pidfd,
            publication,
            None,
        )
    }

    /// The full ordinary path retains a separate original B deployment and
    /// datagram before any learning work. Legacy callers keep the former entry.
    pub fn enable_original_post_a_learning_with_independent_b(
        &mut self,
        path: &Path,
        learning_handoff: UnixDatagram,
        model_handoff: UnixDatagram,
        root_pidfd: OwnedFd,
        publication: Option<(&Path, UnixDatagram)>,
        independent_evaluation: Option<(&Path, UnixDatagram)>,
    ) -> io::Result<()> {
        original_root()?;
        if independent_evaluation.is_some() && publication.is_none() {
            return Err(io::Error::other(
                "original independent B requires the original publication route",
            ));
        }
        if self.learning.is_some() || self.publication.is_some() {
            return Err(io::Error::other(
                "post-A owners cannot replace eager learning",
            ));
        }
        let runtime = self.historical_read.as_mut().ok_or_else(|| {
            io::Error::other("original historical route required before post-A setup")
        })?;
        if runtime.phase.load(Ordering::Acquire) != PREPARED
            || runtime.post_a.is_some()
            || runtime.post_a_worker.is_some()
            || runtime
                .post_a_submitter
                .get_mut()
                .map_err(|_| io::Error::other("original post-A submission slot poisoned"))?
                .is_some()
        {
            return Err(io::Error::other("original post-A setup already consumed"));
        }
        let plan = self.service.with_learning_profile(
            &self.config,
            &self.registration,
            &self.owner_pidfd,
            &runtime.deployment.initial,
            |initial, proof| {
                runtime.metadata.require_metadata_unchanged()?;
                let expected = HistoricalTaskReadProfileV1::require_original_context(
                    &runtime.profile,
                    &self.registration.registered_identity.identity()?,
                    &proof,
                    &runtime.deployment.initial,
                )?;
                if expected != initial {
                    return Err(io::Error::other(
                        "original post-A initial recipient changed",
                    ));
                }
                RootHistoricalLearningTrustV1::revalidate(
                    &runtime.learning_trust,
                    &self.service,
                    &initial,
                )?;
                let plan = post_a::PostALearningRuntime::retain_original_plan(
                    path,
                    &initial,
                    &runtime.deployment.target,
                    self.config.peer_uid,
                    self.config.peer_gid,
                    publication.as_ref().map(|(path, _)| *path),
                    independent_evaluation.as_ref().map(|(path, _)| *path),
                )?;
                runtime.metadata.require_metadata_unchanged()?;
                RootHistoricalLearningTrustV1::revalidate(
                    &runtime.learning_trust,
                    &self.service,
                    &initial,
                )?;
                Ok(plan)
            },
        )?;
        let (submitter, worker) = post_a_worker::prepare(
            learning_handoff,
            model_handoff,
            root_pidfd,
            publication.map(|(_, handoff)| handoff),
            independent_evaluation.map(|(_, handoff)| handoff),
        )?;
        runtime.post_a = Some(plan);
        runtime.post_a_worker = Some(worker);
        *runtime
            .post_a_submitter
            .get_mut()
            .map_err(|_| io::Error::other("original post-A submission slot poisoned"))? =
            Some(submitter);
        Ok(())
    }

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
        let runtime: &HistoricalTaskReadRuntime = self
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
