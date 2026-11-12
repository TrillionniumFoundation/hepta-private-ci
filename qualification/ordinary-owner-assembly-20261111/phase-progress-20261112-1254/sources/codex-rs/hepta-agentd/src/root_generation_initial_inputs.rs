//! Connect the independent initial-purpose route from the original sealed
//! handoff and live five-lane session. No CURRENT is prepared by observation.

use std::io::Read;
use std::io::Seek;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::Digest32;

use crate::AgentdError;
use crate::AgentdRootAuthorityPeer;
use crate::RootGenerationInitialHandoffV1;
use crate::RootGenerationPublicationConnectionV1;

/// Same original Root route before any initial CURRENT exists. It is not
/// Clone or deserializable; the distinct initial preparation consumes it.
pub struct OriginalRootGenerationInitialV1 {
    pub(crate) client: RootGenerationInitialClient,
}
use crate::authority_host_service::generation_initial::InitialBootstrap;
use crate::authority_host_service::generation_initial::PURPOSE;
use crate::authority_host_service::generation_initial::SOCKET;
use crate::root_generation_current_client::OriginalPublicationStream;
use crate::root_generation_initial_client::RootGenerationInitialClient;

impl RootGenerationInitialHandoffV1 {
    /// Receive the exact deployment profile from the same original Root. No
    /// initial grant, nonce owner, CURRENT or task completion is manufactured.
    pub async fn connect(
        mut self,
        connection: RootGenerationPublicationConnectionV1,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<OriginalRootGenerationInitialV1, AgentdError> {
        // SAFETY: both calls only read the current process's credentials.
        if unsafe { libc::getuid() } == 0
            || unsafe { libc::geteuid() } == 0
            || timeout.is_zero()
            || timeout > Duration::from_millis(500)
            || lifetime.is_zero()
            || lifetime > Duration::from_secs(300)
        {
            return Err(refused(
                "original non-Root consumer and bounded initial publication timing required",
            ));
        }
        connection.require_original_publication_session()?;
        let end = Instant::now() + lifetime;
        let size = self.bootstrap.metadata()?.len();
        if size == 0 || size > crate::HOST_AUTHORITY_BOOTSTRAP_BOUND as u64 {
            return Err(refused("initial publication bootstrap bound"));
        }
        crate::authority_host_bootstrap_seal::validate_sealed(&self.bootstrap, size)?;
        self.bootstrap.rewind()?;
        let mut raw = Vec::with_capacity(size as usize);
        self.bootstrap
            .by_ref()
            .take(size + 1)
            .read_to_end(&mut raw)?;
        crate::authority_host_bootstrap_seal::validate_sealed(&self.bootstrap, size)?;
        if raw.len() as u64 != size {
            return Err(refused("initial publication bootstrap changed"));
        }
        let bundle: InitialBootstrap = serde_json::from_slice(&raw)?;
        let (original, identity) = connection.original_launch_binding();
        let socket = original
            .sockets
            .observation
            .parent()
            .ok_or_else(|| refused("original Root socket parent missing"))?
            .join(SOCKET);
        if bundle.purpose != PURPOSE
            || bundle.root != original.root
            || bundle.consumer != original.consumer
            || bundle.root.pid != self.root_pid
            || bundle.root.uid != 0
            || bundle.identity.identity()? != *identity
            || original.registered_identity.identity()? != *identity
            || bundle.writer != original.writer_proof.sha256()?.as_str()
            || bundle.socket != socket
            || !bundle
                .writer
                .parse::<Digest32>()
                .is_ok_and(|digest| !digest.is_zero() && digest.to_string() == bundle.writer)
            || bundle.deployment.target.scope().agent_id != identity.agent_id.as_str()
        {
            return Err(refused(
                "initial publication route differs from original Root launch",
            ));
        }
        codex_hepta_types::StableId::new(&bundle.deployment.operation)
            .map_err(|error| refused(error.to_string()))?;
        let paths = &original.sockets;
        // SAFETY: getegid only observes the actual current credential.
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
        connection.require_original_publication_session()?;
        let stream = tokio::time::timeout(timeout, tokio::net::UnixStream::connect(&socket))
            .await
            .map_err(|_| refused("initial publication Root connection timed out"))??;
        let remaining = end
            .checked_duration_since(Instant::now())
            .filter(|value| !value.is_zero())
            .ok_or_else(|| refused("initial publication route expired"))?;
        let original = OriginalPublicationStream::from_stream(
            stream.into_std()?,
            self.root_pidfd,
            AgentdRootAuthorityPeer {
                pid: bundle.root.pid,
                boot_id: bundle.root.boot_id.clone(),
                process_start_ticks: bundle.root.process_start_ticks,
            },
            timeout,
            remaining,
        )?;
        // Only observation occurs during bootstrap. Cancellation discards the
        // result and original stream; it never starts a CURRENT mutation.
        tokio::task::spawn_blocking(move || {
            connection.require_original_publication_session()?;
            let client = RootGenerationInitialClient::from_original_initial_stream(
                original, &bundle, connection,
            )?;
            Ok(OriginalRootGenerationInitialV1 { client })
        })
        .await
        .map_err(|_| refused("initial publication connect worker lost"))?
    }
}

fn refused(message: impl Into<String>) -> AgentdError {
    AgentdError::GenerationFenced(message.into())
}

#[path = "root_generation_same_actor_inputs.rs"]
mod same_actor_phase;
