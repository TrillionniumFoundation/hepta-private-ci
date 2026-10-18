use super::*;
use crate::AgentdConfig;
use crate::config::runtime_composition;
use codex_hepta_agent_components::contracts::AgentId;
use codex_hepta_agent_components::fleet::AgentLifecycle;
use codex_hepta_agent_components::fleet::AgentManifest;
use codex_hepta_agent_components::fleet::FleetRegistry;
use codex_hepta_agent_components::fleet::ResourceBudget;
use codex_hepta_agent_components::fleet::WorkspaceBinding;
use codex_hepta_agent_components::paths::HeptaFleetRoot;

type TestResult = Result<(), Box<dyn std::error::Error>>;

struct Fixture {
    _directory: tempfile::TempDir,
    registry: FleetRegistry,
    identity: crate::AgentdIdentity,
}

impl Fixture {
    fn new() -> Result<(Self, AgentdConfig), Box<dyn std::error::Error>> {
        let directory = tempfile::tempdir()?;
        let root = directory.path().canonicalize()?;
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet"))?;
        let registry = FleetRegistry::initialize(fleet_root.clone())?;
        let workspace = root.join("workspace");
        fs::create_dir(&workspace)?;
        let id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
        registry.register(AgentManifest::new(
            id.clone(),
            WorkspaceBinding::new(&workspace, &fleet_root)?,
            ResourceBudget::local_default(),
        )?)?;
        registry.compare_and_transition(&id, 0, AgentLifecycle::Starting)?;
        let record = registry.load_agent(&id)?;
        let config = AgentdConfig::load(
            root.join("fleet"),
            id,
            1,
            record.layout.home_root().into(),
            record.layout.run_root().into(),
            record.layout.home_root().into(),
            workspace,
        )?;
        Ok((
            Self {
                _directory: directory,
                registry,
                identity: config.identity().clone(),
            },
            config,
        ))
    }

    fn config(&self, generation: u64) -> Result<AgentdConfig, crate::AgentdError> {
        AgentdConfig::load(
            self.identity.fleet_root.clone(),
            self.identity.agent_id.clone(),
            generation,
            self.identity.home_root.clone(),
            self.identity.run_root.clone(),
            self.identity.home_root.clone(),
            self.identity.workspace.clone(),
        )
    }

    fn path(&self) -> PathBuf {
        self.identity
            .run_root
            .join("runtime-codex-agent-runs-v1.json")
    }

    fn transition(
        &self,
        generation: u64,
        lifecycle: AgentLifecycle,
    ) -> Result<(), Box<dyn std::error::Error>> {
        self.registry
            .compare_and_transition(&self.identity.agent_id, generation, lifecycle)?;
        Ok(())
    }
}

fn seed(
    coordinator: &mut AgentRunCoordinator,
    id: &str,
    phase: RunPhase,
) -> Result<(), AgentRunError> {
    let snapshot = RunSnapshot {
        run_id: id.into(),
        request_digest: "1".repeat(64),
        objective_digest: "2".repeat(64),
        body_digest: "3".repeat(64),
        artifact_set_digest: "4".repeat(64),
        authority_epoch: 1,
        generation: 2,
        fence_digest: "5".repeat(64),
        deadline_ms: 10_000,
    };
    let attached = ContextAttachment {
        run_id: id.into(),
        request_digest: snapshot.request_digest.clone(),
        objective_digest: snapshot.objective_digest.clone(),
        body_digest: snapshot.body_digest.clone(),
        artifact_set_digest: snapshot.artifact_set_digest.clone(),
        authority_epoch: 1,
        generation: 2,
        fence_digest: snapshot.fence_digest.clone(),
        deadline_ms: 10_000,
        context_digest: "6".repeat(64),
        compilation_receipt_digest: "7".repeat(64),
    };
    coordinator.start_run(100, snapshot)?;
    coordinator.attach_context(200, 1, attached)?;
    if phase != RunPhase::ContextAttached {
        let dispatch =
            coordinator.mark_dispatched_bound(300, id, 2, "8".repeat(64), "9".repeat(64))?;
        if phase == RunPhase::Succeeded {
            let terminal =
                coordinator.observe_terminal(id, dispatch.revision, RunPhase::Succeeded, true)?;
            coordinator.remove_closed_run(id, terminal.revision)?;
        } else if phase == RunPhase::Cancelling {
            coordinator.cancel_run(400, id, dispatch.revision, "original_cancel")?;
        }
    }
    Ok(())
}

