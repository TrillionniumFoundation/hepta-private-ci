//! The production writer's runtime destination over the original durable jobs owner.
//! This adapter creates no operation identity, outbox, journal or grant authority.

use anyhow::Result;
use anyhow::bail;
use std::sync::Arc;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::FinalUseProductionOutboxTarget;
use codex_hepta_memory::PRODUCTION_DURABLE_WRITER_NAMESPACE;
use codex_hepta_memory::PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION;
use codex_hepta_memory::ProductionDispatchFuture;
use codex_hepta_memory::ProductionDispatchRequest;
use codex_hepta_memory::ProductionEffectEntry;
use codex_hepta_memory::ProductionEntryCurrentness;
use codex_hepta_memory::ProductionOutboxTarget;
use codex_hepta_memory::ProductionTargetOutcome;
use codex_hepta_memory::ProductionTerminalObservation;
use codex_hepta_memory::ProductionTerminalObservationFuture;
use codex_hepta_native_agent::ToolObservation;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::ExecutionReceiptV1;
use codex_hepta_types::ExecutionStatusV1;
use codex_hepta_types::RecoveryDispositionV1;
use codex_hepta_types::RuntimeReceiptV1;
use codex_hepta_types::RuntimeToolIntentV1;
use codex_hepta_types::ToolOutcomeV1;
use hepta_runtime::mcp::runtime::jobs::ProcessStartParams;
use hepta_runtime::native::NativeJobOutcome;
use hepta_runtime::native::NativeTerminalOutput;
use serde_json::json;

pub const NATIVE_RUNTIME_TOPIC_V1: &str = "hepta.native.runtime.process.v1";

/// A registered production destination, sharing the configured runtime owner.
/// Each checked entry must carry its original turn-bound production gate.
pub struct NativeRuntimeTarget {
    destination_id: String,
    max_output_bytes: usize,
}

/// One observation of the original jobs owner's complete raw output. The
/// projection and production receipt refer to this same observation, not two
/// independently fetched or text-reconstructed values.
pub(crate) struct NativeToolTerminalEvidence {
    pub(crate) receipt: RuntimeReceiptV1,
    pub(crate) stdout: Vec<u8>,
    pub(crate) stderr: Vec<u8>,
    pub(crate) terminal_receipt: String,
}

impl NativeRuntimeTarget {
    pub fn new(destination_id: String, max_output_bytes: usize) -> Result<Self> {
        if destination_id.is_empty()
            || destination_id.len() > 128
            || !destination_id
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
            || max_output_bytes == 0
        {
            bail!("native runtime requires a bounded destination and output budget");
        }
        Ok(Self {
            destination_id,
            max_output_bytes,
        })
    }

    pub(crate) fn original_params(
        &self,
        request: &ProductionDispatchRequest,
    ) -> Result<ProcessStartParams> {
        if request.schema_version != PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION
            || request.namespace != PRODUCTION_DURABLE_WRITER_NAMESPACE
            || request.topic != NATIVE_RUNTIME_TOPIC_V1
            || request.operation_destination_id != self.destination_id
            || request.idempotency_key != request.occurrence_key
            || request.operation_policy_generation == 0
            || request.expected_predecessor_sha256.is_some()
            || Sha256Digest::for_bytes(request.payload_json.as_bytes()) != request.payload_sha256
        {
            bail!("runtime request is not the original production process operation");
        }
        let params: ProcessStartParams = serde_json::from_str(&request.payload_json)?;
        if params.idempotency_key.as_deref() != Some(request.idempotency_key.as_str())
            || params.host.trim().is_empty()
            || serde_json::to_vec(&params)? != request.payload_json.as_bytes()
        {
            bail!("runtime request does not preserve its exact admitted process payload");
        }
        Ok(params)
    }

    pub(crate) async fn observe_original(
        &self,
        request: &ProductionDispatchRequest,
    ) -> Result<Option<NativeTerminalOutput>> {
        let params = self.original_params(request)?;
        let observed =
            hepta_runtime::native::observe_terminal_output(&params, self.max_output_bytes).await?;
        if let Some(output) = observed.as_ref()
            && !output.matches_request(&params)?
        {
            bail!("runtime terminal output belongs to a different original request");
        }
        Ok(observed)
    }

