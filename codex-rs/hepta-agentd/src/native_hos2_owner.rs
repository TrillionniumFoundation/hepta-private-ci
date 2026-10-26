//! Original production owner composed with the actual G2 process-bound device.
//!
//! This explicit native entry seam creates no issuer, lease, consumer journal,
//! Registry generation or replacement writer. The trusted Root launcher must
//! supply its original authenticated five-lane inputs and the descriptor this
//! same native image opened before credential drop. It grants no kernel role.

use std::fs::File;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_cognitive_store::ProductionDurableWriter;
use codex_hepta_memory::Hos2DeliveryId;
use codex_hepta_memory::Hos2InstallBudgetV1;
use codex_hepta_memory::Hos2RetirementObservation;
use codex_hepta_memory::ProductionHos2Target;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdHos2Device;
use crate::AgentdHos2Usage;
use crate::AgentdProductionWriterHost;
use crate::AgentdRootProductionAttachment;
use crate::AgentdRootProductionInputs;

/// Select the exact sealed page supplied by the kernel for this actual image.
/// A successor requires the kernel's version-4 image/generation binding; an
/// initial version-3 page cannot be used to adopt or renew an image grant.
pub enum AgentdG2NativeImage<'a> {
    InitialV3(&'a [u8]),
    SuccessorV4(&'a [u8]),
}

/// Retains the same Root feed, protected checkpoint, original writer and native
/// target for their entire shared lifetime. Dropping this attachment closes
/// those original inputs; it never falls back to an ordinary writable store.
pub struct AgentdG2NativeOperationHost {
    root: AgentdRootProductionAttachment,
    host: Arc<AgentdProductionWriterHost>,
    native: Arc<AgentdHos2Device>,
    target: Arc<ProductionHos2Target>,
}

impl AgentdG2NativeOperationHost {
    /// The retained authenticated Root feed/checkpoint and original consumers.
    pub fn root(&self) -> &AgentdRootProductionAttachment {
        &self.root
    }

    /// The actual host installed atomically in the original Agentd config.
    pub fn host(&self) -> Arc<AgentdProductionWriterHost> {
        Arc::clone(&self.host)
    }

    /// The original durable writer; no raw database or new lease is opened.
    pub fn writer(&self) -> Arc<ProductionDurableWriter> {
        self.host.writer()
    }

    /// Query the actual observer slot in this process's kernel image.
    pub fn read_usage(&self, request_id: u64) -> Result<AgentdHos2Usage, AgentdError> {
        self.native
            .read_usage(request_id)
            .map_err(AgentdError::Protocol)
    }

    /// Form original request bytes before the operation owner persists K/D.
    /// `sequence` must come from that original owner, never a local counter.
    /// Constructing a request does not dispatch it or obtain a FinalUse grant.
    pub fn install_request(
        &self,
        sequence: u64,
        expected_revision: u64,
        cap_ns: u64,
    ) -> Result<Hos2InstallBudgetV1, AgentdError> {
        self.native
            .install_request(sequence, expected_revision, cap_ns)
            .map_err(AgentdError::Invalid)
    }

    /// Retire only through the original writer's independently acknowledged
    /// durable prefix and its retained native history target. This delegates
    /// permit construction, live authority checks and Current barriers to the
    /// original owner. No caller-supplied retirement proof is accepted here.
    pub async fn retire_through(
        &self,
        through: &Hos2DeliveryId,
    ) -> Result<Hos2RetirementObservation, AgentdError> {
        self.host
            .writer()
            .retire_hos2_through(&self.target, through)
            .await
            .map_err(|error| AgentdError::Protocol(format!("original HOS2 retirement: {error}")))
    }
}

/// Attach the actual G2 device to the original protected production composition.
///
/// Device discovery validates the actual PID/parent/image/bootstrap and QueryAbi
/// before opening any writer. The original Root composition retains its live
/// verifier, Current/material recovery and original Device/Notes frontier owners.
/// It publishes both host handles only after every check succeeds. No Notes
/// application channel is installed by this CPU-control-only entry seam.
pub async fn attach_g2_native_operation_host(
    config: &mut AgentdConfig,
    inputs: AgentdRootProductionInputs,
    descriptor: File,
    image: AgentdG2NativeImage<'_>,
) -> Result<AgentdG2NativeOperationHost, AgentdError> {
    config.require_unconfigured_production_hosts()?;
    let native = Arc::new(
        match image {
            AgentdG2NativeImage::InitialV3(page) => {
                AgentdHos2Device::from_g2_initial_bootstrap(descriptor, page)
            }
            AgentdG2NativeImage::SuccessorV4(page) => {
                AgentdHos2Device::from_g2_successor_bootstrap(descriptor, page)
            }
        }
        .map_err(AgentdError::Protocol)?,
    );
    let target = Arc::new(ProductionHos2Target::new(native.clone()));
    let root = crate::attach_root_production_operation_host(
        config,
        inputs,
        target.clone(),
        /*notes_bootstrap*/ None,
        Duration::from_millis(100),
    )
    .await?;
    let host = config
        .production_writer_host()
        .ok_or(AgentdError::CognitiveWriteRuntimeUnavailable)?;
    Ok(AgentdG2NativeOperationHost {
        root,
        host,
        native,
        target,
    })
}
