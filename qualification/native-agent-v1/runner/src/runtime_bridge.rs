//! Qualification-only binding of the native loop to the existing runtime owner.
//!
//! Admission and persistence belong to SessionOwner. This bridge allocates no
//! operation identities and owns no effect journal. It accepts only the exact
//! compiled ProcessStartParams bytes already admitted by that owner.

use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use codex_hepta_native_agent::ToolObservation;
use codex_hepta_native_agent::ToolPort;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::ExecutionReceiptV1;
use codex_hepta_types::ExecutionStatusV1;
use codex_hepta_types::RecoveryDispositionV1;
use codex_hepta_types::RuntimeReceiptV1;
use codex_hepta_types::RuntimeToolIntentV1;
use codex_hepta_types::ToolOutcomeV1;
use hepta_runtime::mcp::runtime::jobs::ProcessCancelParams;
use hepta_runtime::mcp::runtime::jobs::ProcessReadParams;
use hepta_runtime::mcp::runtime::jobs::ProcessRefParams;
use hepta_runtime::mcp::runtime::jobs::ProcessStartParams;
use hepta_runtime::mcp::runtime::runtime_config;
use serde_json::Value;
use serde_json::json;

use crate::runtime_output::bounded_terminal_output;

#[path = "runtime_bridge_wire.rs"]
mod wire;
use wire::decode_page;
use wire::require_job_id;
use wire::terminal_proof;
use wire::validate_admission;
use wire::validate_job;
use wire::validate_observation_envelope;

const PAGE_BYTES: u64 = 16 * 1024;

/// Immutable admission retained by the embedding owner across reconnects.
#[derive(Clone, Debug)]
pub struct AdmittedTool {
    pub intent: RuntimeToolIntentV1,
    /// Exact serde_json::to_vec(&params) bytes, not the model's proposal bytes.
    pub arguments: Vec<u8>,
    pub params: ProcessStartParams,
}

/// Read the original owner admission. Implementations must reject stale or
/// substituted identities and must not allocate/admit anything in this method.
pub trait AdmissionResolver: Send + Sync {
    fn resolve(&self, intent: &RuntimeToolIntentV1) -> Result<AdmittedTool>;
}

impl<T: AdmissionResolver + ?Sized> AdmissionResolver for Arc<T> {
    fn resolve(&self, intent: &RuntimeToolIntentV1) -> Result<AdmittedTool> {
        self.as_ref().resolve(intent)
    }
}

pub struct RuntimeToolBridge<R: AdmissionResolver> {
    resolver: R,
    max_output_bytes: usize,
    model_item_bytes: Option<usize>,
}

impl<R: AdmissionResolver> RuntimeToolBridge<R> {
    pub fn new(resolver: R, max_output_bytes: usize) -> Result<Self> {
        if max_output_bytes == 0 {
            bail!("native runtime bridge requires a nonzero output budget");
        }
        Ok(Self {
            resolver,
            max_output_bytes,
            model_item_bytes: None,
        })
    }

    /// Keep the original full-byte retention bound separate from the model's
    /// per-item presentation budget. This policy is frozen by SessionOwner.
    pub fn with_model_item_bytes(mut self, limit: Option<usize>) -> Result<Self> {
        if limit.is_some_and(|value| value < 3072) {
            bail!("model item budget is too small for an original-owner reference");
        }
        self.model_item_bytes = limit;
        Ok(self)
    }

    fn admitted(
        &self,
        intent: &RuntimeToolIntentV1,
        submitted: Option<&[u8]>,
    ) -> Result<AdmittedTool> {
        let admitted = self.resolver.resolve(intent)?;
        validate_admission(&admitted, intent, submitted)?;
        Ok(admitted)
    }

