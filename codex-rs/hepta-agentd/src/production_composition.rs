//! Atomic registration of the original recovered writer and operation runtime.

use std::os::unix::net::UnixDatagram;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_cognitive_store::CognitiveRecoveryRequirement;
use codex_hepta_cognitive_store::ProductionAuthorityLease;
use codex_hepta_cognitive_store::ProductionAuthorityVerifier;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_memory::FinalUseProductionOutboxTarget;
use codex_hepta_memory::NotesTargetIdentity;
use codex_hepta_memory::ObjectiveSenderCheckpoint;
use codex_hepta_memory::ProductionObjectiveSender;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdFinalUseHostInputs;
use crate::AgentdFinalUseIssuerPeer;
use crate::AgentdProductionOperationRuntimeConfig;
use crate::AgentdProductionWriterHost;
use crate::AgentdUnixFinalUseGrantProvider;

/// Complete host-owned input set. The current cut must already be independently
/// retained and authenticated before recovery; this composition never derives
/// that initial authorization from the database being recovered. The same
/// independently protected checkpoint must acknowledge the live post-recovery
/// cut and remain attached to the returned restricted sender capability.
/// The authority lease/verifier, protected FinalUse inputs, private issuer
/// descriptor, and original destination are not discovered from local files or
/// environment variables. No grant is accepted or requested during bootstrap.
pub struct AgentdProductionHostInputs<'a, C: ObjectiveSenderCheckpoint> {
    pub current_cut: CognitiveRecoveryRequirement<'a>,
    pub checkpoint: Arc<C>,
    pub checkpoint_deadline: Duration,
    pub authority: ProductionAuthorityLease,
    pub verifier: Arc<dyn ProductionAuthorityVerifier>,
    pub lease_id: String,
    pub lease_generation: u64,
    pub final_use: AgentdFinalUseHostInputs,
    pub issuer_stream: UnixStream,
    pub issuer_peer: AgentdFinalUseIssuerPeer,
    pub issuer_timeout: Duration,
    pub target: Arc<dyn FinalUseProductionOutboxTarget>,
    pub reconcile_interval: Duration,
    pub notes: Option<AgentdProductionNotesInputs>,
}

/// Successful strict composition. The canonical embedding uses this sender,
/// bound to the same original writer and checkpoint Arc used for bootstrap.
/// The optional Notes identity is returned only after both handles install;
/// neither value claims that a runtime, Objective or effect has started.
pub struct AgentdProductionHostAttachment<C: ObjectiveSenderCheckpoint> {
    pub notes_identity: Option<NotesTargetIdentity>,
    pub original_sender: ProductionObjectiveSender<C>,
}

/// Optional original Session handoff, with independently supplied Notes trust.
/// The inherited descriptor is consumed by the existing one-shot receiver.
pub struct AgentdProductionNotesInputs {
    pub bootstrap: UnixDatagram,
    pub final_use: AgentdFinalUseHostInputs,
}

// Keep the same protected clock in every original writer/runtime authority
// check, including checks made after bootstrap. The original verifier remains
// responsible for the grant, scope, epoch, revocation and opaque token.
struct ProtectedClockVerifier {
    inner: Arc<dyn ProductionAuthorityVerifier>,
    clock: Arc<dyn AuthorityClock>,
}

impl ProtectedClockVerifier {
    fn verify_clock(&self, authority: &ProductionAuthorityLease) -> Result<(), String> {
        let now = self
            .clock
            .now_unix_ms()
            .map_err(|_| "protected authority clock is unavailable".to_string())?;
        if authority.is_expired_at(now / 1_000) {
            return Err("production authority expired on the protected clock".to_string());
        }
        Ok(())
    }
}

impl ProductionAuthorityVerifier for ProtectedClockVerifier {
    fn verify(
        &self,
        authority: &ProductionAuthorityLease,
        expected_agent: &AgentId,
    ) -> Result<(), String> {
        self.verify_clock(authority)?;
        self.inner.verify(authority, expected_agent)?;
        // The external verifier may itself block. Recheck after it returns.
        self.verify_clock(authority)
    }
}

impl AgentdConfig {
    /// Obtain the restricted Objective sender from the installed original owner.
    /// The trusted embedding must supply an independent current-cut checkpoint;
    /// no default checkpoint, new writer, database open or transport is created.
    /// This remains an explicit trusted-embedding compatibility entry point.
    /// Strict composition uses the returned attachment's already-bound sender.
    pub fn original_objective_sender<C: ObjectiveSenderCheckpoint>(
        &self,
        checkpoint: Arc<C>,
        deadline: Duration,
    ) -> Result<ProductionObjectiveSender<C>, AgentdError> {
        let host = self
            .production_writer_host()
            .ok_or(AgentdError::CognitiveWriteRuntimeUnavailable)?;
        let writer = host.writer();
        if writer.owner_agent_id() != &self.identity().agent_id
            || writer.generation() != self.identity().spawn_generation
        {
            return Err(AgentdError::GenerationFenced(
                "Objective sender owner differs from installed Agentd identity".to_string(),
            ));
        }
        writer
            .objective_sender(checkpoint, deadline)
            .map_err(|error| {
                AgentdError::Invalid(format!("original Objective sender unavailable: {error}"))
            })
    }
}

