//! Only the original purpose-bound file transfer plus a live Root lane can
//! construct the factory used by ordinary Model dispatch.

use std::io::Read;
use std::io::Seek;
use std::time::Duration;
use std::time::Instant;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdRootAuthorityPeer;
use crate::AgentdRootLearningInputsV1;
use crate::AgentdRootProductionInputs;
use crate::AgentdRootQ24ModelFactoryV1;
use crate::RootQ24ModelFactoryHandoffV1;
use crate::authority_host_service::q24_model::Q24ModelFactoryBootstrap;
use crate::root_observation_stream::RootObservationStream;

impl RootQ24ModelFactoryHandoffV1 {
    pub(crate) async fn connect(
        self,
        production: &AgentdRootProductionInputs,
        learning: &AgentdRootLearningInputsV1,
        identity: &AgentdIdentity,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<AgentdRootQ24ModelFactoryV1, AgentdError> {
        if timeout.is_zero()
            || timeout > Duration::from_millis(500)
            || lifetime.is_zero()
            || lifetime > Duration::from_secs(300)
        {
            return Err(refused("bounded original factory timing required"));
        }
        self.connect_until(
            production,
            learning,
            identity,
            timeout,
            Instant::now() + lifetime,
        )
        .await
    }

    pub(crate) async fn connect_until(
        mut self,
        production: &AgentdRootProductionInputs,
        learning: &AgentdRootLearningInputsV1,
        identity: &AgentdIdentity,
        timeout: Duration,
        end: Instant,
    ) -> Result<AgentdRootQ24ModelFactoryV1, AgentdError> {
        if timeout.is_zero()
            || timeout > Duration::from_millis(500)
            || remaining(end)? > Duration::from_secs(300)
        {
            return Err(refused("bounded original factory timing required"));
        }
        let length = self.bootstrap.metadata()?.len();
        if length == 0 || length > crate::HOST_AUTHORITY_BOOTSTRAP_BOUND as u64 {
            return Err(refused("factory descriptor exceeds its bound"));
        }
        crate::authority_host_bootstrap_seal::validate_sealed(&self.bootstrap, length)?;
        self.bootstrap.rewind()?;
        let mut bytes = Vec::with_capacity(length as usize);
        self.bootstrap
            .by_ref()
            .take(length + 1)
            .read_to_end(&mut bytes)?;
        crate::authority_host_bootstrap_seal::validate_sealed(&self.bootstrap, length)?;
        if bytes.len() as u64 != length {
            return Err(refused("factory descriptor length changed"));
        }
        let bundle: Q24ModelFactoryBootstrap = serde_json::from_slice(&bytes)?;
        let original = &production.bootstrap;
        let socket = original
            .sockets
            .observation
            .parent()
            .ok_or_else(|| refused("original Root socket parent missing"))?
            .join(bundle.profile.socket_filename());
        if bundle.root != original.root
            || bundle.consumer != original.consumer
            || bundle.root.pid != self.root_pid
            || bundle.root.uid != 0
            || bundle.identity.identity()? != *identity
            || original.registered_identity.identity()? != *identity
            || bundle.socket_path != socket
        {
            return Err(refused("factory handoff differs from original Root launch"));
        }
        let (initial, scope) = learning.q24_model_scope(identity)?;
        bundle.profile.require_context(
            identity,
            original.writer_proof.sha256()?.as_str(),
            &initial,
            &scope,
        )?;
        bundle.profile.require_files(&self.journal, &self.witness)?;
        let paths = &original.sockets;
        // SAFETY: getegid only observes the current process's kernel credential.
        crate::authority_host_runtime::validate_lane_paths(
            &[
                &paths.observation,
                &paths.issuer,
                &paths.checkpoint,
                &paths.device_frontier,
                &paths.notes_frontier,
                &socket,
            ],
            unsafe { libc::getegid() },
        )?;
        let stream = tokio::time::timeout(
            timeout.min(remaining(end)?),
            tokio::net::UnixStream::connect(&socket),
        )
        .await
        .map_err(|_| refused("factory Root connection timed out"))??;
        remaining(end)?;
        let transport = RootObservationStream::from_stream_until(
            stream.into_std()?,
            AgentdRootAuthorityPeer {
                pid: bundle.root.pid,
                boot_id: bundle.root.boot_id,
                process_start_ticks: bundle.root.process_start_ticks,
            },
            self.root_pidfd,
            timeout,
            end,
        )
        .map_err(|error| refused(format!("factory Root peer: {error}")))?;
        AgentdRootQ24ModelFactoryV1::from_original_handoff(
            transport,
            bundle.profile,
            initial,
            scope,
            identity.spawn_generation,
            self.journal,
            self.witness,
        )
        .await
    }
}

fn remaining(end: Instant) -> Result<Duration, AgentdError> {
    end.checked_duration_since(Instant::now())
        .filter(|value| !value.is_zero())
        .ok_or_else(|| refused("original factory session expired"))
}

fn refused(message: impl Into<String>) -> AgentdError {
    AgentdError::GenerationFenced(message.into())
}
