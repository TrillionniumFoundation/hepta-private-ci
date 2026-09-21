//! Exercise the actual ABI-to-task boundary, not a parallel registry fixture.
use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_control_plane::ActiveRuntimeModuleV1;
use codex_hepta_control_plane::RuntimeModuleAbiV1;
use codex_hepta_control_plane::RuntimeModuleStateClassV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use tokio_util::sync::CancellationToken;

use crate::RuntimeTasks;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture identity")
}

fn binding(epoch: u64) -> (ActiveRuntimeModuleV1, RuntimeModuleAbiV1) {
    let generation = Generation::new(epoch).expect("generation");
    let selected = ActiveRuntimeModuleV1 {
        module_id: id("feature.optional"),
        generation,
        implementation_digest: Digest32::of_bytes(b"compiled"),
        candidate_artifact_digest: Digest32::of_bytes(b"artifact"),
        owner_id: id("feature.owner"),
        state_class: RuntimeModuleStateClassV1::Stateless,
        dependencies: vec![id("runtime.codex")],
        input_ports: vec![id("request.v1")],
        output_ports: vec![id("response.v1")],
        authoritative_domains: BTreeSet::new(),
        effect_scope: BTreeSet::new(),
    };
    let implementation = RuntimeModuleAbiV1 {
        module_id: selected.module_id.clone(),
        owner_id: selected.owner_id.clone(),
        generation,
        implementation_digest: selected.implementation_digest,
        candidate_artifact_digest: selected.candidate_artifact_digest,
        predecessor_generation: None,
        rollback_predecessor_digest: Digest32::ZERO,
        state_class: selected.state_class,
        dependencies: selected.dependencies.clone(),
        input_ports: selected.input_ports.clone(),
        output_ports: selected.output_ports.clone(),
        authoritative_domains: selected.authoritative_domains.clone(),
        effect_scope: selected.effect_scope.clone(),
    };
    (selected, implementation)
}

#[tokio::test]
async fn incompatible_abi_never_starts_factory_or_consumes_a_slot() {
    let (selected, implementation) = binding(1);
    let mut invalid = Vec::new();
    let mut changed = implementation.clone();
    changed.input_ports = vec![id("request.v2")];
    invalid.push(changed);
    let mut changed = implementation.clone();
    changed.output_ports = vec![id("response.v2")];
    invalid.push(changed);
    let mut changed = implementation.clone();
    changed.owner_id = id("another.owner");
    invalid.push(changed);
    let mut changed = implementation.clone();
    changed.generation = Generation::new(2).expect("generation");
    invalid.push(changed);
    let mut changed = implementation.clone();
    changed.candidate_artifact_digest = Digest32::of_bytes(b"unevaluated");
    invalid.push(changed);
    let mut changed = implementation.clone();
    changed.effect_scope.insert(id("network.write"));
    invalid.push(changed);
    let mut changed = implementation.clone();
    changed.authoritative_domains.insert(id("another.store"));
    invalid.push(changed);
    let mut changed = implementation.clone();
    changed.input_ports.push(id("request.v1"));
    invalid.push(changed);
    let mut changed = implementation.clone();
    changed.implementation_digest = Digest32::ZERO;
    invalid.push(changed);

    for candidate in invalid {
        let cancellation = CancellationToken::new();
        let mut tasks =
            RuntimeTasks::new(cancellation.clone(), Duration::from_secs(1)).expect("host");
        let slots = tasks.remaining_admission_slots();
        let started = Arc::new(AtomicBool::new(false));
        let worker_started = Arc::clone(&started);
        assert!(
            tasks
                .spawn_bound_optional_service(
                    &selected,
                    &candidate,
                    move |stop| async move {
                        worker_started.store(true, Ordering::SeqCst);
                        stop.cancelled().await;
                        Ok(())
                    },
                    || Ok(()),
                    || Ok(()),
                )
                .is_err()
        );
        tokio::task::yield_now().await;
        assert!(!started.load(Ordering::SeqCst));
        assert_eq!(tasks.active_count(), 0);
        assert_eq!(tasks.remaining_admission_slots(), slots);
        assert!(!cancellation.is_cancelled());
    }
}

#[tokio::test]
async fn abi_bound_replacements_reuse_one_slot_and_reject_stale_retirement() {
    let cancellation = CancellationToken::new();
    let mut tasks = RuntimeTasks::new(cancellation.clone(), Duration::from_secs(1)).expect("host");
    let slots = tasks.remaining_admission_slots();
    for epoch in 1..=512 {
        let (selected, mut implementation) = binding(epoch);
        if epoch > 1 {
            implementation.predecessor_generation =
                Some(Generation::new(epoch - 1).expect("predecessor"));
            implementation.rollback_predecessor_digest = implementation.implementation_digest;
        }
        tasks
            .spawn_bound_optional_service(
                &selected,
                &implementation,
                |stop| async move {
                    stop.cancelled().await;
                    Ok(())
                },
                || Ok(()),
                || Ok(()),
            )
            .expect("same ABI/task entry point");
        if epoch > 1 {
            assert!(
                tasks
                    .retire_optional_generation(
                        "feature.optional",
                        Generation::new(epoch - 1).expect("old generation"),
                    )
                    .await
                    .is_err()
            );
            assert_eq!(tasks.active_count(), 1);
        }
        tasks
            .retire_optional_generation("feature.optional", selected.generation)
            .await
            .expect("cooperative retirement");
        assert_eq!(tasks.remaining_admission_slots(), slots - 1);
        assert_eq!(tasks.active_count(), 0);
        assert!(!cancellation.is_cancelled());
    }
}
