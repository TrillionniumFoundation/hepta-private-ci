//! Pure source-fixture tests: none run a real UI, OS call, JIT or GPU.
use super::*;
use crate::{ActionArgumentsV1, CapabilityGrantV1};

fn h(x: &[u8]) -> Digest32 {
    Digest32::of_bytes(x)
}
fn verifier() -> ActionVerifierV1 {
    ActionVerifierV1 {
        generation: 9,
        grant: CapabilityGrantV1 {
            digest: h(b"external-grant-claim"),
            allowed: 1 | 2 | 4 | 8 | 16,
        },
    }
}
fn readback() -> UiReadbackV1 {
    UiReadbackV1 {
        principal_scope_digest: h(b"principal-a"),
        observer_digest: h(b"source-owner"),
        tree_digest: h(b"tree-version-1"),
        generation: 9,
        observed_at_ms: 100_000,
        max_age_ms: 1_000,
    }
}
fn plan() -> UiGuardedPlanV1 {
    let grant = verifier().grant.digest;
    UiGuardedPlanV1 {
        required_readback: readback(),
        actions: vec![
            ActionFrameV1 {
                generation: 9,
                sequence: 1,
                capability_digest: grant,
                arguments: ActionArgumentsV1::Click {
                    target_digest: h(b"visible-button"),
                    x: 10,
                    y: 20,
                },
            },
            ActionFrameV1 {
                generation: 9,
                sequence: 2,
                capability_digest: grant,
                arguments: ActionArgumentsV1::TypeText {
                    text: "ok".to_string(),
                },
            },
        ],
    }
}

#[test]
fn guarded_shadow_round_trips_with_no_authority() {
    let p =
        propose_ui_guarded_shadow_v1(verifier(), &plan(), &readback(), 100_999).expect("shadow");
    assert!(!p.authority.grants_any());
    assert!(!p.proposed_actions.authority.grants_any());
    assert_ne!(p.guarded_digest, p.proposed_actions.proposal_digest);
    verify_ui_guarded_shadow_v1(verifier(), &p, &readback(), 100_999).expect("verify");
}
#[test]
fn different_principal_or_tree_is_rejected() {
    let mut observed = readback();
    observed.principal_scope_digest = h(b"principal-b");
    assert_eq!(
        propose_ui_guarded_shadow_v1(verifier(), &plan(), &observed, 100_100),
        Err(UiGuardErrorV1::ChangedObservation)
    );
    observed = readback();
    observed.tree_digest = h(b"next-tree");
    assert_eq!(
        propose_ui_guarded_shadow_v1(verifier(), &plan(), &observed, 100_100),
        Err(UiGuardErrorV1::ChangedObservation)
    );
}
#[test]
fn stale_and_future_observation_are_rejected() {
    assert_eq!(
        propose_ui_guarded_shadow_v1(verifier(), &plan(), &readback(), 101_001),
        Err(UiGuardErrorV1::StaleObservation)
    );
    assert_eq!(
        propose_ui_guarded_shadow_v1(verifier(), &plan(), &readback(), 99_999),
        Err(UiGuardErrorV1::ObservationFromFuture)
    );
}
#[test]
fn changed_generation_and_bounds_fail_closed() {
    let mut p = plan();
    p.required_readback.generation = 8;
    assert_eq!(
        propose_ui_guarded_shadow_v1(verifier(), &p, &p.required_readback, 100_100),
        Err(UiGuardErrorV1::WrongGeneration)
    );
    p = plan();
    p.required_readback.max_age_ms = 5_001;
    assert_eq!(
        propose_ui_guarded_shadow_v1(verifier(), &p, &p.required_readback, 100_100),
        Err(UiGuardErrorV1::InvalidObservationWindow)
    );
    p = plan();
    p.required_readback.tree_digest = Digest32::from_array([0; 32]);
    assert_eq!(
        propose_ui_guarded_shadow_v1(verifier(), &p, &p.required_readback, 100_100),
        Err(UiGuardErrorV1::EmptyIdentity)
    );
}
#[test]
fn invalid_action_sequence_or_capability_denied() {
    let mut p = plan();
    p.actions[1].sequence = 4;
    assert_eq!(
        propose_ui_guarded_shadow_v1(verifier(), &p, &readback(), 100_100),
        Err(UiGuardErrorV1::Action(ActionErrorV1::SequenceMismatch))
    );
    p = plan();
    p.actions[1].capability_digest = h(b"different-grant");
    assert_eq!(
        propose_ui_guarded_shadow_v1(verifier(), &p, &readback(), 100_100),
        Err(UiGuardErrorV1::Action(ActionErrorV1::CapabilityDenied))
    );
}
#[test]
fn modified_proposal_and_binding_are_denied() {
    let mut p =
        propose_ui_guarded_shadow_v1(verifier(), &plan(), &readback(), 100_100).expect("shadow");
    p.proposed_actions.actions[0].arguments = ActionArgumentsV1::Scroll { delta: 3 };
    assert_eq!(
        verify_ui_guarded_shadow_v1(verifier(), &p, &readback(), 100_101),
        Err(UiGuardErrorV1::Action(ActionErrorV1::DigestMismatch))
    );
    p = propose_ui_guarded_shadow_v1(verifier(), &plan(), &readback(), 100_100).expect("shadow");
    p.guarded_digest = h(b"not-its-source");
    assert_eq!(
        verify_ui_guarded_shadow_v1(verifier(), &p, &readback(), 100_101),
        Err(UiGuardErrorV1::ChangedGuardedDigest)
    );
}
#[test]
fn replaced_observer_and_stale_recheck_are_denied() {
    let p =
        propose_ui_guarded_shadow_v1(verifier(), &plan(), &readback(), 100_100).expect("shadow");
    let mut forged = readback();
    forged.observer_digest = h(b"not-the-observer");
    assert_eq!(
        verify_ui_guarded_shadow_v1(verifier(), &p, &forged, 100_101),
        Err(UiGuardErrorV1::ChangedObservation)
    );
    assert_eq!(
        verify_ui_guarded_shadow_v1(verifier(), &p, &readback(), 101_001),
        Err(UiGuardErrorV1::StaleObservation)
    );
}