    async fn observe_envelope(
        &self,
        admitted: &AdmittedTool,
        envelope: Value,
    ) -> Result<ToolObservation> {
        let configured = runtime_config()?.host(&admitted.params.host)?;
        let job_id = validate_job(&envelope, admitted, configured)?;
        let status = match envelope.get("status") {
            Some(value) => value.clone(),
            None => serde_json::from_str(
                &hepta_runtime::native::status(ProcessRefParams {
                    host: admitted.params.host.clone(),
                    job_id: job_id.clone(),
                })
                .await?,
            )?,
        };
        let Some(proof) = terminal_proof(&status, &job_id)? else {
            return Ok(ToolObservation::Accepted);
        };
        let total = proof
            .stdout_bytes
            .checked_add(proof.stderr_bytes)
            .context("runtime output length overflow")?;
        if u128::from(total) > self.max_output_bytes as u128 {
            bail!("original runtime output exceeds the admitted retention budget");
        }

        let mut stdout = Vec::new();
        let mut stderr = Vec::new();
        let mut stdout_offset = 0;
        let mut stderr_offset = 0;
        let page_limit = PAGE_BYTES.min(u64::try_from(self.max_output_bytes)?);
        loop {
            let page: Value = serde_json::from_str(
                &hepta_runtime::native::read(ProcessReadParams {
                    host: admitted.params.host.clone(),
                    job_id: job_id.clone(),
                    stdout_offset: Some(stdout_offset),
                    stderr_offset: Some(stderr_offset),
                    limit: Some(page_limit),
                })
                .await?,
            )?;
            require_job_id(&page, &job_id)?;
            let out = decode_page(
                &page["stdout"],
                stdout_offset,
                proof.stdout_bytes,
                page_limit,
            )?;
            let err = decode_page(
                &page["stderr"],
                stderr_offset,
                proof.stderr_bytes,
                page_limit,
            )?;
            let next_size = stdout
                .len()
                .checked_add(stderr.len())
                .and_then(|n| n.checked_add(out.bytes.len()))
                .and_then(|n| n.checked_add(err.bytes.len()))
                .context("runtime output accumulation overflow")?;
            if next_size > self.max_output_bytes {
                bail!("runtime output exceeds the admitted retention budget");
            }
            stdout.extend_from_slice(&out.bytes);
            stderr.extend_from_slice(&err.bytes);
            stdout_offset = out.next_offset;
            stderr_offset = err.next_offset;
            if out.eof && err.eof {
                break;
            }
        }

        // Re-resolve the same full original request after reading. The registry
        // or terminal publication changing cannot manufacture a final receipt.
        let final_raw = hepta_runtime::native::observe_request(admitted.params.clone())
            .await?
            .context("original runtime binding unavailable after output read; reconcile only")?;
        let final_envelope: Value = serde_json::from_str(&final_raw)?;
        validate_observation_envelope(&final_envelope)?;
        let final_id = validate_job(&final_envelope, admitted, configured)?;
        if final_id != job_id
            || terminal_proof(&final_envelope["status"], &job_id)?.as_ref() != Some(&proof)
        {
            bail!("original runtime terminal publication changed while reading output");
        }

        let tool_outcome = ToolOutcomeV1 {
            terminal_observed: true,
            exit_code: Some(proof.exit_code),
            stdout_digest: Some(Digest32::of_bytes(&stdout)),
            stderr_digest: Some(Digest32::of_bytes(&stderr)),
            retryable: false,
        };
        let receipt = RuntimeReceiptV1 {
            execution: ExecutionReceiptV1 {
                operation_id: admitted.intent.cell.operation_id.clone(),
                intent_digest: admitted.intent.cell.intent_digest(),
                generation: admitted.intent.cell.generation,
                final_payload_digest: admitted.intent.cell.final_payload.clone(),
                outcome_digest: Some(tool_outcome.outcome_digest()),
                status: if proof.state == "succeeded" {
                    ExecutionStatusV1::Completed
                } else {
                    ExecutionStatusV1::Failed
                },
                recovery: RecoveryDispositionV1::None,
                authority: AuthorityPosture::DENY_ALL,
            },
            runtime_intent_digest: admitted.intent.intent_digest(),
            tool_outcome,
        };
        receipt.validate_against(&admitted.intent)?;
        Ok(ToolObservation::Terminal {
            receipt,
            stdout,
            stderr,
        })
    }
}

