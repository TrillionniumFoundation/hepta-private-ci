//! Native filesystem/crypto controls; the in-memory frontier is a test fixture,
//! not external durability, attestation or production Windows qualification.
use super::*;
use crate::AuthorityTrustError;
use crate::SystemAuthorityClock;
use crate::final_use::FinalUseBinding;
use crate::final_use::FinalUseGrant;
use crate::final_use::SignedFinalUseGrant;
use crate::windows_private_owner::OriginalFileAccess;
use crate::windows_private_owner::ParentAnchor;
use crate::windows_private_owner::PrivateStoreDirectory;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::collections::BTreeSet;
use std::error::Error;
use std::fs;
use std::io;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

type Result<T = ()> = std::result::Result<T, Box<dyn Error>>;
static NEXT: AtomicU64 = AtomicU64::new(0);
struct Frontier(Mutex<FinalUseFrontier>);
impl AuthorityFrontierStore<FinalUseFrontier> for Frontier {
    fn load(&self, _: &str) -> std::result::Result<FinalUseFrontier, AuthorityTrustError> {
        self.0
            .lock()
            .map(|value| *value)
            .map_err(|_| AuthorityTrustError::Unavailable)
    }
    fn compare_and_set(
        &self,
        _: &str,
        expected: &FinalUseFrontier,
        next: &FinalUseFrontier,
    ) -> std::result::Result<(), AuthorityTrustError> {
        let mut held = self
            .0
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if &*held != expected {
            return Err(AuthorityTrustError::Conflict);
        }
        *held = *next;
        Ok(())
    }
}
struct Fixture {
    parent: PathBuf,
    leaf: String,
}
impl Fixture {
    fn new() -> Result<(Self, PrivateStoreDirectory)> {
        let parent = PathBuf::from(format!(r"{}\", std::env::var("SystemDrive")?));
        let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
        let sequence = NEXT.fetch_add(1, Ordering::Relaxed);
        let leaf = format!(
            "hepta-final-owner-{}-{nonce}-{sequence}",
            std::process::id()
        );
        let directory = ParentAnchor::for_create_only(&parent)?.create_private_directory(&leaf)?;
        Ok((
            Self { parent, leaf },
            PrivateStoreDirectory::Fresh(directory),
        ))
    }
    fn cold(&self) -> Result<PrivateStoreDirectory> {
        Ok(PrivateStoreDirectory::Existing(
            ParentAnchor::for_create_only(&self.parent)?.open_existing_candidate(&self.leaf)?,
        ))
    }
    fn path(&self, leaf: &str) -> PathBuf {
        self.parent.join(&self.leaf).join(leaf)
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        for name in [
            "authority.json",
            "authority.next",
            "authority.claims",
            "authority.claims.next",
            "authority.lock",
        ] {
            let _ = fs::remove_file(self.path(name));
        }
        let _ = fs::remove_dir(self.parent.join(&self.leaf));
    }
}
fn head() -> FinalUseRevocations {
    FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    }
}
fn open(input: PrivateStoreDirectory, frontier: Arc<Frontier>) -> Result<FinalUseAuthority> {
    Ok(FinalUseAuthority::open_windows_private_with_trust(
        input,
        "security-owner".into(),
        SigningKey::from_bytes(&[47; 32]).verifying_key().to_bytes(),
        head(),
        Arc::new(SystemAuthorityClock),
        frontier,
    )?)
}

#[test]
fn native_explicit_owner_keeps_original_signed_claim_replay_and_os_lock() -> Result {
    let (fixture, input) = Fixture::new()?;
    let frontier = Arc::new(Frontier(Mutex::new(FinalUseFrontier::for_initial_head(
        &head(),
    )?)));
    let owner = open(input, Arc::clone(&frontier))?;
    assert!(
        matches!(open(fixture.cold()?, Arc::clone(&frontier)), Err(error)
        if error.downcast_ref::<FinalUseError>() == Some(&FinalUseError::StateLocked))
    );
    let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner".into(),
        authority_epoch: 9,
        grant_id: "read-one".into(),
        nonce: [5; 32],
        binding: FinalUseBinding {
            subject_id: "agent-one".into(),
            destination_id: "provider:heptabao".into(),
            request_sha256: [1; 32],
            scope_sha256: [2; 32],
            payload_sha256: [3; 32],
        },
        not_before_unix_ms: now - 1000,
        expires_at_unix_ms: now + 30_000,
    };
    let signature = SigningKey::from_bytes(&[47; 32])
        .sign(&grant.signing_bytes()?)
        .to_bytes()
        .to_vec();
    let signed = SignedFinalUseGrant { grant, signature };
    let token = owner.claim(&signed, &signed.grant.binding)?;
    assert_eq!(
        owner.with_verified_use(token, &signed.grant.binding, || 7),
        Ok(7)
    );
    drop(owner);
    let reopened = open(fixture.cold()?, frontier)?;
    assert!(matches!(
        reopened.claim(&signed, &signed.grant.binding),
        Err(FinalUseError::AlreadyClaimed)
    ));
    assert_eq!(fs::metadata(fixture.path("authority.claims"))?.len(), 40);
    Ok(())
}

