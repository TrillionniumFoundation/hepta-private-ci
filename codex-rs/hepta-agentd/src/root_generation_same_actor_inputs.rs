//! Distinct Initial and post-join CURRENT purposes on the SAME actual phase.
//! Only original Root-sealed handoffs and the original live verifier enter.
//! Legacy constructors are not changed and neither purpose renews a deadline.

use super::*;
use std::sync::Arc;

use crate::NeuronGenerationCurrentOwnerV1;
use crate::RootGenerationPublicationHandoffV1;
use crate::authority_host_service::generation_publication::PublicationBootstrap;
use crate::root_generation_current_client::RootGenerationCurrentClient;
use crate::root_production_inputs::same_actor_phase::OriginalSameActorRootContext;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;
use crate::same_actor_q24_phase_protocol::OriginalScopedPhaseBootstrap;

impl RootGenerationInitialHandoffV1 {
    pub(crate) fn connect_original_same_actor_initial(
        mut self,
        connection: RootGenerationPublicationConnectionV1,
        context: Arc<OriginalSameActorRootContext>,
        timeout: Duration,
    ) -> impl std::future::Future<Output = Result<OriginalRootGenerationInitialV1, AgentdError>>
    {
        let mut closing = CloseSameActorPhaseOnDrop::new(context.gate());
        async move {
            OriginalSameActorRootContext::require_current(&context)?;
            connection.require_same_successor_session(context.successor_session().as_ref())?;
            let lifetime = context.gate().require_open()?;
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
            let end = context.gate().deadline().instant();
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
                || serde_json::to_vec(&bundle.deployment)?
                    != serde_json::to_vec(&context.descriptor().original.initial)?
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
            OriginalSameActorRootContext::require_current(&context)?;
            let stream = tokio::time::timeout(
                timeout.min(context.gate().require_open()?),
                tokio::net::UnixStream::connect(&socket),
            )
            .await
            .map_err(|_| refused("initial publication Root connection timed out"))??;
            OriginalSameActorRootContext::require_current(&context)?;
            if Instant::now() >= end {
                return Err(refused("initial publication route expired"));
            }
            let original = OriginalPublicationStream::from_original_initial_phase_stream_until(
                stream.into_std()?,
                self.root_pidfd,
                AgentdRootAuthorityPeer {
                    pid: bundle.root.pid,
                    boot_id: bundle.root.boot_id.clone(),
                    process_start_ticks: bundle.root.process_start_ticks,
                },
                timeout,
                context.gate(),
                Arc::clone(context.initial_lifetime()),
            )?;
            // Only observation occurs during bootstrap. Cancellation discards the
            // result and original stream; it never starts a CURRENT mutation.
            let worker_context = Arc::clone(&context);
            let result = tokio::task::spawn_blocking(move || {
                OriginalSameActorRootContext::require_current(&worker_context)?;
                connection.require_original_publication_session()?;
                let client = RootGenerationInitialClient::from_original_initial_stream(
                    original, &bundle, connection,
                )?;
                OriginalSameActorRootContext::require_current(&worker_context)?;
                Ok::<_, AgentdError>(OriginalRootGenerationInitialV1 { client })
            })
            .await
            .map_err(|_| refused("initial publication connect worker lost"))??;
            OriginalSameActorRootContext::require_current(&context)?;
            closing.disarm();
            Ok(result)
        }
    }
}

impl RootGenerationPublicationHandoffV1 {
    pub(crate) fn connect_original_same_actor_publication(
        mut self,
        connection: RootGenerationPublicationConnectionV1,
        context: Arc<OriginalSameActorRootContext>,
        scoped: OriginalScopedPhaseBootstrap,
        timeout: Duration,
    ) -> impl std::future::Future<Output = Result<Arc<NeuronGenerationCurrentOwnerV1>, AgentdError>>
    {
        let mut closing = CloseSameActorPhaseOnDrop::new(context.gate());
        async move {
            OriginalSameActorRootContext::require_current(&context)?;
            connection.require_same_successor_session(context.successor_session().as_ref())?;
            if scoped.original != *context.descriptor()
                || scoped.phase != context.descriptor().phase
                || scoped.purpose != crate::same_actor_q24_phase_protocol::SCOPED_PURPOSE
            {
                return Err(refused(
                    "scoped CURRENT purpose differs from the original phase",
                ));
            }
            let lifetime = context.gate().require_open()?;
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
            let end = context.gate().deadline().instant();
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
            let expected_initial = scoped
                .learning
                .require_binding(identity, original.writer_proof.sha256()?.as_str())?;
            let expected_scope = scoped.learning.require_cell_scope(&expected_initial)?;
            let socket = original
                .sockets
                .observation
                .parent()
                .ok_or_else(|| refused("original Root socket parent missing"))?
                .join(crate::authority_host_service::generation_publication::SOCKET);
            if bundle.purpose != crate::authority_host_service::generation_publication::PURPOSE
                || bundle.root != original.root
                || bundle.consumer != original.consumer
                || bundle.root.pid != self.root_pid
                || bundle.root.uid != 0
                || bundle.identity.identity()? != *identity
                || original.registered_identity.identity()? != *identity
                || bundle.writer != original.writer_proof.sha256()?.as_str()
                || bundle.socket != socket
                || bundle.initial != expected_initial.head_digest.to_string()
                || bundle.scope != expected_scope.binding().to_string()
                || bundle.learning_operation != expected_initial.request.operation_id.to_string()
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
            OriginalSameActorRootContext::require_current(&context)?;
            let stream = tokio::time::timeout(
                timeout.min(context.gate().require_open()?),
                tokio::net::UnixStream::connect(&socket),
            )
            .await
            .map_err(|_| refused("publication Root connection timed out"))??;
            OriginalSameActorRootContext::require_current(&context)?;
            if Instant::now() >= end {
                return Err(refused("publication route expired"));
            }
            let original = OriginalPublicationStream::from_original_scoped_phase_stream_until(
                stream.into_std()?,
                self.root_pidfd,
                AgentdRootAuthorityPeer {
                    pid: bundle.root.pid,
                    boot_id: bundle.root.boot_id.clone(),
                    process_start_ticks: bundle.root.process_start_ticks,
                },
                timeout,
                context.gate(),
            )?;
            // Only observation occurs during bootstrap. Cancellation discards the
            // result and original stream; it never starts a CURRENT mutation.
            let worker_context = Arc::clone(&context);
            let result = tokio::task::spawn_blocking(move || {
                OriginalSameActorRootContext::require_current(&worker_context)?;
                connection.require_original_publication_session()?;
                let client = RootGenerationCurrentClient::from_original_stream(
                    original,
                    &bundle,
                    &bundle.learning_operation,
                    connection,
                )?;
                let owner = NeuronGenerationCurrentOwnerV1::from_original_root_publication(client)
                    .map(Arc::new)?;
                OriginalSameActorRootContext::require_current(&worker_context)?;
                Ok::<_, AgentdError>(owner)
            })
            .await
            .map_err(|_| refused("publication connect worker lost"))??;
            OriginalSameActorRootContext::require_current(&context)?;
            closing.disarm();
            Ok(result)
        }
    }
}
