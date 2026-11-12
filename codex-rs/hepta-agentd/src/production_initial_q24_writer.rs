//! Keep the original protected writer and all actual Root lanes for first A.
//! Circuit execution has no synthetic Android or Notes effect destination.

use std::sync::Arc;
use std::time::Instant;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_memory::ProtectedCognitiveCheckpoint;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdProductionWriterHost;
use crate::AgentdRootAuthoritySession;
use crate::AgentdRootProductionInputs;
use crate::AgentdUnixCognitiveCheckpointTransport;
use crate::AgentdUnixFinalUseGrantProvider;

pub(in crate::production_launcher) struct OriginalWriterAttachment {
    _session: Arc<AgentdRootAuthoritySession>,
    _checkpoint: Arc<ProtectedCognitiveCheckpoint<AgentdUnixCognitiveCheckpointTransport>>,
    _grants: Arc<AgentdUnixFinalUseGrantProvider>,
    _device: FinalUseAuthority,
    _notes: FinalUseAuthority,
}

pub(in crate::production_launcher) async fn attach(
    config: AgentdConfig,
    original: AgentdRootProductionInputs,
    end: Instant,
) -> Result<(AgentdConfig, OriginalWriterAttachment), AgentdError> {
    super::initial_remaining(end)?;
    config.require_unconfigured_production_hosts()?;
    if original.bootstrap.registered_identity.identity()? != *config.identity() {
        return Err(super::refused(
            "Root writer identity differs from Initial A",
        ));
    }
    original.bootstrap.writer.validate()?;
    let session = Arc::new(original.session);
    let authority = session.authority();
    let verifier = session.verifier();
    let writer = &original.bootstrap.writer;
    let require_current = || {
        super::initial_remaining(end)?;
        verifier
            .verify_sender_process_binding(
                &authority,
                &config.identity().agent_id,
                &writer.local_lease_id,
                writer.local_lease_generation,
                config.identity().spawn_generation,
            )
            .map_err(AgentdError::GenerationFenced)
    };
    require_current()?;
    config.retain_root_session(&session)?;
    let (host, checkpoint) = AgentdProductionWriterHost::open_with_protected_recovery(
        &config,
        authority.clone(),
        Arc::clone(&verifier),
        writer.local_lease_id.clone(),
        writer.local_lease_generation,
        original.checkpoint,
    )
    .await?;
    require_current()?;
    let config = config.with_production_writer_host(Arc::new(host))?;
    super::initial_remaining(end)?;
    Ok((
        config,
        OriginalWriterAttachment {
            _session: session,
            _checkpoint: checkpoint,
            _grants: original.grants,
            _device: original.device,
            _notes: original.notes,
        },
    ))
}
