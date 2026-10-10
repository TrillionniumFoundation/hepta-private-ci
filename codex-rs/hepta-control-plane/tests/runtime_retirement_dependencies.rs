//! Public-API dependency retirement tests. These exercise lifecycle behavior,
//! not deployment evidence or an independent authorization decision.

use std::collections::BTreeSet;
use std::error::Error;
use std::io;

use codex_hepta_control_plane::RuntimeModuleAbiV1;
use codex_hepta_control_plane::RuntimeModuleLifecycleV1;
use codex_hepta_control_plane::RuntimeModulePromotionWitnessV1;
use codex_hepta_control_plane::RuntimeModuleRegistryError;
use codex_hepta_control_plane::RuntimeModuleRegistryV1;
use codex_hepta_control_plane::RuntimeModuleStateClassV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

type TestResult<T = ()> = Result<T, Box<dyn Error + Send + Sync>>;

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
            .collect::<TestResult<Vec<_>>>()?,
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
        let provider = id("provider")?;
        let consumer = id("consumer")?;
        let epoch = generation()?;
        let mut registry = RuntimeModuleRegistryV1::new();
        select(&mut registry, abi("provider", &[])?)?;
        select(&mut registry, abi("consumer", &["provider"])?)?;
        if quarantine {
            registry.quarantine(&consumer, epoch)?;
        }
        let before = registry.snapshot();
        assert_eq!(
            registry.begin_retire(&provider, epoch),
            Err(RuntimeModuleRegistryError::SelectedDependent(
                consumer.clone()
            ))
        );
        assert_eq!(registry.snapshot(), before);
        let provider_record = registry
            .record(&provider, epoch)
            .ok_or_else(|| io::Error::other("provider record missing"))?;
        assert_eq!(provider_record.lifecycle, RuntimeModuleLifecycleV1::Active);
        registry.begin_retire(&consumer, epoch)?;
        assert_eq!(
            registry.begin_retire(&provider, epoch),
            Err(RuntimeModuleRegistryError::SelectedDependent(
                consumer.clone()
            ))
        );
        registry.finish_retire(&consumer, epoch)?;
        registry.begin_retire(&provider, epoch)?;
        registry.finish_retire(&provider, epoch)?;
        assert!(registry.snapshot().active.is_empty());
        assert_eq!(registry.active_generation(&provider), None);
    }
    Ok(())
}

#[test]
fn finish_rechecks_consumers_selected_during_the_drain_window() -> TestResult {
    let provider = id("provider")?;
    let late_consumer = id("late-consumer")?;
    let epoch = generation()?;
    let mut registry = RuntimeModuleRegistryV1::new();
    select(&mut registry, abi("provider", &[])?)?;
    registry.begin_retire(&provider, epoch)?;
    // The registry is not the host's dependency admission evaluator. Even if a
    // caller admits a consumer during this interval, retirement must not free
    // the provider reservation until that consumer has finished draining.
    select(&mut registry, abi("late-consumer", &["provider"])?)?;
    let before = registry.snapshot();
    assert_eq!(
        registry.finish_retire(&provider, epoch),
        Err(RuntimeModuleRegistryError::SelectedDependent(
            late_consumer.clone()
        ))
    );
    assert_eq!(registry.snapshot(), before);
    assert_eq!(registry.active_generation(&provider), Some(epoch));
    let provider_record = registry
        .record(&provider, epoch)
        .ok_or_else(|| io::Error::other("provider record missing"))?;
    assert_eq!(
        provider_record.lifecycle,
        RuntimeModuleLifecycleV1::Quiescing
    );
    registry.begin_retire(&late_consumer, epoch)?;
    registry.finish_retire(&late_consumer, epoch)?;
    registry.finish_retire(&provider, epoch)?;
    assert_eq!(registry.active_generation(&provider), None);
    Ok(())
}

#[test]
fn unselected_candidate_does_not_pin_a_provider_forever() -> TestResult {
    let provider = id("provider")?;
    let pending_consumer = id("pending-consumer")?;
    let epoch = generation()?;
    let mut registry = RuntimeModuleRegistryV1::new();
    select(&mut registry, abi("provider", &[])?)?;
    registry.register_candidate(abi("pending-consumer", &["provider"])?)?;
    registry.begin_retire(&provider, epoch)?;
    registry.finish_retire(&provider, epoch)?;
    assert!(registry.snapshot().active.is_empty());
    let pending_record = registry
        .record(&pending_consumer, epoch)
        .ok_or_else(|| io::Error::other("pending consumer record missing"))?;
    assert_eq!(
        pending_record.lifecycle,
        RuntimeModuleLifecycleV1::Registered
    );
    Ok(())
}

#[test]
fn invalid_self_dependency_does_not_consume_the_generation_identity() -> TestResult {
    let module = id("self-dependent")?;
    let epoch = generation()?;
    let mut registry = RuntimeModuleRegistryV1::new();
    assert_eq!(
        registry.register_candidate(abi("self-dependent", &["self-dependent"])?),
        Err(RuntimeModuleRegistryError::SelfDependency)
    );
    assert!(registry.record(&module, epoch).is_none());
    select(&mut registry, abi("self-dependent", &[])?)?;
    assert_eq!(registry.active_generation(&module), Some(epoch));
    Ok(())
}
