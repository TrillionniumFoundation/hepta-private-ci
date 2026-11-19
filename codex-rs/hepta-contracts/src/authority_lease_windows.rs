//! Windows owner for durable kernel.authority lease/revocation state.
//!
//! Reuse the OS-enforced private-state handle contract already required by
//! the Final-use and Prompt Registry owners. Never fall back to path-based
//! ordinary File::open, permissive inherited ACLs, or reparse/hardlink aliases.

use std::fs::File;
use std::io;
use std::path::Path;

use codex_utils_path::PrivateFileAccess;

use super::Access;
use super::AuthorityLeaseError;

pub(super) fn prepare_directory(root: &Path) -> Result<File, AuthorityLeaseError> {
    codex_utils_path::open_private_state_directory(root).map_err(map_error)
}

pub(super) fn open_private(
    directory: &File,
    name: &str,
    access: Access,
) -> Result<File, AuthorityLeaseError> {
    let access = match access {
        Access::Read => PrivateFileAccess::Read,
        Access::Create => PrivateFileAccess::Create,
    };
    codex_utils_path::open_private_state_child(directory, name, access).map_err(map_error)
}

pub(super) fn entry_exists(directory: &File, name: &str) -> Result<bool, AuthorityLeaseError> {
    codex_utils_path::private_state_child_exists(directory, name).map_err(map_error)
}

pub(super) fn replace_state(directory: &File) -> Result<(), AuthorityLeaseError> {
    codex_utils_path::replace_private_state_child(
        directory,
        "authority-leases.next",
        "authority-leases.json",
    )
    .map_err(map_error)
}

fn map_error(error: io::Error) -> AuthorityLeaseError {
    match error.kind() {
        io::ErrorKind::InvalidData
        | io::ErrorKind::InvalidInput
        | io::ErrorKind::PermissionDenied => AuthorityLeaseError::UnsafeStateDirectory,
        _ => AuthorityLeaseError::Unavailable,
    }
}

#[cfg(test)]
mod tests {
    use super::super::AuthorityLease;
    use super::super::AuthorityLeaseBinding;
    use super::super::AuthorityLeaseFrontier;
    use super::super::AuthorityLeaseRegistry;
    use super::super::LEASE_SCHEMA_VERSION;
    use super::*;
    use crate::AuthorityClock;
    use crate::AuthorityTrustError;
    use std::sync::Arc;

    #[derive(Debug)]
    struct FixedClock;
    impl AuthorityClock for FixedClock {
        fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
            Ok(2_000)
        }
    }

    fn sample() -> AuthorityLease {
        AuthorityLease {
            schema_version: LEASE_SCHEMA_VERSION,
            lease_id: "win-lease-one".to_string(),
            authority_epoch: 7,
            revision: 1,
            binding: AuthorityLeaseBinding {
                principal_id: "win-agent".to_string(),
                operation_class: "provider.read".to_string(),
                destination_id: "provider:local".to_string(),
                scope_sha256: [2; 32],
                payload_sha256: [3; 32],
            },
            issued_at_unix_ms: 1_000,
            expires_at_unix_ms: 30_000,
        }
    }

    #[test]
    fn private_authority_lease_roundtrip_reopens_with_exact_frontier() {
        let root = tempfile::tempdir().expect("secure temp root");
        let state_dir = root.path().join("authority-lease-store");
        let initial = AuthorityLeaseFrontier::for_empty_epoch(7).expect("genesis");
        let clock: Arc<dyn AuthorityClock> = Arc::new(FixedClock);
        let owner = "windows-kernel-authority".to_string();
        let registry = AuthorityLeaseRegistry::open_state_dir_with_clock(
            &state_dir,
            owner.clone(),
            initial,
            Arc::clone(&clock),
        )
        .expect("create private Windows authority owner");
        registry
            .put_lease(sample(), 0)
            .expect("append exact signed lease identity");
        let next = registry.frontier().expect("durable frontier");
        assert!(next.store_revision > initial.store_revision);
        drop(registry);

        let reopened = AuthorityLeaseRegistry::open_state_dir_with_clock(
            &state_dir,
            owner.clone(),
            next,
            Arc::clone(&clock),
        )
        .expect("exact reopen without recreating authority");
        assert_eq!(reopened.frontier().expect("recovered frontier"), next);
        let recovered = reopened
            .read_lease("win-lease-one")
            .expect("read exact lease")
            .expect("lease survived reopen");
        assert_eq!(recovered.lease, sample());
        assert_eq!(recovered.store_revision, next.store_revision);
        assert!(
            reopened
                .verifier()
                .verify_use("win-lease-one", 1, &sample().binding,)
                .is_ok()
        );
        let receipt = reopened
            .revoke("win-lease-one", 1, [9; 32])
            .expect("persist revocation and prevent lease reuse");
        assert_eq!(receipt.lease_revision, 2);
        let revoked_head = reopened.frontier().expect("revoked store frontier");
        drop(reopened);

        let reopened = AuthorityLeaseRegistry::open_state_dir_with_clock(
            &state_dir,
            owner.clone(),
            revoked_head,
            Arc::clone(&clock),
        )
        .expect("reopen exact persisted revocation");
        assert!(
            reopened
                .read_revocation("win-lease-one")
                .expect("durable revocation lookup")
                .is_some()
        );
        assert!(matches!(
            reopened
                .verifier()
                .verify_use("win-lease-one", 2, &sample().binding,),
            Err(AuthorityLeaseError::Revoked),
        ));
        drop(reopened);

        // Even if local lease bytes still exist, a forged future external
        // host frontier must never be accepted as a clean current snapshot.
        let mut false_future = revoked_head;
        false_future.store_revision += 1;
        assert!(matches!(
            AuthorityLeaseRegistry::open_state_dir_with_clock(
                &state_dir,
                owner,
                false_future,
                Arc::clone(&clock),
            ),
            Err(AuthorityLeaseError::AntiRollbackViolation),
        ));
        // A second owner identity cannot adopt previously authenticated
        // lease/revocation files or manufacture an empty authority history.
        assert!(matches!(
            AuthorityLeaseRegistry::open_state_dir_with_clock(
                &state_dir,
                "other-owner".into(),
                revoked_head,
                Arc::clone(&clock),
            ),
            Err(AuthorityLeaseError::InvalidTrust),
        ));
    }

    #[test]
    fn hardlink_alias_of_authority_state_is_rejected_before_reopen() {
        let root = tempfile::tempdir().expect("secure temp root");
        let state_dir = root.path().join("authority-lease-store");
        let initial = AuthorityLeaseFrontier::for_empty_epoch(7).expect("genesis");
        let registry = AuthorityLeaseRegistry::open_state_dir_with_clock(
            &state_dir,
            "windows-kernel-authority".into(),
            initial,
            Arc::new(FixedClock),
        )
        .expect("create owner");
        let frontier = registry.frontier().expect("head");
        drop(registry);
        std::fs::hard_link(
            state_dir.join("authority-leases.json"),
            state_dir.join("untrusted-alias"),
        )
        .expect("real NTFS hardlink");
        assert!(matches!(
            AuthorityLeaseRegistry::open_state_dir_with_clock(
                &state_dir,
                "windows-kernel-authority".into(),
                frontier,
                Arc::new(FixedClock),
            ),
            Err(AuthorityLeaseError::UnsafeStateDirectory),
        ));
    }
}
