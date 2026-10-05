//! Direct and staged publication must preserve predecessor obligations.
//!
//! Existing test-only selection setup isolates host publication. Fixture
//! digests are not independent production authority or physical migration.

use codex_hepta_control_plane::RuntimeModuleStateClassV1;
use codex_hepta_types::RuntimeTopologyDeltaV1;

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

fn replacement(obligation: Obligation) -> RuntimeModuleSupervisorV1 {
    let mut old = RuntimeModuleAbiV1 {
        module_id: id("owner"),
        owner_id: id("owner-team"),
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
        Obligation::Stateful => old.state_class = RuntimeModuleStateClassV1::Stateful,
        Obligation::ExternalStateful => {
            old.state_class = RuntimeModuleStateClassV1::ExternalStateful;
        }
        Obligation::Domain => {
            old.authoritative_domains.insert(id("retained-data"));
        }
        Obligation::Effect => {
            old.effect_scope.insert(id("external-write"));
        }
        Obligation::Stateless => {}
    }
    let mut candidate = old.clone();
    candidate.generation = generation(2);
    candidate.implementation_digest = digest("new");
    candidate.candidate_artifact_digest = digest("replacement");
    candidate.predecessor_generation = Some(old.generation);
    candidate.rollback_predecessor_digest = old.implementation_digest;
    candidate.state_class = RuntimeModuleStateClassV1::Stateless;
    candidate.authoritative_domains.clear();
    candidate.effect_scope.clear();
    let mut supervisor = RuntimeModuleSupervisorV1::new();
    supervisor.register_bootstrap(old).expect("old owner");
    supervisor
        .register_shadow_for_test(candidate, digest("selection"))
        .expect("selected shadow");
    supervisor
        .enter_canary(&id("owner"), generation(2))
        .expect("canary");
    supervisor
}

fn stage_topology(supervisor: &mut RuntimeModuleSupervisorV1) -> Digest32 {
    let candidate_digest = digest("replacement");
    let baseline = supervisor.topology();
    supervisor.pending_topologies.insert(
        candidate_digest,
        RuntimeTopologyCandidateV1 {
            proposal_digest: digest("proposal"),
            candidate_id: id("candidate"),
            candidate_digest,
            baseline_generation: generation(1),
            candidate_generation: generation(2),
            selected_topology_digest: baseline.digest,
            evaluation_digest: digest("evaluation"),
            rollback_predecessor_digest: baseline.digest,
            changed: true,
            deltas: vec![RuntimeTopologyDeltaV1 {
                module_id: id("owner"),
                operation: RuntimeTopologyOperationV1::Replace,
                related_module_ids: Vec::new(),
                predecessor_digest: digest("old"),
                candidate_digest: digest("new"),
                evidence_digest: digest("evidence"),
            }],
        },
    );
    candidate_digest
}

#[test]
fn direct_stateless_promotion_cannot_erase_predecessor_ownership() {
    for obligation in [
        Obligation::Stateful,
        Obligation::ExternalStateful,
        Obligation::Domain,
        Obligation::Effect,
    ] {
        let mut supervisor = replacement(obligation);
        let before = supervisor.topology();
        let old = supervisor.registry.record(&id("owner"), generation(1)).cloned();
        let candidate = supervisor.registry.record(&id("owner"), generation(2)).cloned();
        let selections = supervisor.selections.clone();
        assert_eq!(
            supervisor.promote_stateless(&id("owner"), generation(2), digest("canary")),
            Err(RuntimeModuleSupervisorErrorV1::Registry(
                RuntimeModuleRegistryError::MissingWriterHandoff,
            )),
            "predecessor obligation {obligation:?}",
        );
        assert_eq!(supervisor.topology(), before);
        assert_eq!(supervisor.registry.record(&id("owner"), generation(1)).cloned(), old);
        assert_eq!(supervisor.registry.record(&id("owner"), generation(2)).cloned(), candidate);
        assert_eq!(supervisor.selections, selections);
        assert!(supervisor.pending_promotions.is_empty());
    }
}

#[test]
fn staged_stateless_promotion_cannot_record_missing_predecessor_handoff() {
    for obligation in [
        Obligation::Stateful,
        Obligation::ExternalStateful,
        Obligation::Domain,
        Obligation::Effect,
    ] {
        let mut supervisor = replacement(obligation);
        let before = supervisor.topology();
        stage_topology(&mut supervisor);
        let topologies = supervisor.pending_topologies.clone();
        let selections = supervisor.selections.clone();
        assert_eq!(
            supervisor.promote_stateless(&id("owner"), generation(2), digest("canary")),
            Err(RuntimeModuleSupervisorErrorV1::Registry(
                RuntimeModuleRegistryError::MissingWriterHandoff,
            )),
            "staged predecessor obligation {obligation:?}",
        );
        assert_eq!(supervisor.topology(), before);
        assert_eq!(supervisor.pending_topologies, topologies);
        assert_eq!(supervisor.selections, selections);
        assert!(supervisor.pending_promotions.is_empty());
    }
}

#[test]
fn stateless_direct_and_staged_replacements_keep_the_existing_fast_path() {
    let mut direct = replacement(Obligation::Stateless);
    let selected = direct
        .promote_stateless(&id("owner"), generation(2), digest("canary"))
        .expect("stateless direct replacement");
    assert_eq!(selected.active[0].generation, generation(2));

    let mut staged = replacement(Obligation::Stateless);
    let before = staged.topology();
    let candidate_digest = stage_topology(&mut staged);
    assert_eq!(
        staged
            .promote_stateless(&id("owner"), generation(2), digest("canary"))
            .expect("stateless evidence staging"),
        before,
    );
    let selected = staged
        .finalize_topology_candidate(candidate_digest)
        .expect("atomic stateless replacement");
    assert_eq!(selected.active[0].generation, generation(2));
    assert!(staged.pending_promotions.is_empty());
}
