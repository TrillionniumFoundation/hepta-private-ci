//! Explicit native attachment to the production Agentd owner.
//!
//! The existing ingress selects a persisted ThreadStore turn and QueueStore
//! dispatch. This module creates neither a parallel queue nor a session owner.

use std::sync::Arc;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_memory::FinalUseProductionOutboxTarget;
use codex_hepta_native_agent::{NativeAgent, RunOutcome, TurnState};
use codex_hepta_types::{Digest32, Generation};
use codex_http_client::HttpClientFactory;
use codex_thread_store::{LiveThread, NativeCheckpointBinding, QueueStore};
use tokio_util::sync::CancellationToken;

use crate::{AgentdError, AgentdProductionWriterHost, AgentdState, NativeExecutionBindingV1, NativeQueueDispatch, NativeThreadTurnOwner, NativeToolCompiler, NativeTurnAnchorV1, NativeTurnScope, RunPhase, RunReceipt};
use crate::native_admission::NativeProductionAdmission;
use crate::native_model_target::{NativeResponsesTarget, NativeResponsesTargetConfig};
use crate::native_ports::NativeEntryOwner;
use crate::native_runtime_target::NativeRuntimeTarget;
use crate::intelligence_product::NativeContextBindingV1;
use crate::state::native::NativeActiveTurn;
use crate::state::native::NativeEntryGate;

#[path = "native_host_drive.rs"]
mod drive;
#[path = "native_host_recovery.rs"]
mod recovery;

use drive::NativeDriveMode;

/// Startup inputs from the existing trusted product host. Native destinations
/// share an explicitly selected, already registered final-use authority;
/// this constructor never creates keys, grants, queues, or authority stores.
pub struct AgentdNativeRuntimeConfig {
    pub model: NativeResponsesTargetConfig,
    pub http: Arc<HttpClientFactory>,
    pub runtime_destination: String,
    pub required_hosts: Vec<String>,
    pub max_tool_output_bytes: usize,
    pub policy_generation: Generation,
    /// Existing production destination whose authority both native targets
    /// must share. Empty or unknown sources are rejected before runtime setup.
    pub final_use_authority_destination: String,
    pub compiler: Arc<dyn NativeToolCompiler>,
    pub hosted_turn: Option<crate::NativeHostedRuntimeConfig>,
    pub attach: Box<dyn FnOnce(Arc<AgentdNativeHost>) -> Result<(), AgentdError> + Send>,
}

pub(crate) struct NativeRuntimeAttachment {
    pub(crate) writer_host: Arc<AgentdProductionWriterHost>,
    pub(crate) hosted_turn_executor: Option<Arc<dyn codex_core::hosted_turn::HostedTurnExecutor>>,
}

/// In-process handle delivered only by a running Agentd composition. All
/// durable identities and execution authority remain with its original owners.
pub struct AgentdNativeHost {
    pub(crate) gate: Arc<NativeEntryGate>,
    pub(crate) host: Arc<AgentdProductionWriterHost>,
    pub(crate) model: Arc<NativeResponsesTarget>,
    pub(crate) runtime: Arc<NativeRuntimeTarget>,
    compiler: Arc<dyn NativeToolCompiler>,
}

/// An existing input, history boundary, and context-attached run. `initial`
/// must hash to the original coordinator's context digest. Its bytes may not
/// silently replace the context compiled by the existing owner.
pub struct NativeTurnHandoff {
    pub live_thread: LiveThread,
    pub anchor: NativeTurnAnchorV1,
    pub run: RunReceipt,
    pub scope: NativeTurnScope,
    pub initial: TurnState,
    pub queue: Option<NativeQueueDispatch>,
}

/// Correlation needed to find an already durable native turn. Scope, original
/// policy and coordinator recovery are read from that same checkpoint, never
/// reconstructed from caller-supplied replacements.
pub struct NativeTurnRecovery {
    pub live_thread: LiveThread,
    pub original: NativeCheckpointBinding,
    pub queue: Option<Arc<dyn QueueStore>>,
}

