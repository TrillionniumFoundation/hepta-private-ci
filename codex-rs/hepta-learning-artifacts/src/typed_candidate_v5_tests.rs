use super::*;
use crate::ArtifactEvent;
use crate::ArtifactRegistry;
use crate::StateChange;
use pretty_assertions::assert_eq;

#[path = "typed_candidate_v5_fixtures.rs"]
mod fixtures;
use fixtures::*;

#[test]
fn selected_typed_value_closes_permanently_on_stale_current() {
    let f = Fixture::new();
    let mut registry = ArtifactRegistry::new();
    f.add(&mut registry, "baseline", None, 1);
    let old = f.save(&registry, "old.snapshot");
    f.add(&mut registry, "candidate", Some("baseline"), 2);
    let current = f.save(&registry, "current.snapshot");
    let mut typed = f.load(&current, "candidate");
    assert_eq!(
        must(typed.with_current(f.view(&current), |value| *value)),
        2
    );
    assert_eq!(
        typed.with_current(f.view(&old), |value| *value),
        Err(PinnedCandidateLoadError::FrontierMismatch)
    );
    assert_eq!(
        typed.with_current(f.view(&current), |value| *value),
        Err(PinnedCandidateLoadError::Unavailable)
    );
}

#[test]
fn explicit_predecessor_rollback_requires_current_history_and_keeps_it_forward() {
    let f = Fixture::new();
    let mut registry = ArtifactRegistry::new();
    f.add(&mut registry, "baseline", None, 1);
    let old = f.save(&registry, "old.snapshot");
    f.add(&mut registry, "candidate", Some("baseline"), 2);
    let current = f.save(&registry, "current.snapshot");
    let mut typed = f.load(&current, "candidate");
    assert!(matches!(
        typed.rollback_to_predecessor(
            must(File::open(&old.path)),
            f.payload("baseline"),
            f.selection(&old, "baseline"),
            f.view(&old),
            decode
        ),
        Err(TypedCandidateErrorV5::Current(
            PinnedCandidateLoadError::FrontierMismatch
        ))
    ));
    assert_eq!(
        must(typed.with_current(f.view(&current), |value| *value)),
        2
    );
    assert!(matches!(
        typed.rollback_to_predecessor(
            must(File::open(&current.path)),
            f.payload("candidate"),
            f.selection(&current, "candidate"),
            f.view(&current),
            decode
        ),
        Err(TypedCandidateErrorV5::RollbackTarget)
    ));
    must(typed.rollback_to_predecessor(
        must(File::open(&current.path)),
        f.payload("baseline"),
        f.selection(&current, "baseline"),
        f.view(&current),
        decode,
    ));
    assert_eq!(
        must(typed.with_current(f.view(&current), |value| *value)),
        1
    );
    assert_eq!(typed.spec().registry_receipt, current.receipt);
    assert_eq!(typed.spec().manifest.artifact_id, id("baseline"));
}

#[test]
fn revoked_candidate_closes_and_only_explicit_eligible_predecessor_reload_recovers() {
    let f = Fixture::new();
    let mut registry = ArtifactRegistry::new();
    f.add(&mut registry, "baseline", None, 1);
    f.add(&mut registry, "candidate", Some("baseline"), 2);
    let current = f.save(&registry, "current.snapshot");
    let mut typed = f.load(&current, "candidate");
    must(registry.append(ArtifactEvent::Revoke(StateChange {
        event_id: id("withdraw-candidate"),
        artifact_id: id("candidate"),
        evaluator_id: id("independent-evaluator"),
        reason_digest: digest("source withdrawal"),
    })));
    let revoked = f.save(&registry, "revoked.snapshot");
    assert_eq!(
        typed.with_current(f.view(&revoked), |value| *value),
        Err(PinnedCandidateLoadError::Ineligible)
    );
    assert_eq!(
        typed.with_current(f.view(&current), |value| *value),
        Err(PinnedCandidateLoadError::Unavailable)
    );
    must(typed.rollback_to_predecessor(
        must(File::open(&revoked.path)),
        f.payload("baseline"),
        f.selection(&revoked, "baseline"),
        f.view(&revoked),
        decode,
    ));
    assert_eq!(
        must(typed.with_current(f.view(&revoked), |value| *value)),
        1
    );
}

#[test]
fn wrong_schema_or_failed_decoder_cannot_create_a_usable_typed_snapshot() {
    let f = Fixture::new();
    let mut registry = ArtifactRegistry::new();
    f.add(&mut registry, "baseline", None, 1);
    let current = f.save(&registry, "current.snapshot");
    assert!(matches!(
        TypedSelectedCandidateV5::load(
            must(File::open(&current.path)),
            f.payload("baseline"),
            f.selection(&current, "baseline"),
            f.view(&current),
            digest("wrong-schema"),
            decode
        ),
        Err(TypedCandidateErrorV5::Binding)
    ));
    let result = TypedSelectedCandidateV5::<u64>::load(
        must(File::open(&current.path)),
        f.payload("baseline"),
        f.selection(&current, "baseline"),
        f.view(&current),
        digest("typed-u64"),
        |_, _| Err(std::io::Error::from(std::io::ErrorKind::InvalidData)),
    );
    assert!(matches!(result, Err(TypedCandidateErrorV5::Decode(_))));
}

#[test]
fn failed_refresh_remembers_revocations_and_cannot_rollback_to_an_old_eligible_view() {
    let f = Fixture::new();
    let mut registry = ArtifactRegistry::new();
    f.add(&mut registry, "baseline", None, 1);
    f.add(&mut registry, "candidate", Some("baseline"), 2);
    let old = f.save(&registry, "old.snapshot");
    let mut typed = f.load(&old, "candidate");
    for name in ["candidate", "baseline"] {
        must(registry.append(ArtifactEvent::Revoke(StateChange {
            event_id: id(&format!("withdraw-{name}")),
            artifact_id: id(name),
            evaluator_id: id("independent-evaluator"),
            reason_digest: digest("both sources withdrawn"),
        })));
    }
    let revoked = f.save(&registry, "revoked.snapshot");
    assert_eq!(
        typed.with_current(f.view(&revoked), |value| *value),
        Err(PinnedCandidateLoadError::Ineligible)
    );
    assert_eq!(typed.spec().registry_receipt, old.receipt);
    assert!(matches!(
        typed.rollback_to_predecessor(
            must(File::open(&old.path)),
            f.payload("baseline"),
            f.selection(&old, "baseline"),
            f.view(&old),
            decode
        ),
        Err(TypedCandidateErrorV5::Current(
            PinnedCandidateLoadError::FrontierMismatch
        ))
    ));
    assert_eq!(
        typed.with_current(f.view(&old), |value| *value),
        Err(PinnedCandidateLoadError::Unavailable)
    );
    assert_eq!(
        typed.with_current(f.view(&revoked), |value| *value),
        Err(PinnedCandidateLoadError::Unavailable)
    );
}