#[test]
fn restart_migrates_real_empty_failed_spawn_to_generation_four_without_reset() -> TestResult {
    let (fixture, original_config) = Fixture::new()?;
    let original = runtime_composition(original_config.identity(), 1);
    let old = AgentRunCoordinator::open_durable(original, fixture.path())?;
    let previous_digest = old.committed_store_sha256;
    drop(original_config);
    fixture.transition(1, AgentLifecycle::Failed)?;
    fixture.transition(2, AgentLifecycle::Stopped)?;
    fixture.transition(3, AgentLifecycle::Starting)?;
    let config = fixture.config(4)?;
    let admission = config.verified_run_store_restart()?;
    let current = runtime_composition(config.identity(), 4);
    let before = fs::read(fixture.path())?;
    // Composition includes the run ceiling but does not encode every host
    // resource field. A proof cannot be detached from its full Config identity.
    let mut substituted = config.identity().clone();
    substituted.resources.memory_limit_mib += 1;
    assert_eq!(runtime_composition(&substituted, 4), current);
    assert!(
        crate::AgentdState::new_with_verified_restart(
            substituted,
            fixture.registry.clone(),
            /*event_capacity*/ 128,
            &admission,
        )
        .is_err()
    );
    assert_eq!(fs::read(fixture.path())?, before);
    assert!(AgentRunCoordinator::open_durable(current.clone(), fixture.path()).is_err());
    assert_eq!(fs::read(fixture.path())?, before);
    let migrated =
        AgentRunCoordinator::open_durable_for_restart(current.clone(), fixture.path(), &admission)?;
    let store = load_durable_run_store(&fixture.path())?.ok_or("migrated store")?;
    assert_eq!(store.store_revision, 2);
    assert_eq!(store.previous_store_sha256, previous_digest);
    assert_eq!(store.composition, current);
    assert!(store.runs.is_empty() && store.tombstones.is_empty());
    assert_eq!(migrated.composition().agentd_generation, 4);
    let committed = fs::read(fixture.path())?;
    AgentRunCoordinator::open_durable_for_restart(current, fixture.path(), &admission)?;
    assert_eq!(
        fs::read(fixture.path())?,
        committed,
        "same generation reopen must not publish a new revision"
    );
    // The private proof cannot outlive its exclusive writer authority.
    drop(config);
    assert!(fixture.config(4).is_err());
    drop(admission);
    drop(fixture.config(4)?);
    Ok(())
}

