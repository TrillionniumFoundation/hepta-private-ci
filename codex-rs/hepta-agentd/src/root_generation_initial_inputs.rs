//! Connect the independent initial-purpose route from the original sealed
//! handoff and live five-lane session. No CURRENT is prepared by observation.

use std::io::Read;
use std::io::Seek;
use std::sync::Arc;
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
    pub(crate) client: Arc<RootGenerationInitialClient>,
}
use crate::authority_host_service::generation_initial::InitialBootstrap;
use crate::authority_host_service::generation_initial::PURPOSE;
use crate::authority_host_service::generation_initial::SOCKET;
use crate::root_generation_current_client::OriginalPublicationStream;
use crate::root_generation_initial_client::RootGenerationInitialClient;

enum OriginalEnrollment {
    RegisteredByRoot,
    ReadyPeer,
}

impl RootGenerationInitialHandoffV1 {
    /// Receive the exact deployment profile from the same original Root. No
    /// initial grant, nonce owner, CURRENT or task completion is manufactured.
    pub async fn connect(
        self,
        connection: RootGenerationPublicationConnectionV1,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<OriginalRootGenerationInitialV1, AgentdError> {
        if lifetime.is_zero() || lifetime > Duration::from_secs(300) {
            return Err(refused("original Initial lifetime exceeds its bound"));
        }
        let end = Instant::now()
            .checked_add(lifetime)
            .ok_or_else(|| refused("original Initial deadline overflow"))?;
        self.connect_until(connection, timeout, end).await
    }

    /// Carry the original launch's absolute end through every file and peer
    /// check. This entry cannot renew time already consumed by startup.
    pub(crate) async fn connect_until(
        self,
        connection: RootGenerationPublicationConnectionV1,
        timeout: Duration,
        end: Instant,
    ) -> Result<OriginalRootGenerationInitialV1, AgentdError> {
        self.connect_original_until(
            connection,
            timeout,
            end,
            OriginalEnrollment::RegisteredByRoot,
        )
        .await
    }

    /// Ask the original Root to validate its pre-held deployment after this
    /// daemon has opened its real nonce and first-A owners. No path is sent.
    pub(crate) async fn connect_ready_until(
        self,
        connection: RootGenerationPublicationConnectionV1,
        timeout: Duration,
        end: Instant,
    ) -> Result<OriginalRootGenerationInitialV1, AgentdError> {
        self.connect_original_until(connection, timeout, end, OriginalEnrollment::ReadyPeer)
            .await
    }

    async fn connect_original_until(
        mut self,
        connection: RootGenerationPublicationConnectionV1,
        timeout: Duration,
        end: Instant,
        enrollment: OriginalEnrollment,
    ) -> Result<OriginalRootGenerationInitialV1, AgentdError> {
        remaining_until(end)?;
        // SAFETY: both calls only read the current process's credentials.
        if unsafe { libc::getuid() } == 0
            || unsafe { libc::geteuid() } == 0
            || timeout.is_zero()
            || timeout > Duration::from_millis(500)
        {
            return Err(refused(
                "original non-Root consumer and bounded initial publication timing required",
            ));
        }
        connection.require_original_publication_session()?;
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
        let stream = tokio::time::timeout(
            timeout.min(remaining_until(end)?),
            tokio::net::UnixStream::connect(&socket),
        )
        .await
        .map_err(|_| refused("initial publication Root connection timed out"))??;
        let original = OriginalPublicationStream::from_stream_until(
            stream.into_std()?,
            self.root_pidfd,
            AgentdRootAuthorityPeer {
                pid: bundle.root.pid,
                boot_id: bundle.root.boot_id.clone(),
                process_start_ticks: bundle.root.process_start_ticks,
            },
            timeout,
            end,
        )?;
        // The selected readiness mode may register Root's exact existing
        // inputs. Cancellation discards this stream and never retries; neither
        // branch prepares or publishes CURRENT during connection.
        tokio::task::spawn_blocking(move || {
            remaining_until(end)?;
            connection.require_original_publication_session()?;
            let client = match enrollment {
                OriginalEnrollment::RegisteredByRoot => {
                    RootGenerationInitialClient::from_original_initial_stream(
                        original, &bundle, connection,
                    )?
                }
                OriginalEnrollment::ReadyPeer => {
                    RootGenerationInitialClient::from_original_ready_stream(
                        original, &bundle, connection,
                    )?
                }
            };
            remaining_until(end)?;
            Ok(OriginalRootGenerationInitialV1 {
                client: Arc::new(client),
            })
        })
        .await
        .map_err(|_| refused("initial publication connect worker lost"))?
    }
}

fn remaining_until(end: Instant) -> Result<Duration, AgentdError> {
    end.checked_duration_since(Instant::now())
        .filter(|remaining| !remaining.is_zero() && *remaining <= Duration::from_secs(300))
        .ok_or_else(|| refused("original Initial absolute deadline expired"))
}

fn refused(message: impl Into<String>) -> AgentdError {
    AgentdError::GenerationFenced(message.into())
}