/// Build against the original owners and install both handles only on success.
/// A failure leaves `config` unchanged. Original durable recovery/authority
/// writes are never deleted or rolled back: a later retry still needs current
/// independent recovery authorization. No runtime or effect starts here.
pub async fn attach_production_operation_host<C: ObjectiveSenderCheckpoint>(
    config: &mut AgentdConfig,
    inputs: AgentdProductionHostInputs<'_, C>,
) -> Result<AgentdProductionHostAttachment<C>, AgentdError> {
    config.require_unconfigured_production_hosts()?;
    if inputs.checkpoint_deadline.is_zero() || inputs.checkpoint_deadline > Duration::from_secs(5) {
        return Err(AgentdError::Invalid(
            "production checkpoint requires a positive deadline of at most five seconds"
                .to_string(),
        ));
    }
    match &inputs.current_cut {
        CognitiveRecoveryRequirement::Revoked => {
            return Err(AgentdError::GenerationFenced(
                "production current-cut authorization is revoked".to_string(),
            ));
        }
        CognitiveRecoveryRequirement::ExactCurrentCut(anchor)
            if anchor.owner_agent_id != config.identity().agent_id =>
        {
            return Err(AgentdError::GenerationFenced(
                "production current cut belongs to another Agent".to_string(),
            ));
        }
        CognitiveRecoveryRequirement::ExactCurrentCut(_) => {}
    }
    if inputs.lease_generation != config.identity().spawn_generation
        || inputs.lease_generation == 0
        || inputs.lease_id.trim().is_empty()
        || inputs.reconcile_interval.is_zero()
        || inputs.target.destination_id().is_empty()
    {
        return Err(AgentdError::Invalid(
            "production composition requires exact generation and non-empty lease/destination/interval"
                .to_string(),
        ));
    }
    if inputs.authority.agent_id != config.identity().agent_id {
        return Err(AgentdError::GenerationFenced(
            "production authority belongs to another Agent".to_string(),
        ));
    }
    if inputs.authority.fencing_token_digest().is_err() {
        return Err(AgentdError::GenerationFenced(
            "production authority lacks its original token".to_string(),
        ));
    }
    let verifier: Arc<dyn ProductionAuthorityVerifier> = Arc::new(ProtectedClockVerifier {
        inner: inputs.verifier,
        clock: Arc::clone(&inputs.final_use.clock),
    });
    verifier
        .verify(&inputs.authority, &config.identity().agent_id)
        .map_err(AgentdError::GenerationFenced)?;
    let grants = AgentdUnixFinalUseGrantProvider::from_stream(
        inputs.issuer_stream,
        inputs.issuer_peer,
        inputs.issuer_timeout,
    )
    .map_err(|error| AgentdError::Protocol(format!("final-use issuer transport: {error}")))?;
    let final_use = inputs.final_use.open().map_err(|error| {
        AgentdError::Protocol(format!("protected final-use authority: {error}"))
    })?;
    let operations = AgentdProductionOperationRuntimeConfig::new(
        inputs.authority.clone(),
        Arc::clone(&verifier),
        inputs.lease_id.clone(),
        inputs.lease_generation,
        final_use,
        inputs.target,
        Arc::new(grants),
        inputs.reconcile_interval,
    );
    operations.validate_for(config)?;
    let recovered_host = Arc::new(
        AgentdProductionWriterHost::open_with_recovery(
            config,
            inputs.current_cut,
            inputs.authority,
            verifier,
            inputs.lease_id,
            inputs.lease_generation,
        )
        .await?,
    );
    operations.validate_recovered_host(&recovered_host).await?;
    let (operations, notes_identity) = if let Some(notes) = inputs.notes {
        let notes_final_use = notes.final_use.open().map_err(|error| {
            AgentdError::Protocol(format!("protected Notes final-use authority: {error}"))
        })?;
        let (operations, identity) = operations
            .with_notes_from_session(config, &recovered_host, notes.bootstrap, notes_final_use)
            .await?;
        (operations, Some(identity))
    } else {
        (operations, None)
    };
    let writer = recovered_host.writer();
    // The lease acquired by the original recovered writer changes its exact
    // cut. Publish that live cut without creating a synthetic Objective. Notes
    // attached is a descriptor ACK, not a CognitiveStore row in this cut.
    writer
        .checkpoint_current(inputs.checkpoint.as_ref(), inputs.checkpoint_deadline)
        .await
        .map_err(|error| {
            AgentdError::Invalid(format!("production current-cut checkpoint: {error}"))
        })?;
    let original_sender = writer
        .objective_sender(inputs.checkpoint, inputs.checkpoint_deadline)
        .map_err(|error| {
            AgentdError::Invalid(format!("original Objective sender unavailable: {error}"))
        })?;
    config.install_production_hosts(recovered_host, operations)?;
    // A handoff ACK can precede a final live-authority refusal. Only return
    // this identity after both original handles were installed successfully.
    Ok(AgentdProductionHostAttachment {
        notes_identity,
        original_sender,
    })
}

#[cfg(test)]
#[path = "production_composition_fixture.rs"]
mod fixture;

#[cfg(test)]
#[path = "production_composition_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "production_composition_notes_tests.rs"]
mod notes_tests;

#[cfg(test)]
#[path = "objective_sender_host_tests.rs"]
mod objective_sender_tests;
