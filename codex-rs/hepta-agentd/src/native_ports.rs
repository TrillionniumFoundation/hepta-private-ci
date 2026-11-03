//! Model and tool projections of one original production operation owner.

use codex_hepta_memory::FinalUseProductionOutboxTarget;
use std::sync::Arc;

use anyhow::Result;
use anyhow::ensure;
use codex_core::hosted_turn::HostedTurnEntry;
use codex_hepta_memory::ProductionDispatchRequest;
use codex_hepta_memory::ProductionEntryCurrentness;
use codex_hepta_memory::ProductionTargetOutcome;
use codex_hepta_memory::ProductionWriterError;
use codex_hepta_native_agent::ModelPort;
use codex_hepta_native_agent::ModelRequest;
use codex_hepta_native_agent::ObservedModelCompletion;
use codex_hepta_native_agent::ObservedModelTerminal;
use codex_hepta_native_agent::ResponsesStream;
use codex_hepta_native_agent::ToolObservation;
use codex_hepta_native_agent::ToolPort;
use codex_hepta_types::RuntimeToolIntentV1;

use crate::native_admission::NativeProductionAdmission;
use crate::native_model_target::NativeResponsesTarget;
use crate::native_runtime_target::NativeRuntimeTarget;

/// Selects the already existing execution owner. A hosted turn must retain
/// Core's opaque handle; it cannot fall back when that original task is gone.
#[derive(Clone)]
pub(crate) enum NativeEntryOwner {
    Agentd,
    Core(Arc<HostedTurnEntry>),
}

#[derive(Clone)]
pub(crate) struct NativeProductionPorts {
    pub(crate) admission: Arc<NativeProductionAdmission>,
    pub(crate) model: Arc<NativeResponsesTarget>,
    pub(crate) runtime: Arc<NativeRuntimeTarget>,
    pub(crate) entry_owner: NativeEntryOwner,
}

impl NativeProductionPorts {
    async fn original(
        &self,
        operation_id: &str,
        destination: &str,
    ) -> Result<ProductionDispatchRequest> {
        let request = self
            .admission
            .host
            .writer()
            .resolve_operation_request(operation_id, destination)
            .await?;
        self.admission.verify_request(&request)?;
        Ok(request)
    }

    fn model_outcome(
        terminal: &ObservedModelTerminal,
        operation_id: &str,
    ) -> Result<ProductionTargetOutcome> {
        ensure!(
            terminal.operation_id() == operation_id,
            "model terminal belongs to another original operation"
        );
        Ok(ProductionTargetOutcome::Committed {
            receipt: serde_json::json!({
                "schema": "hepta.native.model.observed.v1",
                "operation_id": terminal.operation_id(),
                "response_id": terminal.response_id(),
                "evidence_sha256": terminal.evidence_digest().to_string(),
            })
            .to_string(),
        })
    }
}

impl ProductionEntryCurrentness for NativeProductionPorts {
    fn enter(
        &self,
        request: &ProductionDispatchRequest,
        enter: &mut dyn FnMut() -> Result<(), ProductionWriterError>,
    ) -> Result<Box<dyn Send>, ProductionWriterError> {
        match &self.entry_owner {
            NativeEntryOwner::Agentd => self.admission.enter(request, enter),
            NativeEntryOwner::Core(owner) => owner
                .with_current(
                    self.admission.original.thread_id,
                    &self.admission.original.turn_id,
                    || self.admission.enter(request, enter),
                )
                .map_err(|error| {
                    ProductionWriterError::AuthorityRejected(format!(
                        "original Core turn rejected native entry: {error}"
                    ))
                })?,
        }
    }
}

