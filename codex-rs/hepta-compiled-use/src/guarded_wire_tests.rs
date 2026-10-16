//! Original kernel Socket source-guard tests only. No real UI effects.
use super::*;
use crate::{
    ActionArgumentsV1, ActionErrorV1, ActionFrameV1, CapabilityGrantV1,
    DenyByDefaultSandboxV1, SandboxActionPortV1, SandboxErrorV1,
    UiGuardedPlanV1, propose_ui_guarded_shadow_v1,
};
use codex_hepta_types::Digest32;
use std::io::Write;
use std::os::unix::net::{Shutdown, UnixStream};
use std::time::Duration;

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}
fn verifier() -> ActionVerifierV1 {
    ActionVerifierV1 {
        generation: 12,
        grant: CapabilityGrantV1 {
            digest: digest(b"research-untrusted-current-grant"),
            allowed: 1 | 2 | 4 | 8 | 16,
        },
    }
}
fn readback() -> UiReadbackV1 {
    UiReadbackV1 {
        principal_scope_digest: digest(b"scope-a"),
        observer_digest: digest(b"observer-claim"),
        tree_digest: digest(b"tree-epoch-12"),
        generation: 12,
        observed_at_ms: 100_000,
        max_age_ms: 1_000,
    }
}
fn action(sequence: u64) -> ActionFrameV1 {
    ActionFrameV1 {
        generation: 12,
        sequence,
        capability_digest: verifier().grant.digest,
        arguments: ActionArgumentsV1::Click {
            target_digest: digest(b"source-grounded-only-button"),
            x: 3,
            y: 5,
        },
    }
}
fn propose(state: UiReadbackV1) -> UiGuardedShadowProposalV1 {
    let plan = UiGuardedPlanV1 {
        required_readback: state,
        actions: vec![action(1), action(2)],
    };
    propose_ui_guarded_shadow_v1(verifier(), &plan, &state, 100_200)
        .expect("proposal")
}
fn socket_pair() -> (UnixStream, UnixStream) {
    let (a, b) = UnixStream::pair().expect("real Unix socket pair");
    a.set_read_timeout(Some(Duration::from_secs(3))).expect("timeout");
    b.set_read_timeout(Some(Duration::from_secs(3))).expect("timeout");
    (a, b)
}
fn preamble(proposal: &UiGuardedShadowProposalV1) -> [u8; PREAMBLE_BYTES] {
    let mut bytes = [0_u8; PREAMBLE_BYTES];
    bytes[..4].copy_from_slice(GUARD_MAGIC);
    bytes[4..].copy_from_slice(proposal.guarded_digest.as_array());
    bytes
}

#[test]
fn real_socket_receives_only_complete_guarded_batch_and_still_denies_effects() {
    let state = readback();
    let proposal = propose(state);
    let copy = proposal.clone();
    let (sender, receiver) = socket_pair();
    let writer = std::thread::spawn(move || {
        send_guarded_shadow_data_v1(sender, verifier(), &copy, &state, 100_200)
    });
    let actions = receive_guarded_shadow_data_v1(
        receiver, verifier(), &proposal, &state, 100_201,
    ).expect("guarded receive");
    assert_eq!(actions.len(), 2);
    assert_eq!(actions[0].frame(), &action(1));
    assert_eq!(actions[1].frame(), &action(2));
    writer.join().expect("join").expect("sender");
    let mut deny = DenyByDefaultSandboxV1;
    for item in actions {
        assert_eq!(deny.submit(item), Err(SandboxErrorV1::NotConfigured));
    }
}

#[test]
fn same_action_bytes_different_source_epoch_is_rejected_by_wire_guard() {
    let state = readback();
    let source_a = propose(state);
    let mut next = state;
    next.tree_digest = digest(b"different-still-untrusted-tree");
    let source_b = propose(next);
    assert_eq!(source_a.proposed_actions.actions, source_b.proposed_actions.actions);
    assert_ne!(source_a.guarded_digest, source_b.guarded_digest);
    let (sender, receiver) = socket_pair();
    send_guarded_shadow_data_v1(
        sender, verifier(), &source_a, &state, 100_201,
    ).expect("write source A");
    assert_eq!(
        receive_guarded_shadow_data_v1(
            receiver, verifier(), &source_b, &next, 100_201,
        ).map(|_| ()),
        Err(GuardedWireErrorV1::PreambleMismatch)
    );
}

