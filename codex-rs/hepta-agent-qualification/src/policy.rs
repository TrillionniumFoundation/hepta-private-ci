//! Compose the existing durable provider governance contributor in Enforce
//! mode for this isolated qualification. No FinalUse grant is issued here.

use crate::request_wire::PreparedOrdinaryWire;
use anyhow::Result;
use anyhow::anyhow;
use codex_core::config::Config;
use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionRegistry;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION;
use codex_extension_api::ModelProviderAttemptLease;
use codex_extension_api::ModelProviderInvocationInput;
use codex_extension_api::ModelProviderPolicyDecision;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderSha256Digest;
use codex_extension_api::ModelProviderTransport;
use codex_extension_api::ThreadStartInput;
use codex_hepta_agent_loop::ModelRequest;
use codex_hepta_agent_loop::TurnBinding;
use codex_hepta_contracts::GovernanceMode;
use codex_hepta_types::Digest32;
use codex_protocol::protocol::SessionSource;
use codex_state::SqliteConfig;
use codex_state::StateRuntime;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde_json::json;
use std::path::Path;
use std::sync::Arc;

pub(crate) struct QualificationPolicy {
    registry: ExtensionRegistry<Config>,
    session: ExtensionData,
    thread: ExtensionData,
    turn: ExtensionData,
    // Keep the actual evidence runtime alive through all terminal callbacks.
    pub(crate) state: Arc<StateRuntime>,
}

impl QualificationPolicy {
    pub(crate) async fn open(config: &Config, path: &Path, binding: &TurnBinding) -> Result<Self> {
        let state = StateRuntime::init(
            SqliteConfig::from_sqlite_home(AbsolutePathBuf::try_from(path.to_path_buf())?),
            config.model_provider_id.clone(),
        )
        .await
        .map_err(|_| anyhow!("qualification provider evidence runtime failed"))?;
        let mut registry = ExtensionRegistryBuilder::new();
        codex_hepta_governance::install_with_mode(
            &mut registry,
            Some(state.clone()),
            GovernanceMode::Enforce,
            |_: &Config| true,
        );
        let registry = registry.build();
        let session = ExtensionData::new(binding.run_id.as_str());
        let thread = ExtensionData::new(binding.run_id.as_str());
        let turn = ExtensionData::new(binding.turn_id.as_str());
        for contributor in registry.thread_lifecycle_contributors() {
            contributor
                .on_thread_start(ThreadStartInput {
                    config,
                    session_source: &SessionSource::Exec,
                    // This is a new qualification host identity, never copied from
                    // or represented as the production Agentd installation.
                    installation_id: binding.run_id.as_str(),
                    persistent_thread_state_available: false,
                    environments: &[],
                    mcp_resource_client: None,
                    extension_metrics: None,
                    session_store: &session,
                    thread_store: &thread,
                })
                .await;
        }
        Ok(Self {
            registry,
            session,
            thread,
            turn,
            state,
        })
    }

    pub(crate) async fn admit(
        &self,
        config: &Config,
        binding: &TurnBinding,
        request: &ModelRequest,
        model: &str,
        endpoint: &str,
        prepared_wire: &PreparedOrdinaryWire,
        auth_policy: &str,
    ) -> Result<Box<dyn ModelProviderAttemptLease>> {
        let policies = self.registry.model_provider_policy_contributors();
        if policies.len() != 1 || !policies[0].is_active(&self.thread) {
            return Err(anyhow!("qualification Enforce provider owner unavailable"));
        }
        let provider_selector = digest(&serde_json::to_vec(&json!({
            "schema":"hepta-native-qualification-provider-selector:v1",
            "provider":config.model_provider_id, "model":model, "auth_policy":auth_policy,
        }))?)?;
        let endpoint = endpoint_digest(endpoint)?;
        let logical = digest(&serde_json::to_vec(&json!({
            "schema":"hepta-native-qualification-logical-request:v2",
            "admission_digest":binding.admission_digest.to_string(),
            "request_id":request.request_id.as_str(), "context_digest":request.context_digest.to_string(),
            "api_body_sha256":prepared_wire.body_digest().to_string(),
            "wire_semantic_sha256":prepared_wire.semantic_digest().to_string(),
        }))?)?;
        let wire = ModelProviderSha256Digest::parse(prepared_wire.semantic_digest().to_string())
            .map_err(|_| anyhow!("qualification request digest invalid"))?;
        match policies[0]
            .begin(ModelProviderInvocationInput {
                schema_version: MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION,
                session_store: &self.session,
                thread_store: &self.thread,
                turn_store: &self.turn,
                attempt_id: request.request_id.as_str(),
                request_binding_id: request.request_id.as_str(),
                thread_id: binding.run_id.as_str(),
                turn_id: binding.turn_id.as_str(),
                request_kind: ModelProviderRequestKind::Turn,
                provider_id: &config.model_provider_id,
                provider_config_sha256: &provider_selector,
                model,
                transport: ModelProviderTransport::Http,
                endpoint_sha256: &endpoint,
                logical_request_sha256: &logical,
                wire_semantic_sha256: &wire,
                ephemeral_input_sha256: None,
                ephemeral_input_witness_sha256: None,
                previous_response_id_sha256: None,
                generate: true,
            })
            .await
            .map_err(|_| anyhow!("qualification durable provider admission failed"))?
        {
            ModelProviderPolicyDecision::Allow { lease } => Ok(lease),
            ModelProviderPolicyDecision::Block { .. } => Err(anyhow!(
                "qualification durable provider owner blocked the request"
            )),
        }
    }
}

fn digest(bytes: &[u8]) -> Result<ModelProviderSha256Digest> {
    ModelProviderSha256Digest::parse(Digest32::of_bytes(bytes).to_string())
        .map_err(|_| anyhow!("qualification binding digest invalid"))
}

fn endpoint_digest(endpoint: &str) -> Result<ModelProviderSha256Digest> {
    let endpoint =
        url::Url::parse(endpoint).map_err(|_| anyhow!("qualification endpoint invalid"))?;
    let mut query_names = endpoint
        .query_pairs()
        .map(|(name, _)| name.into_owned())
        .collect::<Vec<_>>();
    query_names.sort();
    // Match the existing Core rule: never retain or digest URL credentials,
    // fragments, or query values into secret-free provider evidence.
    digest(&serde_json::to_vec(&json!({
        "schema":"model-provider-endpoint:v1", "scheme":endpoint.scheme(),
        "host":endpoint.host_str(), "port":endpoint.port_or_known_default(),
        "path":endpoint.path(), "query_names":query_names,
    }))?)
}