#[test]
fn native_cold_frontier_mismatch_rejects_before_original_state_rewrites() -> Result {
    let (fixture, input) = Fixture::new()?;
    let frontier = Arc::new(Frontier(Mutex::new(FinalUseFrontier::for_initial_head(
        &head(),
    )?)));
    drop(open(input, Arc::clone(&frontier))?);
    let before = (
        fs::read(fixture.path("authority.json"))?,
        fs::read(fixture.path("authority.claims"))?,
    );
    frontier
        .0
        .lock()
        .map_err(|_| io::Error::other("frontier poison"))?
        .state_sha256[0] ^= 1;
    assert!(matches!(open(fixture.cold()?, frontier), Err(error)
        if error.downcast_ref::<FinalUseError>() == Some(&FinalUseError::AntiRollbackViolation)));
    assert_eq!(
        (
            fs::read(fixture.path("authority.json"))?,
            fs::read(fixture.path("authority.claims"))?
        ),
        before
    );
    assert!(!fixture.path("authority.next").exists());
    assert!(!fixture.path("authority.claims.next").exists());
    Ok(())
}

#[test]
fn native_legacy_zero_nonce_preserves_original_staged_and_committed_bytes() -> Result {
    let (fixture, input) = Fixture::new()?;
    let frontier = Arc::new(Frontier(Mutex::new(FinalUseFrontier::for_initial_head(
        &head(),
    )?)));
    drop(open(input, Arc::clone(&frontier))?);
    let held = fixture.cold()?.lock_original_marker("authority.lock")?;
    for name in ["authority.next", "authority.claims.next"] {
        let mut stage = held.open_original_file(name, 1024, OriginalFileAccess::Stage)?;
        stage.write_all(b"original-unselected-stage")?;
        stage.sync_all()?;
    }
    held.sync_all()?;
    drop(held);
    let invalid = super::super::State {
        head: head(),
        used_nonces: BTreeSet::from([[0; 32], [5; 32]]),
        failed: false,
    };
    fs::write(
        fixture.path("authority.json"),
        serde_json::to_vec(&serde_json::json!({
            "schema": 1,
            "signer_id": "security-owner",
            "verifying_key": SigningKey::from_bytes(&[47; 32]).verifying_key().to_bytes(),
            "state": invalid,
        }))?,
    )?;
    // A matching fixture frontier must not hide invalid claims or authorize a
    // partial migration. It is deliberately not production durability proof.
    *frontier
        .0
        .lock()
        .map_err(|_| io::Error::other("frontier poison"))? = frontier_for_state(&invalid);
    let names = [
        "authority.json",
        "authority.claims",
        "authority.next",
        "authority.claims.next",
    ];
    let before = names
        .map(|name| fs::read(fixture.path(name)))
        .into_iter()
        .collect::<std::result::Result<Vec<_>, _>>()?;
    for _ in 0..2 {
        assert!(
            matches!(open(fixture.cold()?, Arc::clone(&frontier)), Err(error)
            if error.downcast_ref::<FinalUseError>() == Some(&FinalUseError::InvalidTrust))
        );
        let after = names
            .map(|name| fs::read(fixture.path(name)))
            .into_iter()
            .collect::<std::result::Result<Vec<_>, _>>()?;
        assert_eq!(after, before);
    }
    Ok(())
}

