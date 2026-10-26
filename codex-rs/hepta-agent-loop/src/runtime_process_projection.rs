//! Verify output against the original durable effect receipt before projection.

use super::*;
use codex_hepta_automation::TaskFlowReconcileOutcome;
use codex_hepta_automation::TaskFlowStepObservation;

impl<A: RuntimeProcessOwner> RuntimeProcessEffectOwner<'_, A> {
    pub(super) async fn project(
        &self,
        receipt: TaskFlowStepReceipt,
        result: Option<RuntimeProcessResult>,
    ) -> Result<EffectObservation> {
        let effect = &self.admitted.0;
        if receipt.run_id != effect.intent.run_id
            || receipt.step_id != effect.intent.step_id
            || receipt.attempt != effect.intent.attempt
            || receipt.fence != effect.fence
            || receipt.intent_digest != effect.intent_digest
            || receipt.payload_digest != effect.intent.payload_digest
        {
            return Err(Error::Contract("original runtime receipt identity changed"));
        }
        let Some(status) = terminal_status(&receipt) else {
            return Ok(EffectObservation::Unresolved);
        };
        let result = match result {
            Some(result) => result,
            None => match self
                .driver
                .owner
                .observe(&self.driver.intent, &effect.payload)
                .await
            {
                RuntimeProcessObservation::Terminal(result) => result,
                RuntimeProcessObservation::Unresolved => return Ok(EffectObservation::Unresolved),
            },
        };
        let evidence = result.receipt(&self.driver.intent)?;
        if result.status != status
            || receipt.receipt_digest.as_ref() != Some(&evidence.receipt_digest)
        {
            return Err(Error::Contract(
                "original runtime output differs from its durable receipt",
            ));
        }
        let output: serde_json::Value = serde_json::from_str(&result.output)
            .map_err(|_| Error::Contract("original runtime output JSON"))?;
        let projected = serde_json::json!({
            "schema":"hepta-native-runtime-process:v1", "status":result.status_name(),
            "native_run_id":effect.binding.run_id.as_str(), "native_turn_id":effect.binding.turn_id.as_str(),
            "native_generation":effect.binding.generation.get(), "native_operation_key":effect.operation_key.to_string(),
            "native_mapping_digest":effect.mapping_digest.to_string(), "selected_call_index":effect.selected_index,
            "effect_run_id":receipt.run_id, "step_id":receipt.step_id, "attempt":receipt.attempt,
            "provider_occurrence_key":effect.provider_key.as_str(), "intent_digest":receipt.intent_digest.as_str(),
            "payload_digest":receipt.payload_digest.as_str(), "receipt_digest":evidence.receipt_digest.as_str(),
            "receipt_event_seq":receipt.event_seq, "job_identity_digest":result.job_identity_digest.as_str(),
            "owner_receipt_digest":result.owner_receipt_digest.as_str(), "output":output,
        });
        Ok(EffectObservation::Completed(
            serde_json::to_string(&projected)
                .map_err(|_| Error::Contract("runtime receipt serialization"))?,
        ))
    }
}

pub(super) fn terminal_status(receipt: &TaskFlowStepReceipt) -> Option<RuntimeProcessStatus> {
    match (receipt.final_outcome, receipt.observation) {
        (Some(TaskFlowReconcileOutcome::Succeeded), _)
        | (None, Some(TaskFlowStepObservation::Succeeded)) => Some(RuntimeProcessStatus::Succeeded),
        (Some(TaskFlowReconcileOutcome::Failed), _)
        | (None, Some(TaskFlowStepObservation::Failed)) => Some(RuntimeProcessStatus::Failed),
        _ => None,
    }
}

pub(super) fn stop_from(observation: EffectObservation) -> StopObservation {
    match observation {
        EffectObservation::Completed(_) => StopObservation::Stopped,
        EffectObservation::Unresolved => StopObservation::Unresolved,
    }
}
