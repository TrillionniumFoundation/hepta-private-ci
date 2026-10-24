//! Actual Root owner failure cuts. The original runtime clock, canonical
//! registry/key/proofs, filesystem publication and pidfd death are exercised.
//! These tests do not assert native kernel roles or complete daemon recovery.

use super::*;
use codex_hepta_contracts::AuthorityTrustError;
use pretty_assertions::assert_eq;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

#[path = "authority_host_writer_reentry_fixture.rs"]
mod fixture;
use fixture::Fixture;
use fixture::Publisher;
use fixture::checkpoint_registration;
use fixture::current;

#[path = "authority_host_boot_retirement_tests.rs"]
mod boot_retirement;

#[path = "authority_host_writer_state_tests.rs"]
mod writer_state;

#[tokio::test]
#[ignore = "requires isolated actual Root checkpoint directory and UID60001 peers"]
async fn root_unactivated_writer_replacement_retains_original_generation_and_exact_lost_reply() {
    let mut f = Fixture::new().await;
    f.failed.stop();
    // An actual dead Process is insufficient while its original registry
    // lease remains live. No alternate verifier is accepted by this API.
    assert!(f.replace().is_err());
    assert_eq!(
        f.issuer
            .retained_writer_authorization(&f.failed_writer)
            .unwrap(),
        f.failed_proof
    );
    assert_eq!(f.actual_head(), f.previous.head);
    f.registry
        .revoke(&f.failed_writer.authority_lease.lease_id, 1, [10; 32])
        .unwrap();
    let replacement = f.replace().unwrap();
    assert_eq!(
        replacement.claims.local_lease_generation,
        f.failed_writer.local_lease_generation
    );
    assert_eq!(
        replacement.claims.sequence,
        f.failed_proof.claims.sequence + 1
    );
    assert_eq!(
        replacement.claims.authority_lease,
        f.replacement.authority_lease
    );
    assert_eq!(
        f.actual_head(),
        f.previous.head,
        "authorization replacement must not manufacture Current"
    );
    assert_eq!(
        f.replace().unwrap(),
        replacement,
        "exact lost-reply reconciliation must spend no new sequence"
    );
    assert!(
        f.issuer
            .rotate_writer_authorization(&f.failed_writer, &f.failed_proof, &f.replacement)
            .is_err(),
        "ordinary rotation retains its generation +1 rule"
    );
    let registration = checkpoint_registration(
        &f.issuer,
        &f.registry,
        &f.replacement,
        &replacement,
        f.previous.head.publisher_epoch + 1,
        &f.successor,
    );
    let adopted = crate::HostCognitiveCheckpoint::adopt_retained_material_after_root_restart(
        f.directory.clone(),
        &f.previous,
        &f.old.retired(),
        registration.clone(),
        &f.successor.retained,
        f.clock.clone(),
        &f.material,
    )
    .unwrap();
    let observed = current(&adopted, registration.publisher_epoch);
    assert_eq!(
        observed.head.writer_binding.generation,
        f.previous.head.writer_binding.generation + 1
    );
    assert_eq!(
        observed.head.publisher_epoch,
        f.previous.head.publisher_epoch + 1
    );
    assert_eq!(observed.head.counter, f.previous.head.counter + 1);
    assert_eq!(observed.head.last_current, f.previous.head.last_current);
    f.material.verify_unchanged().unwrap();
}

#[tokio::test]
#[ignore = "requires isolated actual Root checkpoint directory and UID60001 peers"]
async fn root_unactivated_replacement_rejects_an_actually_committed_checkpoint() {
    let mut f = Fixture::new().await;
    let registration = checkpoint_registration(
        &f.issuer,
        &f.registry,
        &f.failed_writer,
        &f.failed_proof,
        f.previous.head.publisher_epoch + 1,
        &f.failed,
    );
    let adopted = crate::HostCognitiveCheckpoint::adopt_retained_material_after_root_restart(
        f.directory.clone(),
        &f.previous,
        &f.old.retired(),
        registration.clone(),
        &f.failed.retained,
        f.clock.clone(),
        &f.material,
    )
    .unwrap();
    let committed = current(&adopted, registration.publisher_epoch);
    f.retire_failed_authority();
    assert!(
        f.replace().is_err(),
        "an installed generation may not be reused by replacement"
    );
    assert_eq!(f.actual_head(), committed.head);
    assert_eq!(
        f.issuer
            .retained_writer_authorization(&f.failed_writer)
            .unwrap(),
        f.failed_proof
    );
    let observed = crate::HostCognitiveCheckpoint::read_retired_head_for_root(
        f.directory.clone(),
        &registration,
        &f.failed.retired(),
        &f.material,
    )
    .unwrap();
    assert_eq!(
        observed, committed,
        "retired observation must return the actual opaque full receipt"
    );
}

