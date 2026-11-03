//! Native execution in Core's original durable queue and active-turn task.
//! This adapter owns no queue, route registry, grant issuer, or session writer.

use std::collections::BTreeMap;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_core::hosted_turn::{HostedAdmittedTurn, HostedFuture, HostedQueueBinding, HostedTurnExecution, HostedTurnExecutor, HostedTurnInput, HostedTurnObservation, HostedTurnOutcome, HostedTurnPlan, HostedTurnProvenance, HostedTurnRecoveryInput};
use codex_hepta_native_agent::{NativeAgent, RunOutcome, TurnState};
use codex_hepta_types::Digest32;
use codex_protocol::error::CodexErr;
use codex_protocol::user_input::user_input_payload_sha256;
use codex_thread_store::NativeCheckpointBinding;
use serde::{Deserialize, Serialize};

use crate::intelligence_product::NativeContextBindingV1;
use crate::native_host::AgentdNativeHost;
use crate::native_ports::NativeEntryOwner;
use crate::native_turn_checkpoint::{NativeQueueBindingV1, NativeTurnAnchorV1};
use crate::{NativeTurnScope, RunPhase, RunReceipt};

#[path = "native_hosted_preparation.rs"]
mod preparation;
pub(crate) use preparation::retained_preparation_scope;
#[path = "native_hosted_config.rs"]
mod execution_config;

#[path = "native_checkpoint_continuation.rs"]
mod checkpoint_continuation;
pub(crate) use checkpoint_continuation::NativeContinuationEvidence;

enum NativeHostedPreparation {
    Initial,
    RecoveredInitial(codex_hepta_memory::ProductionUnusedScope),
    Retained(codex_hepta_memory::ProductionUnusedScope),
}

impl NativeHostedPreparation {
    fn expected_phase(&self) -> RunPhase {
        match self {
            Self::Initial | Self::RecoveredInitial(_) => RunPhase::ContextAttached,
            Self::Retained(_) => RunPhase::Dispatched,
        }
    }
}

const EXECUTOR_ID: &str = "hepta.native-agent.v1";
const LEGACY_CORRELATION_SCHEMA: &str = "hepta.native.hosted-correlation.v1";
const CORRELATION_SCHEMA: &str = "hepta.native.hosted-correlation.v2";

pub type NativeHostedResolveFuture<'a> = Pin<Box<dyn Future<Output = Result<NativeHostedResolution>> + Send + 'a>>;

/// Original admission selected by the embedding's existing product owner.
/// `context` can only come from the real canonical compilation path.
pub struct NativeHostedResolution {
    pub run: RunReceipt,
    pub scope: NativeTurnScope,
    pub context: NativeContextBindingV1,
}

/// Resolves the actual queued input against the existing product owners.
/// This callback must return an already admitted/context-attached run, never
/// create a replacement run, route table, queue claim, operation, or grant.
/// Missing original context is an error and cannot fall back to Core sampling.
pub trait NativeHostedTurnResolver: Send + Sync {
    fn resolve<'a>(&'a self, input: &'a HostedTurnInput) -> NativeHostedResolveFuture<'a>;
    /// Return the configured original host scope for retained preparation.
    /// This is an owner lookup only and must not admit or dispatch a run.
    fn preparation_scope(&self) -> Result<NativeTurnScope> {
        anyhow::bail!("the original resolver does not support retained preparation")
    }
}

/// Explicit host opt-in. Core records the complete execution configuration
/// digest separately from its exact first-model-request fingerprint.
pub struct NativeHostedTurnConfig {
    pub agent: Arc<NativeAgent>,
    pub resolver: Arc<dyn NativeHostedTurnResolver>,
}

pub struct AgentdNativeHostedExecutor {
    host: Arc<AgentdNativeHost>,
    agent: Arc<NativeAgent>,
    resolver: Arc<dyn NativeHostedTurnResolver>,
}

impl AgentdNativeHostedExecutor {
    pub fn new(host: Arc<AgentdNativeHost>, config: NativeHostedTurnConfig) -> Result<Self> {
        let limits = &config.agent.limits;
        ensure!(!config.agent.model_name.is_empty() && limits.context_bytes > 0
            && limits.output_tokens > 0 && limits.model_calls > 0 && limits.tool_output_bytes > 0
            && !limits.model_timeout.is_zero() && !limits.tool_timeout.is_zero()
            && !limits.observation_interval.is_zero(), "native hosted execution needs explicit bounded configuration");
        Ok(Self { host, agent: config.agent, resolver: config.resolver })
    }

