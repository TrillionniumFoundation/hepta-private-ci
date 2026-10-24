//! Golden wire expectations for the original owner settings rules.
#![allow(
    clippy::expect_used,
    reason = "explicit original metadata serialization fixtures"
)]

use super::*;
use codex_protocol::openai_models::ModelServiceTier;
use pretty_assertions::assert_eq;
use serde_json::json;

fn fallback() -> ModelInfo {
    codex_models_manager::model_info::model_info_from_slug("settings-fixture")
}

#[test]
fn observed_fallback_configuration_keeps_max_adds_auto_and_filters_priority() {
    let model = fallback();
    assert!(model.used_fallback_model_metadata);
    let settings = ResponsesModelSettings::for_model(
        &model,
        Some(ReasoningEffort::Max),
        None,
        None,
        Some("priority".into()),
    );
    assert_eq!(
        serde_json::to_value(&settings.reasoning).expect("reasoning JSON"),
        json!({"effort":"max", "summary":"auto"})
    );
    assert_eq!(settings.verbosity, None);
    assert_eq!(settings.service_tier, None);
}

#[test]
fn effort_defaults_and_ultra_compatibility_do_not_downgrade_explicit_max_or_custom() {
    let mut model = fallback();
    model.default_reasoning_level = Some(ReasoningEffort::Ultra);
    assert_eq!(
        normalized_response_reasoning(&model, None, None).effort,
        Some(ReasoningEffort::Max)
    );
    assert_eq!(
        normalized_response_effort(ReasoningEffort::Max),
        ReasoningEffort::Max
    );
    assert_eq!(
        normalized_response_effort(ReasoningEffort::Ultra),
        ReasoningEffort::Max
    );
    assert_eq!(
        normalized_response_effort(ReasoningEffort::Custom("future-effort".into())),
        ReasoningEffort::Custom("future-effort".into())
    );
}

#[test]
fn disabled_or_unsupported_summary_is_omitted_instead_of_literal_none() {
    let mut model = fallback();
    let disabled = normalized_response_reasoning(&model, None, Some(ReasoningSummary::None));
    assert_eq!(
        serde_json::to_value(disabled).expect("reasoning JSON"),
        json!({})
    );
    model.supports_reasoning_summary_parameter = false;
    let unsupported = normalized_response_reasoning(&model, None, Some(ReasoningSummary::Auto));
    assert_eq!(
        serde_json::to_value(unsupported).expect("reasoning JSON"),
        json!({})
    );
}

#[test]
fn supported_verbosity_uses_configured_or_model_default_and_otherwise_omits() {
    let mut model = fallback();
    model.default_verbosity = Some(Verbosity::Low);
    assert_eq!(
        normalized_response_verbosity(&model, Some(Verbosity::High)),
        None
    );
    model.support_verbosity = true;
    assert_eq!(
        normalized_response_verbosity(&model, None),
        Some(Verbosity::Low)
    );
    assert_eq!(
        normalized_response_verbosity(&model, Some(Verbosity::High)),
        Some(Verbosity::High)
    );
}

#[test]
fn tier_filter_uses_original_method_without_inventing_a_default_tier() {
    let mut model = fallback();
    model.service_tiers = vec![ModelServiceTier {
        id: "priority".into(),
        name: "Fixture priority".into(),
        description: "Explicit fixture".into(),
    }];
    model.default_service_tier = Some("priority".into());
    for (configured, expected) in [
        (None, None),
        (Some("default"), None),
        (Some("unsupported"), None),
        (Some("priority"), Some("priority")),
    ] {
        let settings = ResponsesModelSettings::for_model(
            &model,
            None,
            None,
            None,
            configured.map(str::to_string),
        );
        assert_eq!(settings.service_tier.as_deref(), expected);
    }
}

#[test]
fn lite_reasoning_context_is_explicit_without_claiming_body_or_header_construction() {
    let mut model = fallback();
    assert_eq!(
        normalized_response_reasoning(&model, None, None).context,
        None
    );
    model.use_responses_lite = true;
    assert_eq!(
        normalized_response_reasoning(&model, None, None).context,
        Some(ReasoningContext::AllTurns)
    );
}