#[test]
fn restart_preserves_tombstones_and_complete_uncertain_tuples_and_fences_stale_writer() -> TestResult
{
    let (fixture, original_config) = Fixture::new()?;
    fixture.transition(1, AgentLifecycle::Running)?;
    let mut old = AgentRunCoordinator::open_durable(
        runtime_composition(original_config.identity(), 1),
        fixture.path(),
    )?;
    seed(&mut old, "closed", RunPhase::Succeeded)?;
    seed(&mut old, "dispatched", RunPhase::Dispatched)?;
    seed(&mut old, "cancelling", RunPhase::Cancelling)?;
    old.persist()?;
    let previous = load_durable_run_store(&fixture.path())?.ok_or("previous store")?;
    let previous_sha = durable_run_store_sha256(&previous)?;
    drop(original_config);
    fixture.transition(2, AgentLifecycle::Draining)?;
    fixture.transition(3, AgentLifecycle::Stopped)?;
    fixture.transition(4, AgentLifecycle::Starting)?;
    let config = fixture.config(5)?;
    let admission = config.verified_run_store_restart()?;
    AgentRunCoordinator::open_durable_for_restart(
        runtime_composition(config.identity(), 5),
        fixture.path(),
        &admission,
    )?;
    let current = load_durable_run_store(&fixture.path())?.ok_or("current store")?;
    assert_eq!(
        current.previous_store_sha256.as_deref(),
        Some(previous_sha.as_str())
    );
    assert_eq!(
        serde_json::to_vec(&current.tombstones)?,
        serde_json::to_vec(&previous.tombstones)?
    );
    for id in ["dispatched", "cancelling"] {
        let prior = previous.runs.get(id).ok_or("previous run")?;
        let retained = current.runs.get(id).ok_or("retained run")?;
        assert_eq!(retained.snapshot, prior.snapshot);
        assert_eq!(retained.context_digest, prior.context_digest);
        assert_eq!(
            retained.compilation_receipt_digest,
            prior.compilation_receipt_digest
        );
        assert_eq!(
            retained.dispatch_binding_digest,
            prior.dispatch_binding_digest
        );
        assert_eq!(
            retained.pre_effect_abort_commitment_digest,
            prior.pre_effect_abort_commitment_digest
        );
        assert_eq!(retained.phase, RunPhase::Indeterminate);
        assert_eq!(retained.revision, prior.revision + 1);
    }
    assert_eq!(
        current.runs["cancelling"].cancel_reason.as_deref(),
        Some("original_cancel")
    );
    let before = fs::read(fixture.path())?;
    assert!(old.persist().is_err());
    assert_eq!(fs::read(fixture.path())?, before);
    Ok(())
}

#[test]
fn restart_rejects_unrelated_tuple_false_prior_spawn_corrupt_predecessor_and_stale_fleet()
-> TestResult {
    let (fixture, old_config) = Fixture::new()?;
    let old = AgentRunCoordinator::open_durable(
        runtime_composition(old_config.identity(), 1),
        fixture.path(),
    )?;
    let previous = load_durable_run_store(&fixture.path())?.ok_or("old store")?;
    drop(old_config);
    fixture.transition(1, AgentLifecycle::Failed)?;
    fixture.transition(2, AgentLifecycle::Stopped)?;
    fixture.transition(3, AgentLifecycle::Starting)?;
    let config = fixture.config(4)?;
    let proof = config.verified_run_store_restart()?;
    let current = runtime_composition(config.identity(), 4);
    for variant in 0..8 {
        let mut corrupt = previous.clone();
        match variant {
            0 => corrupt.composition.agent_id = "another-agent".into(),
            1 => corrupt.composition.ports_digest = "a".repeat(64),
            2 => corrupt.composition.configuration_digest = "b".repeat(64),
            3 => corrupt.composition.supervisor_generation = 2,
            4 => corrupt.composition = runtime_composition(config.identity(), 3), // true Stopped, not spawn
            5 => corrupt.composition = runtime_composition(config.identity(), 5), // future owner
            6 => {
                corrupt.store_revision = 2;
                corrupt.previous_store_sha256 = Some("q".repeat(64));
            }
            7 => corrupt.composition.max_active_runs += 1,
            _ => unreachable!(),
        }
        atomic_replace_durable_run_store(&fixture.path(), &corrupt)?;
        let before = fs::read(fixture.path())?;
        assert!(
            AgentRunCoordinator::open_durable_for_restart(current.clone(), fixture.path(), &proof)
                .is_err(),
            "variant {variant}"
        );
        assert_eq!(fs::read(fixture.path())?, before);
    }
    atomic_replace_durable_run_store(&fixture.path(), &previous)?;
    fixture.transition(4, AgentLifecycle::Failed)?;
    let before = fs::read(fixture.path())?;
    assert!(
        AgentRunCoordinator::open_durable_for_restart(current, fixture.path(), &proof).is_err()
    );
    assert_eq!(fs::read(fixture.path())?, before);
    drop(old);
    Ok(())
}

