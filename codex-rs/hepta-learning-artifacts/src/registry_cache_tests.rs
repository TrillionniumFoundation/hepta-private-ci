use super::*;

use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid fixture identity")
}

fn append_candidate(
    registry: &mut ArtifactRegistry,
    artifact: &str,
    predecessor: Option<&str>,
    generation: u64,
) -> Result<RegistryAppendReceipt, ArtifactRegistryError> {
    registry.append(ArtifactEvent::Register {
        event_id: id(&format!("register-{artifact}")),
        manifest: ArtifactManifest {
            artifact_id: id(artifact),
            kind: ArtifactKind::Policy,
            generation: Generation::new(generation).expect("positive generation"),
            predecessor_id: predecessor.map(id),
            content_digest: Digest32::of_bytes(artifact.as_bytes()),
            objective_digest: Digest32::of_bytes(b"objective"),
            support_digest: Digest32::of_bytes(b"source"),
            producer_id: id("producer"),
            compatibility_digest: Digest32::of_bytes(b"compatibility"),
            encoded_size_bytes: 128,
        },
    })
}

fn quarantine(artifact: &str) -> ArtifactEvent {
    ArtifactEvent::Quarantine(StateChange {
        event_id: id(&format!("quarantine-{artifact}")),
        artifact_id: id(artifact),
        evaluator_id: id("evaluator"),
        reason_digest: Digest32::of_bytes(b"quarantine evidence"),
    })
}

#[test]
fn deep_lineage_invalidation_preserves_branch_and_replay_semantics() {
    let mut registry = ArtifactRegistry::new();
    append_candidate(
        &mut registry,
        "root",
        /*predecessor*/ None,
        /*generation*/ 1,
    )
    .expect("root");
    append_candidate(
        &mut registry,
        "unrelated",
        /*predecessor*/ None,
        /*generation*/ 1,
    )
    .expect("unrelated");
    // A long legal chain must remain iterative both when invalidated and when
    // recovered. Exercise a branch before the excluded subtree as well.
    let depth = 2_048_u64;
    let mut predecessor = "root".to_string();
    for generation in 2..=depth {
        let artifact = format!("chain-{generation}");
        append_candidate(&mut registry, &artifact, Some(&predecessor), generation)
            .expect("chain append");
        predecessor = artifact;
    }
    append_candidate(
        &mut registry,
        "branch",
        Some("chain-512"),
        /*generation*/ 513,
    )
    .expect("branch");
    assert!(registry.is_eligible(&id(&predecessor)));
    assert!(!registry.is_eligible(&id("missing")));

    let event = quarantine("chain-1024");
    registry.append(event.clone()).expect("quarantine subtree");
    assert!(registry.is_eligible(&id("root")));
    assert!(registry.is_eligible(&id("chain-1023")));
    assert!(registry.is_eligible(&id("branch")));
    assert!(registry.is_eligible(&id("unrelated")));
    assert!(!registry.is_eligible(&id("chain-1024")));
    assert!(!registry.is_eligible(&id(&predecessor)));
    assert_eq!(
        registry.state(&id(&predecessor)),
        Some(ArtifactState::Candidate)
    );
    assert_eq!(
        append_candidate(&mut registry, "late-child", Some(&predecessor), depth + 1),
        Err(ArtifactRegistryError::PredecessorUnavailable(predecessor)),
    );

    let cloned = registry.clone();
    let restored = ArtifactRegistry::from_snapshot(registry.snapshot()).expect("replay");
    for recovered in [cloned, restored] {
        assert_eq!(recovered.snapshot(), registry.snapshot());
        assert_eq!(
            recovered.eligible_candidates(ArtifactKind::Policy, Digest32::of_bytes(b"objective")),
            registry.eligible_candidates(ArtifactKind::Policy, Digest32::of_bytes(b"objective")),
        );
    }
    assert_eq!(
        registry.append(event).expect("exact retry").disposition,
        RegistryAppendDisposition::IdempotentReplay,
    );
}

#[test]
fn overlapping_quarantine_and_revocation_never_revive_descendants() {
    let mut registry = ArtifactRegistry::new();
    append_candidate(
        &mut registry,
        "root",
        /*predecessor*/ None,
        /*generation*/ 1,
    )
    .expect("root");
    append_candidate(&mut registry, "child", Some("root"), /*generation*/ 2).expect("child");
    append_candidate(
        &mut registry,
        "grandchild",
        Some("child"),
        /*generation*/ 3,
    )
    .expect("grandchild");
    append_candidate(
        &mut registry,
        "sibling",
        Some("root"),
        /*generation*/ 2,
    )
    .expect("sibling");
    registry
        .append(quarantine("child"))
        .expect("child quarantine");
    assert!(registry.is_eligible(&id("sibling")));
    registry
        .append(quarantine("root"))
        .expect("ancestor quarantine");
    registry
        .append(ArtifactEvent::Revoke(StateChange {
            event_id: id("revoke-child"),
            artifact_id: id("child"),
            evaluator_id: id("revocation-authority"),
            reason_digest: Digest32::of_bytes(b"revocation evidence"),
        }))
        .expect("revoke previously excluded child");
    assert_eq!(registry.state(&id("child")), Some(ArtifactState::Revoked));
    let mut restored = ArtifactRegistry::from_snapshot(registry.snapshot()).expect("replay");
    assert!(
        restored
            .eligible_candidates(ArtifactKind::Policy, Digest32::of_bytes(b"objective"))
            .is_empty()
    );
    assert_eq!(
        append_candidate(
            &mut restored,
            "new-child",
            Some("root"),
            /*generation*/ 4
        ),
        Err(ArtifactRegistryError::PredecessorUnavailable(
            "root".to_string()
        )),
    );
    assert_eq!(restored.snapshot(), registry.snapshot());
}
