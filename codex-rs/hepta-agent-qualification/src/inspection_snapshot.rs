//! Whitelisted metadata only. No config/auth Debug, URL, prompt, ETag or credential output.

use super::CatalogObservation;
use super::InspectionFailure;
use super::InspectionResult;
use codex_core::config::Config;
use codex_features::Feature;
use codex_hepta_types::Digest32;
use codex_protocol::auth::AuthMode;
use codex_protocol::config_types::ReasoningSummary;
use codex_protocol::config_types::Verbosity;
use codex_protocol::openai_models::ReasoningEffort;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;
use std::io::Write;

const MAXIMUM_CATALOG_BYTES: usize = 8 * 1024 * 1024;
const MAXIMUM_CATALOG_MODELS: usize = 512;
const MAXIMUM_SETTING_CHOICES: usize = 64;
const MAXIMUM_SNAPSHOT_BYTES: usize = 65_536;

pub(super) struct Settings {
    pub(super) model: String,
    pub(super) provider_id: String,
    pub(super) configured_catalog: bool,
    pub(super) effort: Option<ReasoningEffort>,
    pub(super) summary: Option<ReasoningSummary>,
    pub(super) verbosity: Option<Verbosity>,
    pub(super) service_tier: Option<String>,
    pub(super) features: FeatureSnapshot,
}

#[derive(Serialize)]
pub(super) struct FeatureSnapshot {
    pub(super) use_agent_identity: bool,
    pub(super) request_compression: bool,
    pub(super) concurrent_reasoning_summaries: bool,
    pub(super) content_item_kinds: bool,
    pub(super) fast_mode: bool,
}

impl Settings {
    pub(super) fn from_config(config: &Config, model: &str) -> Self {
        Self {
            model: model.to_string(),
            provider_id: config.model_provider_id.clone(),
            configured_catalog: config.model_catalog.is_some(),
            effort: config.model_reasoning_effort.clone(),
            summary: config.model_reasoning_summary,
            verbosity: config.model_verbosity,
            service_tier: config.service_tier.clone(),
            features: FeatureSnapshot {
                use_agent_identity: config.features.enabled(Feature::UseAgentIdentity),
                request_compression: config.features.enabled(Feature::EnableRequestCompression),
                concurrent_reasoning_summaries: config
                    .features
                    .enabled(Feature::ConcurrentReasoningSummaries),
                content_item_kinds: config.features.enabled(Feature::ContentItemKinds),
                fast_mode: config.features.enabled(Feature::FastMode),
            },
        }
    }
}

/// Even whitelisted configuration strings can contain a URL or diagnostic
/// payload. Render only bounded symbolic labels; otherwise retain a digest.
pub(super) fn identifier(value: &str) -> Value {
    let symbolic = !value.is_empty()
        && value.len() <= 128
        && !value.starts_with('/')
        && !value.contains("//")
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"-_./".contains(&b));
    json!({
        "value":symbolic.then_some(value),
        "sha256":Digest32::of_bytes(value.as_bytes()).to_string(),
        "bytes":value.len(),
    })
}

