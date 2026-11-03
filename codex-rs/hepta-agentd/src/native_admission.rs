//! Admission through the existing production writer and original Agentd run.

use std::sync::Arc;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_memory::{ProductionDispatchRequest, ProductionEntryCurrentness, ProductionWriterError};
use codex_hepta_native_agent::{ModelRequest, ToolAdmission, ToolCall, TurnBinding};
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_types::{CellExecutionIntentV1, Digest32, ExecutionIntentKindV1, FinalPayloadDigestV1, Generation, RuntimeToolIntentV1, StableId};
use codex_thread_store::{NativeCheckpointBinding, NativeCheckpointCurrentness, NativeCheckpointPermit, ThreadStoreError, ThreadStoreFuture};
use hepta_runtime::mcp::runtime::jobs::ProcessStartParams;

use crate::AgentdProductionWriterHost;
use crate::NativeTurnAdmission;
use crate::native_model_target::NATIVE_MODEL_TOPIC_V1;
use crate::native_runtime_target::NATIVE_RUNTIME_TOPIC_V1;
use crate::state::native::NativeEntryGate;

/// The existing product tool compiler selects the concrete host and execution
/// policy. Model arguments are proposals; this callback must not issue grants
/// or start a process. Runtime policy and final-use checks remain mandatory.
pub trait NativeToolCompiler: Send + Sync {
    fn compile(&self, call: &ToolCall) -> Result<ProcessStartParams>;
}

/// Original product identities supplied by the admitted run, never by a model.
#[derive(Clone, Debug)]
pub struct NativeTurnScope {
    pub cell_id: StableId,
    pub organ_id: StableId,
    pub final_scope_id: StableId,
}

pub(crate) fn execution_scope_digest(original: &NativeCheckpointBinding, run: &crate::RunReceipt,
    owner: &codex_hepta_contracts::AgentId, scope: &NativeTurnScope, policy: Generation) -> Result<Digest32> {
    Ok(Digest32::of_bytes(&serde_json::to_vec(&serde_json::json!({
        "schema":"hepta.native.production.scope.v1", "agent": owner.as_str(),
        "thread": original.thread_id, "turn": original.turn_id, "run": run.run_id,
        "fleet_generation": original.generation, "authority_epoch": run.authority_epoch,
        "context":run.context_digest, "compilation":run.compilation_receipt_digest,
        "fence":run.fence_digest, "deadline_ms":run.deadline_ms,
        "cell":scope.cell_id.as_str(), "organ":scope.organ_id.as_str(), "scope":scope.final_scope_id.as_str(),
        "policy_generation":policy.get(),
    }))?))
}

pub(crate) struct NativeProductionAdmission {
    pub(crate) host: Arc<AgentdProductionWriterHost>,
    pub(crate) gate: Arc<NativeEntryGate>,
    pub(crate) original: NativeCheckpointBinding,
    pub(crate) scope: NativeTurnScope,
    pub(crate) scope_digest: Digest32,
    // Original operation policy, retained across observation-only recovery.
    // The live entry gate's policy separately controls every new effect.
    pub(crate) original_policy_generation: Generation,
    pub(crate) model_destination: String,
    pub(crate) runtime_destination: String,
    pub(crate) compiler: Arc<dyn NativeToolCompiler>,
    // Fresh permission belongs to one actual dispatched coordinator revision.
    // Observer admissions intentionally carry no such permission.
    pub(crate) fresh_revision: Option<u64>,
    pub(crate) observation_revision: u64,
}

impl NativeProductionAdmission {
    pub(crate) fn binding(&self) -> Result<TurnBinding> {
        Ok(TurnBinding {
            thread_id: StableId::new(self.original.thread_id.to_string())?,
            turn_id: StableId::new(self.original.turn_id.clone())?,
            operation_id: StableId::new(self.original.operation_id.clone())?,
            generation: Generation::new(self.original.generation)?,
        })
    }

    pub(crate) fn verify_request(&self, request: &ProductionDispatchRequest) -> Result<()> {
        ensure!(request.lease_id == self.original.lease_id
            && request.operation_subject_id == self.host.writer().owner_agent_id().as_str()
            && request.operation_scope_sha256.as_str() == self.scope_digest.to_string()
            && request.operation_policy_generation == self.original_policy_generation.get(),
            "operation belongs to another native run or policy");
        Ok(())
    }

