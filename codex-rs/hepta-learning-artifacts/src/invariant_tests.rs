use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::ArtifactEvent;
use crate::ArtifactKind;
use crate::ArtifactManifest;
use crate::ArtifactRegistry;
use crate::ArtifactState;
use crate::RegistryAppendDisposition;
use crate::StateChange;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid invariant fixture id")
}

fn manifest(name: &str, generation: u64, predecessor: Option<&str>) -> ArtifactManifest {
    ArtifactManifest {
        artifact_id: id(name),
        kind: ArtifactKind::Policy,
        generation: Generation::new(generation).expect("valid generation"),
        predecessor_id: predecessor.map(id),
        content_digest: Digest32::of_bytes(format!("bytes:{name}").as_bytes()),
        objective_digest: Digest32::of_bytes(b"objective"),
        support_digest: Digest32::of_bytes(b"support"),
        producer_id: id("generator"),
        compatibility_digest: Digest32::of_bytes(b"compatibility"),
        encoded_size_bytes: 128,
    }
}

fn register(event: &str, value: ArtifactManifest) -> ArtifactEvent {
    ArtifactEvent::Register {
        event_id: id(event),
        manifest: value,
    }
}

fn revoke(event: &str, artifact: &str) -> ArtifactEvent {
    ArtifactEvent::Revoke(StateChange {
        event_id: id(event),
        artifact_id: id(artifact),
        evaluator_id: id("revocation-authority"),
        reason_digest: Digest32::of_bytes(b"revoked"),
    })
}

#[test]
fn property_exact_duplicate_has_one_successful_mutation() {
    for replay_count in 1..=64 {
        let mut registry = ArtifactRegistry::new();
        let event = register("register-a", manifest("artifact-a", 1, None));
        let first = registry.append(event.clone()).expect("initial append");
        assert_eq!(first.disposition, RegistryAppendDisposition::Appended);
        for _ in 0..replay_count {
            let replay = registry.append(event.clone()).expect("exact replay");
            assert_eq!(
                replay.disposition,
                RegistryAppendDisposition::IdempotentReplay
            );
        }
        assert_eq!(registry.records().len(), 1);
        assert_eq!(
            ArtifactRegistry::from_snapshot(registry.snapshot())
                .expect("snapshot replay")
                .snapshot(),
            registry.snapshot()
        );
    }
}

#[test]
fn property_revoked_dependency_never_reactivates() {
    for descendant_count in 1..=16 {
        let mut registry = ArtifactRegistry::new();
        registry
            .append(register("register-root", manifest("root", 1, None)))
            .expect("root");
        let mut predecessor = "root".to_owned();
        for index in 0..descendant_count {
            let name = format!("child-{index}");
            registry
                .append(register(
                    &format!("register-{name}"),
                    manifest(&name, index as u64 + 2, Some(&predecessor)),
                ))
                .expect("descendant");
            predecessor = name;
        }
        registry.append(revoke("revoke-root", "root")).expect("revoke");
        assert_eq!(registry.state(&id("root")), Some(ArtifactState::Revoked));
        assert!(!registry.is_eligible(&id("root")));
        for index in 0..descendant_count {
            assert!(!registry.is_eligible(&id(&format!("child-{index}"))));
        }

        let replay = registry
            .append(revoke("revoke-root", "root"))
            .expect("exact revoke replay");
        assert_eq!(
            replay.disposition,
            RegistryAppendDisposition::IdempotentReplay
        );
        assert_eq!(registry.state(&id("root")), Some(ArtifactState::Revoked));
        assert!(
            registry
                .append(register(
                    "attempt-reactivation",
                    manifest("root", descendant_count as u64 + 2, None),
                ))
                .is_err()
        );
        assert_eq!(registry.state(&id("root")), Some(ArtifactState::Revoked));
    }
}

#[test]
fn property_identity_drift_is_never_idempotent() {
    for generation in 1..=32 {
        let mut registry = ArtifactRegistry::new();
        registry
            .append(register(
                "shared-event",
                manifest("artifact-a", generation, None),
            ))
            .expect("initial append");
        assert!(
            registry
                .append(register(
                    "shared-event",
                    manifest("artifact-b", generation, None),
                ))
                .is_err()
        );
        assert_eq!(registry.records().len(), 1);
    }
}
