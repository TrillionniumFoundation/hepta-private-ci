use pretty_assertions::assert_eq;

use super::*;
use codex_hepta_native_agent::{Limits, TurnBinding};
use codex_hepta_types::{Generation, StableId};
use serde_json::json;
use std::time::Duration;

fn agent() -> NativeAgent {
    NativeAgent {
        model_name: "original-model".to_owned(), instructions: "original instructions".to_owned(),
        tools: vec![json!({"type":"function", "name":"original_tool"})], store_responses: true,
        limits: Limits { context_bytes: 48 * 1024, output_tokens: 128, model_calls: 2,
            tool_calls: 3, tool_output_bytes: 1024, model_timeout: Duration::new(10, 1),
            tool_timeout: Duration::new(20, 2), observation_interval: Duration::new(0, 100) },
    }
}

fn correlation(agent: &NativeAgent) -> Result<NativeHostedCorrelationV1> {
    Ok(serde_json::from_value(json!({
        "schema": CORRELATION_SCHEMA, "agent_id":"agent", "thread_id":"thread", "turn_id":"turn",
        "run_id":"run", "lease_id":"lease", "fleet_generation":"1", "policy_generation":"1",
        "cell_id":"cell", "organ_id":"organ", "final_scope_id":"organ",
        "rendered_context_sha256":"a".repeat(64), "context_receipt_sha256":"b".repeat(64),
        "compilation_receipt_sha256":"c".repeat(64),
        "execution_config_sha256": execution_config::digest(agent)?,
    }))?)
}

#[test]
fn retained_preparation_binds_every_limit_beyond_the_first_model_request() {
    let original = agent();
    let binding = correlation(&original).expect("original configuration fixture");
    binding.verify_preparation_config(&original).unwrap();
    let state = TurnState::new(TurnBinding {
        thread_id: StableId::new("thread").unwrap(), turn_id: StableId::new("turn").unwrap(),
        operation_id: StableId::new("run").unwrap(), generation: Generation::new(1).unwrap(),
    }, "original input".to_owned());
    let body = original.model_request_body(&state).unwrap();
    for field in 0..8 {
        let mut changed = agent();
        match field {
            0 => changed.limits.context_bytes += 1,
            1 => changed.limits.output_tokens += 1,
            2 => changed.limits.model_calls += 1,
            3 => changed.limits.tool_calls += 1,
            4 => changed.limits.tool_output_bytes += 1,
            5 => changed.limits.model_timeout += Duration::from_nanos(1),
            6 => changed.limits.tool_timeout += Duration::from_nanos(1),
            _ => changed.limits.observation_interval += Duration::from_nanos(1),
        }
        if field != 1 { assert_eq!(changed.model_request_body(&state).unwrap(), body); }
        assert!(binding.verify_preparation_config(&changed).is_err(), "changed limit {field}");
    }
}

#[test]
fn retained_configuration_includes_provider_tools_and_exact_duration_components() {
    let binding = correlation(&agent()).expect("original configuration fixture");
    for field in 0..7 {
        let mut changed = agent();
        match field {
            0 => changed.model_name.push_str("-changed"),
            1 => changed.instructions.push_str(" changed"),
            2 => changed.tools[0]["name"] = json!("changed_tool"),
            3 => changed.store_responses = false,
            4 => changed.limits.model_timeout += Duration::from_secs(1),
            5 => changed.limits.tool_timeout += Duration::from_secs(1),
            _ => changed.limits.observation_interval += Duration::from_secs(1),
        }
        assert!(binding.verify_preparation_config(&changed).is_err(), "changed configuration {field}");
    }
}

#[test]
fn legacy_observation_never_supplies_a_missing_preparation_configuration() {
    let original = agent();
    let mut value = serde_json::to_value(correlation(&original).expect("original configuration fixture")).unwrap();
    value["schema"] = json!(LEGACY_CORRELATION_SCHEMA);
    value.as_object_mut().unwrap().remove("execution_config_sha256");
    let legacy: NativeHostedCorrelationV1 = serde_json::from_value(value.clone()).unwrap();
    legacy.validate_schema().unwrap();
    assert!(legacy.verify_preparation_config(&original).is_err());
    value["schema"] = json!(CORRELATION_SCHEMA);
    let missing: NativeHostedCorrelationV1 = serde_json::from_value(value).unwrap();
    assert!(missing.validate_schema().is_err());
    let current = correlation(&original).expect("original configuration fixture");
    let mut observation_config = agent();
    observation_config.limits.model_timeout += Duration::from_secs(1);
    current.validate_schema().unwrap(); // Observer accepts original metadata without reconfiguration.
    assert!(current.verify_preparation_config(&observation_config).is_err());
}