#[tokio::test]
#[ignore = "requires isolated actual Root checkpoint directory and UID60001 peers"]
async fn root_unactivated_replacement_rejects_wrong_proof_generation_and_changed_physical_image() {
    let mut f = Fixture::new().await;
    f.retire_failed_authority();
    let mut wrong = f.replacement.clone();
    wrong.local_lease_generation += 1;
    assert!(
        f.issuer
            .replace_unactivated_writer_authorization(
                &f.failed_writer,
                &f.failed_proof,
                &wrong,
                f.directory.clone(),
                &f.previous,
                &f.old.retired(),
                &f.failed.retired(),
                &f.successor.retained,
                &f.material
            )
            .is_err()
    );
    wrong = f.replacement.clone();
    wrong.authority_lease.lease_id = f.failed_writer.authority_lease.lease_id.clone();
    assert!(
        f.issuer
            .replace_unactivated_writer_authorization(
                &f.failed_writer,
                &f.failed_proof,
                &wrong,
                f.directory.clone(),
                &f.previous,
                &f.old.retired(),
                &f.failed.retired(),
                &f.successor.retained,
                &f.material
            )
            .is_err()
    );
    let mut forged = f.failed_proof.clone();
    let first = if forged.signature_hex.starts_with('0') {
        "1"
    } else {
        "0"
    };
    forged.signature_hex.replace_range(..1, first);
    assert!(
        f.issuer
            .replace_unactivated_writer_authorization(
                &f.failed_writer,
                &forged,
                &f.replacement,
                f.directory.clone(),
                &f.previous,
                &f.old.retired(),
                &f.failed.retired(),
                &f.successor.retained,
                &f.material
            )
            .is_err()
    );
    assert_eq!(f.actual_head(), f.previous.head);
    assert_eq!(
        f.issuer
            .retained_writer_authorization(&f.failed_writer)
            .unwrap(),
        f.failed_proof
    );
    use std::io::Write;
    std::fs::OpenOptions::new()
        .append(true)
        .open(f.material.path())
        .unwrap()
        .write_all(b"changed actual retained bytes")
        .unwrap();
    assert!(f.replace().is_err());
    assert_eq!(f.actual_head(), f.previous.head);
    assert_eq!(
        f.issuer
            .retained_writer_authorization(&f.failed_writer)
            .unwrap(),
        f.failed_proof
    );
}

/// Delegate every value to the real original clock. The second read is the
/// original adoption's post-CAS boundary; kill the actual retained successor
/// there and observe its pidfd before returning that unchanged real time.
struct KillAfterCasClock {
    original: Arc<HostAuthorityClock>,
    reads: AtomicUsize,
    successor: OwnedFd,
}
impl AuthorityClock for KillAfterCasClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        let actual = self.original.now_unix_ms()?;
        if self.reads.fetch_add(1, Ordering::SeqCst) + 1 == 2 {
            let rc = unsafe {
                libc::syscall(
                    libc::SYS_pidfd_send_signal,
                    self.successor.as_raw_fd(),
                    libc::SIGKILL,
                    std::ptr::null::<libc::siginfo_t>(),
                    0,
                )
            };
            if rc < 0 {
                return Err(AuthorityTrustError::Unavailable);
            }
            let end = Instant::now() + Duration::from_secs(5);
            loop {
                let mut fd = libc::pollfd {
                    fd: self.successor.as_raw_fd(),
                    events: libc::POLLIN,
                    revents: 0,
                };
                let observed = unsafe { libc::poll(&mut fd, 1, 10) };
                match (observed, fd.revents) {
                    (1, libc::POLLIN) => break,
                    (0, 0) if Instant::now() < end => {}
                    _ => return Err(AuthorityTrustError::Unavailable),
                }
            }
        }
        Ok(actual)
    }
}