// Restore only this fixture's already-held marker attributes on every unwind.
// This is not a namespace/ACL repair and provides no production trust source.
struct RestoreOwnedMarkerPermissions {
    path: PathBuf,
    original: fs::Permissions,
}
impl RestoreOwnedMarkerPermissions {
    fn restore(&self) -> io::Result<()> {
        fs::set_permissions(&self.path, self.original.clone())
    }
}
impl Drop for RestoreOwnedMarkerPermissions {
    fn drop(&mut self) {
        if let Err(error) = self.restore() {
            eprintln!("owned final-use fixture marker attribute restore failed: {error}");
        }
    }
}

#[test]
fn native_retained_owner_drift_fences_preclaimed_entries_and_stays_failed() -> Result {
    #[derive(Debug)]
    enum Boundary {
        TokenEntry,
        RevocationRead,
        ConsumerEntry,
        EffectEntry,
        DispatchEntry,
    }
    // The original in-memory frontier and system clock remain test fixtures.
    // Each case uses a distinct real NTFS owner and original signed claim path.
    for boundary in [
        Boundary::TokenEntry,
        Boundary::RevocationRead,
        Boundary::ConsumerEntry,
        Boundary::EffectEntry,
        Boundary::DispatchEntry,
    ] {
        let (fixture, input) = Fixture::new()?;
        let frontier = Arc::new(Frontier(Mutex::new(FinalUseFrontier::for_initial_head(
            &head(),
        )?)));
        let owner = open(input, frontier)?;
        let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "security-owner".into(),
            authority_epoch: 9,
            grant_id: "held-owner-probe".into(),
            nonce: [7; 32],
            binding: FinalUseBinding {
                subject_id: "agent-one".into(),
                destination_id: "provider:heptabao".into(),
                request_sha256: [1; 32],
                scope_sha256: [2; 32],
                payload_sha256: [3; 32],
            },
            not_before_unix_ms: now - 1000,
            expires_at_unix_ms: now + 30_000,
        };
        let signed = SignedFinalUseGrant {
            signature: SigningKey::from_bytes(&[47; 32])
                .sign(&grant.signing_bytes()?)
                .to_bytes()
                .to_vec(),
            grant,
        };
        let expected = signed.grant.binding.clone();
        let token = owner.claim(&signed, &expected)?;
        let marker = fixture.path("authority.lock");
        let original = fs::metadata(&marker)?.permissions();
        assert!(!original.readonly());
        let restore = RestoreOwnedMarkerPermissions {
            path: marker.clone(),
            original: original.clone(),
        };
        let mut changed = original;
        changed.set_readonly(/*readonly*/ true);
        fs::set_permissions(&marker, changed)?;
        assert!(fs::metadata(&marker)?.permissions().readonly());
        let callbacks = std::sync::atomic::AtomicUsize::new(/*v*/ 0);
        let outcome = match boundary {
            Boundary::TokenEntry => token.enter(&expected).map(|_| ()),
            Boundary::RevocationRead => {
                drop(token);
                owner.revocation_head().map(|_| ())
            }
            Boundary::ConsumerEntry => owner.with_verified_use(token, &expected, || {
                callbacks.fetch_add(/*val*/ 1, Ordering::SeqCst);
            }),
            Boundary::EffectEntry => owner.with_verified_effect(token, &expected, || {
                callbacks.fetch_add(/*val*/ 1, Ordering::SeqCst);
            }),
            Boundary::DispatchEntry => owner.with_dispatch_boundary(token, &expected, || {
                callbacks.fetch_add(/*val*/ 1, Ordering::SeqCst);
            }),
        };
        assert!(
            matches!(outcome, Err(FinalUseError::Unavailable)),
            "{boundary:?}"
        );
        assert_eq!(callbacks.load(Ordering::SeqCst), 0, "{boundary:?}");
        assert!(
            owner
                .0
                .state
                .lock()
                .map_err(|_| "authority state poisoned")?
                .failed
        );
        restore.restore()?;
        assert!(!fs::metadata(&marker)?.permissions().readonly());
        assert!(matches!(owner.frontier(), Err(FinalUseError::Unavailable)));
    }
    Ok(())
}
