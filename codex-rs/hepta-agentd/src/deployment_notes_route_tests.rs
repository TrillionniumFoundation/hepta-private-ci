use super::super::ProtectedLease;
use super::super::STATE_OWNER;
use super::Fixture;
use crate::DeploymentGrantPolicy;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use pretty_assertions::assert_eq;
use std::io;

// Extend the existing ordinary-owner fixture using its same registry, signer,
// counter and writer registration. This is explicit test provisioning, not a
// protected Root bootstrap or a Runtime/device capability.
fn register_original_policy(f: &Fixture, binding: &FinalUseBinding) {
    let state = f.issuer.store.load(STATE_OWNER).unwrap();
    let mut changed = state.clone();
    changed.policies.push(DeploymentGrantPolicy {
        subject_id: binding.subject_id.clone(),
        destination_id: binding.destination_id.clone(),
        scope_sha256: binding.scope_sha256,
        lifetime_ms: 1_000,
    });
    f.issuer
        .store
        .compare_and_set(STATE_OWNER, &state, &changed)
        .unwrap();
}

fn pin_original_effect_lease(f: &mut Fixture, binding: &FinalUseBinding) {
    let lease = AuthorityLease {
        schema_version: 1,
        lease_id: "original-effect".into(),
        authority_epoch: 1,
        revision: 1,
        binding: AuthorityLeaseBinding {
            principal_id: binding.subject_id.clone(),
            operation_class: "runtime.agentd.production_operation".into(),
            destination_id: binding.destination_id.clone(),
            scope_sha256: binding.scope_sha256,
            payload_sha256: binding.payload_sha256,
        },
        issued_at_unix_ms: 10_000,
        expires_at_unix_ms: 20_000,
    };
    f.registry
        .put_lease(lease.clone(), /*expected_revision*/ 0)
        .unwrap();
    f.issuer.lease =
        Some(ProtectedLease::new(f.registry.verifier(), lease.lease_id, /*revision*/ 1).unwrap());
}

#[test]
fn deployment_notes_route_preserves_authorized_non_notes_and_canonical_issuer() {
    let mut f = Fixture::new();
    let device = FinalUseBinding {
        destination_id: "original-device".into(),
        scope_sha256: [6; 32],
        payload_sha256: [7; 32],
        request_sha256: [8; 32],
        ..f.binding.clone()
    };
    register_original_policy(&f, &device);
    pin_original_effect_lease(&mut f, &device);
    let admission = f.admission();
    let key = f.issuer.trust_key().unwrap();
    let head = f.issuer.revocations().unwrap();
    let before = f.registry.frontier().unwrap();
    let device_grant = admission
        .issue_registered_route(&f.issuer, &device)
        .unwrap()
        .unwrap();
    assert_eq!(device_grant.grant.binding, device);
    assert_eq!(f.registry.frontier().unwrap(), before);
    assert_eq!(f.sequence(), 2);

    let notes_grant = admission
        .issue_registered_route(&f.issuer, &f.binding)
        .unwrap()
        .unwrap();
    assert_eq!(notes_grant.grant.binding, f.binding);
    assert_eq!(f.sequence(), 3);
    assert_eq!(f.issuer.revocations().unwrap(), head);
    let verifier = ed25519_dalek::VerifyingKey::from_bytes(&key.verifying_key).unwrap();
    for signed in [device_grant, notes_grant] {
        verifier
            .verify_strict(
                &signed.grant.signing_bytes().unwrap(),
                &ed25519_dalek::Signature::from_slice(&signed.signature).unwrap(),
            )
            .unwrap();
    }
}

#[test]
fn deployment_notes_route_requires_original_non_notes_policy_and_exact_live_lease() {
    let mut f = Fixture::new();
    let device = FinalUseBinding {
        destination_id: "original-device".into(),
        scope_sha256: [6; 32],
        ..f.binding.clone()
    };
    pin_original_effect_lease(&mut f, &device);
    let admission = f.admission();
    let before = f.registry.frontier().unwrap();
    // An exact lease alone cannot create an issuer policy.
    assert!(
        admission
            .issue_registered_route(&f.issuer, &device)
            .unwrap()
            .is_none()
    );
    register_original_policy(&f, &device);
    for binding in [
        FinalUseBinding {
            destination_id: "unregistered-device".into(),
            ..device.clone()
        },
        FinalUseBinding {
            subject_id: "another-owner".into(),
            ..device.clone()
        },
        FinalUseBinding {
            scope_sha256: [9; 32],
            ..device.clone()
        },
        FinalUseBinding {
            payload_sha256: [9; 32],
            ..device.clone()
        },
    ] {
        assert_eq!(
            admission
                .issue_registered_route(&f.issuer, &binding)
                .unwrap_err()
                .kind(),
            io::ErrorKind::PermissionDenied
        );
    }
    assert_eq!(f.registry.frontier().unwrap(), before);
    assert_eq!(f.sequence(), 1);
    f.registry
        .revoke("original-effect", /*expected_revision*/ 1, [9; 32])
        .unwrap();
    let revoked = f.registry.frontier().unwrap();
    assert_eq!(
        admission
            .issue_registered_route(&f.issuer, &device)
            .unwrap_err()
            .kind(),
        io::ErrorKind::PermissionDenied
    );
    assert_eq!(f.registry.frontier().unwrap(), revoked);
    assert_eq!(f.sequence(), 1);
}

#[test]
fn deployment_notes_route_wrong_notes_scope_or_owner_creates_no_authority() {
    let f = Fixture::new();
    let admission = f.admission();
    let before = f.registry.frontier().unwrap();
    for binding in [
        FinalUseBinding {
            scope_sha256: [9; 32],
            ..f.binding.clone()
        },
        FinalUseBinding {
            subject_id: "another-owner".into(),
            ..f.binding.clone()
        },
    ] {
        assert!(
            admission
                .issue_registered_route(&f.issuer, &binding)
                .unwrap()
                .is_none()
        );
    }
    assert_eq!(f.registry.frontier().unwrap(), before);
    assert_eq!(f.sequence(), 1);
}

#[test]
fn deployment_notes_route_denied_notes_writer_never_falls_back_to_generic_grant() {
    let mut f = Fixture::new();
    let binding = f.binding.clone();
    // The generic route has its own exact live lease and the original Notes
    // policy. A fallback would therefore sign successfully despite revocation
    // of the writer required by the installed Notes delegation.
    pin_original_effect_lease(&mut f, &binding);
    let admission = f.admission();
    f.registry
        .revoke(
            &f.writer.authority_lease.lease_id,
            /*expected_revision*/ 1,
            [8; 32],
        )
        .unwrap();
    let before = f.registry.frontier().unwrap();
    assert_eq!(
        admission
            .issue_registered_route(&f.issuer, &binding)
            .unwrap_err()
            .kind(),
        io::ErrorKind::PermissionDenied
    );
    assert_eq!(f.registry.frontier().unwrap(), before);
    assert_eq!(f.sequence(), 1);

    // Exercise the control, rather than only assuming the fallback is viable.
    let generic = f.issuer.issue(&binding).unwrap().unwrap();
    assert_eq!(generic.grant.binding, binding);
    assert_eq!(f.sequence(), 2);
}
