//! Assemble a concrete CURRENT client only from the original sealed Root
//! route, same launch identity and a successful live late-enrollment readback.

use std::io::Read;
use std::io::Seek;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::Digest32;

use crate::AgentdError;
use crate::AgentdRootAuthorityPeer;
use crate::NeuronGenerationCurrentOwnerV1;
use crate::RootGenerationPublicationConnectionV1;
use crate::RootGenerationPublicationHandoffV1;
use crate::authority_host_service::generation_publication::PURPOSE;
use crate::authority_host_service::generation_publication::PublicationBootstrap;
use crate::authority_host_service::generation_publication::SOCKET;
use crate::root_generation_current_client::OriginalPublicationStream;
use crate::root_generation_current_client::RootGenerationCurrentClient;

impl RootGenerationPublicationHandoffV1 {
    /// Trusted embedded hosts pass this actual owner to the existing Q24
    /// publication driver. No caller profile, issuer, grant, CAS or path is
    /// accepted. Original A/B/source and FinalUse owners remain necessary there.
    pub async fn connect(
        mut self,
        connection: RootGenerationPublicationConnectionV1,
        timeout: Duration,
        lifetime: Duration,
    ) -> Result<Arc<NeuronGenerationCurrentOwnerV1>, AgentdError> {
        // SAFETY: both calls only read the current process's credentials.
        if unsafe { libc::getuid() } == 0
            || unsafe { libc::geteuid() } == 0
            || timeout.is_zero()
            || timeout > Duration::from_millis(500)
            || lifetime.is_zero()
            || lifetime > Duration::from_secs(300)
        {
            return Err(refused(
                "original non-Root consumer and bounded publication timing required",
            ));
        }
        connection.require_original_publication_session()?;
        let end = Instant::now() + lifetime;
        let size = self.bootstrap.metadata()?.len();
        if size == 0 || size > crate::HOST_AUTHORITY_BOOTSTRAP_BOUND as u64 {
            return Err(refused("publication bootstrap bound"));
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
            return Err(refused("publication bootstrap changed"));
        }
        let bundle: PublicationBootstrap = serde_json::from_slice(&raw)?;
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
            || [&bundle.initial, &bundle.scope, &bundle.writer]
                .iter()
                .any(|value| {
                    !value
                        .parse::<Digest32>()
                        .is_ok_and(|digest| !digest.is_zero() && digest.to_string() == **value)
                })
        {
            return Err(refused(
                "publication route differs from original Root launch",
            ));
        }
        codex_hepta_types::StableId::new(&bundle.learning_operation)
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
            .map_err(|_| refused("publication Root connection timed out"))??;
        let remaining = end
            .checked_duration_since(Instant::now())
            .filter(|value| !value.is_zero())
            .ok_or_else(|| refused("publication route expired"))?;
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
            let client = RootGenerationCurrentClient::from_original_stream(
                original,
                &bundle,
                &bundle.learning_operation,
                connection,
            )?;
            NeuronGenerationCurrentOwnerV1::from_original_root_publication(client).map(Arc::new)
        })
        .await
        .map_err(|_| refused("publication connect worker lost"))?
    }
}

fn refused(message: impl Into<String>) -> AgentdError {
    AgentdError::GenerationFenced(message.into())
}