    pub(crate) async fn cancel_original(&self, request: &ProductionDispatchRequest) -> Result<()> {
        let params = self.original_params(request)?;
        hepta_runtime::native::cancel_request(&params, /*grace_seconds*/ 1).await
    }

    /// Project evidence from the original jobs owner into the model-facing
    /// receipt. The calling host retains the production operation and settles
    /// its writer independently; this projection grants no execution authority.
    pub(crate) async fn observe_tool(
        &self,
        request: &ProductionDispatchRequest,
        intent: &RuntimeToolIntentV1,
    ) -> Result<ToolObservation> {
        Ok(match self.observe_tool_evidence(request, intent).await? {
            Some(evidence) => ToolObservation::Terminal {
                receipt: evidence.receipt,
                stdout: evidence.stdout,
                stderr: evidence.stderr,
            },
            None => ToolObservation::Accepted,
        })
    }

    pub(crate) async fn observe_tool_evidence(
        &self,
        request: &ProductionDispatchRequest,
        intent: &RuntimeToolIntentV1,
    ) -> Result<Option<NativeToolTerminalEvidence>> {
        intent.validate()?;
        let params = self.original_params(request)?;
        if intent.tool_id.as_str() != "process_start"
            || intent.idempotency_key.as_str() != request.idempotency_key
            || intent.host_scope.as_str() != params.host
            || intent.arguments_digest != Digest32::of_bytes(request.payload_json.as_bytes())
        {
            bail!("tool intent is not bound to the original production process request");
        }
        let Some(output) = self.observe_original(request).await? else {
            return Ok(None);
        };
        let exit_code = output.exit_code();
        let job_id = output.job_id().to_string();
        let outcome = terminal_outcome(output.outcome());
        let status = match output.outcome() {
            NativeJobOutcome::Succeeded => ExecutionStatusV1::Completed,
            NativeJobOutcome::Failed | NativeJobOutcome::Cancelled | NativeJobOutcome::TimedOut => {
                ExecutionStatusV1::Failed
            }
        };
        let (stdout, stderr) = output.into_streams();
        let tool_outcome = ToolOutcomeV1 {
            terminal_observed: true,
            exit_code: Some(exit_code),
            stdout_digest: Some(Digest32::of_bytes(&stdout)),
            stderr_digest: Some(Digest32::of_bytes(&stderr)),
            retryable: false,
        };
        let receipt = RuntimeReceiptV1 {
            execution: ExecutionReceiptV1 {
                operation_id: intent.cell.operation_id.clone(),
                intent_digest: intent.cell.intent_digest(),
                generation: intent.cell.generation,
                final_payload_digest: intent.cell.final_payload.clone(),
                outcome_digest: Some(tool_outcome.outcome_digest()),
                status,
                recovery: RecoveryDispositionV1::None,
                authority: AuthorityPosture::DENY_ALL,
            },
            runtime_intent_digest: intent.intent_digest(),
            tool_outcome,
        };
        receipt.validate_against(intent)?;
        let terminal_receipt =
            terminal_receipt_parts(request, &job_id, exit_code, outcome, &stdout, &stderr);
        Ok(Some(NativeToolTerminalEvidence {
            receipt,
            stdout,
            stderr,
            terminal_receipt,
        }))
    }

