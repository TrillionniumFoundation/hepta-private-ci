//! Actual original registry and receipt checks; no actual-Root qualification.
use super::*;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseError;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;
use std::time::Duration;

struct Clock;
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(10_000)
    }
}

fn fixture()
-> Result<(AuthorityLeaseRegistry, AuthorityLease, tempfile::TempDir), Box<dyn std::error::Error>> {
    let directory = tempfile::Builder::new()
        .permissions(std::fs::Permissions::from_mode(0o700))
        .tempdir()?;
    let registry = AuthorityLeaseRegistry::open_state_dir_with_clock(
        directory.path(),
        "original-root-issuer-revoke".into(),
        AuthorityLeaseFrontier::for_empty_epoch(1)?,
        Arc::new(Clock),
    )?;
    let original = AuthorityLease {
        schema_version: 1,
        lease_id: "original-root-issuer".into(),
        authority_epoch: 1,
        revision: 1,
        binding: AuthorityLeaseBinding {
            principal_id: "original-root".into(),
            operation_class: "original-issuer".into(),
            destination_id: "original-desktop".into(),
            scope_sha256: [3; 32],
            payload_sha256: [4; 32],
        },
        issued_at_unix_ms: 1_000,
        expires_at_unix_ms: 30_000,
    };
    registry.put_lease(original.clone(), 0)?;
    Ok((registry, original, directory))
}

#[test]
fn actual_issuer_receipt_matches_exact_retained_canonical_postimage()
-> Result<(), Box<dyn std::error::Error>> {
    let (registry, original, _directory) = fixture()?;
    let end = Instant::now() + Duration::from_secs(1);
    let receipt = registry.revoke_exact_before(&original, [9; 32], end)?;
    let frontier = registry.frontier()?;
    assert_eq!(
        confirm_committed(&registry, &original, &receipt, end)?,
        frontier
    );
    for field in 0..7 {
        let mut changed = receipt.clone();
        match field {
            0 => changed.lease_id.push('x'),
            1 => changed.authority_epoch += 1,
            2 => changed.previous_lease_revision += 1,
            3 => changed.lease_revision += 1,
            4 => changed.store_revision += 1,
            5 => changed.reason_sha256[0] ^= 1,
            6 => changed.revoked_at_unix_ms += 1,
            _ => unreachable!(),
        }
        assert!(confirm_committed(&registry, &original, &changed, end).is_err());
        assert_eq!(registry.frontier()?, frontier);
    }
    let mut changed_original = original.clone();
    changed_original.binding.destination_id.push('x');
    assert!(confirm_committed(&registry, &changed_original, &receipt, end).is_err());
    assert_eq!(registry.frontier()?, frontier);
    Ok(())
}

#[test]
fn late_client_confirmation_preserves_committed_revoke_and_refuses_renewal()
-> Result<(), Box<dyn std::error::Error>> {
    let (registry, original, _directory) = fixture()?;
    let receipt = registry.revoke_exact_before(
        &original,
        [7; 32],
        Instant::now() + Duration::from_secs(1),
    )?;
    let frontier = registry.frontier()?;
    let elapsed = Instant::now()
        .checked_sub(Duration::from_secs(1))
        .ok_or("clock range")?;
    assert!(confirm_committed(&registry, &original, &receipt, elapsed).is_err());
    let retained = registry
        .read_revocation(&original.lease_id)?
        .ok_or("revocation absent")?;
    assert_eq!(retained.revocation.reason_sha256, [7; 32]);
    let mut renewed = original.clone();
    renewed.revision = receipt
        .lease_revision
        .checked_add(1)
        .ok_or("revision range")?;
    renewed.expires_at_unix_ms += 1;
    assert_eq!(
        registry.put_lease(renewed, receipt.lease_revision),
        Err(AuthorityLeaseError::Revoked)
    );
    assert_eq!(registry.frontier()?, frontier);
    Ok(())
}

#[test]
fn terminal_confirmation_refuses_new_epoch_without_reconstructing_original_lease()
-> Result<(), Box<dyn std::error::Error>> {
    let (registry, original, _directory) = fixture()?;
    let end = Instant::now() + Duration::from_secs(1);
    let receipt = registry.revoke_exact_before(&original, [7; 32], end)?;
    let prior = registry.frontier()?;
    registry.advance_epoch(prior.store_revision, 2)?;
    let frontier = registry.frontier()?;
    assert!(confirm_committed(&registry, &original, &receipt, end).is_err());
    assert_eq!(registry.frontier()?, frontier);
    assert!(registry.read_lease(&original.lease_id)?.is_none());
    Ok(())
}