    async fn admit(&self, operation_id: &str, destination: &str, topic: &str, payload: &[u8]) -> Result<()> {
        self.require_fresh_run()?;
        self.host.writer().verify_current_authority().await?;
        let operation = OperationIntentV1::new(
            StableId::new(operation_id)?, StableId::new(self.host.writer().owner_agent_id().as_str())?,
            StableId::new(destination)?, Digest32::of_bytes(payload), self.scope_digest,
            self.original_policy_generation, None,
        )?;
        let gate = self.gate.clone();
        let run_id = self.original.operation_id.clone();
        let revision = self.fresh_revision.context("observation cannot admit a native operation")?;
        self.host.writer().prepare_operation_checked(operation, topic, std::str::from_utf8(payload)?, move || {
            let state = gate.state().map_err(|error| ProductionWriterError::AuthorityRejected(error.to_string()))?;
            let current = state.require_native_effect(&run_id)
                .map_err(|error| ProductionWriterError::AuthorityRejected(error.to_string()))?;
            if current.revision != revision {
                return Err(ProductionWriterError::AuthorityRejected("original native admission revision was replaced".to_owned()));
            }
            Ok(())
        }).await?;
        Ok(())
    }

    fn require_fresh_run(&self) -> Result<crate::RunReceipt> {
        ensure!(self.original_policy_generation.get() == self.gate.policy_generation,
            "original native policy is observation-only under the current gate");
        let current = self.gate.state()?.require_native_effect(&self.original.operation_id)?;
        ensure!(self.fresh_revision == Some(current.revision), "original native admission revision was replaced or is observation-only");
        Ok(current)
    }

    /// Reconstruct only the original saved intent. Compilation is deliberately
    /// absent here: a changed tool compiler cannot rewrite a past process.
    pub(crate) fn intent_for_arguments(&self, binding: &TurnBinding, call: &ToolCall,
        arguments: &[u8], host: &str, deadline_ms: u64) -> Result<RuntimeToolIntentV1> {
        let operation_id = self.operation_id("tool", &call.call_id)?;
        let digest = Digest32::of_bytes(arguments);
        let intent = RuntimeToolIntentV1 {
            cell: CellExecutionIntentV1 {
                operation_id: StableId::new(operation_id.clone())?, cell_id: self.scope.cell_id.clone(),
                organ_id: self.scope.organ_id.clone(), generation: binding.generation,
                kind: ExecutionIntentKindV1::RuntimeTool, codex_binding: None,
                input_digest: Digest32::of_bytes(&call.arguments),
                final_payload: FinalPayloadDigestV1 {
                    scope_id: self.scope.final_scope_id.clone(), generation: binding.generation,
                    payload_kind: StableId::new("hepta.runtime.process.v1")?, digest,
                },
                deadline_ms,
            },
            tool_id: StableId::new("process_start")?, arguments_digest: digest,
            idempotency_key: StableId::new(operation_id.clone())?, host_scope: StableId::new(host)?,
        };
        intent.validate()?;
        Ok(intent)
    }

    pub(crate) fn operation_id(&self, kind: &str, identity: &str) -> Result<String> {
        // Run/turn/call ids are local to their original owner. The runtime job
        // key is shared by configured host, so fresh operations must retain the
        // full immutable owner domain. Recovery reads saved keys unchanged.
        let writer = self.host.writer();
        let material = serde_json::to_vec(&(
            "hepta.native.operation.v2",
            writer.owner_agent_id().as_str(),
            self.original.thread_id,
            &self.original.lease_id,
            &self.original.operation_id,
            &self.original.turn_id,
            kind,
            identity,
        ))?;
        let digest = Digest32::of_bytes(&material);
        Ok(format!("native:{kind}:{digest}"))
    }
}

