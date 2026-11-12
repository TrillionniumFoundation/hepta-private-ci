use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;

use super::AgentdConfig;
use super::CognitiveRetrievalMode;
use crate::AgentdError;
use crate::ORIGINAL_NOTES_THREAD_ENVIRONMENTS_CONFIG;
use crate::ORIGINAL_NOTES_THREAD_EXECUTION_CONFIG;

fn fixture() -> (tempfile::TempDir, AgentdConfig) {
    let temp = tempfile::tempdir().expect("temporary registry");
    let root = temp.path().canonicalize().expect("canonical registry");
    let fleet_path = root.join("fleet");
    let fleet = HeptaFleetRoot::parse(fleet_path.clone()).expect("fleet path");
    let registry = FleetRegistry::initialize(fleet.clone()).expect("original registry");
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).expect("workspace");
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent");
    let record = registry
        .register(
            AgentManifest::new(
                agent_id.clone(),
                WorkspaceBinding::new(workspace.clone(), &fleet).expect("workspace binding"),
                ResourceBudget::local_default(),
            )
            .expect("manifest"),
        )
        .expect("register agent");
    registry
        .compare_and_transition(
            &agent_id,
            /*expected_generation*/ 0,
            AgentLifecycle::Starting,
        )
        .expect("original starting generation");
    std::fs::write(
        record.layout.home_root().join("config.toml"),
        format!(
            "model = \"fixture-model\"\nmodel_provider = \"fixture-provider\"\n{ORIGINAL_NOTES_THREAD_EXECUTION_CONFIG}"
        ),
    )
    .expect("finite configuration");
    std::fs::write(
        record.layout.home_root().join("environments.toml"),
        ORIGINAL_NOTES_THREAD_ENVIRONMENTS_CONFIG,
    )
    .expect("disabled environments");
    let config = AgentdConfig::load(
        fleet_path,
        agent_id,
        /*spawn_generation*/ 1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace,
    )
    .expect("ordinary registered configuration");
    (temp, config)
}

#[test]
fn original_notes_seed_profile_does_not_supply_notes_execution_owners() {
    let (_temp, config) = fixture();
    let config = config
        .with_original_notes_seed_profile()
        .expect("explicit finite seed profile");
    assert!(config.original_notes_seed_profile().expect("finite files"));
    assert!(matches!(
        config.require_finite_notes_profile(),
        Err(AgentdError::Invalid(message))
            if message == "finite Notes profile requires its original writer, Notes, AuthBus and admission owners without another execution plane"
    ));
}

#[test]
fn original_notes_seed_profile_rejects_mixed_configurations_in_both_orders() {
    let profiles: [fn(AgentdConfig) -> AgentdConfig; 3] = [
        |config| config.with_objective_profile_file("unused-objective.json".into()),
        |config| config.with_authbus_trust_file("unused-authbus.json".into()),
        |config| config.with_cognitive_retrieval_mode(CognitiveRetrievalMode::HnmfRequired),
    ];
    for profile in profiles {
        for seed_selected_first in [false, true] {
            let (_temp, config) = fixture();
            let config = if seed_selected_first {
                config
                    .with_original_notes_seed_profile()
                    .expect("initial seed selection")
            } else {
                config
            };
            let config = profile(config);
            let result = if seed_selected_first {
                config.original_notes_seed_profile()
            } else {
                config.with_original_notes_seed_profile().map(|_| true)
            };
            assert!(matches!(
                result,
                Err(AgentdError::Invalid(message))
                    if message == "original Notes seed profile cannot be combined with an execution or owner profile"
            ));
        }
    }
}

#[test]
fn original_notes_seed_profile_rechecks_files_before_runtime() {
    for (file, original, changed, error) in [
        (
            "config.toml",
            "hepta_memory = false",
            "hepta_memory = true",
            "original Notes Core execution profile is not finite",
        ),
        (
            "config.toml",
            "hepta_cognitive_write = false",
            "hepta_cognitive_write = true",
            "original Notes Core execution profile is not finite",
        ),
        (
            "environments.toml",
            "include_local = false",
            "include_local = true",
            "original Notes execution environments are not disabled",
        ),
    ] {
        let (_temp, config) = fixture();
        let config = config
            .with_original_notes_seed_profile()
            .expect("initial finite files");
        let path = config.identity().home_root.join(file);
        let bytes = std::fs::read_to_string(&path).expect("original file");
        assert!(bytes.contains(original));
        std::fs::write(path, bytes.replace(original, changed)).expect("changed file");
        assert!(matches!(
            config.original_notes_seed_profile(),
            Err(AgentdError::Invalid(message)) if message.contains(error)
        ));
    }
}
