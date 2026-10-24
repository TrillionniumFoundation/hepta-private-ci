#![allow(
    clippy::expect_used,
    reason = "controlled original-owner metadata fixtures fail loudly"
)]

use super::*;
use chrono::Utc;
use codex_models_manager::cache::ModelsCacheEntry;
use codex_models_manager::manager::ModelsEndpointClient;
use codex_models_manager::manager::ModelsEndpointFuture;
use codex_models_manager::manager::OpenAiModelsManager;
use codex_models_manager::manager::StaticModelsManager;
use codex_protocol::config_types::ReasoningSummary;
use codex_protocol::config_types::Verbosity;
use codex_protocol::openai_models::ModelServiceTier;
use codex_protocol::openai_models::ModelsResponse;
use codex_protocol::openai_models::ReasoningEffort;
use codex_protocol::openai_models::ReasoningEffortPreset;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

pub(super) const MODEL: &str = "inspection-fixture-model";
pub(super) const PRIVATE: &str =
    "https://SECRET_CREDENTIAL@private.invalid/config?token=SECRET_PROMPT";

#[derive(Debug, Default)]
pub(super) struct NoCatalogFetch {
    pub calls: AtomicUsize,
}

impl ModelsEndpointClient for NoCatalogFetch {
    fn has_command_auth(&self) -> bool {
        false
    }

    fn uses_codex_backend(&self) -> ModelsEndpointFuture<'_, bool> {
        Box::pin(async { false })
    }

    fn list_models<'a>(
        &'a self,
        _: &'a str,
        _: HttpClientFactory,
    ) -> ModelsEndpointFuture<'a, codex_protocol::error::Result<(Vec<ModelInfo>, Option<String>)>>
    {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Box::pin(async {
            Err(codex_protocol::error::CodexErr::Fatal(
                "inspection fixture forbids catalog fetch".into(),
            ))
        })
    }
}

pub(super) fn metadata() -> ModelInfo {
    let mut model = codex_models_manager::bundled_models_response()
        .expect("bundled owner catalog")
        .models
        .into_iter()
        .next()
        .expect("bundled fixture model");
    model.slug = MODEL.into();
    model.display_name = PRIVATE.into();
    model.description = Some(PRIVATE.into());
    if let Some(messages) = model.model_messages.as_mut() {
        messages.instructions_template = Some(PRIVATE.into());
    }
    model.default_reasoning_level = Some(ReasoningEffort::Max);
    model.supported_reasoning_levels = vec![ReasoningEffortPreset {
        effort: ReasoningEffort::Max,
        description: PRIVATE.into(),
    }];
    model.supports_reasoning_summary_parameter = false;
    model.default_reasoning_summary = ReasoningSummary::None;
    model.support_verbosity = true;
    model.default_verbosity = Some(Verbosity::Low);
    model.service_tiers = vec![ModelServiceTier {
        id: "fixture-priority".into(),
        name: PRIVATE.into(),
        description: PRIVATE.into(),
    }];
    model.default_service_tier = Some("fixture-priority".into());
    model.use_responses_lite = true;
    model
}

pub(super) fn settings(configured_catalog: bool) -> snapshot::Settings {
    snapshot::Settings {
        model: MODEL.into(),
        provider_id: "fixture-provider".into(),
        configured_catalog,
        effort: Some(ReasoningEffort::Max),
        summary: Some(ReasoningSummary::None),
        verbosity: Some(Verbosity::High),
        service_tier: Some("unsupported-tier".into()),
        features: snapshot::FeatureSnapshot {
            use_agent_identity: false,
            request_compression: true,
            concurrent_reasoning_summaries: true,
            content_item_kinds: true,
            fast_mode: false,
        },
    }
}

pub(super) fn cached_manager(
    path: &Path,
    entry: ModelsCacheEntry,
) -> (SharedModelsManager, Arc<NoCatalogFetch>) {
    std::fs::write(
        path.join("models_cache.json"),
        serde_json::to_vec(&entry).expect("cache fixture encode"),
    )
    .expect("owned cache write");
    let endpoint = Arc::new(NoCatalogFetch::default());
    let manager = Arc::new(OpenAiModelsManager::new(
        path.to_path_buf(),
        endpoint.clone(),
        None,
    ));
    (manager, endpoint)
}

pub(super) fn cache_entry() -> ModelsCacheEntry {
    ModelsCacheEntry {
        fetched_at: Utc::now(),
        etag: Some(PRIVATE.into()),
        client_version: Some(codex_models_manager::client_version_to_whole()),
        models: vec![metadata()],
    }
}

pub(super) fn static_manager(model: ModelInfo) -> SharedModelsManager {
    Arc::new(StaticModelsManager::new(
        None,
        ModelsResponse {
            models: vec![model],
        },
    ))
}

pub(super) fn http_factory() -> HttpClientFactory {
    HttpClientFactory::new(codex_http_client::OutboundProxyPolicy::ReqwestDefault)
}
