//! A successor cannot erase the incumbent's handoff obligations.

use super::*;

#[derive(Clone, Copy, Debug)]
enum Obligation {
    Stateful,
    ExternalStateful,
    Domain,
    Effect,
    Stateless,
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn prepared(
    obligation: Obligation,
) -> (
    RuntimeModuleRegistryV1,
    RuntimeModuleAbiV1,
    RuntimeModuleAbiV1,
) {
    let mut previous = RuntimeModuleAbiV1 {
        module_id: id("retained"),
        owner_id: id("owner"),
        generation: generation(1),
        implementation_digest: digest("old"),
        candidate_artifact_digest: digest("old"),
        predecessor_generation: None,
        rollback_predecessor_digest: Digest32::ZERO,
        state_class: RuntimeModuleStateClassV1::Stateless,
        dependencies: Vec::new(),
        input_ports: Vec::new(),
        output_ports: Vec::new(),
        authoritative_domains: BTreeSet::new(),
        effect_scope: BTreeSet::new(),
    };
    match obligation {
        Obligation::Stateful => previous.state_class = RuntimeModuleStateClassV1::Stateful,
        Obligation::ExternalStateful => {
            previous.state_class = RuntimeModuleStateClassV1::ExternalStateful;
        }
        Obligation::Domain => {
            previous.authoritative_domains.insert(id("retained-data"));
        }
        Obligation::Effect => {
            previous.effect_scope.insert(id("external-write"));
        }
        Obligation::Stateless => {}
    }
    let mut registry = RuntimeModuleRegistryV1::new();
    registry
        .register_candidate(previous.clone())
        .expect("old candidate");
    registry
        .activate_bootstrap(&previous.module_id, previous.generation)
        .expect("old owner");
    let mut candidate = previous.clone();
    candidate.generation = generation(2);
    candidate.implementation_digest = digest("new-stateless-program");
    candidate.candidate_artifact_digest = candidate.implementation_digest;
    candidate.predecessor_generation = Some(previous.generation);
    candidate.rollback_predecessor_digest = previous.implementation_digest;
    candidate.state_class = RuntimeModuleStateClassV1::Stateless;
    candidate.authoritative_domains.clear();
    candidate.effect_scope.clear();
    registry
        .register_candidate(candidate.clone())
        .expect("new candidate");
    registry
        .enter_shadow(&candidate.module_id, candidate.generation)
        .expect("shadow");
    registry
        .enter_canary(&candidate.module_id, candidate.generation)
        .expect("canary");
    (registry, previous, candidate)
}

#[test]
fn stateless_successor_keeps_predecessor_handoff_obligation() {
    for obligation in [
        Obligation::Stateful,
        Obligation::ExternalStateful,
        Obligation::Domain,
        Obligation::Effect,
    ] {
        let (mut registry, previous, candidate) = prepared(obligation);
        let before = registry.clone();
        let mut witness = RuntimeModulePromotionWitnessV1 {
            selection_digest: digest("selection"),
            canary_digest: digest("canary"),
            handoff_digest: Digest32::ZERO,
        };
        assert_eq!(
            registry.promote_after_handoff(
                &candidate.module_id,
                candidate.generation,
                witness.clone(),
            ),
            Err(RuntimeModuleRegistryError::MissingWriterHandoff),
            "predecessor obligation {obligation:?}",
        );
        assert_eq!(registry.records, before.records);
        assert_eq!(registry.active, before.active);
        assert_eq!(registry.generation_fences, before.generation_fences);

        // This library checks witness shape, not a physical migration. The
        // host must independently observe and admit the actual handoff.
        witness.handoff_digest = digest("owner-observed-handoff");
        let selected = registry
            .promote_after_handoff(&candidate.module_id, candidate.generation, witness)
            .expect("explicit handoff");
        assert_eq!(selected.active[0].generation, candidate.generation);
        assert_eq!(
            registry
                .record(&previous.module_id, previous.generation)
                .expect("previous")
                .lifecycle,
            RuntimeModuleLifecycleV1::Retired,
        );
    }
}

#[test]
fn genuinely_stateless_replacement_does_not_acquire_a_handoff_requirement() {
    let (mut registry, _, candidate) = prepared(Obligation::Stateless);
    let selected = registry
        .promote_after_handoff(
            &candidate.module_id,
            candidate.generation,
            RuntimeModulePromotionWitnessV1 {
                selection_digest: digest("selection"),
                canary_digest: digest("canary"),
                handoff_digest: Digest32::ZERO,
            },
        )
        .expect("both generations are stateless and effect-free");
    assert_eq!(selected.active[0].generation, candidate.generation);
}
