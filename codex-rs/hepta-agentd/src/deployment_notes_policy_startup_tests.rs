//! Failure cuts on the existing ordinary-owner issuer fixture. These exercise
//! the real retained CAS and admission; they do not qualify a Root deployment.

use super::*;
use pretty_assertions::assert_eq;

#[test]
fn notes_policy_post_cas_clock_error_retains_the_same_successor_for_exact_retry() {
    let f = Fixture::new();
    let next = NotesTargetIdentity {
        incarnation: "3".repeat(32),
        ..f.target.clone()
    };
    let before = f.issuer.store.load(STATE_OWNER).unwrap();
    let mut expected = before.clone();
    expected.policies[0].destination_id = next.destination_id();
    expected.policies[0].scope_sha256 = next.scope_digest().into_array();
    let frontier = f.registry.frontier().unwrap();
    let key = f.issuer.trust_key().unwrap().verifying_key;
    // The original verifier samples at verify_use and the dispatch fence,
    // then the issuer checks its retained proof. The fourth read follows CAS.
    f.clock.reads.store(0, Ordering::SeqCst);
    f.clock.unavailable_on.store(4, Ordering::SeqCst);
    assert!(
        f.issuer
            .replace_notes_policy(
                &f.writer, &f.target, /*previous_lifetime_ms*/ 1000, &next,
                /*lifetime_ms*/ 1000,
            )
            .is_err()
    );
    assert_eq!(f.clock.reads.load(Ordering::SeqCst), 4);
    assert_eq!(
        serde_json::to_value(f.issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
        serde_json::to_value(&expected).unwrap(),
    );
    assert_eq!(f.registry.frontier().unwrap(), frontier);
    f.clock.unavailable_on.store(u64::MAX, Ordering::SeqCst);
    f.issuer
        .replace_notes_policy(
            &f.writer, &f.target, /*previous_lifetime_ms*/ 1000, &next,
            /*lifetime_ms*/ 1000,
        )
        .unwrap();
    RootNotesGrantAdmission::open(
        &f.issuer,
        f.registry.clone(),
        f.writer.clone(),
        &next,
        /*lifetime_ms*/ 1000,
    )
    .unwrap();
    assert_eq!(
        serde_json::to_value(f.issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
        serde_json::to_value(expected).unwrap(),
    );
    assert_eq!(f.registry.frontier().unwrap(), frontier);
    assert_eq!(f.issuer.trust_key().unwrap().verifying_key, key);
}

#[test]
fn notes_policy_admission_error_cannot_rollback_the_retained_update_or_sign() {
    let f = Fixture::new();
    let next = NotesTargetIdentity {
        incarnation: "3".repeat(32),
        ..f.target.clone()
    };
    f.issuer
        .replace_notes_policy(
            &f.writer, &f.target, /*previous_lifetime_ms*/ 1000, &next,
            /*lifetime_ms*/ 1000,
        )
        .unwrap();
    let retained = f.issuer.store.load(STATE_OWNER).unwrap();
    let frontier = f.registry.frontier().unwrap();
    f.clock.reads.store(0, Ordering::SeqCst);
    f.clock.unavailable_on.store(1, Ordering::SeqCst);
    assert!(
        RootNotesGrantAdmission::open(
            &f.issuer,
            f.registry.clone(),
            f.writer.clone(),
            &next,
            /*lifetime_ms*/ 1000,
        )
        .is_err()
    );
    assert_eq!(f.clock.reads.load(Ordering::SeqCst), 1);
    assert_eq!(
        serde_json::to_value(f.issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
        serde_json::to_value(&retained).unwrap(),
    );
    f.clock.unavailable_on.store(u64::MAX, Ordering::SeqCst);
    f.issuer
        .replace_notes_policy(
            &f.writer, &f.target, /*previous_lifetime_ms*/ 1000, &next,
            /*lifetime_ms*/ 1000,
        )
        .unwrap();
    RootNotesGrantAdmission::open(
        &f.issuer,
        f.registry.clone(),
        f.writer.clone(),
        &next,
        /*lifetime_ms*/ 1000,
    )
    .unwrap();
    assert_eq!(
        serde_json::to_value(f.issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
        serde_json::to_value(retained).unwrap(),
    );
    assert_eq!(f.registry.frontier().unwrap(), frontier);
}

#[test]
fn notes_policy_retained_successor_cannot_revive_an_expired_writer() {
    let f = Fixture::new();
    let next = NotesTargetIdentity {
        incarnation: "3".repeat(32),
        ..f.target.clone()
    };
    f.issuer
        .replace_notes_policy(
            &f.writer, &f.target, /*previous_lifetime_ms*/ 1000, &next,
            /*lifetime_ms*/ 1000,
        )
        .unwrap();
    let retained = f.issuer.store.load(STATE_OWNER).unwrap();
    let frontier = f.registry.frontier().unwrap();
    f.clock.value.store(20_000, Ordering::SeqCst);
    assert!(
        RootNotesGrantAdmission::open(
            &f.issuer,
            f.registry.clone(),
            f.writer.clone(),
            &next,
            /*lifetime_ms*/ 1000,
        )
        .is_err()
    );
    assert!(
        f.issuer
            .replace_notes_policy(
                &f.writer, &f.target, /*previous_lifetime_ms*/ 1000, &next,
                /*lifetime_ms*/ 1000,
            )
            .is_err()
    );
    assert_eq!(
        serde_json::to_value(f.issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
        serde_json::to_value(retained).unwrap(),
    );
    assert_eq!(f.registry.frontier().unwrap(), frontier);
}
