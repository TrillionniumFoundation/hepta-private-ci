//! Pure Responses settings derived from the caller's original ModelInfo.
//!
//! This module performs no model lookup, authentication, routing, admission or
//! transport. Callers retain their original catalog refresh and owner policy.

use codex_api::Reasoning;
use codex_api::ReasoningContext;
use codex_protocol::config_types::ReasoningSummary;
use codex_protocol::config_types::Verbosity;
use codex_protocol::openai_models::ModelInfo;
use codex_protocol::openai_models::ReasoningEffort;

#[derive(Clone, Debug)]
pub struct ResponsesModelSettings {
    pub reasoning: Reasoning,
    pub verbosity: Option<Verbosity>,
    pub service_tier: Option<String>,
}

impl ResponsesModelSettings {
    /// Apply the original Core request rules to already resolved metadata.
    /// This does not certify that fallback metadata or a selected model is
    /// supported by a remote provider, and does not construct a Lite body.
    pub fn for_model(
        model: &ModelInfo,
        effort: Option<ReasoningEffort>,
        summary: Option<ReasoningSummary>,
        verbosity: Option<Verbosity>,
        service_tier: Option<String>,
    ) -> Self {
        Self {
            reasoning: normalized_response_reasoning(model, effort, summary),
            verbosity: normalized_response_verbosity(model, verbosity),
            service_tier: model.service_tier_for_request(service_tier),
        }
    }
}

/// Preserve explicit effort, including Max and custom provider values. Core's
/// existing compatibility spelling changes only Ultra to Max.
pub fn normalized_response_effort(effort: ReasoningEffort) -> ReasoningEffort {
    match effort {
        ReasoningEffort::Ultra => ReasoningEffort::Max,
        effort => effort,
    }
}

/// An unset summary follows the original TurnContext model default. Core can
/// pass Some(already-resolved-summary) to preserve its per-turn override.
pub fn normalized_response_reasoning(
    model: &ModelInfo,
    effort: Option<ReasoningEffort>,
    summary: Option<ReasoningSummary>,
) -> Reasoning {
    let summary = summary.unwrap_or(model.default_reasoning_summary);
    Reasoning {
        effort: effort
            .or_else(|| model.default_reasoning_level.clone())
            .map(normalized_response_effort),
        summary: (model.supports_reasoning_summary_parameter && summary != ReasoningSummary::None)
            .then_some(summary),
        context: model
            .use_responses_lite
            .then_some(ReasoningContext::AllTurns),
    }
}

pub fn normalized_response_verbosity(
    model: &ModelInfo,
    configured: Option<Verbosity>,
) -> Option<Verbosity> {
    if model.support_verbosity {
        configured.or(model.default_verbosity)
    } else {
        None
    }
}

#[cfg(test)]
#[path = "response_settings_tests.rs"]
mod tests;