    async fn original_anchor(&self, observation: &HostedTurnObservation) -> Result<NativeTurnAnchorV1> {
        let provenance = observation.provenance()?;
        ensure!(provenance.executor_id == EXECUTOR_ID, "original turn belongs to another hosted executor");
        let correlation: NativeHostedCorrelationV1 = serde_json::from_value(serde_json::to_value(provenance.correlation)?)?;
        let writer = self.host.host.writer();
        ensure!(correlation.agent_id == writer.owner_agent_id().as_str()
            && correlation.lease_id == writer.lease_id(), "hosted observation changed its original writer owner");
        let original = correlation.checkpoint(observation)?;
        let (anchor, _) = self.host.read_hosted_checkpoint(&observation.live_thread, &original).await?;
        ensure!(anchor.recovery == observation.recovery
            && anchor.queue.as_ref() == Some(&queue_binding(&observation.queue)),
            "hosted observation changed its original typed history or queue input");
        correlation.verify_checkpoint(&anchor)?;
        Ok(anchor)
    }
}

// Persisted solely inside Core's existing typed recovery metadata. These
// strings locate and cross-check the original checkpoint; they grant nothing.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct NativeHostedCorrelationV1 {
    schema: String,
    agent_id: String,
    thread_id: String,
    turn_id: String,
    run_id: String,
    lease_id: String,
    fleet_generation: String,
    policy_generation: String,
    cell_id: String,
    organ_id: String,
    final_scope_id: String,
    rendered_context_sha256: String,
    context_receipt_sha256: String,
    compilation_receipt_sha256: String,
    /// V1 observations remain readable. Their missing configuration cannot be
    /// inferred from a model request or upgraded into fresh preparation.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    execution_config_sha256: Option<String>,
}

impl NativeHostedCorrelationV1 {
    fn validate_schema(&self) -> Result<()> {
        match (self.schema.as_str(), self.execution_config_sha256.as_deref()) {
            (LEGACY_CORRELATION_SCHEMA, None) => Ok(()),
            (CORRELATION_SCHEMA, Some(digest)) => { digest.parse::<Digest32>()?; Ok(()) }
            _ => anyhow::bail!("original hosted execution configuration format is incomplete"),
        }
    }

    fn verify_preparation_config(&self, agent: &NativeAgent) -> Result<()> {
        self.validate_schema()?;
        let expected = execution_config::digest(agent)?;
        ensure!(self.schema == CORRELATION_SCHEMA
            && self.execution_config_sha256.as_deref() == Some(expected.as_str()),
            "original native execution configuration is missing or changed; preparation is held");
        Ok(())
    }

    fn checkpoint(&self, observation: &HostedTurnObservation) -> Result<NativeCheckpointBinding> {
        self.validate_schema()?;
        ensure!(self.thread_id == observation.thread_id.to_string() && self.turn_id == observation.turn_id,
            "hosted correlation changed its original thread or turn");
        Ok(NativeCheckpointBinding {
            thread_id: observation.thread_id, turn_id: self.turn_id.clone(), operation_id: self.run_id.clone(),
            generation: self.fleet_generation.parse()?, lease_id: self.lease_id.clone(),
        })
    }

    fn verify_checkpoint(&self, anchor: &NativeTurnAnchorV1) -> Result<()> {
        let run = anchor.run.as_ref().context("hosted checkpoint lacks original coordinator recovery")?;
        let scope = anchor.execution.as_ref().context("hosted checkpoint lacks original execution scope")?;
        ensure!(anchor.rendered_context_sha256.as_ref() == Some(&self.rendered_context_sha256)
            && run.context_digest == self.context_receipt_sha256
            && run.compilation_receipt_digest == self.compilation_receipt_sha256
            && anchor.checkpoint.generation.to_string() == self.fleet_generation
            && scope.policy_generation.to_string() == self.policy_generation
            && scope.cell_id == self.cell_id && scope.organ_id == self.organ_id
            && scope.final_scope_id == self.final_scope_id,
            "hosted checkpoint changed its original compilation or execution binding");
        Ok(())
    }
}