pub(super) fn build(
    settings: &Settings,
    observed: &CatalogObservation,
    auth_before: Option<AuthMode>,
    auth_after: Option<AuthMode>,
) -> InspectionResult<Value> {
    let model = &observed.model;
    if model.slug != settings.model {
        return Err(InspectionFailure::ModelMismatch);
    }
    if observed.before.len() > MAXIMUM_CATALOG_MODELS
        || observed.active.len() > MAXIMUM_CATALOG_MODELS
        || model.supported_reasoning_levels.len() > MAXIMUM_SETTING_CHOICES
        || model.service_tiers.len() > MAXIMUM_SETTING_CHOICES
    {
        return Err(InspectionFailure::SnapshotBound);
    }
    let supported_efforts = model
        .supported_reasoning_levels
        .iter()
        .map(|preset| identifier(preset.effort.as_str()))
        .collect::<Vec<_>>();
    let service_tiers = model
        .service_tiers
        .iter()
        .map(|tier| identifier(&tier.id))
        .collect::<Vec<_>>();
    let owner_tier = model.service_tier_for_request(settings.service_tier.clone());
    let report = json!({
        "schema":"hepta-native-owner-inspection:v1",
        "inspection_completed":true,
        "generation_attempted":false, "maximum_responses_calls":0,
        "catalog_refresh_strategy":"offline", "catalog_fetch_requested":false,
        "auth_owner_bootstrap_or_refresh_may_contact_network":true,
        "auth_network_activity_observed":null,
        "auth_mode_before_catalog":auth_before, "auth_mode_after_catalog":auth_after,
        "compiled_package_version":env!("CARGO_PKG_VERSION"),
        "model_cache_client_version":codex_models_manager::client_version_to_whole(),
        "configured":{
            "model":identifier(&settings.model), "provider_id":identifier(&settings.provider_id),
            "reasoning_effort":settings.effort.as_ref().map(|e| identifier(e.as_str())),
            "reasoning_summary":settings.summary, "verbosity":settings.verbosity,
            "service_tier":settings.service_tier.as_deref().map(identifier),
            "auth_policy":if settings.features.use_agent_identity { "configured_chatgpt_agent_identity" } else { "configured_jwt_only" },
        },
        "catalog":{
            "source":if settings.configured_catalog { "configured_static" } else { "provider_owner_offline" },
            "before_serialized_sha256":catalog_digest(&observed.before)?,
            "active_serialized_sha256":catalog_digest(&observed.active)?,
            "before_model_count":observed.before.len(), "active_model_count":observed.active.len(),
            "values_changed_from_initial":observed.before != observed.active,
            "cache_may_apply":!settings.configured_catalog,
            "cache_hit":null,
            "cache_eligibility":if settings.configured_catalog { "not_applicable_to_configured_static_catalog" } else { "enforced_by_original_owner_result_not_exposed" },
            "cache_rejection_reason":null,
            "unchanged_catalog_does_not_prove_cache_miss":true,
        },
        "model_metadata":{
            "slug":identifier(&model.slug),
            "used_fallback_model_metadata":model.used_fallback_model_metadata,
            "default_reasoning_effort":model.default_reasoning_level.as_ref().map(|e| identifier(e.as_str())),
            "supported_reasoning_efforts":supported_efforts,
            "supports_reasoning_summary_parameter":model.supports_reasoning_summary_parameter,
            "default_reasoning_summary":model.default_reasoning_summary,
            "supports_verbosity":model.support_verbosity, "default_verbosity":model.default_verbosity,
            "supported_service_tier_ids":service_tiers,
            "default_service_tier":model.default_service_tier.as_deref().map(identifier),
            "configured_tier_accepted_by_original_model_method":owner_tier.as_deref().map(identifier),
            "use_responses_lite":model.use_responses_lite,
            "supported_in_api":model.supported_in_api,
        },
        "feature_flags":settings.features,
        "snapshot_digests_are_observations_not_signed_profile_attestations":true,
        "provider_model_support_or_tokenizer_qualified":false,
        "production_native_agent_qualified":false,
        "core_linked_for_config_bootstrap":true,
    });
    let encoded = serde_json::to_vec(&report).map_err(|_| InspectionFailure::SnapshotEncoding)?;
    if encoded.len() > MAXIMUM_SNAPSHOT_BYTES {
        return Err(InspectionFailure::SnapshotBound);
    }
    Ok(report)
}

fn catalog_digest(value: &impl Serialize) -> InspectionResult<String> {
    let mut writer = BoundedBytes {
        bytes: Vec::new(),
        maximum: MAXIMUM_CATALOG_BYTES,
    };
    serde_json::to_writer(&mut writer, value).map_err(|_| InspectionFailure::SnapshotBound)?;
    Ok(Digest32::of_bytes(&writer.bytes).to_string())
}

struct BoundedBytes {
    bytes: Vec<u8>,
    maximum: usize,
}

impl Write for BoundedBytes {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        if self
            .bytes
            .len()
            .checked_add(bytes.len())
            .is_none_or(|size| size > self.maximum)
        {
            return Err(std::io::Error::other(
                "inspection catalog serialization bound",
            ));
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

#[cfg(test)]
#[path = "inspection_snapshot_tests.rs"]
mod tests;
