//! Genuine old-API histories and bounded terminal retention across restore.

use pretty_assertions::assert_eq;

use super::*;

// Captured from public lifecycle operations on 555dfd4a before the two-sided
// invariant was enforced. These are genuinely admitted legacy histories, not
// an assertion that a self-rehashed backup authenticates the host's root.
const LEGACY_CHECKPOINTS: [(&[u8], &str); 4] = [
    (
        include_bytes!("../fixtures/legacy_stateful_predecessor_no_handoff_v1.bin").as_slice(),
        "00c24decce70ed0398d0baddb7cc4f14ad810ceb8a7f45bbef72aa2b73a14c06",
    ),
    (
        include_bytes!("../fixtures/legacy_external_stateful_predecessor_no_handoff_v1.bin")
            .as_slice(),
        "e809befe4a5671a981efc983e74460bc2cad09538f5c554fce3677d2ece9125e",
    ),
    (
        include_bytes!("../fixtures/legacy_domain_predecessor_no_handoff_v1.bin").as_slice(),
        "76afc3aafceafae8ba654089523e4f2e60726ee5658db9643470238bf88ccc41",
    ),
    (
        include_bytes!("../fixtures/legacy_effect_predecessor_no_handoff_v1.bin").as_slice(),
        "50d2f50cf809670e7f52e4f9df31ec9ac6b5138469980c421448d02d9c10907d",
    ),
];

#[test]
fn legacy_promotions_missing_predecessor_handoff_are_rejected() {
    for (bytes, root) in LEGACY_CHECKPOINTS {
        let current = root.parse().unwrap();
        let checkpoint = codec::decode(bytes).unwrap();
        assert_eq!(
            RuntimeModuleRegistryV1::restore_checkpoint(checkpoint, current).unwrap_err(),
            Error::MissingWriterHandoff,
        );
        assert_eq!(
            RuntimeModuleRegistryV1::restore_checkpoint_bytes(bytes, current).unwrap_err(),
            Error::MissingWriterHandoff,
        );
    }
}

#[test]
fn retired_successors_keep_retained_predecessor_handoff_requirements() {
    for (bytes, _) in LEGACY_CHECKPOINTS {
        let mut checkpoint = codec::decode(bytes).unwrap();
        checkpoint.records[1].lifecycle = RuntimeModuleLifecycleV1::Retired;
        checkpoint.active_reservations.clear();
        resign(&mut checkpoint);
        let mut bytes = codec::encode(&checkpoint);
        bytes.extend_from_slice(checkpoint.checkpoint_digest.as_array());
        assert_eq!(
                RuntimeModuleRegistryV1::restore_checkpoint_bytes(
                    &bytes,
                    checkpoint.checkpoint_digest,
                )
                .unwrap_err(),
                Error::MissingWriterHandoff,
            );
        assert_eq!(
            restore(checkpoint).unwrap_err(),
            Error::MissingWriterHandoff
        );
    }
}

#[test]
fn compacted_stateless_terminal_history_remains_restorable() {
    let mut registry = RuntimeModuleRegistryV1::new();
    let mut previous = abi("stateless", /*value*/ 1, /*previous*/ None);
    previous.state_class = RuntimeModuleStateClassV1::Stateless;
    previous.authoritative_domains.clear();
    bootstrap(&mut registry, previous.clone());
    for value in 2..=4 {
        let mut candidate = abi("stateless", value, Some(&previous));
        candidate.state_class = RuntimeModuleStateClassV1::Stateless;
        candidate.authoritative_domains.clear();
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
                    selection_digest: digest("selection"),
                    canary_digest: digest("canary"),
                    handoff_digest: Digest32::ZERO,
                },
            )
            .unwrap();
        previous = candidate;
    }
    assert!(registry.record(&id("stateless"), generation(1)).is_none());
    assert_eq!(
        registry
            .record(&id("stateless"), generation(2))
            .unwrap()
            .lifecycle,
        RuntimeModuleLifecycleV1::Retired,
    );
    let checkpoint = registry.checkpoint();
    let bytes = registry.checkpoint_bytes();
    let restored =
        RuntimeModuleRegistryV1::restore_checkpoint_bytes(&bytes, checkpoint.checkpoint_digest)
            .unwrap();
    assert_eq!(restored.checkpoint(), checkpoint);
    assert_eq!(restored.checkpoint_bytes(), bytes);
    assert_eq!(
        restore(checkpoint.clone()).unwrap().checkpoint(),
        checkpoint
    );
}