impl ModelPort for NativeProductionPorts {
    async fn open(&self, request: &ModelRequest) -> Result<ResponsesStream> {
        let original = self
            .original(&request.operation_id, self.model.destination_id())
            .await?;
        let exact = self.model.original_request(&original)?;
        ensure!(
            exact.operation_id == request.operation_id && exact.body == request.body,
            "model checkpoint differs from original production operation"
        );
        let (entry, observation) = self
            .admission
            .host
            .begin_native_effect(self.model.destination_id(), &request.operation_id)
            .await?;
        let stream = self.model.open_effect_entry(entry, self).await?;
        let host = Arc::clone(&self.admission.host);
        let operation_id = request.operation_id.clone();
        stream.with_terminal_observer(request, move |terminal| async move {
            let outcome = Self::model_outcome(&terminal, &operation_id)?;
            host.settle_native_effect(observation, outcome).await?;
            Ok(())
        })
    }

    async fn reconcile(
        &self,
        request: &ModelRequest,
        response_id: &str,
    ) -> Result<Option<ObservedModelCompletion>> {
        let original = self
            .original(&request.operation_id, self.model.destination_id())
            .await?;
        let exact = self.model.original_request(&original)?;
        ensure!(
            exact.body == request.body,
            "recovery changed the original model body"
        );
        let Some(completion) = self
            .model
            .reconcile_original(&original, response_id)
            .await?
        else {
            return Ok(None);
        };
        let terminal = completion.terminal()?;
        ensure!(
            terminal.response_id() == response_id,
            "model recovery changed original response"
        );
        self.admission
            .host
            .reconcile_native_effect(
                self.model.destination_id(),
                &request.operation_id,
                Self::model_outcome(&terminal, &request.operation_id)?,
            )
            .await?;
        Ok(Some(completion))
    }
}

impl ToolPort for NativeProductionPorts {
    async fn execute_or_observe(
        &self,
        intent: &RuntimeToolIntentV1,
        arguments: &[u8],
    ) -> Result<ToolObservation> {
        let key = intent.idempotency_key.as_str();
        let original = self.original(key, self.runtime.destination_id()).await?;
        ensure!(
            original.payload_json.as_bytes() == arguments,
            "tool checkpoint differs from original production operation"
        );
        let (entry, observation) = self
            .admission
            .host
            .begin_native_effect(self.runtime.destination_id(), key)
            .await?;
        // Retain only clones of the existing owner projections across the
        // independent runtime queue. This creates no new admission or grant.
        let currentness: Arc<dyn ProductionEntryCurrentness> = Arc::new(self.clone());
        let outcome = self.runtime.dispatch_effect_entry(entry, currentness).await;
        self.admission
            .host
            .settle_native_effect(observation, outcome)
            .await?;
        // A short job can publish its terminal after dispatch observed it as
        // pending. Every returned terminal must settle this same original
        // writer before the native loop clears its durable pending tool.
        self.observe(intent).await
    }

    async fn observe(&self, intent: &RuntimeToolIntentV1) -> Result<ToolObservation> {
        let key = intent.idempotency_key.as_str();
        let original = self.original(key, self.runtime.destination_id()).await?;
        let Some(evidence) = self
            .runtime
            .observe_tool_evidence(&original, intent)
            .await?
        else {
            return Ok(ToolObservation::Accepted);
        };
        // Settle the original writer and return model feedback from the same
        // complete raw observation. A second fetch could bind the production
        // receipt to different bytes and needlessly transfers the output twice.
        evidence.receipt.validate_against(intent)?;
        self.admission
            .host
            .reconcile_native_effect(
                self.runtime.destination_id(),
                key,
                ProductionTargetOutcome::Committed {
                    receipt: evidence.terminal_receipt,
                },
            )
            .await?;
        Ok(ToolObservation::Terminal {
            receipt: evidence.receipt,
            stdout: evidence.stdout,
            stderr: evidence.stderr,
        })
    }

    async fn cancel(&self, intent: &RuntimeToolIntentV1) -> Result<()> {
        let original = self
            .original(
                intent.idempotency_key.as_str(),
                self.runtime.destination_id(),
            )
            .await?;
        // This invokes only the original job's cancellation endpoint. An ack
        // neither settles its production operation nor authorizes another job.
        self.runtime.cancel_original(&original).await
    }
}