pub struct NativeTurnResult {
    pub outcome: RunOutcome,
    pub state: TurnState,
    pub run: RunReceipt,
}

pub(crate) struct NativePreparedTurn {
    owner: NativeThreadTurnOwner<NativeProductionAdmission>,
    admission: Arc<NativeProductionAdmission>,
    turn: TurnState,
    _original: NativePreparedGuard,
}

impl NativePreparedTurn {
    pub(crate) async fn confirm_durable(&self) -> Result<()> {
        self.owner.confirm_durable().await
    }
}

// Losing the caller before queue acknowledgement or during execution must not
// leave a locally dispatched run looking eligible for another fresh handoff.
pub(crate) struct NativePreparedGuard {
    state: Arc<AgentdState>,
    run_id: String,
    dispatched_revision: u64,
    _active: NativeActiveTurn,
}

impl Drop for NativePreparedGuard {
    fn drop(&mut self) {
        let _ = self.state.abandon_native_run(&self.run_id, self.dispatched_revision);
    }
}

#[derive(Clone, Copy)]
pub(crate) enum NativePreparationDisposition { Initial, Retained }

impl AgentdNativeRuntimeConfig {
    pub(crate) async fn attach_to(self, state: &Arc<AgentdState>, recovered: Arc<AgentdProductionWriterHost>) -> Result<NativeRuntimeAttachment, AgentdError> {
        let result: Result<_> = async {
            ensure!(recovered.has_target(), "native runtime needs the existing external grant provider and production destinations");
            // Resolve the explicit original authority before health probes or
            // runtime store preparation. These constructors perform no effects.
            let model = Arc::new(NativeResponsesTarget::new(self.model, &self.http)?);
            let runtime = Arc::new(NativeRuntimeTarget::new(self.runtime_destination, self.max_tool_output_bytes)?);
            let host = Arc::new(recovered.as_ref().clone()
                .attach_target_with_existing_authority(&self.final_use_authority_destination, model.clone())?
                .attach_target_with_existing_authority(&self.final_use_authority_destination, runtime.clone())?);
            ensure!(Arc::ptr_eq(&recovered.writer(), &host.writer()), "native attachment replaced the recovered writer");
            recovered.writer().verify_current_authority().await?;
            let runtime_config = hepta_runtime::mcp::runtime::runtime_config()?;
            ensure!(!self.required_hosts.is_empty(), "native runtime requires explicit existing hosts");
            for host in &self.required_hosts {
                ensure!(runtime_config.host(host)?.allow_execute, "native host does not allow execution");
                let health: serde_json::Value = serde_json::from_str(&hepta_runtime::mcp::runtime::health::host_health(
                    hepta_runtime::mcp::runtime::health::HostHealthParams { host: host.clone() },
                ).await?)?;
                ensure!(health["reachable"] == true && health["authenticated"] == true, "native host readiness failed");
            }
            hepta_runtime::mcp::runtime::prepare_durable_stores().await?;
            let gate = Arc::new(NativeEntryGate { state: Arc::downgrade(state), policy_generation: self.policy_generation.get() });
            let native = Arc::new(AgentdNativeHost { gate, host: host.clone(), model, runtime, compiler: self.compiler });
            let hosted_turn_executor = self.hosted_turn
                .map(|config| config.attach(state, native.clone())).transpose()?;
            (self.attach)(native)?;
            Ok(NativeRuntimeAttachment { writer_host: host, hosted_turn_executor })
        }.await;
        result.map_err(|error| AgentdError::Protocol(format!("native production attachment failed: {error:#}")))
    }
}

impl AgentdNativeHost {
    fn admission(&self, original: NativeCheckpointBinding, scope: NativeTurnScope, run: &RunReceipt) -> Result<Arc<NativeProductionAdmission>> {
        self.admission_with_policy(original, scope, Generation::new(self.gate.policy_generation)?, run)
    }