#[test]
fn restart_refuses_lossy_nested_history_and_duplicate_ids_without_rewriting_source() -> TestResult {
    let (fixture, old_config) = Fixture::new()?;
    fixture.transition(1, AgentLifecycle::Running)?;
    let mut old = AgentRunCoordinator::open_durable(
        runtime_composition(old_config.identity(), 1),
        fixture.path(),
    )?;
    seed(&mut old, "closed", RunPhase::Succeeded)?;
    seed(&mut old, "pending", RunPhase::ContextAttached)?;
    old.persist()?;
    let previous = load_durable_run_store(&fixture.path())?.ok_or("original source")?;
    let source: serde_json::Value = serde_json::from_slice(&fs::read(fixture.path())?)?;
    drop(old_config);
    fixture.transition(2, AgentLifecycle::Draining)?;
    fixture.transition(3, AgentLifecycle::Stopped)?;
    fixture.transition(4, AgentLifecycle::Starting)?;
    let config = fixture.config(5)?;
    let admission = config.verified_run_store_restart()?;
    let current = runtime_composition(config.identity(), 5);
    for pointer in [
        "/composition",
        "/runs/pending",
        "/runs/pending/snapshot",
        "/tombstones/closed/snapshot",
        "/tombstones/closed/receipt",
    ] {
        let mut unsupported = source.clone();
        unsupported
            .pointer_mut(pointer)
            .and_then(serde_json::Value::as_object_mut)
            .ok_or("source object")?
            .insert(
                "unrecognized_history".into(),
                "must_not_be_discarded".into(),
            );
        let bytes = serde_json::to_vec(&unsupported)?;
        fs::write(fixture.path(), &bytes)?;
        assert!(
            AgentRunCoordinator::open_durable_for_restart(
                current.clone(),
                fixture.path(),
                &admission,
            )
            .is_err(),
            "unsupported source field at {pointer}"
        );
        assert_eq!(fs::read(fixture.path())?, bytes);
    }
    let original_json = serde_json::to_string(&source)?;
    let runs_json = serde_json::to_string(&source["runs"])?;
    let record_json = serde_json::to_string(&source["runs"]["pending"])?;
    let duplicate = original_json.replacen(
        &format!("\"runs\":{runs_json}"),
        &format!("\"runs\":{{\"pending\":{record_json},\"pending\":{record_json}}}"),
        1,
    );
    assert_ne!(original_json, duplicate);
    fs::write(fixture.path(), duplicate.as_bytes())?;
    assert!(
        AgentRunCoordinator::open_durable_for_restart(current.clone(), fixture.path(), &admission,)
            .is_err()
    );
    assert_eq!(fs::read(fixture.path())?, duplicate.as_bytes());
    // Existing optional-null omissions carry the same typed history and are
    // compatible; no public RPC deserialization policy changes are needed.
    let mut legacy = source;
    // This persisted revision has a non-null predecessor commitment. Only an
    // actually null optional field can be omitted without losing history.
    legacy["runs"]["pending"]
        .as_object_mut()
        .ok_or("source pending run")?
        .remove("cancel_reason");
    fs::write(fixture.path(), serde_json::to_vec(&legacy)?)?;
    AgentRunCoordinator::open_durable_for_restart(current, fixture.path(), &admission)?;
    let retained = load_durable_run_store(&fixture.path())?.ok_or("retained source")?;
    assert_eq!(
        retained.previous_store_sha256,
        Some(durable_run_store_sha256(&previous)?)
    );
    assert_eq!(
        serde_json::to_value(retained.tombstones)?,
        serde_json::to_value(previous.tombstones)?
    );
    assert_eq!(
        serde_json::to_value(retained.runs)?,
        serde_json::to_value(previous.runs)?
    );
    Ok(())
}
