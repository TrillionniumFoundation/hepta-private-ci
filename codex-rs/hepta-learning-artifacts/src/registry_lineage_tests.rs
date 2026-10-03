use super::*;
use pretty_assertions::assert_eq;

// Independent semantic oracle: public immutable manifests, not owner indexes.
fn reference_eligible(owner: &ArtifactRegistry, artifact: &StableId) -> bool {
    let mut cursor = Some(artifact);
    while let Some(current) = cursor {
        let Some(manifest) = owner.manifest(current) else {
            return false;
        };
        if owner.state(current) != Some(ArtifactState::Candidate) {
            return false;
        }
        cursor = manifest.predecessor_id.as_ref();
    }
    true
}

#[test]
fn branching_lineage_invalidation_replay_and_recovery_match_source_truth() {
    let mut owner = ArtifactRegistry::new();
    let mut events = Vec::new();
    for index in 0..255_u64 {
        let mut item = manifest(&format!("artifact-{index}"), index + 1);
        if index > 1 {
            item.predecessor_id = Some(id(&format!("artifact-{}", (index - 2) / 2)));
        }
        let event = register(&format!("register-{index}"), item);
        must(owner.append(event.clone()));
        events.push(event);
    }
    for (step, target) in [7, 3, 0, 1].into_iter().enumerate() {
        let change = StateChange {
            event_id: id(&format!("invalidate-{step}")),
            artifact_id: id(&format!("artifact-{target}")),
            evaluator_id: id("independent-evaluator"),
            reason_digest: Digest32::of_bytes(b"regression"),
        };
        must(owner.append(ArtifactEvent::Quarantine(change.clone())));
        let expected = (0..255)
            .filter_map(|index| {
                let artifact = id(&format!("artifact-{index}"));
                reference_eligible(&owner, &artifact).then_some(artifact)
            })
            .collect::<std::collections::BTreeSet<_>>();
        let snapshot = owner.snapshot();
        for mut observed in [
            owner.clone(),
            must(ArtifactRegistry::from_snapshot(snapshot.clone())),
        ] {
            let selected = observed
                .eligible_candidates(ArtifactKind::Policy, Digest32::of_bytes(b"objective"))
                .iter()
                .map(|item| item.artifact_id.clone())
                .collect::<std::collections::BTreeSet<_>>();
            assert_eq!(selected, expected);
            for index in 0..255 {
                let artifact = id(&format!("artifact-{index}"));
                assert_eq!(
                    observed.is_eligible(&artifact),
                    expected.contains(&artifact)
                );
            }
            assert!(!observed.is_eligible(&id("unknown")));
            // Historical retries cannot resurrect invalidated descendants.
            for event in &events {
                must(observed.append(event.clone()));
            }
            assert_eq!(observed.snapshot(), snapshot);
            assert_eq!(
                observed
                    .eligible_candidates(ArtifactKind::Policy, Digest32::of_bytes(b"objective"))
                    .len(),
                expected.len()
            );
            let mut rejected = manifest("new-descendant", 300);
            rejected.predecessor_id = Some(change.artifact_id.clone());
            assert_eq!(
                must_err(observed.append(register("rejected", rejected))),
                ArtifactRegistryError::PredecessorUnavailable(change.artifact_id.to_string())
            );
            assert_eq!(observed.snapshot(), snapshot);
        }
        let mut revoked = change;
        revoked.event_id = id(&format!("revoke-{step}"));
        must(owner.append(ArtifactEvent::Revoke(revoked)));
        owner = must(ArtifactRegistry::from_snapshot(owner.snapshot()));
    }
    assert!(
        owner
            .eligible_candidates(ArtifactKind::Policy, Digest32::of_bytes(b"objective"))
            .is_empty()
    );
}

#[test]
#[ignore = "explicit lineage growth diagnostic; not deployment throughput qualification"]
fn lineage_growth_records_real_query_recovery_and_revocation_cost() {
    use std::hint::black_box;
    use std::time::Instant;
    for records in [64_u64, 256, 1024, 4000] {
        let mut owner = ArtifactRegistry::new();
        let started = Instant::now();
        for index in 0..records {
            let mut item = manifest(&format!("artifact-{index}"), index + 1);
            if index != 0 {
                item.predecessor_id = Some(id(&format!("artifact-{}", index - 1)));
            }
            must(owner.append(register(&format!("register-{index}"), item)));
        }
        let append_us = started.elapsed().as_micros();
        let started = Instant::now();
        let candidates = black_box(
            owner.eligible_candidates(ArtifactKind::Policy, Digest32::of_bytes(b"objective")),
        );
        assert_eq!(candidates.len(), records as usize);
        let query_us = started.elapsed().as_micros();
        let started = Instant::now();
        let reference_count = (0..records)
            .filter(|index| reference_eligible(&owner, &id(&format!("artifact-{index}"))))
            .count();
        let reference_us = started.elapsed().as_micros();
        assert_eq!(reference_count, candidates.len());
        let started = Instant::now();
        let mut restored = must(ArtifactRegistry::from_snapshot(owner.snapshot()));
        let recovery_us = started.elapsed().as_micros();
        let started = Instant::now();
        must(restored.append(ArtifactEvent::Revoke(StateChange {
            event_id: id("withdraw-root"),
            artifact_id: id("artifact-0"),
            evaluator_id: id("independent-evaluator"),
            reason_digest: Digest32::of_bytes(b"withdrawn"),
        })));
        let revoke_us = started.elapsed().as_micros();
        assert!(
            restored
                .eligible_candidates(ArtifactKind::Policy, Digest32::of_bytes(b"objective"))
                .is_empty()
        );
        println!(
            "lineage_growth records={records} append_us={append_us} query_us={query_us} reference_us={reference_us} recovery_us={recovery_us} revoke_us={revoke_us}"
        );
    }
}
