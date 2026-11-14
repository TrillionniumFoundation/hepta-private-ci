use std::sync::Arc;

use pretty_assertions::assert_eq;

use super::*;

#[derive(Debug)]
struct FixedClock;

impl AuthorityClock for FixedClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(2_000)
    }
}

fn lease() -> AuthorityLease {
    AuthorityLease {
        schema_version: LEASE_SCHEMA_VERSION,
        lease_id: "lease-one".into(),
        authority_epoch: 7,
        revision: 1,
        binding: AuthorityLeaseBinding {
            principal_id: "agent-one".into(),
            operation_class: "provider.read".into(),
            destination_id: "provider:heptabao".into(),
            scope_sha256: [2; 32],
            payload_sha256: [3; 32],
        },
        issued_at_unix_ms: 1_000,
        expires_at_unix_ms: 30_000,
    }
}

#[test]
fn windows_revocation_reopens_and_rejects_rolled_back_state()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("owner");
    let registry = AuthorityLeaseRegistry::open_state_dir_with_clock(
        &root,
        "security-authority".into(),
        AuthorityLeaseFrontier::for_empty_epoch(7)?,
        Arc::new(FixedClock),
    )?;
    let granted = lease();
    registry.put_lease(granted.clone(), 0)?;
    let old_state = std::fs::read(root.join("authority-leases.json"))?;
    let verifier = registry.verifier();
    let token = verifier.verify_use(&granted.lease_id, 1, &granted.binding)?;
    assert_eq!(
        verifier.with_verified_use(token, &granted.binding, || 7),
        Ok(7)
    );
    registry.revoke(&granted.lease_id, 1, [9; 32])?;
    assert!(matches!(
        verifier.verify_use(&granted.lease_id, 2, &granted.binding),
        Err(AuthorityLeaseError::Revoked)
    ));
    let frontier = registry.frontier()?;
    let revocation = registry.read_revocation(&granted.lease_id)?;
    drop(verifier);
    drop(registry);
    let reopened =
        AuthorityLeaseRegistry::open_state_dir(&root, "security-authority".into(), frontier)?;
    assert_eq!(reopened.read_revocation(&granted.lease_id)?, revocation);
    assert_eq!(reopened.frontier()?, frontier);
    drop(reopened);

    std::fs::write(root.join("authority-leases.json"), &old_state)?;
    assert!(matches!(
        AuthorityLeaseRegistry::open_state_dir(&root, "security-authority".into(), frontier),
        Err(AuthorityLeaseError::AntiRollbackViolation)
    ));
    assert_eq!(
        std::fs::read(root.join("authority-leases.json"))?,
        old_state
    );
    Ok(())
}

#[test]
fn windows_owner_lock_and_namespace_anchor_survive_root_rename()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("owner");
    let moved = temp.path().join("retained-owner");
    let initial = AuthorityLeaseFrontier::for_empty_epoch(7)?;
    let registry = AuthorityLeaseRegistry::open_state_dir_with_clock(
        &root,
        "security-authority".into(),
        initial,
        Arc::new(FixedClock),
    )?;
    assert!(matches!(
        AuthorityLeaseRegistry::open_state_dir(&root, "security-authority".into(), initial),
        Err(AuthorityLeaseError::StateLocked)
    ));
    std::fs::rename(&root, &moved)?;
    let replacement = StateDirectory::open_or_create(&root)?;
    registry.put_lease(lease(), 0)?;
    assert!(!replacement.entry_exists("authority-leases.json")?);
    let frontier = registry.frontier()?;
    let expected = registry
        .read_lease("lease-one")?
        .ok_or_else(|| std::io::Error::other("written lease is missing"))?;
    drop(registry);
    let reopened =
        AuthorityLeaseRegistry::open_state_dir(&moved, "security-authority".into(), frontier)?;
    assert_eq!(reopened.frontier()?, frontier);
    assert_eq!(reopened.read_lease("lease-one")?, Some(expected));
    Ok(())
}
