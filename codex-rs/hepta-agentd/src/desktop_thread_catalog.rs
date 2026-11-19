//! The explicit six-tool catalog for a newly created original Core thread.
//! Existing Notes-only threads retain the exact original three-tool catalog.
use codex_app_server_protocol::DynamicToolFunctionSpec;
use codex_app_server_protocol::DynamicToolSpec;
use serde_json::json;

pub(crate) const CALCULATOR_READ_TOOL: &str = "hepta_calculator_state";
pub(crate) const CALCULATOR_EVALUATE_TOOL: &str = "hepta_calculator_evaluate";
pub(crate) const CALCULATOR_STATUS_TOOL: &str = "hepta_calculator_status";

/// Catalog metadata grants no authority. The original callback owner enforces
/// the shared durable per-turn fence for both effect tools, including unknowns.
pub fn original_desktop_thread_tools() -> Vec<DynamicToolSpec> {
    let mut tools = crate::original_notes_thread_tools();
    for tool in &mut tools {
        if let DynamicToolSpec::Function(function) = tool
            && function.name == "hepta_notes_status"
        {
            function.description = "Read only the original retained Notes operation in this same thread, using turn_id and call_id or selector {kind: latest_original_replace}. Selection uses the original protected sender's complete bounded retained history; missing or ambiguous history is unknown. Preserve its original application, destination and operation identity. The causal receipt and independent current_state are separate. This never prepares, signs, sends or repeats an operation.".into();
        }
        if let DynamicToolSpec::Function(function) = tool
            && function.name == "hepta_notes_replace"
        {
            function.description = "Replace the attached Notes document at its independently observed revision. This and hepta_calculator_evaluate share one effect attempt per original turn. After either attempt, use only state/status tools for the rest of the turn. Switching application, call ID or arguments cannot retry an unknown effect. Root must authorize the exact original operation.".into();
        }
    }
    let operand = || json!({"type":"string","minLength":1,"maxLength":20,"pattern":"^(0|-?[1-9][0-9]{0,18})$"});
    for (name, description, input_schema) in [
        (
            CALCULATOR_READ_TOOL,
            "Read the attached Calculator's current target, revision, operands, operator and result. Current state is independent of earlier operation receipts and grants no effect authority.",
            json!({
                "type":"object","properties":{},"required":[],"additionalProperties":false
            }),
        ),
        (
            CALCULATOR_EVALUATE_TOOL,
            "Evaluate one checked signed i64 arithmetic operation at the revision from hepta_calculator_state. Operands are canonical decimal strings; divide must be integral. Root authorizes the exact original target and operation. This and hepta_notes_replace share one effect attempt per original turn. After any attempt use only state/status tools; a new call or target cannot repeat an unknown effect.",
            json!({
                "type":"object","properties":{
                    "left":operand(),"operator":{"type":"string","enum":["add","subtract","multiply","divide"]},
                    "right":operand(),"expected_revision":{"type":"integer","minimum":0}
                },"required":["left","operator","right","expected_revision"],"additionalProperties":false
            }),
        ),
        (
            CALCULATOR_STATUS_TOOL,
            "Read only the original retained Calculator operation in this same thread, using its turn_id and call_id or selector {kind: latest_original_evaluate}. Selection uses the original protected sender's complete bounded retained history. Unknown, missing or ambiguous history and changed incarnation never authorize another effect. Preserve the original application, destination and operation identity. The causal original receipt and independent current_state are separate. This never prepares, signs, sends or repeats an operation.",
            json!({
                "type":"object","properties":{
                    "turn_id":{"type":"string","maxLength":128},"call_id":{"type":"string","maxLength":128},
                    "selector":{"type":"object","properties":{"kind":{"type":"string","enum":["latest_original_evaluate"]}},"required":["kind"],"additionalProperties":false}
                },"oneOf":[{"required":["turn_id","call_id"],"not":{"required":["selector"]}},
                    {"required":["selector"],"not":{"anyOf":[{"required":["turn_id"]},{"required":["call_id"]}]}}],
                "additionalProperties":false
            }),
        ),
    ] {
        tools.push(DynamicToolSpec::Function(DynamicToolFunctionSpec {
            name: name.into(),
            description: description.into(),
            input_schema,
            defer_loading: false,
        }));
    }
    tools
}

#[cfg(test)]
#[path = "desktop_thread_catalog_tests.rs"]
mod tests;
