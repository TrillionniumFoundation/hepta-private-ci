//! Qualification-only checkpoint projection; canonical contracts remain unchanged.
use crate::owner::SessionOwner;
use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use codex_hepta_native_agent::ModelRequest;
use codex_hepta_native_agent::PendingTool;
use codex_hepta_native_agent::ToolCall;
use codex_hepta_native_agent::TurnBinding;
use codex_hepta_native_agent::TurnState;
use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;

pub fn binding_json(binding: &TurnBinding) -> Value {
    json!({"thread":binding.thread_id.as_str(),"turn":binding.turn_id.as_str(),
        "operation":binding.operation_id.as_str(),"generation":binding.generation.get()})
}

pub fn call_json(call: &ToolCall) -> Value {
    json!({"call_id":call.call_id,"name":call.name,"arguments":String::from_utf8_lossy(&call.arguments)})
}

pub fn parse_call(value: &Value) -> Result<ToolCall> {
    Ok(ToolCall {
        call_id: text(value, "call_id")?,
        name: text(value, "name")?,
        arguments: text(value, "arguments")?.into_bytes(),
    })
}

fn text(value: &Value, key: &str) -> Result<String> {
    Ok(value[key]
        .as_str()
        .with_context(|| format!("missing checkpoint {key}"))?
        .to_owned())
}

pub fn encode(state: &TurnState) -> Result<Value> {
    let pending = state.pending_tool.as_ref().map(|pending| json!({"call":call_json(&pending.call),
        "intent_digest":pending.intent.intent_digest().to_string(),
        "arguments_digest":Digest32::of_bytes(&pending.arguments).to_string(),
        "submission_attempted":pending.submission_attempted,"cancel_requested":pending.cancel_requested}));
    let model = state.pending_model.as_ref().map(|request| {
        json!({"operation_id":request.operation_id,
        "body":String::from_utf8_lossy(&request.body)})
    });
    Ok(
        json!({"binding":binding_json(&state.binding),"context":state.context,"model_calls":state.model_calls,
        "tool_calls":state.tool_calls,"pending_model":model,"provider_response_id":state.provider_response_id,
        "queued_tools":state.queued_tools.iter().map(call_json).collect::<Vec<_>>(),"pending_tool":pending,
        "completed_call_ids":state.completed_call_ids,"final_answer":state.final_answer,"cancelled":state.cancelled,
        "last_error":state.last_error,"model_usage":state.model_usage}),
    )
}

pub fn restore(owner: &SessionOwner, value: Value) -> Result<TurnState> {
    if value["binding"] != binding_json(&owner.binding) {
        bail!("checkpoint belongs to another turn");
    }
    let mut state = TurnState::new(owner.binding.clone(), String::new());
    state.context = serde_json::from_value(value["context"].clone())?;
    state.model_calls = serde_json::from_value(value["model_calls"].clone())?;
    state.tool_calls = serde_json::from_value(value["tool_calls"].clone())?;
    state.provider_response_id = serde_json::from_value(value["provider_response_id"].clone())?;
    state.completed_call_ids = serde_json::from_value(value["completed_call_ids"].clone())?;
    state.final_answer = serde_json::from_value(value["final_answer"].clone())?;
    state.cancelled = serde_json::from_value(value["cancelled"].clone())?;
    state.last_error = serde_json::from_value(value["last_error"].clone())?;
    state.model_usage = serde_json::from_value(value["model_usage"].clone())?;
    state.queued_tools = value["queued_tools"]
        .as_array()
        .context("queued calls missing")?
        .iter()
        .map(parse_call)
        .collect::<Result<_>>()?;
    if !value["pending_model"].is_null() {
        let model = &value["pending_model"];
        let request = ModelRequest {
            operation_id: text(model, "operation_id")?,
            body: text(model, "body")?.into_bytes(),
        };
        let index = state
            .model_calls
            .checked_sub(1)
            .context("pending model without admission count")?;
        let stored: Value = serde_json::from_slice(&crate::persist::read_regular(
            &owner.store.root.join(format!("model-{index:08}.json")),
        )?)?;
        if stored != *model {
            bail!("pending model differs from immutable admission");
        }
        state.pending_model = Some(request);
    }
    if !value["pending_tool"].is_null() {
        let pending = &value["pending_tool"];
        let call = parse_call(&pending["call"])?;
        let admitted = owner.load_call(&call)?;
        if pending["intent_digest"] != admitted.intent.intent_digest().to_string()
            || pending["arguments_digest"] != Digest32::of_bytes(&admitted.arguments).to_string()
        {
            bail!("pending tool differs from immutable original request");
        }
        state.pending_tool = Some(PendingTool {
            call,
            intent: admitted.intent,
            arguments: admitted.arguments,
            submission_attempted: serde_json::from_value(pending["submission_attempted"].clone())?,
            cancel_requested: serde_json::from_value(pending["cancel_requested"].clone())?,
        });
    }
    Ok(state)
}