impl AgentdNativeHostedExecutor {
    async fn plan_from_resolution(&self, input: HostedTurnInput, resolved: NativeHostedResolution,
        preparation: NativeHostedPreparation) -> Result<HostedTurnPlan> {
        input.origin.validate(input.thread_id, &input.turn_id, &input.queue)?;
        ensure!(user_input_payload_sha256(&input.input)? == input.queue.payload_sha256,
            "native hosted preparation changed the original queued input");
        let state = self.host.gate.state()?;
        ensure!(resolved.run.phase == preparation.expected_phase()
            && state.native_run_receipt(&resolved.run.run_id)? == resolved.run,
            "native hosted resolver did not return the actual context-attached run");
        ensure!(resolved.scope.final_scope_id == resolved.scope.organ_id,
            "native hosted scope differs from the original organ");
        resolved.context.verify_run(&resolved.run, resolved.context.context())?;
        resolved.context.verify_run_snapshot(&state.native_run_snapshot(&resolved.run.run_id)?)?;
        let writer = self.host.host.writer();
        ensure!(&state.identity().agent_id == writer.owner_agent_id(), "native hosted writer belongs to another Agentd");
        writer.verify_current_authority().await?;
        let original = NativeCheckpointBinding {
            thread_id: input.thread_id, turn_id: input.turn_id.clone(), operation_id: resolved.run.run_id.clone(),
            generation: resolved.run.generation, lease_id: writer.lease_id().to_owned(),
        };
        let correlation = NativeHostedCorrelationV1 {
            schema: CORRELATION_SCHEMA.to_owned(), agent_id: writer.owner_agent_id().as_str().to_owned(),
            thread_id: input.thread_id.to_string(), turn_id: input.turn_id.clone(), run_id: resolved.run.run_id.clone(),
            lease_id: original.lease_id.clone(), fleet_generation: resolved.run.generation.to_string(),
            policy_generation: self.host.gate.policy_generation.to_string(),
            cell_id: resolved.scope.cell_id.to_string(), organ_id: resolved.scope.organ_id.to_string(),
            final_scope_id: resolved.scope.final_scope_id.to_string(),
            rendered_context_sha256: resolved.context.rendered_context_digest().to_string(),
            context_receipt_sha256: resolved.context.context_receipt_digest().to_string(),
            compilation_receipt_sha256: resolved.context.compilation_receipt_digest().to_string(),
            execution_config_sha256: Some(execution_config::digest(&self.agent)?),
        };
        let correlation: BTreeMap<String, String> = serde_json::from_value(serde_json::to_value(correlation)?)?;
        let mut initial = TurnState::new(codex_hepta_native_agent::TurnBinding {
            thread_id: codex_hepta_types::StableId::new(input.thread_id.to_string())?,
            turn_id: codex_hepta_types::StableId::new(input.turn_id)?,
            operation_id: codex_hepta_types::StableId::new(resolved.run.run_id.clone())?,
            generation: codex_hepta_types::Generation::new(resolved.run.generation)?,
        }, String::new());
        initial.context = resolved.context.context().to_vec();
        let fingerprint = Digest32::of_bytes(&self.agent.model_request_body(&initial)?).to_string();
        Ok(HostedTurnPlan {
            request_fingerprint_sha256: fingerprint.clone(), correlation: correlation.clone(),
            execution: Box::new(NativeHostedExecution {
                host: self.host.clone(), agent: self.agent.clone(), resolved, original,
                queue: input.queue, correlation, fingerprint, preparation,
            }) as Box<dyn HostedTurnExecution>,
        })
    }
}

#[cfg(test)]
#[path = "native_hosted_config_tests.rs"]
mod config_tests;


impl HostedTurnExecutor for AgentdNativeHostedExecutor {
    fn executor_id(&self) -> &str { EXECUTOR_ID }

    fn prepare<'a>(&'a self, input: HostedTurnInput) -> HostedFuture<'a, HostedTurnPlan> {
        Box::pin(async move {
            input.origin.require_initial()?;
            let resolved = self.resolver.resolve(&input).await.map_err(held)?;
            self.plan_from_resolution(input, resolved, NativeHostedPreparation::Initial).await.map_err(held)
        })
    }

    fn resume_preparation<'a>(&'a self, input: codex_core::hosted_turn::HostedPreparationRecoveryInput) -> HostedFuture<'a, HostedTurnPlan> {
        Box::pin(async move { self.resume_original_preparation(input).await.map_err(held) })
    }

    fn supports_checkpoint_continuation(&self) -> bool { true }

    fn prepare_checkpoint_continuation<'a>(&'a self, input: codex_core::hosted_turn::HostedCheckpointContinuationInput)
        -> HostedFuture<'a, Option<HostedTurnPlan>> {
        Box::pin(async move { self.prepare_original_checkpoint_continuation(input).await.map_err(held) })
    }

    fn observe_admission<'a>(&'a self, observation: HostedTurnObservation) -> HostedFuture<'a, Option<String>> {
        Box::pin(async move {
            let observed: Result<_> = async {
                let original = self.preparation_binding(&observation)?.1;
                if !self.host.has_hosted_checkpoint(&observation.live_thread, &original).await? {
                    return Ok(None);
                }
                let anchor = self.original_anchor(&observation).await?;
                self.host.confirm_hosted_checkpoint(observation.live_thread, &anchor).await?;
                Ok(Some(anchor.checkpoint.turn_id))
            }.await;
            observed.map_err(held)
        })
    }

    fn recover<'a>(&'a self, input: HostedTurnRecoveryInput) -> HostedFuture<'a, HostedTurnOutcome> {
        Box::pin(async move {
            let result: Result<_> = async {
                let anchor = self.original_anchor(&input.observation).await?;
                let result = self.host.recover_hosted_turn(&self.agent, input.observation.live_thread,
                    anchor, &input.cancellation).await?;
                Ok(hosted_outcome(result.outcome))
            }.await;
            result.map_err(held)
        })
    }
}