impl<R: AdmissionResolver> ToolPort for RuntimeToolBridge<R> {
    async fn present_output(
        &self,
        intent: &RuntimeToolIntentV1,
        receipt: &RuntimeReceiptV1,
        stdout: &[u8],
        stderr: &[u8],
    ) -> Result<String> {
        receipt.validate_against(intent)?;
        if !receipt.tool_outcome.terminal_observed
            || receipt.tool_outcome.stdout_digest != Some(Digest32::of_bytes(stdout))
            || receipt.tool_outcome.stderr_digest != Some(Digest32::of_bytes(stderr))
            || stdout.len().saturating_add(stderr.len()) > self.max_output_bytes
        {
            bail!("presentation requires the complete verified terminal bytes");
        }
        let Some(limit) = self.model_item_bytes else {
            return Ok(json!({"exit_code":receipt.tool_outcome.exit_code,
                "stdout":String::from_utf8_lossy(stdout),"stderr":String::from_utf8_lossy(stderr)}).to_string());
        };
        let admitted = self.admitted(intent, None)?;
        let raw = hepta_runtime::native::observe_request(admitted.params.clone())
            .await?
            .context("original retained output binding is unavailable")?;
        let envelope: Value = serde_json::from_str(&raw)?;
        validate_observation_envelope(&envelope)?;
        let job_id = validate_job(&envelope, &admitted, runtime_config()?.host(&admitted.params.host)?)?;
        let proof = terminal_proof(&envelope["status"], &job_id)?
            .context("retained output lost its original terminal publication")?;
        if u128::from(proof.stdout_bytes) != stdout.len() as u128
            || u128::from(proof.stderr_bytes) != stderr.len() as u128
            || Some(proof.exit_code) != receipt.tool_outcome.exit_code
        {
            bail!("retained output reference changed after complete verification");
        }
        let retained = json!({
            "host":admitted.params.host,"job_id":job_id,
            "operation_id":intent.cell.operation_id.as_str(),
            "idempotency_key":intent.idempotency_key.as_str(),
            "runtime_intent_digest":receipt.runtime_intent_digest.to_string(),
            "stdout":{"bytes":stdout.len(),"sha256":Digest32::of_bytes(stdout).to_string()},
            "stderr":{"bytes":stderr.len(),"sha256":Digest32::of_bytes(stderr).to_string()},
        });
        bounded_terminal_output(receipt.tool_outcome.exit_code, stdout, stderr, retained, limit)
    }

    async fn execute_or_observe(
        &self,
        intent: &RuntimeToolIntentV1,
        arguments: &[u8],
    ) -> Result<ToolObservation> {
        let admitted = self.admitted(intent, Some(arguments))?;
        let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis();
        if now > u128::from(intent.cell.deadline_ms) {
            bail!("tool deadline expired before native runtime submission");
        }
        let envelope = serde_json::from_str(
            &hepta_runtime::native::execute_or_observe(admitted.params.clone()).await?,
        )?;
        self.observe_envelope(&admitted, envelope).await
    }

    async fn observe(&self, intent: &RuntimeToolIntentV1) -> Result<ToolObservation> {
        let admitted = self.admitted(intent, None)?;
        let Some(raw) = hepta_runtime::native::observe_request(admitted.params.clone()).await?
        else {
            // Absence in this registry is not proof of non-admission. The host
            // keeps submission_attempted and the exact original identity.
            return Ok(ToolObservation::Accepted);
        };
        let envelope: Value = serde_json::from_str(&raw)?;
        validate_observation_envelope(&envelope)?;
        self.observe_envelope(&admitted, envelope).await
    }

    async fn cancel(&self, intent: &RuntimeToolIntentV1) -> Result<()> {
        let admitted = self.admitted(intent, None)?;
        // Never call execute_or_observe to discover a lost job ID.
        let raw = hepta_runtime::native::observe_request(admitted.params.clone())
            .await?
            .context("original runtime binding not found; cancellation remains unconfirmed")?;
        let envelope: Value = serde_json::from_str(&raw)?;
        validate_observation_envelope(&envelope)?;
        let job_id = validate_job(
            &envelope,
            &admitted,
            runtime_config()?.host(&admitted.params.host)?,
        )?;
        let result: Value = serde_json::from_str(
            &hepta_runtime::native::cancel(ProcessCancelParams {
                host: admitted.params.host.clone(),
                job_id: job_id.clone(),
                grace_seconds: Some(1),
            })
            .await?,
        )?;
        require_job_id(&result, &job_id)?;
        if !matches!(
            result["result"].as_str(),
            Some("already_exited" | "stop_requested" | "term_sent" | "kill_sent" | "not_running")
        ) {
            bail!("original runtime cancellation outcome is unknown; observe the same request");
        }
        // An acknowledgement is not terminality. ToolPort's owner continues
        // observing the same request before considering cancellation complete.
        Ok(())
    }
}
