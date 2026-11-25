//! Preserve the native exact-task binding without changing local effect authority.

use codex_hepta_agent_protocol::AutomationEffectTaskAcceptanceV1;
use serde_json::Value;

pub(super) fn parse(result: &Value) -> Option<Option<AutomationEffectTaskAcceptanceV1>> {
    let Some(value) = result.get("accepted_task").filter(|value| !value.is_null()) else {
        // Historical native observations and ambiguous/missing acceptances carry
        // no task match. They are never inferred from height or work depth.
        return Some(None);
    };
    let task: AutomationEffectTaskAcceptanceV1 = serde_json::from_value(value.clone()).ok()?;
    task.is_settled_in_exact_packet().then_some(Some(task))
}

#[cfg(test)]
#[path = "automation_effect_host_pon_task_acceptance_tests.rs"]
mod tests;