impl ProductionEntryCurrentness for NativeProductionAdmission {
    fn enter(&self, request: &ProductionDispatchRequest, enter: &mut dyn FnMut() -> Result<(), ProductionWriterError>) -> Result<Box<dyn Send>, ProductionWriterError> {
        // The operation subject is the durable writer's owner, not a run id.
        // The immutable scope binds this original run/turn/context separately;
        // check it again at physical entry, after every asynchronous wait.
        self.verify_request(request)
            .map_err(|error| ProductionWriterError::AuthorityRejected(error.to_string()))?;
        let revision = self.fresh_revision.ok_or_else(|| ProductionWriterError::AuthorityRejected(
            "original native observation has no fresh entry revision".to_owned()))?;
        self.gate.enter_original(request, &self.original.operation_id, self.original.generation, revision, enter)
    }
}

impl NativeTurnAdmission for NativeProductionAdmission {
    async fn verify_current(&self, binding: &TurnBinding) -> Result<()> {
        ensure!(binding == &self.binding()?, "native original turn binding changed");
        ensure!(self.host.writer().lease_id() == self.original.lease_id, "native production lease changed");
        let state = self.gate.state()?;
        ensure!(state.identity().agent_id == *self.host.writer().owner_agent_id(), "native Agentd writer changed");
        // Observation/checkpointing may continue after cancellation. Only
        // admit()/the physical-entry gate authorize a new effect.
        let run = state.native_run_receipt(&self.original.operation_id)?;
        ensure!(run.generation == self.original.generation, "original run generation changed");
        self.host.writer().verify_current_authority().await?;
        Ok(())
    }

    async fn admit_model(&self, binding: &TurnBinding, sequence: usize, exact_body: &[u8]) -> Result<ModelRequest> {
        self.verify_current(binding).await?;
        let operation_id = self.operation_id("model", &sequence.to_string())?;
        self.admit(&operation_id, &self.model_destination, NATIVE_MODEL_TOPIC_V1, exact_body).await?;
        Ok(ModelRequest { operation_id, body: exact_body.to_vec() })
    }

    async fn admit_tool(&self, binding: &TurnBinding, call: &ToolCall) -> Result<ToolAdmission> {
        self.verify_current(binding).await?;
        let run = self.require_fresh_run()?;
        let operation_id = self.operation_id("tool", &call.call_id)?;
        let mut params = self.compiler.compile(call)?;
        ensure!(params.idempotency_key.is_none() || params.idempotency_key.as_deref() == Some(&operation_id), "tool compiler changed original operation");
        params.idempotency_key = Some(operation_id.clone());
        let arguments = serde_json::to_vec(&params)?;
        let intent = self.intent_for_arguments(binding, call, &arguments, &params.host, run.deadline_ms)?;
        self.admit(&operation_id, &self.runtime_destination, NATIVE_RUNTIME_TOPIC_V1, &arguments).await?;
        Ok(ToolAdmission { intent, arguments })
    }
}

impl NativeCheckpointCurrentness for NativeProductionAdmission {
    fn acquire<'a>(&'a self, binding: &'a NativeCheckpointBinding) -> ThreadStoreFuture<'a, NativeCheckpointPermit<'a>> {
        Box::pin(async move {
            let permit = async {
                ensure!(binding == &self.original, "checkpoint original owner changed");
                self.verify_current(&self.binding()?).await?;
                let writer = self.host.writer();
                let lease = writer.acquire_current_lease().await?;
                let current = self.gate.state()?.native_run_receipt(&self.original.operation_id)?;
                let same_attempt = match self.fresh_revision {
                    Some(revision) => (current.phase == crate::RunPhase::Dispatched && current.revision == revision)
                        || (revision.checked_add(1) == Some(current.revision)
                            && (current.phase == crate::RunPhase::Indeterminate
                                || (current.phase == crate::RunPhase::Cancelling && current.cancel_reason.is_some()))),
                    None => current.revision == self.observation_revision,
                };
                ensure!(same_attempt, "original native checkpoint writer revision was replaced");
                // Retain the original writer's generation fence through the
                // actual detached SQLite commit, including lost acknowledgments.
                Ok::<_, anyhow::Error>(NativeCheckpointPermit::hold(lease))
            }.await.context("native production checkpoint currentness");
            permit.map_err(|error| ThreadStoreError::Conflict { message: format!("{error:#}") })
        })
    }
}
