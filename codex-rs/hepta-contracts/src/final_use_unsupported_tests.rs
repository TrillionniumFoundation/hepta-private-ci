use crate::AuthorityClock;
use crate::AuthorityFrontierStore;
use crate::AuthorityTrustError;
use crate::FinalUseAuthority;
use crate::FinalUseError;
use crate::FinalUseFrontier;
use crate::FinalUseIssuerTrustKey;
use crate::FinalUseRevocations;
use ed25519_dalek::SigningKey;
use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

struct FixedClock;

impl AuthorityClock for FixedClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(100)
    }
}

#[derive(Default)]
struct RecordingFrontier {
    loads: AtomicUsize,
    changes: AtomicUsize,
}

impl AuthorityFrontierStore<FinalUseFrontier> for RecordingFrontier {
    fn load(&self, _owner_id: &str) -> Result<FinalUseFrontier, AuthorityTrustError> {
        self.loads.fetch_add(1, Ordering::SeqCst);
        Err(AuthorityTrustError::Unavailable)
    }

    fn compare_and_set(
        &self,
        _owner_id: &str,
        _expected: &FinalUseFrontier,
        _next: &FinalUseFrontier,
    ) -> Result<(), AuthorityTrustError> {
        self.changes.fetch_add(1, Ordering::SeqCst);
        Err(AuthorityTrustError::Unavailable)
    }
}

#[test]
fn unsupported_authority_constructors_leave_local_claims_and_external_frontier_untouched()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let existing = temp.path().join("existing");
    let missing = temp.path().join("missing");
    std::fs::create_dir(&existing)?;
    // An unsupported host must not interpret, migrate, or overwrite an existing
    // owner snapshot or nonce journal before rejecting the platform.
    let retained = ["authority.json", "authority.claims", "authority.next"];
    for name in retained {
        std::fs::write(existing.join(name), name.as_bytes())?;
    }
    let public = SigningKey::from_bytes(&[47; 32]).verifying_key().to_bytes();
    let frontier = Arc::new(RecordingFrontier::default());
    for root in [&existing, &missing] {
        for constructor in 0..4 {
            let head = FinalUseRevocations {
                authority_epoch: 9,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            };
            let result = match constructor {
                0 => FinalUseAuthority::open_state_dir(root, "owner".into(), public, head),
                1 => FinalUseAuthority::open_state_dir_with_clock(
                    root,
                    "owner".into(),
                    public,
                    head,
                    Arc::new(FixedClock),
                ),
                2 => FinalUseAuthority::open_state_dir_with_trust(
                    root,
                    "owner".into(),
                    public,
                    head,
                    Arc::new(FixedClock),
                    frontier.clone(),
                ),
                _ => FinalUseAuthority::open_state_dir_with_issuer_keys(
                    root,
                    "owner".into(),
                    vec![FinalUseIssuerTrustKey {
                        key_id: "issuer".into(),
                        verifying_key: public,
                        not_before_authority_epoch: 1,
                        not_after_authority_epoch: 10,
                    }],
                    head,
                    Arc::new(FixedClock),
                    frontier.clone(),
                ),
            };
            assert_eq!(result.err(), Some(FinalUseError::UnsafeStateDirectory));
            assert!(!missing.exists());
            assert_eq!(std::fs::read_dir(&existing)?.count(), retained.len());
            for name in retained {
                assert_eq!(std::fs::read(existing.join(name))?, name.as_bytes());
            }
        }
    }
    assert_eq!(frontier.loads.load(Ordering::SeqCst), 0);
    assert_eq!(frontier.changes.load(Ordering::SeqCst), 0);
    Ok(())
}