    pub(crate) fn admission_with_policy(&self, original: NativeCheckpointBinding, scope: NativeTurnScope, original_policy_generation: Generation, run: &RunReceipt) -> Result<Arc<NativeProductionAdmission>> {
        ensure!(scope.final_scope_id == scope.organ_id,
            "native final payload scope must match the original organ");
        ensure!(original.operation_id == run.run_id && original.generation == run.generation,
            "native turn does not belong to the original Agentd run");
        ensure!(original.lease_id == self.host.writer().lease_id(), "native turn uses another production lease");
        let scope_digest = crate::native_admission::execution_scope_digest(&original, run,
            self.host.writer().owner_agent_id(), &scope, original_policy_generation)?;
        let fresh_revision = match run.phase {
            RunPhase::ContextAttached => Some(run.revision.checked_add(1).context("native dispatch revision exhausted")?),
            RunPhase::Dispatched => Some(run.revision),
            _ => None,
        };
        Ok(Arc::new(NativeProductionAdmission {
            host:self.host.clone(), gate:self.gate.clone(), original, scope, scope_digest, original_policy_generation,
            model_destination:self.model.destination_id().to_owned(), runtime_destination:self.runtime.destination_id().to_owned(),
            compiler:self.compiler.clone(),
            fresh_revision,
            observation_revision: run.revision,
        }))
    }

    /// Consume a dispatch borrowed from the original queue. Its completion is
    /// after exact history + the first checkpoint and before any physical effect.
    pub async fn run_turn(&self, agent: &NativeAgent, mut handoff: NativeTurnHandoff, cancellation: &CancellationToken) -> Result<NativeTurnResult> {
        let context_digest = Digest32::of_bytes(&serde_json::to_vec(&handoff.initial.context)?).to_string();
        ensure!(handoff.run.context_digest.as_deref() == Some(&context_digest), "native context differs from the original compiled context");
        ensure!(handoff.anchor.queue.as_ref() == handoff.queue.as_ref().map(NativeQueueDispatch::binding), "native handoff lost its original queue dispatch");
        let admission = self.validate_preparation(&handoff.anchor, &handoff.run, handoff.scope,
            &handoff.initial, &context_digest)?;
        self.host.writer().verify_current_authority().await?;
        if let Some(queue) = handoff.queue.as_mut() {
            let now = now_ms()?;
            let expiry = now.checked_add(30_000).context("queue dispatch deadline overflow")?;
            queue.authorize(now, expiry).await?;
        }
        let prepared = self.prepare_owner(handoff.live_thread, handoff.anchor, handoff.run,
            handoff.initial, context_digest, admission, NativePreparationDisposition::Initial).await?;
        if let Some(queue) = handoff.queue.as_mut() { queue.complete(&prepared.owner).await?; }
        self.drive_prepared(agent, prepared, cancellation, NativeEntryOwner::Agentd).await
    }

    fn validate_preparation(&self, anchor: &NativeTurnAnchorV1, run: &RunReceipt, scope: NativeTurnScope,
        initial: &TurnState, rendered_digest: &str) -> Result<Arc<NativeProductionAdmission>> {
        ensure!(self.gate.state()?.native_run_receipt(&run.run_id)? == *run, "native handoff run receipt is stale");
        ensure!(initial.binding == anchor.turn_binding()?, "native initial turn binding changed");
        ensure!(Digest32::of_bytes(&serde_json::to_vec(&initial.context)?).to_string() == rendered_digest,
            "native rendered context changed after binding");
        ensure!(anchor.rendered_context_sha256.as_deref().is_none_or(|digest| digest == rendered_digest),
            "native handoff changed its original rendering digest");
        self.admission(anchor.checkpoint.clone(), scope, run)
    }

    /// A sealed canonical compilation supplies the rendering; neither a Core
    /// queue payload nor model JSON may substitute the original receipt digest.
    pub(crate) async fn prepare_hosted_turn(&self, live: LiveThread, anchor: NativeTurnAnchorV1,
        run: RunReceipt, scope: NativeTurnScope, context: NativeContextBindingV1) -> Result<NativePreparedTurn> {
        self.prepare_hosted_with_disposition(live, anchor, run, scope, context, NativePreparationDisposition::Initial).await
    }

