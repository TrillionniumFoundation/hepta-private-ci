use serde_json::Value;

use crate::AutomationAcceptedTaskObservation;

pub(super) fn parse(
    result: &Value,
    stored_exact: bool,
    active_chain_member: bool,
) -> Option<Option<AutomationAcceptedTaskObservation>> {
    let Some(value) = result.get("accepted_task").filter(|value| !value.is_null()) else {
        return Some(None);
    };
    let task: AutomationAcceptedTaskObservation = serde_json::from_value(value.clone()).ok()?;
    if !stored_exact
        || !active_chain_member
        || task.schema_version != 1
        || !task.accepted_in_exact_packet
        || task.current_status != "settled"
        || [
            &task.task_id,
            &task.owner,
            &task.provider,
            &task.output_sha256,
            &task.accept_tx_id,
        ]
        .into_iter()
        .any(|value| !super::lower_hex_32(value) || value.bytes().all(|byte| byte == b'0'))
    {
        return None;
    }
    Some(Some(task))
}
