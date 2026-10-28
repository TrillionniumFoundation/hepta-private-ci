//! Pure projection of a runtime tool intent onto the existing canonical ABI.
//!
//! No execution authority or effect receipt is created here. The source runtime
//! intent remains the owner of its payload, tool and recovery semantics.

use codex_execution_core::Currentness;
use codex_execution_core::ExecutionBinding;
use codex_execution_core::ExecutionClass;
use codex_execution_core::ExecutionError;
use codex_execution_core::ExecutionIntent;
use codex_execution_core::ExecutionRecord;
use codex_hepta_types::RuntimeToolIntentV1;

/// Project an already compiled tool request without changing either v1 wire identity.
///
/// The independent caller supplies the original principal, run, turn, objective,
/// policy and currentness evidence. For this projection `candidate_digest` must
/// be the entire `RuntimeToolIntentV1::intent_digest()`, not a model's proposed
/// arguments. This binds the tool, both cell and organ identities, source input,
/// deadline, final payload, host and idempotency key even though the canonical
/// envelope names exactly one cell or organ. `class` remains the trusted host's
/// effect classification; a model must not select it.
///
/// A returned intent is structural correlation only. The original effect owner
/// must durably admit it and independently verify final use at physical entry.
pub fn canonical_runtime_intent_v1(
    binding: ExecutionBinding,
    operation: &RuntimeToolIntentV1,
    class: ExecutionClass,
) -> Result<ExecutionIntent, ExecutionError> {
    operation
        .validate()
        .map_err(|_| ExecutionError::Binding("invalid runtime tool intent"))?;
    binding.validate()?;
    let subject_matches = match (&binding.cell_id, &binding.organ_id) {
        (Some(cell), None) => cell == operation.cell.cell_id.as_str(),
        (None, Some(organ)) => organ == operation.cell.organ_id.as_str(),
        (None, None) | (Some(_), Some(_)) => false,
    };
    if !subject_matches
        || binding.operation_id != operation.cell.operation_id.as_str()
        || binding.generation != operation.cell.generation.get()
        || binding.host != operation.host_scope.as_str()
        || binding.idempotency_key != operation.idempotency_key.as_str()
        || binding.candidate_digest != operation.intent_digest().to_string()
        || binding.currentness != Currentness::Current
    {
        return Err(ExecutionError::Binding(
            "runtime operation requires exact external admission",
        ));
    }
    let intent = ExecutionIntent {
        binding,
        class,
        // validate() above requires arguments_digest == final_payload.digest.
        // input_digest refers to model/source input, not the dispatched bytes.
        payload_digest: operation.cell.final_payload.digest.to_string(),
    };
    ExecutionRecord::ExecutionIntent(intent.clone()).validate()?;
    Ok(intent)
}

#[cfg(test)]
#[path = "runtime_execution_core_tests.rs"]
mod tests;