    pub(crate) async fn resume_hosted_preparation(&self, live: LiveThread, anchor: NativeTurnAnchorV1,
        run: RunReceipt, scope: NativeTurnScope, context: NativeContextBindingV1,
        proof: codex_hepta_memory::ProductionUnusedScope) -> Result<NativePreparedTurn> {
        let writer = self.host.writer();
        let digest = crate::native_admission::execution_scope_digest(&anchor.checkpoint, &run,
            writer.owner_agent_id(), &scope, Generation::new(self.gate.policy_generation)?)?;
        proof.verify_binding(&writer, &codex_hepta_contracts::Sha256Digest::parse(digest.to_string()).map_err(anyhow::Error::msg)?)?;
        // Core and the original Queue still own this turn. Drop the observed
        // lease before checkpointing reacquires it, so a pending writer close
        // cannot deadlock behind a recursively retained read permit.
        drop(proof);
        self.prepare_hosted_with_disposition(live, anchor, run, scope, context, NativePreparationDisposition::Retained).await
    }

    async fn prepare_hosted_with_disposition(&self, live: LiveThread, anchor: NativeTurnAnchorV1,
        run: RunReceipt, scope: NativeTurnScope, context: NativeContextBindingV1,
        disposition: NativePreparationDisposition) -> Result<NativePreparedTurn> {
        context.verify_run(&run, context.context())?;
        context.verify_run_snapshot(&self.gate.state()?.native_run_snapshot(&run.run_id)?)?;
        let mut initial = TurnState::new(anchor.turn_binding()?, String::new());
        initial.context = context.context().to_vec();
        let rendered = context.rendered_context_digest().to_string();
        let admission = self.validate_preparation(&anchor, &run, scope, &initial, &rendered)?;
        self.prepare_owner(live, anchor, run, initial, rendered, admission, disposition).await
    }

    async fn prepare_owner(&self, live: LiveThread, mut anchor: NativeTurnAnchorV1, run: RunReceipt,
        initial: TurnState, rendered_digest: String, admission: Arc<NativeProductionAdmission>,
        disposition: NativePreparationDisposition) -> Result<NativePreparedTurn> {
        self.host.writer().verify_current_authority().await?;
        let state = self.gate.state()?;
        let dispatched_revision = match disposition {
            NativePreparationDisposition::Initial => run.revision.checked_add(1).context("native dispatch revision exhausted")?,
            NativePreparationDisposition::Retained => run.revision,
        };
        let active = match disposition {
            NativePreparationDisposition::Initial => state.dispatch_native_run(&run)?,
            NativePreparationDisposition::Retained => {
                ensure!(state.require_native_effect(&run.run_id)? == run,
                    "retained preparation lost its original dispatched receipt");
                state.track_native_recovery(&run.run_id)?
            }
        };
        let original = NativePreparedGuard { state: state.clone(), run_id: run.run_id.clone(), dispatched_revision, _active: active };
        anchor.run = Some(state.native_recovery_record(&run.run_id)?);
        anchor.execution = Some(NativeExecutionBindingV1 {
            cell_id: admission.scope.cell_id.to_string(), organ_id: admission.scope.organ_id.to_string(),
            final_scope_id: admission.scope.final_scope_id.to_string(),
            policy_generation: admission.original_policy_generation.get(),
        });
        anchor.rendered_context_sha256 = Some(rendered_digest);
        let owner = NativeThreadTurnOwner::create(live, anchor, admission.clone(), admission.clone(), &initial).await?;
        Ok(NativePreparedTurn { owner, admission, turn: initial, _original: original })
    }

    pub(crate) async fn drive_prepared(&self, agent: &NativeAgent, prepared: NativePreparedTurn,
        cancellation: &CancellationToken, entry_owner: NativeEntryOwner) -> Result<NativeTurnResult> {
        let NativePreparedTurn { owner, admission, turn, _original } = prepared;
        self.drive(agent, owner, admission, turn, cancellation, NativeDriveMode::Live, entry_owner).await
    }


}

fn now_ms() -> Result<i64> {
    Ok(i64::try_from(std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)?.as_millis())?)
}

#[cfg(test)]
#[path = "native_host_tests.rs"]
mod tests;
