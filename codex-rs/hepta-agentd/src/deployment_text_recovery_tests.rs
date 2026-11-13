use super::*;
use crate::deployment_issuer::text::tests::body;
use crate::deployment_issuer::text::tests::identity;
use crate::deployment_issuer::text::tests::issuer;
use codex_hepta_contracts::SystemAuthorityClock;
use pretty_assertions::assert_eq;

#[test]
fn restart_recovers_only_exact_namespace_and_old_generation_without_signing() {
    let directory = tempfile::tempdir().unwrap();
    let mut owner = identity(directory.path());
    let path = directory.path().join("issuer");
    let original = issuer(&path, &owner);
    let first = original
        .text(&owner, "principal-a:1", body(), TextIssuerOperation::Sign)
        .unwrap();
    original
        .text(&owner, "principal-b:2", body(), TextIssuerOperation::Sign)
        .unwrap();
    let third = original
        .text(&owner, "principal-a:3", body(), TextIssuerOperation::Sign)
        .unwrap();
    drop(original);
    owner.spawn_generation = 2;
    let original = DeploymentFinalUseIssuer::open(&path, Arc::new(SystemAuthorityClock)).unwrap();
    let before = original.store.load(STATE_OWNER).unwrap();
    assert_eq!(
        original
            .retained_text_page(&owner, "principal-a", "thread-one", 0, 3)
            .unwrap(),
        Some(("principal-a:1".into(), first))
    );
    assert_eq!(
        original
            .retained_text_page(&owner, "principal-a", "thread-one", 1, 3)
            .unwrap(),
        Some(("principal-a:3".into(), third))
    );
    assert_eq!(
        original
            .retained_text_page(&owner, "principal-a", "thread-one", 3, 3)
            .unwrap(),
        None
    );
    assert!(
        original
            .retained_text_page(&owner, "principal-a", "thread-one", 0, 4)
            .is_err()
    );
    assert!(
        original
            .retained_text_page(&owner, "principal-a", "another-thread", 0, 3)
            .is_err()
    );
    assert!(original.store.load(STATE_OWNER).unwrap() == before);
}

#[test]
fn encoded_capacity_preserves_original_refs_and_does_not_consume_next_intent() {
    let directory = tempfile::tempdir().unwrap();
    let owner = identity(directory.path());
    let original = issuer(&directory.path().join("issuer"), &owner);
    let mut input = body();
    input.text = "x".repeat(8192);
    let first = original
        .text(&owner, "input:1", input.clone(), TextIssuerOperation::Sign)
        .unwrap();
    let mut refused = false;
    for sequence in 2..=32 {
        let before = original.store.load(STATE_OWNER).unwrap();
        if original
            .text(
                &owner,
                &format!("input:{sequence}"),
                input.clone(),
                TextIssuerOperation::Sign,
            )
            .is_err()
        {
            assert!(original.store.load(STATE_OWNER).unwrap() == before);
            refused = true;
            break;
        }
    }
    assert!(refused);
    assert_eq!(
        original
            .text(&owner, "input:1", input, TextIssuerOperation::Lookup)
            .unwrap(),
        first
    );
}
