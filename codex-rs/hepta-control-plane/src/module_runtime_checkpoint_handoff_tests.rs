//! Restoring a published successor cannot erase retained owner obligations.
//! Matching test roots exercise structure, not production authorization.

use pretty_assertions::assert_eq;

use super::*;

#[derive(Clone, Copy, Debug)]
enum Predecessor {
    Stateful,
    ExternalStateful,
    Domain,
    Effect,
    Stateless,
}

fn promoted(predecessor: Predecessor) -> RuntimeModuleRegistryV1 {
    let mut old = abi("handoff", /*value*/ 1, /*previous*/ None);
    old.state_class = RuntimeModuleStateClassV1::Stateless;
    old.authoritative_domains.clear();
    match predecessor {
        Predecessor::Stateful => old.state_class = RuntimeModuleStateClassV1::Stateful,
        Predecessor::ExternalStateful => {
            old.state_class = RuntimeModuleStateClassV1::ExternalStateful;
        }
        Predecessor::Domain => {
            old.authoritative_domains.insert(id("retained-domain"));
        }
        Predecessor::Effect => {
            old.effect_scope.insert(id("outstanding-effect"));
        }
        Predecessor::Stateless => {}
    }
    let mut candidate = abi("handoff", /*value*/ 2, Some(&old));
    candidate.state_class = RuntimeModuleStateClassV1::Stateless;
    candidate.authoritative_domains.clear();
    let mut registry = RuntimeModuleRegistryV1::new();
    bootstrap(&mut registry, old);
    registry.register_candidate(candidate.clone()).unwrap();
    registry
        .enter_shadow(&candidate.module_id, candidate.generation)
        .unwrap();
    registry
        .enter_canary(&candidate.module_id, candidate.generation)
        .unwrap();
    registry
        .promote_after_handoff(
            &candidate.module_id,
            candidate.generation,
            RuntimeModulePromotionWitnessV1 {
                selection_digest: digest("selected"),
                canary_digest: digest("canary"),
                handoff_digest: match predecessor {
                    Predecessor::Stateless => Digest32::ZERO,
                    _ => digest("independently-observed-owner-handoff"),
                },
            },
        )
        .unwrap();
    registry
}

#[test]
fn checkpoint_handoff_cannot_be_erased_by_a_stateless_successor() {
    for obligation in [
        Predecessor::Stateful,
        Predecessor::ExternalStateful,
        Predecessor::Domain,
        Predecessor::Effect,
    ] {
        for lifecycle in [
            RuntimeModuleLifecycleV1::Active,
            RuntimeModuleLifecycleV1::Quiescing,
            RuntimeModuleLifecycleV1::Quarantined,
        ] {
            let mut registry = promoted(obligation);
            match lifecycle {
                RuntimeModuleLifecycleV1::Quiescing => {
                    registry
                        .begin_retire(&id("handoff"), generation(2))
                        .unwrap();
                }
                RuntimeModuleLifecycleV1::Quarantined => {
                    registry.quarantine(&id("handoff"), generation(2)).unwrap();
                }
                RuntimeModuleLifecycleV1::Active => {}
                _ => unreachable!("only selected writer lifecycles are exercised"),
            }
            let original = registry.checkpoint();
            let mut malformed = original.clone();
            malformed
                .records
                .iter_mut()
                .find(|record| record.abi.generation == generation(2))
                .unwrap()
                .handoff_digest = None;
            resign(&mut malformed);
            let mut bytes = codec::encode(&malformed);
            bytes.extend_from_slice(malformed.checkpoint_digest.as_array());
            assert_eq!(
                restore(malformed.clone()).unwrap_err(),
                Error::MissingWriterHandoff,
                "typed restore: {obligation:?}, {lifecycle:?}"
            );
            assert_eq!(
                RuntimeModuleRegistryV1::restore_checkpoint_bytes(
                    &bytes,
                    malformed.checkpoint_digest
                )
                .unwrap_err(),
                Error::MissingWriterHandoff,
                "byte restore: {obligation:?}, {lifecycle:?}"
            );
            assert_eq!(registry.checkpoint(), original);
        }
    }
}

#[test]
fn checkpoint_handoff_with_complete_evidence_preserves_exact_state_and_bytes() {
    for obligation in [
        Predecessor::Stateful,
        Predecessor::ExternalStateful,
        Predecessor::Domain,
        Predecessor::Effect,
        Predecessor::Stateless,
    ] {
        let registry = promoted(obligation);
        let checkpoint = registry.checkpoint();
        let bytes = registry.checkpoint_bytes();
        let restored =
            RuntimeModuleRegistryV1::restore_checkpoint_bytes(&bytes, checkpoint.checkpoint_digest)
                .unwrap();
        assert_eq!(restored.checkpoint(), checkpoint);
        assert_eq!(restored.checkpoint_bytes(), bytes);
        assert_eq!(restored.snapshot(), registry.snapshot());
    }
}

#[test]
fn checkpoint_handoff_is_not_required_before_candidate_publication() {
    let mut registry = active();
    let previous = registry
        .record(&id("persisted"), generation(1))
        .unwrap()
        .abi
        .clone();
    let mut candidate = abi("persisted", /*value*/ 2, Some(&previous));
    candidate.state_class = RuntimeModuleStateClassV1::Stateless;
    candidate.authoritative_domains.clear();
    registry.register_candidate(candidate.clone()).unwrap();
    registry
        .enter_shadow(&candidate.module_id, candidate.generation)
        .unwrap();
    registry
        .enter_canary(&candidate.module_id, candidate.generation)
        .unwrap();
    let checkpoint = registry.checkpoint();
    let restored = RuntimeModuleRegistryV1::restore_checkpoint_bytes(
        &registry.checkpoint_bytes(),
        checkpoint.checkpoint_digest,
    )
    .unwrap();
    assert_eq!(restored.checkpoint(), checkpoint);
    assert_eq!(
        restored.active_generation(&id("persisted")),
        Some(generation(1))
    );
}
