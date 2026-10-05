use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::ArtifactRegistry;
use crate::ArtifactEvent;
use crate::ArtifactKind;
use crate::ArtifactManifest;
use crate::ArtifactRegistryError;
use crate::ArtifactState;
use crate::RegistryAppendDisposition;
use crate::StateChange;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn must_err<T: Debug, E>(result: Result<T, E>) -> E {
    match result {
        Err(error) => error,
        Ok(value) => panic!("expected error, received value: {value:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn manifest(artifact_id: &str, generation: u64) -> ArtifactManifest {
    ArtifactManifest {
        artifact_id: id(artifact_id),
        kind: ArtifactKind::Policy,
        generation: must(Generation::new(generation)),
        predecessor_id: None,
        content_digest: Digest32::of_bytes(artifact_id.as_bytes()),
        objective_digest: Digest32::of_bytes(b"objective"),
        support_digest: Digest32::of_bytes(b"support"),
        producer_id: id("candidate-generator"),
        compatibility_digest: Digest32::of_bytes(b"compatibility"),
        encoded_size_bytes: 1024,
    }
}

fn register(event_id: &str, manifest: ArtifactManifest) -> ArtifactEvent {
    ArtifactEvent::Register {
        event_id: id(event_id),
        manifest,
    }
}

#[test]
fn registration_is_immutable_and_idempotent() {
    let event = register("event-a", manifest("artifact-a", 1));
    let mut registry = ArtifactRegistry::new();
    let first = must(registry.append(event.clone()));
    let replay = must(registry.append(event));

    assert_eq!(first.disposition, RegistryAppendDisposition::Appended);
    assert_eq!(
        replay.disposition,
        RegistryAppendDisposition::IdempotentReplay
    );
    assert_eq!(
        registry.state(&id("artifact-a")),
        Some(ArtifactState::Candidate)
    );
}

#[test]
fn derived_artifact_requires_monotonic_matching_lineage() {
    let mut registry = ArtifactRegistry::new();
    must(registry.append(register("event-a", manifest("artifact-a", 2))));
    let mut derived = manifest("artifact-b", 1);
    derived.predecessor_id = Some(id("artifact-a"));

    assert_eq!(
        must_err(registry.append(register("event-b", derived))),
        ArtifactRegistryError::GenerationNotAdvanced
    );
}

#[test]
fn quarantine_and_revoke_remove_candidate_eligibility() {
    let objective = Digest32::of_bytes(b"objective");
    let mut registry = ArtifactRegistry::new();
    must(registry.append(register("event-a", manifest("artifact-a", 1))));
    assert_eq!(
        registry
            .eligible_candidates(ArtifactKind::Policy, objective)
            .len(),
        1
    );
    must(registry.append(ArtifactEvent::Quarantine(StateChange {
        event_id: id("event-quarantine-a"),
        artifact_id: id("artifact-a"),
        evaluator_id: id("independent-evaluator"),
        reason_digest: Digest32::of_bytes(b"regression"),
    })));
    assert!(
        registry
            .eligible_candidates(ArtifactKind::Policy, objective)
            .is_empty()
    );
    must(registry.append(ArtifactEvent::Revoke(StateChange {
        event_id: id("event-revoke-a"),
        artifact_id: id("artifact-a"),
        evaluator_id: id("deletion-authority"),
        reason_digest: Digest32::of_bytes(b"delete"),
    })));
    assert_eq!(
        registry.state(&id("artifact-a")),
        Some(ArtifactState::Revoked)
    );
}

#[test]
fn ancestor_revocation_makes_derived_artifacts_ineligible() {
    let objective = Digest32::of_bytes(b"objective");
    let mut registry = ArtifactRegistry::new();
    must(registry.append(register("event-a", manifest("artifact-a", 1))));
    let mut derived = manifest("artifact-b", 2);
    derived.predecessor_id = Some(id("artifact-a"));
    must(registry.append(register("event-b", derived)));
    assert_eq!(
        registry
            .eligible_candidates(ArtifactKind::Policy, objective)
            .len(),
        2
    );

    must(registry.append(ArtifactEvent::Revoke(StateChange {
        event_id: id("event-revoke-a"),
        artifact_id: id("artifact-a"),
        evaluator_id: id("deletion-authority"),
        reason_digest: Digest32::of_bytes(b"delete"),
    })));

    assert!(!registry.is_eligible(&id("artifact-a")));
    assert!(!registry.is_eligible(&id("artifact-b")));
    assert!(
        registry
            .eligible_candidates(ArtifactKind::Policy, objective)
            .is_empty()
    );
}

#[test]
fn artifact_producer_cannot_self_evaluate() {
    let mut registry = ArtifactRegistry::new();
    must(registry.append(register("event-a", manifest("artifact-a", 1))));

    assert_eq!(
        must_err(registry.append(ArtifactEvent::Quarantine(StateChange {
            event_id: id("event-quarantine-a"),
            artifact_id: id("artifact-a"),
            evaluator_id: id("candidate-generator"),
            reason_digest: Digest32::of_bytes(b"self-label"),
        }))),
        ArtifactRegistryError::ProducerSelfEvaluates("artifact-a".to_owned())
    );
}

#[test]
fn snapshot_replay_preserves_lineage_and_state() {
    let mut registry = ArtifactRegistry::new();
    must(registry.append(register("event-a", manifest("artifact-a", 1))));
    let mut derived = manifest("artifact-b", 2);
    derived.predecessor_id = Some(id("artifact-a"));
    must(registry.append(register("event-b", derived)));
    let restored = must(ArtifactRegistry::from_snapshot(registry.snapshot()));

    assert_eq!(restored.snapshot(), registry.snapshot());
    let derived_manifest = match restored.manifest(&id("artifact-b")) {
        Some(value) => value,
        None => panic!("derived manifest should exist"),
    };
    assert_eq!(derived_manifest.predecessor_id, Some(id("artifact-a")));
}

#[test]
fn event_identity_reuse_with_drift_fails() {
    let mut registry = ArtifactRegistry::new();
    must(registry.append(register("event-a", manifest("artifact-a", 1))));

    assert_eq!(
        must_err(registry.append(register("event-a", manifest("artifact-b", 1)))),
        ArtifactRegistryError::IdentityConflict("event-a".to_owned())
    );
}

#[test]
fn indexed_historical_replay_and_head_survive_growth_revocation_and_restore() {
    let mut registry = ArtifactRegistry::new();
    assert_eq!(registry.head_digest(), Digest32::ZERO);
    let mut probes = Vec::new();
    for index in 0..4095 {
        let event = register(
            &format!("event-{index}"),
            manifest(&format!("artifact-{index}"), 1),
        );
        let receipt = must(registry.append(event.clone()));
        assert_eq!(registry.head_digest(), receipt.chain_digest);
        if [0, 2048, 4094].contains(&index) {
            probes.push((event, receipt));
        }
    }
    let revoke = ArtifactEvent::Revoke(StateChange {
        event_id: id("revoke-first"),
        artifact_id: id("artifact-0"),
        evaluator_id: id("independent-evaluator"),
        reason_digest: Digest32::of_bytes(b"withdrawn"),
    });
    let receipt = must(registry.append(revoke.clone()));
    probes.push((revoke, receipt));
    assert_eq!(
        registry.records().len(),
        crate::limits::MAX_DURABLE_ARTIFACT_RECORDS
    );
    assert_eq!(
        must_err(registry.append(register("over-capacity", manifest("over-capacity", 1)))),
        ArtifactRegistryError::RecordLimitExceeded
    );
    let snapshot = registry.snapshot();
    assert_eq!(registry.head_digest(), snapshot.head_digest);
    let restored = must(ArtifactRegistry::from_snapshot(snapshot.clone()));
    for mut owner in [registry, restored] {
        for (event, original) in &probes {
            let replay = must(owner.append(event.clone()));
            let mut expected = original.clone();
            expected.disposition = RegistryAppendDisposition::IdempotentReplay;
            assert_eq!(replay, expected);
        }
        assert_eq!(owner.head_digest(), snapshot.head_digest);
        assert_eq!(owner.snapshot(), snapshot);
        assert_eq!(owner.state(&id("artifact-0")), Some(ArtifactState::Revoked));
        assert_eq!(
            must_err(owner.append(register("event-0", manifest("different-payload", 1)))),
            ArtifactRegistryError::IdentityConflict("event-0".to_owned())
        );
        assert_eq!(owner.head_digest(), snapshot.head_digest);
        assert_eq!(owner.snapshot(), snapshot);
    }
}

#[test]
#[ignore = "explicit local registry growth diagnostic; not a latency acceptance gate"]
fn registry_growth_curve_compares_head_read_with_snapshot_and_historical_retry() {
    use std::hint::black_box;
    use std::time::Instant;

    let mut owner = ArtifactRegistry::new();
    let first = register("first-event", manifest("first-artifact", 1));
    let first_receipt = must(owner.append(first.clone()));
    let mut count = 1;
    for records in [64_usize, 256, 1024, 4096] {
        for index in count..records {
            must(owner.append(register(
                &format!("event-{index}"),
                manifest(&format!("artifact-{index}"), 1),
            )));
        }
        let expected = owner.snapshot();
        let started = Instant::now();
        for _ in 0..256 {
            assert_eq!(black_box(&owner).head_digest(), expected.head_digest);
        }
        let head_ns = started.elapsed().as_nanos();
        let started = Instant::now();
        for _ in 0..256 {
            assert_eq!(
                black_box(&owner).snapshot().head_digest,
                expected.head_digest
            );
        }
        let snapshot_head_ns = started.elapsed().as_nanos();
        let started = Instant::now();
        for _ in 0..256 {
            assert_eq!(
                must(owner.append(first.clone())).chain_digest,
                first_receipt.chain_digest
            );
        }
        let retry_ns = started.elapsed().as_nanos();
        assert_eq!(owner.snapshot(), expected);
        let started = Instant::now();
        let restored = must(ArtifactRegistry::from_snapshot(expected.clone()));
        let restore_ns = started.elapsed().as_nanos();
        assert_eq!(restored.snapshot(), expected);
        println!(
            "HEPTA_ARTIFACT_GROWTH_V1 {{\"records\":{records},\"samples\":256,\"head_total_ns\":{head_ns},\"snapshot_head_total_ns\":{snapshot_head_ns},\"retry_total_ns\":{retry_ns},\"restore_ns\":{restore_ns}}}"
        );
        count = records;
    }
}

#[path = "registry_lineage_tests.rs"]
mod lineage;
