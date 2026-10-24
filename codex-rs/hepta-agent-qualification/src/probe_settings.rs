//! Original model-owner lookup and bounded ordinary-request settings evidence.
//! Offline preserves that owner's cache/auth rules; it is not full Core parity.

use crate::evidence::Evidence;
use anyhow::Result;
use anyhow::anyhow;
use codex_core::config::Config;
use codex_hepta_types::Digest32;
use codex_model_provider::ResponsesModelSettings;
use codex_model_provider::SharedModelProvider;
use codex_models_manager::manager::RefreshStrategy;
use codex_protocol::openai_models::ModelInfo;
use serde_json::Value;
use serde_json::json;
use std::time::Duration;

pub(super) struct PreparedSettings {
    pub(super) settings: ResponsesModelSettings,
    pub(super) evidence_digest: Digest32,
}

pub(super) async fn prepare(
    config: &Config,
    provider: &SharedModelProvider,
    requested_model: &str,
    evidence: &Evidence,
) -> Result<PreparedSettings> {
    let manager = provider.models_manager(
        config.codex_home.to_path_buf(),
        config.model_catalog.clone(),
    );
    let model = tokio::time::timeout(Duration::from_secs(20), async {
        // Populate through the original owner. Do not open a second cache,
        // forge a client version, change auth policy or refresh a catalog online.
        manager
            .raw_model_catalog(RefreshStrategy::Offline, config.http_client_factory())
            .await;
        manager
            .get_model_info(requested_model, &config.to_models_manager_config())
            .await
    })
    .await
    .map_err(|_| anyhow!("qualification original model metadata deadline"))?;
    if model.slug != requested_model {
        return Err(anyhow!(
            "qualification original model metadata identity mismatch"
        ));
    }
    let settings = ResponsesModelSettings::for_model(
        &model,
        config.model_reasoning_effort.clone(),
        config.model_reasoning_summary,
        config.model_verbosity,
        config.service_tier.clone(),
    );
    let report = observation(config, &model, &settings);
    let evidence_digest = evidence
        .record("request-settings.json", &report)
        .map_err(|_| anyhow!("qualification request settings evidence failed"))?;
    require_ordinary_model(&model)?;
    Ok(PreparedSettings {
        settings,
        evidence_digest,
    })
}

fn require_ordinary_model(model: &ModelInfo) -> Result<()> {
    if model.use_responses_lite {
        // Lite also changes instructions/input/tools/parallel-call semantics.
        // Never attach only its header to this ordinary fixed-marker body.
        return Err(anyhow!(
            "qualification Responses Lite body and header are not qualified"
        ));
    }
    Ok(())
}

fn identifier(value: &str) -> Value {
    let symbolic = !value.is_empty()
        && value.len() <= 128
        && !value.starts_with('/')
        && !value.contains("//")
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"-_./".contains(&b));
    json!({"value":symbolic.then_some(value), "bytes":value.len(),
           "sha256":Digest32::of_bytes(value.as_bytes()).to_string()})
}

fn observation(config: &Config, model: &ModelInfo, settings: &ResponsesModelSettings) -> Value {
    json!({
        "schema":"hepta-native-request-settings:v1",
        "model":identifier(&model.slug),
        "catalog_refresh_strategy":"offline",
        "catalog_source":if config.model_catalog.is_some() { "configured_static" } else { "provider_owner_offline" },
        "used_fallback_model_metadata":model.used_fallback_model_metadata,
        "model_cache_client_version":codex_models_manager::client_version_to_whole(),
        "cache_hit":null, "cache_rejection_reason":null,
        "auth_owner_bootstrap_or_refresh_may_contact_network":true,
        "configured":{
            "effort":config.model_reasoning_effort.as_ref().map(|v| identifier(v.as_str())),
            "summary":config.model_reasoning_summary,
            "verbosity":config.model_verbosity,
            "service_tier":config.service_tier.as_deref().map(identifier),
        },
        "normalized":{
            "effort":settings.reasoning.effort.as_ref().map(|v| identifier(v.as_str())),
            "summary":settings.reasoning.summary,
            "reasoning_context":settings.reasoning.context,
            "verbosity":settings.verbosity,
            "service_tier":settings.service_tier.as_deref().map(identifier),
        },
        "use_responses_lite":model.use_responses_lite,
        "ordinary_fixed_marker_supported":!model.use_responses_lite,
        "pure_settings_shared_with_core":true,
        "catalog_refresh_matches_every_core_path":false,
        "full_core_body_header_or_auth_parity":false,
        "production_native_agent_qualified":false,
    })
}

#[cfg(test)]
#[path = "probe_settings_tests.rs"]
mod tests;