#[test]
fn stale_or_changed_readback_fails_before_emitting_any_wire_byte() {
    let state = readback();
    let proposal = propose(state);
    let mut outbound = std::io::Cursor::new(Vec::<u8>::new());
    assert_eq!(
        send_guarded_shadow_data_v1(
            &mut outbound, verifier(), &proposal, &state, 101_001,
        ),
        Err(GuardedWireErrorV1::Guard(UiGuardErrorV1::StaleObservation))
    );
    assert!(outbound.get_ref().is_empty());
    let mut changed = state;
    changed.principal_scope_digest = digest(b"unrelated-principal");
    assert_eq!(
        send_guarded_shadow_data_v1(
            &mut outbound, verifier(), &proposal, &changed, 100_200,
        ),
        Err(GuardedWireErrorV1::Guard(UiGuardErrorV1::ChangedObservation))
    );
    assert!(outbound.get_ref().is_empty());
}

#[test]
fn unknown_or_truncated_preamble_rejected_without_returning_frames() {
    let state = readback();
    let plan = propose(state);
    let (mut raw, receiver) = socket_pair();
    raw.write_all(&[0_u8; PREAMBLE_BYTES]).expect("wrong magic");
    raw.shutdown(Shutdown::Write).expect("shutdown");
    assert_eq!(
        receive_guarded_shadow_data_v1(
            receiver, verifier(), &plan, &state, 100_201,
        ).map(|_| ()),
        Err(GuardedWireErrorV1::PreambleMismatch)
    );
    let (mut raw, receiver) = socket_pair();
    raw.write_all(b"HGP").expect("partial preamble");
    raw.shutdown(Shutdown::Write).expect("shutdown");
    assert_eq!(
        receive_guarded_shadow_data_v1(
            receiver, verifier(), &plan, &state, 100_201,
        ).map(|_| ()),
        Err(GuardedWireErrorV1::Io(std::io::ErrorKind::UnexpectedEof))
    );
}

#[test]
fn invalid_first_frame_under_correct_guard_is_rejected() {
    let state = readback();
    let plan = propose(state);
    let (mut raw, receiver) = socket_pair();
    raw.write_all(&preamble(&plan)).expect("preamble");
    let mut invalid = action(1).encode().expect("encode");
    invalid[255] = 1;
    raw.write_all(&invalid).expect("invalid wire data");
    raw.shutdown(Shutdown::Write).expect("shutdown");
    assert_eq!(
        receive_guarded_shadow_data_v1(
            receiver, verifier(), &plan, &state, 100_201,
        ).map(|_| ()),
        Err(GuardedWireErrorV1::Frame(FrameWireErrorV1::Action(
            ActionErrorV1::NonCanonicalPadding,
        )))
    );
}

#[test]
fn valid_prefix_without_second_frame_never_returns_partial_batch() {
    let state = readback();
    let plan = propose(state);
    let (mut raw, receiver) = socket_pair();
    raw.write_all(&preamble(&plan)).expect("preamble");
    raw.write_all(&action(1).encode().expect("frame 1")).expect("first frame");
    raw.shutdown(Shutdown::Write).expect("shutdown");
    assert_eq!(
        receive_guarded_shadow_data_v1(
            receiver, verifier(), &plan, &state, 100_201,
        ).map(|_| ()),
        Err(GuardedWireErrorV1::Frame(FrameWireErrorV1::Io(
            std::io::ErrorKind::UnexpectedEof,
        )))
    );
}

#[test]
fn alternate_digest_valid_frame_still_rejected_by_exact_plan_match() {
    let state = readback();
    let plan = propose(state);
    let (mut raw, receiver) = socket_pair();
    raw.write_all(&preamble(&plan)).expect("preamble");
    let mut alternate = action(1);
    alternate.arguments = ActionArgumentsV1::Click {
        target_digest: digest(b"not-the-planned-button"),
        x: 3,
        y: 5,
    };
    raw.write_all(&alternate.encode().expect("valid alternate frame"))
        .expect("frame");
    raw.shutdown(Shutdown::Write).expect("shutdown");
    assert_eq!(
        receive_guarded_shadow_data_v1(
            receiver, verifier(), &plan, &state, 100_201,
        ).map(|_| ()),
        Err(GuardedWireErrorV1::FrameMismatch)
    );
}

#[test]
fn stale_generation_and_invalid_grant_do_not_open_guarded_session() {
    let state = readback();
    let plan = propose(state);
    let mut wrong = verifier();
    wrong.generation += 1;
    let mut io = std::io::Cursor::new(Vec::<u8>::new());
    assert_eq!(
        send_guarded_shadow_data_v1(&mut io, wrong, &plan, &state, 100_201),
        Err(GuardedWireErrorV1::Guard(UiGuardErrorV1::WrongGeneration))
    );
    assert!(io.get_ref().is_empty());
    let mut invalid = verifier();
    invalid.grant.digest = digest(b"wrong-grant");
    assert!(send_guarded_shadow_data_v1(
        &mut io, invalid, &plan, &state, 100_201,
    ).is_err());
    assert!(io.get_ref().is_empty());
}
