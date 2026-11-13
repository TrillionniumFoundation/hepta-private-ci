//! Actual original issuer-store CAS/reopen tests. These do not provision a
//! production Root authority or claim a human/model login.
use super::*;
use crate::deployment_issuer::text::tests::body;
use crate::deployment_issuer::text::tests::identity;
use crate::deployment_issuer::text::tests::issuer;
use codex_hepta_contracts::SystemAuthorityClock;
use pretty_assertions::assert_eq;

#[test]
fn lost_unsigned_close_ack_and_late_sign_stay_closed_after_original_owner_reopen() {
    let directory = tempfile::tempdir().unwrap();
    let owner = identity(directory.path());
    let path = directory.path().join("issuer");
    let original = issuer(&path, &owner);
    let proof = original
        .close_unsigned_text_until(&owner, "input", "input:1", body(), None)
        .unwrap();
    assert!(matches!(
        proof,
        TextUnsignedClosure::Closed {
            through_sequence: 1,
            ..
        }
    ));
    assert_eq!(original.store.load(STATE_OWNER).unwrap().sequence, 0);
    drop(original); // The closure reply was lost before the client could use it.
    let original = DeploymentFinalUseIssuer::open(&path, Arc::new(SystemAuthorityClock)).unwrap();
    assert_eq!(
        original
            .close_unsigned_text_until(&owner, "input", "input:1", body(), None)
            .unwrap(),
        proof
    );
    // This is the delayed first Sign, not a lookup. It cannot issue after the
    // same original record has been reopened, even with a different body/prefix.
    assert!(
        original
            .text(&owner, "input:1", body(), TextIssuerOperation::Sign)
            .is_err()
    );
    let mut altered = body();
    altered.text = "replacement must not issue".into();
    assert!(
        original
            .text(&owner, "other:1", altered, TextIssuerOperation::Sign)
            .is_err()
    );
    assert_eq!(original.store.load(STATE_OWNER).unwrap().sequence, 0);
    assert!(
        original
            .store
            .load(STATE_OWNER)
            .unwrap()
            .text_signatures
            .is_empty()
    );
    let next = original
        .text(&owner, "input:2", body(), TextIssuerOperation::Sign)
        .unwrap();
    assert_eq!(next.sequence, 1);
}

#[test]
fn lost_sign_ack_returns_exact_retained_original_and_cannot_be_closed_or_replaced() {
    let directory = tempfile::tempdir().unwrap();
    let mut owner = identity(directory.path());
    let path = directory.path().join("issuer");
    let original = issuer(&path, &owner);
    let signed = original
        .text(&owner, "input:1", body(), TextIssuerOperation::Sign)
        .unwrap();
    drop(original); // Sign committed, its response was lost.
    owner.spawn_generation = 2;
    let original = DeploymentFinalUseIssuer::open(&path, Arc::new(SystemAuthorityClock)).unwrap();
    let before = original.store.load(STATE_OWNER).unwrap();
    let mut current = body();
    current.spawn_generation = 2;
    assert_eq!(
        original
            .close_unsigned_text_until(&owner, "input", "input:1", current.clone(), None)
            .unwrap(),
        TextUnsignedClosure::Retained {
            envelope: signed.clone()
        }
    );
    assert!(
        original
            .close_unsigned_text_until(&owner, "other", "input:1", current.clone(), None)
            .is_err()
    );
    let mut changed = current.clone();
    changed.text = "different".into();
    assert!(
        original
            .close_unsigned_text_until(&owner, "input", "input:1", changed, None)
            .is_err()
    );
    assert!(
        original
            .close_unsigned_text_until(&owner, "input", "input:2", body(), None)
            .is_err()
    );
    current.thread_id = "not-installed-thread".into();
    assert!(
        original
            .close_unsigned_text_until(&owner, "input", "input:2", current, None)
            .is_err()
    );
    assert!(original.store.load(STATE_OWNER).unwrap() == before);
    assert_eq!(
        original
            .retained_text_page(&owner, "input", "thread-one", 0, 1)
            .unwrap(),
        Some(("input:1".into(), signed))
    );
}
