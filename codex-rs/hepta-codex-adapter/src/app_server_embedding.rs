use std::sync::Arc;

use codex_core::config::Config;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_hepta_memory::CognitiveRuntime;
use codex_hepta_memory::LocalDevelopmentLifecyclePolicy;
use codex_hepta_memory_extension::HeptaMemoryFeatureFlags;
use codex_hepta_memory_extension::HeptaMemoryThreadConfig;
use codex_hepta_memory_extension::QualificationTurnWriterHost;
use codex_state::StateRuntime;

/// Stable embedding payload owned by the Hepta↔Codex composition layer.
///
/// App Server transports host-owned capabilities through this value but does
/// not know which concrete Hepta extensions consume them. Adding another Hepta
/// extension belongs in this module rather than the App Server registry.
pub struct HeptaAppServerEmbedding {
    cognitive_runtime: CognitiveRuntime,
    local_turn_lifecycle_enabled: bool,
    local_development_policy: Option<LocalDevelopmentLifecyclePolicy>,
    qualification_turn_writer_enabled: bool,
    qualification_turn_writer: Option<QualificationTurnWriterHost>,
}

impl HeptaAppServerEmbedding {
    #[must_use]
    pub fn new(
        cognitive_runtime: CognitiveRuntime,
        local_turn_lifecycle_enabled: bool,
        local_development_policy: Option<LocalDevelopmentLifecyclePolicy>,
        qualification_turn_writer_enabled: bool,
        qualification_turn_writer: Option<QualificationTurnWriterHost>,
    ) -> Self {
        Self {
            cognitive_runtime,
            local_turn_lifecycle_enabled,
            local_development_policy,
            qualification_turn_writer_enabled,
            qualification_turn_writer,
        }
    }
}

/// Install the complete Hepta extension bundle into the stable Codex extension
/// builder. This is the only composition point that knows concrete Hepta
/// extension implementations and their feature mapping.
pub fn install_app_server_extensions(
    builder: &mut ExtensionRegistryBuilder<Config>,
    state_db: Option<Arc<StateRuntime>>,
    embedding: HeptaAppServerEmbedding,
) {
    let HeptaAppServerEmbedding {
        cognitive_runtime,
        local_turn_lifecycle_enabled,
        local_development_policy,
        qualification_turn_writer_enabled,
        qualification_turn_writer,
    } = embedding;

    codex_hepta_governance::install(builder, state_db.clone(), |config: &Config| {
        config
            .features
            .enabled(codex_features::Feature::HeptaGovernance)
    });
    codex_hepta_memory_extension::install_with_turn_writer(
        builder,
        state_db,
        cognitive_runtime,
        local_turn_lifecycle_enabled,
        local_development_policy,
        qualification_turn_writer_enabled,
        qualification_turn_writer,
        |config: &Config| {
            HeptaMemoryThreadConfig::for_features(memory_feature_flags(&config.features))
        },
    );
}

fn memory_feature_flags(features: &codex_features::Features) -> HeptaMemoryFeatureFlags {
    HeptaMemoryFeatureFlags {
        governance_enabled: features.enabled(codex_features::Feature::HeptaGovernance),
        memory_enabled: features.enabled(codex_features::Feature::HeptaMemory),
        read_only_enabled: features.enabled(codex_features::Feature::HeptaMemoryReadOnly),
        write_enabled: features.enabled(codex_features::Feature::HeptaCognitiveWrite),
    }
}
