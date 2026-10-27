//! Real original Registry transitions, not a reconstructed lifecycle model.
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

fn registered() -> Result<(tempfile::TempDir, FleetRegistry, AgentId)> {
    let directory = tempfile::tempdir()?;
    let root = HeptaFleetRoot::parse(directory.path().join("fleet"))?;
    let registry = FleetRegistry::initialize(root.clone())?;
    let workspace = directory.path().join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    registry.register(AgentManifest::new(
        agent.clone(),
        WorkspaceBinding::new(workspace, &root)?,
        ResourceBudget::local_default(),
    )?)?;
    Ok((directory, registry, agent))
}

fn stop_original(registry: &FleetRegistry, agent: &AgentId) -> Result<u64> {
    let start = registry.compare_and_transition(agent, 0, AgentLifecycle::Starting)?;
    let mut state = start.clone();
    for next in [
        AgentLifecycle::Running,
        AgentLifecycle::Draining,
        AgentLifecycle::Stopped,
    ] {
        state = registry.compare_and_transition(agent, state.generation, next)?;
    }
    Ok(start.generation)
}

#[test]
fn stopped_original_keeps_its_spawn_while_lifecycle_advances() -> Result<()> {
    let (_directory, registry, agent) = registered()?;
    let starting = registry.compare_and_transition(&agent, 0, AgentLifecycle::Starting)?;
    let mut state = starting.clone();
    assert_eq!(
        registry.load_agent_for_spawn(&agent, starting.generation)?,
        registry.load_agent(&agent)?
    );
    for next in [
        AgentLifecycle::Running,
        AgentLifecycle::Draining,
        AgentLifecycle::Stopped,
    ] {
        state = registry.compare_and_transition(&agent, state.generation, next)?;
        let observed = registry.load_agent_for_spawn(&agent, starting.generation)?;
        assert_eq!(observed, registry.load_agent(&agent)?);
        assert_eq!(observed.lifecycle, state);
    }
    assert_eq!(
        (starting.generation, state.generation, state.lifecycle),
        (1, 4, AgentLifecycle::Stopped)
    );
    Ok(())
}

#[test]
fn a_later_spawn_is_refused_even_after_its_own_stop() -> Result<()> {
    let (_directory, registry, agent) = registered()?;
    let original = stop_original(&registry, &agent)?;
    let stopped = registry.load_agent(&agent)?;
    let successor = registry.compare_and_transition(
        &agent,
        stopped.lifecycle.generation,
        AgentLifecycle::Starting,
    )?;
    let failed =
        registry.compare_and_transition(&agent, successor.generation, AgentLifecycle::Failed)?;
    registry.compare_and_transition(&agent, failed.generation, AgentLifecycle::Stopped)?;
    for rejected in [0, original, original + 1, successor.generation + 1] {
        assert!(registry.load_agent_for_spawn(&agent, rejected).is_err());
    }
    assert_eq!(
        registry.load_agent_for_spawn(&agent, successor.generation)?,
        registry.load_agent(&agent)?
    );
    Ok(())
}

#[test]
fn missing_original_history_cannot_be_replaced_by_a_terminal_record() -> Result<()> {
    let (_directory, registry, agent) = registered()?;
    let original = stop_original(&registry, &agent)?;
    let record = registry.load_agent(&agent)?;
    let missing = record
        .layout
        .run_root()
        .join("lifecycle-00000000000000000002.json");
    let saved = std::fs::read(&missing)?;
    std::fs::remove_file(&missing)?;
    assert!(registry.load_agent_for_spawn(&agent, original).is_err());
    assert!(registry.load_agent(&agent).is_err());
    assert!(!missing.exists());
    std::fs::write(missing, saved)?;
    assert_eq!(registry.load_agent_for_spawn(&agent, original)?, record);
    Ok(())
}

#[test]
fn invalid_terminal_transition_or_identity_is_refused_without_repair() -> Result<()> {
    for field in ["lifecycle", "agent_id"] {
        let (_directory, registry, agent) = registered()?;
        let original = stop_original(&registry, &agent)?;
        let record = registry.load_agent(&agent)?;
        let terminal = record.layout.run_root().join(format!(
            "lifecycle-{:020}.json",
            record.lifecycle.generation
        ));
        let mut altered = serde_json::to_value(&record.lifecycle)?;
        altered[field] = if field == "lifecycle" {
            serde_json::json!("running") // Draining -> Running is not an original transition.
        } else {
            serde_json::json!("019153a4-3088-7e03-a56a-9b1964f75dd3")
        };
        let bytes = serde_json::to_vec(&altered)?;
        std::fs::write(&terminal, &bytes)?;
        assert!(registry.load_agent_for_spawn(&agent, original).is_err());
        assert_eq!(std::fs::read(terminal)?, bytes);
    }
    Ok(())
}