struct NativeHostedExecution {
    host: Arc<AgentdNativeHost>,
    agent: Arc<NativeAgent>,
    resolved: NativeHostedResolution,
    original: NativeCheckpointBinding,
    queue: HostedQueueBinding,
    correlation: BTreeMap<String, String>,
    fingerprint: String,
    preparation: NativeHostedPreparation,
}

impl HostedTurnExecution for NativeHostedExecution {
    fn run(self: Box<Self>, turn: HostedAdmittedTurn) -> HostedFuture<'static, HostedTurnOutcome> {
        Box::pin(async move {
            let Self { host, agent, resolved, original, queue, correlation, fingerprint, preparation } = *self;
            let validated: Result<_> = (|| {
                ensure!(turn.thread_id() == original.thread_id && turn.turn_id() == original.turn_id
                    && turn.queue() == &queue && turn.recovery().fingerprint_sha256 == fingerprint,
                    "Core changed the exact prepared native turn or model request");
                let provenance = HostedTurnProvenance::from_recovery(turn.recovery())?
                    .context("Core omitted original hosted provenance")?;
                ensure!(provenance.executor_id == EXECUTOR_ID && provenance.correlation == correlation
                    && provenance.queue == queue, "Core changed native preparation correlation");
                Ok(NativeTurnAnchorV1 {
                    checkpoint: original, recovery: turn.recovery().clone(), queue: Some(queue_binding(&queue)),
                    run: None, execution: None,
                    rendered_context_sha256: Some(resolved.context.rendered_context_digest().to_string()),
                })
            })();
            let anchor = validated.map_err(held)?;
            let prepared = match preparation {
                NativeHostedPreparation::Initial => host.prepare_hosted_turn(turn.live_thread().clone(), anchor,
                    resolved.run, resolved.scope, resolved.context).await,
                NativeHostedPreparation::RecoveredInitial(proof) => {
                    drop(proof);
                    host.prepare_hosted_turn(turn.live_thread().clone(), anchor,
                        resolved.run, resolved.scope, resolved.context).await
                }
                NativeHostedPreparation::Retained(proof) => host.resume_hosted_preparation(turn.live_thread().clone(), anchor,
                    resolved.run, resolved.scope, resolved.context, proof).await,
            }.map_err(held)?;
            prepared.confirm_durable().await.map_err(held)?;
            // This awaits the original ext/queue completion transaction. No
            // NativeQueueDispatch is created or completed by the hosted path.
            turn.confirm_durable().await?;
            let result = host.drive_prepared(&agent, prepared, turn.cancellation(),
                NativeEntryOwner::Core(Arc::clone(turn.entry()))).await.map_err(held)?;
            Ok(hosted_outcome(result.outcome))
        })
    }
}

fn queue_binding(queue: &HostedQueueBinding) -> NativeQueueBindingV1 {
    NativeQueueBindingV1 { queued_item_id: queue.queued_item_id.clone(), client_id: queue.client_id.clone(), payload_sha256: queue.payload_sha256.clone() }
}

fn hosted_outcome(outcome: RunOutcome) -> HostedTurnOutcome {
    match outcome {
        RunOutcome::Completed(answer) => HostedTurnOutcome::Completed { final_answer: Some(answer) },
        RunOutcome::Cancelled => HostedTurnOutcome::Cancelled,
        RunOutcome::PendingModel | RunOutcome::PendingTool => HostedTurnOutcome::PendingObservation,
    }
}

fn held(error: anyhow::Error) -> CodexErr {
    CodexErr::InvalidRequest(format!("native hosted turn held: {error:#}"))
}

