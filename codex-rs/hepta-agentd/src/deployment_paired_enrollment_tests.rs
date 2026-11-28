//! Synthetic metadata and original temporary Registry/issuer controls.
//! No physical human, actual Root positive path, material read or fit is claimed.
use super::*;
use codex_hepta_contracts::authority_lease::AuthorityLeaseError;
use pretty_assertions::assert_eq;
use std::time::Duration;
use std::time::Instant;

fn pending() -> (
    Fixture,
    RootPairedTrainingPlanV1,
    crate::HostSignedWriterAuthorizationV1,
) {
    let mut f = Fixture::with_records(PairRecords::PendingEnrollment);
    let manifest = PairedTrainingMaterialManifestV1 {
        failure_sha256: Digest32::of_bytes(b"enrollment failure"),
        failure_bytes: 18,
        correction_sha256: Digest32::of_bytes(b"enrollment correction"),
        correction_bytes: 21,
    };
    f.registration.preparation.frozen_materials = manifest.commitment().unwrap();
    f.registration.request.materials = f.registration.preparation.frozen_materials;
    let plan = RootPairedTrainingPlanV1 {
        training: crate::PairedTrainingPlanV1 {
            preparation: f.registration.preparation.clone(),
            manifest,
            operation: f.registration.request.operation,
        },
        enrollment_revision: 1,
        effect_lifetime_ms: f.registration.effect_lifetime_ms,
    };
    let proof = f.issuer.retained_writer_authorization(&f.writer).unwrap();
    (f, plan, proof)
}

fn register(
    f: &Fixture,
    plan: &RootPairedTrainingPlanV1,
    proof: &crate::HostSignedWriterAuthorizationV1,
) -> io::Result<()> {
    f.issuer.register_paired_enrollment_checked(
        plan,
        &f.registry,
        &f.writer,
        proof,
        /*lifetime_ms*/ 1_000,
        Instant::now() + Duration::from_secs(/*secs*/ 2),
    )
}

#[test]
fn original_first_enrollment_is_exact_and_does_not_authorize_material_use() {
    let (f, plan, proof) = pending();
    let before = f.issuer.store.load(STATE_OWNER).unwrap();
    let frontier = f.registry.frontier().unwrap();
    register(&f, &plan, &proof).unwrap();
    let id = f.registration.enrollment_id().unwrap();
    let lease = f.registry.read_lease(&id).unwrap().unwrap().lease;
    assert_eq!(
        lease,
        AuthorityLease {
            schema_version: 1,
            lease_id: id.clone(),
            revision: 1,
            authority_epoch: f.writer.authority_lease.authority_epoch,
            binding: f.registration.bindings(&f.writer).unwrap().0,
            issued_at_unix_ms: 10_000,
            expires_at_unix_ms: 11_000,
        }
    );
    assert_eq!(
        f.registry.frontier().unwrap().store_revision,
        frontier.store_revision + 1
    );
    assert!(
        f.registry
            .read_lease(&f.registration.effect_id())
            .unwrap()
            .is_none()
    );
    assert!(f.open(f.registration.clone()).is_err());
    assert!(f.issuer.store.load(STATE_OWNER).unwrap() == before);
    let after = f.registry.frontier().unwrap();
    assert!(register(&f, &plan, &proof).is_err());
    let mut changed = plan.clone();
    changed.training.manifest.correction_sha256 = Digest32::of_bytes(b"other correction");
    changed.training.preparation.frozen_materials = changed.training.manifest.commitment().unwrap();
    assert!(register(&f, &changed, &proof).is_err());
    assert_eq!(f.registry.read_lease(&id).unwrap().unwrap().lease, lease);
    assert_eq!(f.registry.frontier().unwrap(), after);
}

#[test]
fn expired_pruned_enrollment_cannot_be_recreated_after_reopen() {
    let (f, plan, proof) = pending();
    register(&f, &plan, &proof).unwrap();
    let id = f.registration.enrollment_id().unwrap();
    let lease = f.registry.read_lease(&id).unwrap().unwrap().lease;
    f.clock.0.store(lease.expires_at_unix_ms, Ordering::SeqCst);
    let prune_limit = 8;
    assert_eq!(f.registry.prune_expired_leases(prune_limit).unwrap(), 1);
    let f = f.reopen();
    let before = f.registry.frontier().unwrap();
    assert!(f.registry.read_lease(&id).unwrap().is_none());
    assert!(matches!(
        f.registry.put_lease(lease, /*expected_revision*/ 0),
        Err(AuthorityLeaseError::RevisionMismatch)
    ));
    assert!(register(&f, &plan, &proof).is_err());
    assert_eq!(f.registry.frontier().unwrap(), before);
}

#[test]
fn revoked_parents_and_foreign_original_registry_cannot_register() {
    for parent in ["issuer", "writer"] {
        let (f, plan, proof) = pending();
        let id = if parent == "issuer" {
            "synthetic-paired-issuer"
        } else {
            &f.writer.authority_lease.lease_id
        };
        let reason = [7; 32];
        f.registry
            .revoke(id, /*expected_revision*/ 1, reason)
            .unwrap();
        let before = f.registry.frontier().unwrap();
        assert!(register(&f, &plan, &proof).is_err());
        assert_eq!(f.registry.frontier().unwrap(), before);
    }
    let (f, plan, proof) = pending();
    let (foreign, _, _) = pending();
    let before = foreign.registry.frontier().unwrap();
    assert!(
        f.issuer
            .register_paired_enrollment_checked(
                &plan,
                &foreign.registry,
                &f.writer,
                &proof,
                /*lifetime_ms*/ 1_000,
                Instant::now() + Duration::from_secs(/*secs*/ 2),
            )
            .is_err()
    );
    assert_eq!(foreign.registry.frontier().unwrap(), before);
}

#[test]
fn wrong_policy_revision_deadline_and_actual_non_root_refuse_without_writes() {
    let (f, plan, proof) = pending();
    let before = f.registry.frontier().unwrap();
    let mut wrong = plan.clone();
    wrong.enrollment_revision = 2;
    assert!(register(&f, &wrong, &proof).is_err());
    wrong = plan.clone();
    wrong.training.preparation.study = Digest32::of_bytes(b"unregistered study");
    assert!(register(&f, &wrong, &proof).is_err());
    assert!(
        f.issuer
            .register_paired_enrollment_checked(
                &plan,
                &f.registry,
                &f.writer,
                &proof,
                /*lifetime_ms*/ 1_000,
                Instant::now(),
            )
            .is_err()
    );
    // The real entry checks actual credentials; no root identity is mocked.
    assert_ne!(unsafe { libc::getuid() }, 0);
    assert!(
        f.issuer
            .register_original_paired_enrollment_once(
                &plan,
                &f.registry,
                &f.writer,
                &proof,
                /*lifetime_ms*/ 1_000,
                Instant::now() + Duration::from_secs(/*secs*/ 2),
            )
            .is_err()
    );
    assert_eq!(f.registry.frontier().unwrap(), before);
}
