//! Negative only: actual kernel checks return late, original isolated CAS
//! methods must not be called. No actual-Root or production authority claim.
use super::*;
use crate::DeploymentFinalUseIssuer;
use crate::DeploymentGrantPolicy;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SystemAuthorityClock;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use std::collections::BTreeMap;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

struct OriginalStores {
    root: tempfile::TempDir,
    registry: AuthorityLeaseRegistry,
    issuer: DeploymentFinalUseIssuer,
    grant_id: String,
}

impl OriginalStores {
    fn new() -> Result<Self, Box<dyn std::error::Error>> {
        let root = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()?;
        let registry = AuthorityLeaseRegistry::open_state_dir(
            &root.path().join("leases"),
            "late-check-registry".into(),
            AuthorityLeaseFrontier::for_empty_epoch(1)?,
        )?;
        let now = SystemAuthorityClock.now_unix_ms()?;
        registry.put_lease(
            AuthorityLease {
                schema_version: 1,
                lease_id: "original-lease".into(),
                authority_epoch: 1,
                revision: 1,
                binding: AuthorityLeaseBinding {
                    principal_id: "late-check-owner".into(),
                    operation_class: "test.original".into(),
                    destination_id: "late-check-note".into(),
                    scope_sha256: [1; 32],
                    payload_sha256: [2; 32],
                },
                issued_at_unix_ms: now,
                expires_at_unix_ms: now + 60_000,
            },
            0,
        )?;
        let issuer = DeploymentFinalUseIssuer::create(
            &root.path().join("issuer"),
            "late-check-issuer".into(),
            vec![DeploymentGrantPolicy {
                subject_id: "late-check-owner".into(),
                destination_id: "late-check-note".into(),
                scope_sha256: [1; 32],
                lifetime_ms: 30_000,
            }],
            Arc::new(SystemAuthorityClock),
        )?;
        let signed = issuer
            .issue(&FinalUseBinding {
                subject_id: "late-check-owner".into(),
                destination_id: "late-check-note".into(),
                scope_sha256: [1; 32],
                payload_sha256: [2; 32],
                request_sha256: [3; 32],
            })?
            .ok_or("fixture grant absent")?;
        Ok(Self {
            root,
            registry,
            issuer,
            grant_id: signed.grant.grant_id,
        })
    }

    fn negative(
        &self,
        slow_check: impl FnOnce(Instant) -> io::Result<()>,
    ) -> Result<(), Box<dyn std::error::Error>> {
        let before_frontier = self.registry.frontier()?;
        let before_head = self.issuer.revocations()?;
        let before_files = json_files(self.root.path())?;
        let registry_calls = AtomicUsize::new(0);
        let issuer_calls = AtomicUsize::new(0);
        let entered = AtomicBool::new(false);
        let end = Instant::now() + Duration::from_millis(100);
        let outcome = checked_step(
            end,
            || {
                entered.store(true, Ordering::Release);
                std::thread::sleep(Duration::from_millis(150));
                slow_check(end)
            },
            || {
                registry_calls.fetch_add(1, Ordering::AcqRel);
                self.registry
                    .revoke("original-lease", 1, [9; 32])
                    .map_err(io::Error::other)?;
                issuer_calls.fetch_add(1, Ordering::AcqRel);
                self.issuer.revoke(&self.grant_id)?;
                Ok(())
            },
        );
        let after_frontier = self.registry.frontier()?;
        let after_head = self.issuer.revocations()?;
        let after_files = json_files(self.root.path())?;
        assert!(
            entered.load(Ordering::Acquire),
            "negative did not enter the actual late check"
        );
        assert_eq!(
            (
                registry_calls.load(Ordering::Acquire),
                issuer_calls.load(Ordering::Acquire)
            ),
            (0, 0),
            "late check entered original registry/issuer CAS; before={before_frontier:?}/{before_head:?}, after={after_frontier:?}/{after_head:?}"
        );
        assert_eq!(before_frontier, after_frontier);
        assert_eq!(before_head, after_head);
        assert_eq!(before_files, after_files);
        assert!(outcome.is_err());
        Ok(())
    }
}

fn json_files(root: &Path) -> io::Result<BTreeMap<PathBuf, Vec<u8>>> {
    let mut result = BTreeMap::new();
    for entry in std::fs::read_dir(root)? {
        let path = entry?.path();
        if path.is_dir() {
            result.extend(json_files(&path)?);
        } else if path.extension().is_some_and(|value| value == "json") {
            result.insert(path.clone(), std::fs::read(path)?);
        }
    }
    Ok(result)
}

#[test]
fn late_actual_owner_check_cannot_enter_registry_or_issuer_cas()
-> Result<(), Box<dyn std::error::Error>> {
    let stores = OriginalStores::new()?;
    // SAFETY: names this actual process, whose lifetime this test retains.
    let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
    if raw < 0 {
        return Err(io::Error::last_os_error().into());
    }
    // SAFETY: adopts precisely the successful fresh pidfd return value.
    let owner = unsafe { OwnedFd::from_raw_fd(raw as i32) };
    stores.negative(|_end| {
        // Reproduce the old check's newly opened deadline. Even this late
        // actual successful kernel check must not permit a subsequent CAS.
        crate::authority_host_runtime::owner_alive(&owner, Instant::now() + Duration::from_secs(1))
    })
}

#[test]
fn late_actual_lifetime_read_cannot_enter_registry_or_issuer_cas()
-> Result<(), Box<dyn std::error::Error>> {
    let stores = OriginalStores::new()?;
    let mut identity = super::super::RootAdminInstance::current()?;
    identity.episode_nonce = [7; 32];
    stores.negative(|_end| identity.verify_current())
}
