//! Synthetic lease boundaries for the checkpoint's actual post-I/O clock read.
//! These cases do not qualify protected Root storage or native IPC latency.
use super::*;
use pretty_assertions::assert_eq;

#[test]
fn checkpoint_post_io_lease_validation_keeps_half_open_expiry_and_exact_epoch() {
    let (trust, _) = crate::root_writer_proof::tests::fixture();
    let lease = trust.authority_lease;
    let mut head = FinalUseRevocations {
        authority_epoch: lease.authority_epoch,
        revision: 1,
        revoked_grant_ids: Default::default(),
    };
    for (now, expected) in [
        (
            lease.issued_at_unix_ms - 1,
            Some(io::ErrorKind::PermissionDenied),
        ),
        (lease.issued_at_unix_ms, None),
        (lease.expires_at_unix_ms - 1, None),
        (
            lease.expires_at_unix_ms,
            Some(io::ErrorKind::PermissionDenied),
        ),
    ] {
        assert_eq!(
            validate_observation_lease(&lease, &head, now)
                .err()
                .map(|error| error.kind()),
            expected
        );
    }
    head.authority_epoch += 1;
    assert_eq!(
        validate_observation_lease(&lease, &head, lease.issued_at_unix_ms)
            .unwrap_err()
            .kind(),
        io::ErrorKind::PermissionDenied
    );
}
