//! Public-API dependency retirement tests. These exercise lifecycle behavior,
//! not deployment evidence or an independent authorization decision.

use std::collections::BTreeSet;

use codex_hepta_control_plane::RuntimeModuleAbiV1;
use codex_hepta_control_plane::RuntimeModuleLifecycleV1;
use codex_hepta_control_plane::RuntimeModulePromotionWitnessV1;
use codex_hepta_control_plane::RuntimeModuleRegistryError;
use codex_hepta_control_plane::RuntimeModuleRegistryV1;
use codex_hepta_control_plane::RuntimeModuleStateClassV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

fn id(value: &str) -> TestResult<StableId> {
    Ok(StableId::new(value)?)
}

fn generation() -> TestResult<Generation> {
    Ok(Generation::new(1)?)
}

fn abi(name: &str, dependencies: &[&str]) -> TestResult<RuntimeModuleAbiV1> {
    Ok(RuntimeModuleAbiV1 {
        module_id: id(name)?,
        owner_id: id("runtime-tests")?,
        generation: generation()?,
        implementation_digest: Digest32::of_bytes(name.as_bytes()),
        candidate_artifact_digest: Digest32::of_bytes(name.as_bytes()),
        predecessor_generation: None,
        rollback_predecessor_digest: Digest32::ZERO,
        state_class: RuntimeModuleStateClassV1::Stateless,
        dependencies: dependencies
            .iter()
            .map(|name| id(name))
            .collect::<TestResult<_>>()?,
        input_ports: Vec::new(),
        output_ports: Vec::new(),
        authoritative_domains: BTreeSet::new(),
        effect_scope: BTreeSet::new(),
    })
}

fn select(registry: &mut RuntimeModuleRegistryV1, value: RuntimeModuleAbiV1) -> TestResult {
    let module = value.module_id.clone();
    let epoch = value.generation;
    registry.register_candidate(value)?;
    registry.enter_shadow(&module, epoch)?;
    registry.enter_canary(&module, epoch)?;
    registry.promote_after_handoff(
        &module,
        epoch,
        RuntimeModulePromotionWitnessV1 {
            selection_digest: Digest32::of_bytes(b"fixture-selection"),
            canary_digest: Digest32::of_bytes(b"fixture-canary"),
            handoff_digest: Digest32::ZERO,
        },
    )?;
    Ok(())
}

#[test]
fn provider_waits_for_active_quarantined_and_draining_dependents() -> TestResult {
    for quarantine in [false, true] {
        let mut registry = RuntimeModuleRegistryV1::new();
        select(&mut registry, abi("provider", &[])?)?;
        select(&mut registry, abi("consumer", &["provider"])?)?;
        if quarantine {
            registry.quarantine(&id("consumer")?, generation()?)?;
        }
        let before = registry.snapshot();
        assert_eq!(
            registry.begin_retire(&id("provider")?, generation()?),
            Err(RuntimeModuleRegistryError::SelectedDependent(id(
                "consumer"
            )?))
        );
        assert_eq!(registry.snapshot(), before);
        assert_eq!(
            registry
                .record(&id("provider")?, generation()?)
                .ok_or("expected registered module")?
                .lifecycle,
            RuntimeModuleLifecycleV1::Active
        );
        registry.begin_retire(&id("consumer")?, generation()?)?;
        assert_eq!(
            registry.begin_retire(&id("provider")?, generation()?),
            Err(RuntimeModuleRegistryError::SelectedDependent(id(
                "consumer"
            )?))
        );
        registry.finish_retire(&id("consumer")?, generation()?)?;
        registry.begin_retire(&id("provider")?, generation()?)?;
        registry.finish_retire(&id("provider")?, generation()?)?;
        assert!(registry.snapshot().active.is_empty());
        assert_eq!(registry.active_generation(&id("provider")?), None);
    }
    Ok(())
}

#[test]
fn finish_rechecks_consumers_selected_during_the_drain_window() -> TestResult {
    let mut registry = RuntimeModuleRegistryV1::new();
    select(&mut registry, abi("provider", &[])?)?;
    registry.begin_retire(&id("provider")?, generation()?)?;
    // The registry is not the host's dependency admission evaluator. Even if a
    // caller admits a consumer during this interval, retirement must not free
    // the provider reservation until that consumer has finished draining.
    select(&mut registry, abi("late-consumer", &["provider"])?)?;
    let before = registry.snapshot();
    assert_eq!(
        registry.finish_retire(&id("provider")?, generation()?),
        Err(RuntimeModuleRegistryError::SelectedDependent(id(
            "late-consumer"
        )?))
    );
    assert_eq!(registry.snapshot(), before);
    assert_eq!(
        registry.active_generation(&id("provider")?),
        Some(generation()?)
    );
    assert_eq!(
        registry
            .record(&id("provider")?, generation()?)
            .ok_or("expected registered module")?
            .lifecycle,
        RuntimeModuleLifecycleV1::Quiescing
    );
    registry.begin_retire(&id("late-consumer")?, generation()?)?;
    registry.finish_retire(&id("late-consumer")?, generation()?)?;
    registry.finish_retire(&id("provider")?, generation()?)?;
    assert_eq!(registry.active_generation(&id("provider")?), None);
    Ok(())
}

#[test]
fn unselected_candidate_does_not_pin_a_provider_forever() -> TestResult {
    let mut registry = RuntimeModuleRegistryV1::new();
    select(&mut registry, abi("provider", &[])?)?;
    registry.register_candidate(abi("pending-consumer", &["provider"])?)?;
    registry.begin_retire(&id("provider")?, generation()?)?;
    registry.finish_retire(&id("provider")?, generation()?)?;
    assert!(registry.snapshot().active.is_empty());
    assert_eq!(
        registry
            .record(&id("pending-consumer")?, generation()?)
            .ok_or("expected registered module")?
            .lifecycle,
        RuntimeModuleLifecycleV1::Registered
    );
    Ok(())
}

#[test]
fn invalid_self_dependency_does_not_consume_the_generation_identity() -> TestResult {
    let mut registry = RuntimeModuleRegistryV1::new();
    assert_eq!(
        registry.register_candidate(abi("self-dependent", &["self-dependent"])?),
        Err(RuntimeModuleRegistryError::SelfDependency)
    );
    assert!(
        registry
            .record(&id("self-dependent")?, generation()?)
            .is_none()
    );
    select(&mut registry, abi("self-dependent", &[])?)?;
    assert_eq!(
        registry.active_generation(&id("self-dependent")?),
        Some(generation()?)
    );
    Ok(())
}
