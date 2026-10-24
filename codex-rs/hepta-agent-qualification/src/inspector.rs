//! No generation: inspect the original config/auth/model owners with Offline catalogs.
//!
//! Offline suppresses catalog fetching, not authentication-owner bootstrap or
//! refresh. Never call a Responses client, API auth scope, policy admission or grant.

use crate::evidence::Evidence;
use crate::inspection_args::InspectionArgs;
use anyhow::Result;
use anyhow::anyhow;
use codex_core::config::ConfigBuilder;
use codex_http_client::HttpClientFactory;
use codex_login::AuthManager;
use codex_model_provider::create_model_provider;
use codex_models_manager::ModelsManagerConfig;
use codex_models_manager::manager::RefreshStrategy;
use codex_models_manager::manager::SharedModelsManager;
use codex_protocol::openai_models::ModelInfo;
use serde_json::Value;
use serde_json::json;
use std::future::Future;
use std::time::Duration;

#[path = "inspection_snapshot.rs"]
mod snapshot;

pub(crate) type InspectionResult<T> = std::result::Result<T, InspectionFailure>;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum InspectionFailure {
    ConfigTimeout,
    ConfigUnavailable,
    MissingModel,
    ModelMismatch,
    AuthTimeout,
    AuthUnavailable,
    CatalogTimeout,
    CatalogUnavailable,
    SnapshotBound,
    SnapshotEncoding,
}

impl InspectionFailure {
    fn code(self) -> &'static str {
        match self {
            Self::ConfigTimeout => "inspection_config_timeout",
            Self::ConfigUnavailable => "inspection_config_unavailable",
            Self::MissingModel => "inspection_configured_model_missing",
            Self::ModelMismatch => "inspection_configured_model_mismatch",
            Self::AuthTimeout => "inspection_auth_owner_timeout",
            Self::AuthUnavailable => "inspection_auth_owner_unavailable",
            Self::CatalogTimeout => "inspection_catalog_owner_timeout",
            Self::CatalogUnavailable => "inspection_catalog_owner_unavailable",
            Self::SnapshotBound => "inspection_snapshot_bound",
            Self::SnapshotEncoding => "inspection_snapshot_encoding",
        }
    }
}

pub(crate) struct CatalogObservation {
    before: Vec<ModelInfo>,
    active: Vec<ModelInfo>,
    model: ModelInfo,
}

pub(crate) async fn run(args: &InspectionArgs) -> Result<()> {
    // Allocate the new evidence directory before touching installed owners.
    let evidence = Evidence::create(&args.evidence_dir)?;
    let plan = json!({
        "schema":"hepta-native-owner-inspection-plan:v1",
        "expected_model":snapshot::identifier(&args.expected_model),
        "catalog_refresh_strategy":"offline",
        "maximum_responses_calls":0, "catalog_fetch_requested":false,
        "auth_owner_bootstrap_or_refresh_may_contact_network":true,
        "maximum_wait_seconds_per_setup_step":args.setup_seconds,
        "maximum_total_owner_wait_seconds":args.setup_seconds * 3,
        "setup_steps":["configuration", "authentication_owner", "model_catalog_owner"],
        "original_auth_policy_preserved":true,
        "creates_provider_policy_lease_or_final_use_grant":false,
    });
    evidence
        .record("inspection-plan.json", &plan)
        .map_err(|_| anyhow!("inspection plan evidence failed"))?;
    let (report, succeeded) = match inspect(args).await {
        Ok(snapshot) => (snapshot, true),
        Err(error) => (
            json!({
                "schema":"hepta-native-owner-inspection:v1",
                "inspection_completed":false, "reason_code":error.code(),
                "generation_attempted":false, "catalog_refresh_strategy":"offline",
                "auth_owner_bootstrap_or_refresh_may_contact_network":true,
                "auth_network_activity_observed":null,
                "production_native_agent_qualified":false,
            }),
            false,
        ),
    };
    evidence
        .record("inspection.json", &report)
        .map_err(|_| anyhow!("inspection snapshot evidence failed"))?;
    println!("{}", serde_json::to_string(&report)?);
    if !succeeded {
        return Err(anyhow!(
            "native owner inspection did not complete successfully"
        ));
    }
    Ok(())
}

async fn inspect(args: &InspectionArgs) -> InspectionResult<Value> {
    let deadline = Duration::from_secs(args.setup_seconds);
    let config = bounded(
        deadline,
        InspectionFailure::ConfigTimeout,
        InspectionFailure::ConfigUnavailable,
        ConfigBuilder::default().build(),
    )
    .await?;
    let requested_model = config
        .model
        .as_deref()
        .ok_or(InspectionFailure::MissingModel)?;
    if requested_model != args.expected_model {
        return Err(InspectionFailure::ModelMismatch);
    }
    let auth = bounded(
        deadline,
        InspectionFailure::AuthTimeout,
        InspectionFailure::AuthUnavailable,
        AuthManager::shared_from_config(&config, true),
    )
    .await?;
    let provider = create_model_provider(config.model_provider.clone(), Some(auth));
    let selected_auth = provider.auth_manager();
    let auth_before = selected_auth.as_ref().and_then(|owner| owner.auth_mode());
    let manager = provider.models_manager(
        config.codex_home.to_path_buf(),
        config.model_catalog.clone(),
    );
    let settings = snapshot::Settings::from_config(&config, requested_model);
    let observed = bounded(
        deadline,
        InspectionFailure::CatalogTimeout,
        InspectionFailure::CatalogUnavailable,
        async {
            Ok::<_, InspectionFailure>(
                observe_catalog(
                    &manager,
                    requested_model,
                    &config.to_models_manager_config(),
                    config.http_client_factory(),
                )
                .await,
            )
        },
    )
    .await?;
    let auth_after = selected_auth.as_ref().and_then(|owner| owner.auth_mode());
    snapshot::build(&settings, &observed, auth_before, auth_after)
}

async fn bounded<T, E>(
    deadline: Duration,
    timeout: InspectionFailure,
    failure: InspectionFailure,
    future: impl Future<Output = std::result::Result<T, E>>,
) -> InspectionResult<T> {
    tokio::time::timeout(deadline, future)
        .await
        .map_err(|_| timeout)?
        .map_err(|_| failure)
}

async fn observe_catalog(
    manager: &SharedModelsManager,
    model: &str,
    config: &ModelsManagerConfig,
    http_factory: HttpClientFactory,
) -> CatalogObservation {
    let before = manager.get_remote_models().await;
    let active = manager
        .raw_model_catalog(RefreshStrategy::Offline, http_factory)
        .await
        .models;
    let model = manager.get_model_info(model, config).await;
    CatalogObservation {
        before,
        active,
        model,
    }
}