    pub(crate) async fn dispatch_effect_entry(
        &self,
        entry: ProductionEffectEntry,
        currentness: Arc<dyn ProductionEntryCurrentness>,
    ) -> ProductionTargetOutcome {
        let request = Arc::new(entry.request().clone());
        let params = match self.original_params(&request) {
            Ok(params) => params,
            Err(error) => {
                return ProductionTargetOutcome::Rejected {
                    reason: error.to_string(),
                };
            }
        };
        let ready = match entry.revalidate().await {
            Ok(ready) => ready,
            Err(error) => {
                return ProductionTargetOutcome::Indeterminate {
                    reason: format!("original runtime entry is no longer current: {error}"),
                };
            }
        };
        // The writer retained the exact signed grant. Claim it only after runtime owner
        // waits and durable preparation, immediately before the actual SSH
        // spawn. Existing unknown/pending jobs never invoke this callback.
        // Keep the original request available for observation without copying
        // its potentially large payload again solely to satisfy owned entry.
        let entry_request = Arc::clone(&request);
        let submitted =
            hepta_runtime::native::execute_or_observe_with_entry(params, move |actual| {
                if serde_json::to_vec(actual)? != entry_request.payload_json.as_bytes() {
                    bail!("runtime substituted the admitted process at physical entry");
                }
                Ok(ready.enter(currentness.as_ref())?)
            })
            .await;
        if let Err(error) = submitted {
            // Admission can already be durable. Errors, lost acknowledgements
            // and cancellation never refund the original key or authorize retry.
            return ProductionTargetOutcome::Indeterminate {
                reason: format!("original runtime submission requires observation: {error}"),
            };
        }
        match self.observe_original(&request).await {
            Ok(Some(output)) => ProductionTargetOutcome::Committed {
                receipt: terminal_receipt(&request, output),
            },
            Ok(None) => ProductionTargetOutcome::Indeterminate {
                reason: "original runtime job has no complete terminal publication".to_string(),
            },
            Err(error) => ProductionTargetOutcome::Indeterminate {
                reason: format!("original runtime observation remains unknown: {error}"),
            },
        }
    }
}

impl ProductionOutboxTarget for NativeRuntimeTarget {
    fn dispatch<'a>(&'a self, _request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        Box::pin(async {
            ProductionTargetOutcome::Rejected {
                reason: "native runtime requires the production writer's final-use handoff"
                    .to_string(),
            }
        })
    }
}

impl FinalUseProductionOutboxTarget for NativeRuntimeTarget {
    fn destination_id(&self) -> &str {
        &self.destination_id
    }

    fn observe_terminal<'a>(
        &'a self,
        request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        Box::pin(async move {
            match self.observe_original(request).await {
                Ok(Some(output)) => ProductionTerminalObservation::Applied {
                    receipt: terminal_receipt(request, output),
                },
                Ok(None) => ProductionTerminalObservation::Indeterminate {
                    reason: "original runtime job has no complete terminal publication".to_string(),
                },
                Err(error) => ProductionTerminalObservation::Unavailable {
                    reason: format!("original runtime observation unavailable: {error}"),
                },
            }
        })
    }
}

fn terminal_receipt(request: &ProductionDispatchRequest, output: NativeTerminalOutput) -> String {
    let job_id = output.job_id().to_string();
    let exit_code = output.exit_code();
    let outcome = terminal_outcome(output.outcome());
    let (stdout, stderr) = output.into_streams();
    terminal_receipt_parts(request, &job_id, exit_code, outcome, &stdout, &stderr)
}

fn terminal_outcome(outcome: NativeJobOutcome) -> &'static str {
    match outcome {
        NativeJobOutcome::Succeeded => "succeeded",
        NativeJobOutcome::Failed => "failed",
        NativeJobOutcome::Cancelled => "cancelled",
        NativeJobOutcome::TimedOut => "timed_out",
    }
}

fn terminal_receipt_parts(
    request: &ProductionDispatchRequest,
    job_id: &str,
    exit_code: i32,
    outcome: &str,
    stdout: &[u8],
    stderr: &[u8],
) -> String {
    // A nonzero process exit is still an observed physical effect. It must not
    // become NotApplied or authorize a resend. Tool completion maps the exit
    // outcome separately after the original writer has settled this receipt.
    json!({
        "schema_version": 2,
        "occurrence_key": request.occurrence_key,
        "operation_semantic_sha256": request.operation_semantic_sha256,
        "payload_sha256": request.payload_sha256,
        "job_id": job_id,
        "exit_code": exit_code,
        "outcome": outcome,
        "stdout_sha256": Sha256Digest::for_bytes(stdout),
        "stderr_sha256": Sha256Digest::for_bytes(stderr),
    })
    .to_string()
}

#[cfg(test)]
#[path = "native_runtime_target_tests.rs"]
mod tests;