#[tokio::test]
#[ignore = "requires isolated actual Root checkpoint directory and UID60001 peers"]
async fn root_real_death_after_checkpoint_cas_recovers_actual_head_without_skipping_generation() {
    let mut f = Fixture::new().await;
    f.retire_failed_authority();
    let replacement = f.replace().unwrap();
    let registration = checkpoint_registration(
        &f.issuer,
        &f.registry,
        &f.replacement,
        &replacement,
        f.previous.head.publisher_epoch + 1,
        &f.successor,
    );
    let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, f.successor.child.id(), 0) };
    assert!(raw >= 0);
    let clock = Arc::new(KillAfterCasClock {
        original: f.clock.clone(),
        reads: AtomicUsize::new(0),
        successor: unsafe { OwnedFd::from_raw_fd(raw as i32) },
    });
    let attempted = crate::HostCognitiveCheckpoint::adopt_retained_material_after_root_restart(
        f.directory.clone(),
        &f.previous,
        &f.old.retired(),
        registration.clone(),
        &f.successor.retained,
        clock,
        &f.material,
    );
    assert_eq!(attempted.err(), Some(AuthorityTrustError::Unavailable));
    f.successor.stop();
    let retired = f.successor.retired();
    let observed = crate::HostCognitiveCheckpoint::read_retired_head_for_root(
        f.directory.clone(),
        &registration,
        &retired,
        &f.material,
    )
    .unwrap();
    assert_eq!(observed.head, f.actual_head());
    assert_eq!(observed.head.counter, f.previous.head.counter + 1);
    assert_eq!(
        observed.head.writer_binding.generation,
        f.previous.head.writer_binding.generation + 1
    );
    assert_eq!(observed.head.last_current, f.previous.head.last_current);
    assert!(
        f.replace().is_err(),
        "the committed actual head must not be reinterpreted as unactivated"
    );

    let next_peer = Publisher::spawn();
    let mut next = f.replacement.clone();
    next.spawn_generation += 2;
    next.owner_epoch += 1;
    next.local_lease_generation += 1;
    next.authority_lease.lease_id = "reentry-after-committed-failure".into();
    next.authority_lease.binding.payload_sha256 = [11; 32];
    next.authority_lease.issued_at_unix_ms = f.clock.now_unix_ms().unwrap();
    next.authority_lease.expires_at_unix_ms = next.authority_lease.issued_at_unix_ms + 90_000;
    f.registry
        .revoke(&f.replacement.authority_lease.lease_id, 1, [12; 32])
        .unwrap();
    f.registry
        .put_lease(next.authority_lease.clone(), /*expected_revision*/ 0)
        .unwrap();
    let proof = f
        .issuer
        .rotate_writer_authorization(&f.replacement, &replacement, &next)
        .unwrap();
    let next_registration = checkpoint_registration(
        &f.issuer,
        &f.registry,
        &next,
        &proof,
        observed.head.publisher_epoch + 1,
        &next_peer,
    );
    let adopted = crate::HostCognitiveCheckpoint::adopt_retained_material_after_root_restart(
        f.directory.clone(),
        &observed,
        &retired,
        next_registration.clone(),
        &next_peer.retained,
        f.clock.clone(),
        &f.material,
    )
    .unwrap();
    let actual = current(&adopted, next_registration.publisher_epoch);
    assert_eq!(
        actual.head.writer_binding.generation,
        observed.head.writer_binding.generation + 1
    );
    assert_eq!(actual.head.counter, observed.head.counter + 1);
    assert_eq!(actual.head.last_current, f.previous.head.last_current);
    f.material.verify_unchanged().unwrap();
}

#[path = "authority_host_checkpoint_observation_tests.rs"]
mod checkpoint_observation;
