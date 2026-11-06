use super::*;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

const OWNER: &str = "hcsn-gate-issuer";

struct TestClock(AtomicU64);

impl AuthorityClock for TestClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}

struct TestFrontier {
    current: Mutex<FinalUseFrontier>,
    unavailable: AtomicBool,
}

impl AuthorityFrontierStore<FinalUseFrontier> for TestFrontier {
    fn load(&self, owner_id: &str) -> Result<FinalUseFrontier, AuthorityTrustError> {
        if owner_id != OWNER {
            return Err(AuthorityTrustError::Invalid);
        }
        if self.unavailable.load(Ordering::SeqCst) {
            return Err(AuthorityTrustError::Unavailable);
        }
        self.current
            .lock()
            .map(|current| *current)
            .map_err(|_| AuthorityTrustError::Unavailable)
    }

    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &FinalUseFrontier,
        next: &FinalUseFrontier,
    ) -> Result<(), AuthorityTrustError> {
        if self.load(owner_id)? != *expected {
            return Err(AuthorityTrustError::Conflict);
        }
        let mut current = self
            .current
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if *current != *expected {
            return Err(AuthorityTrustError::Conflict);
        }
        *current = *next;
        Ok(())
    }
}

fn key(seed: u8, id: &str) -> anyhow::Result<(PqNativeSigningKey, PqAuthorityTrustKey)> {
    let seed = [seed; 32].into();
    let spki = PqNativeSigningKey::public_spki_from_seed(&seed);
    let public_key_id = ml_dsa_65_key_id_from_spki(&spki)?;
    Ok((
        PqNativeSigningKey::from_owned_seed(seed, public_key_id)?,
        PqAuthorityTrustKey {
            key_id: id.into(),
            public_key_id,
            public_key_spki: spki.to_vec(),
            not_before_authority_epoch: 9,
            not_after_authority_epoch: 9,
        },
    ))
}

struct Fixture {
    root: tempfile::TempDir,
    authority: FinalUseAuthority,
    gate: PqFinalUseGate,
    clock: Arc<TestClock>,
    frontier: Arc<TestFrontier>,
    issuer_key: PqNativeSigningKey,
    issuer_trust: PqAuthorityTrustKey,
    grant: SignedFinalUseGrant,
    feed_path: PathBuf,
}

fn fixture() -> anyhow::Result<Fixture> {
    let root = tempfile::tempdir()?;
    let path = root.path().canonicalize()?;
    fs::set_permissions(&path, fs::Permissions::from_mode(0o700))?;
    let clock = Arc::new(TestClock(AtomicU64::new(2_000)));
    let (issuer_key, issuer_trust) = key(/*seed*/ 51, "issuer")?;
    let (feed_key, feed_trust) = key(/*seed*/ 52, "distributor")?;
    let head = FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let frontier = Arc::new(TestFrontier {
        current: Mutex::new(FinalUseFrontier::for_initial_head_with_profile(
            &head,
            FinalUseAuthenticationProfile::MlDsa65V2,
        )?),
        unavailable: AtomicBool::new(false),
    });
    let authority = FinalUseAuthority::open_pq_state_dir_with_issuer_keys(
        &path.join("owner"),
        OWNER.into(),
        vec![issuer_trust.clone()],
        head.clone(),
        clock.clone(),
        frontier.clone(),
    )?;
    let update = FinalUseRevocationUpdate::new_pq(
        "distributor".into(),
        head,
        /*issued_at_unix_ms*/ 1_000,
        /*expires_at_unix_ms*/ 4_000,
    );
    let signed = SignedFinalUseRevocationUpdate {
        signature: feed_key
            .sign_exact_message(&update.signing_bytes()?)?
            .to_vec(),
        update,
    };
    let feed_path = path.join("feed.json");
    fs::write(&feed_path, serde_json::to_vec(&signed)?)?;
    fs::set_permissions(&feed_path, fs::Permissions::from_mode(0o600))?;
    let grant = FinalUseGrant {
        schema_version: 2,
        signer_id: OWNER.into(),
        authority_epoch: 9,
        grant_id: "hcsn-gate-grant".into(),
        nonce: [1; 32],
        binding: FinalUseBinding {
            subject_id: "subject".into(),
            destination_id: "hcsn-provider".into(),
            request_sha256: [1; 32],
            scope_sha256: [2; 32],
            payload_sha256: [3; 32],
        },
        not_before_unix_ms: 1_000,
        expires_at_unix_ms: 3_000,
    };
    let grant = SignedFinalUseGrant {
        signature: issuer_key
            .sign_exact_message(&grant.signing_bytes()?)?
            .to_vec(),
        grant,
    };
    Ok(Fixture {
        root,
        authority,
        gate: PqFinalUseGate {
            clock: clock.clone(),
            feed: FinalUseRevocationFeedVerifier::new_pq_with_keys(
                "distributor".into(),
                vec![feed_trust],
            )?,
            authority_epoch: 9,
            signer_id: OWNER.into(),
            frontier: frontier.clone(),
        },
        clock,
        frontier,
        issuer_key,
        issuer_trust,
        grant,
        feed_path,
    })
}

#[test]
fn final_contact_rechecks_external_nonce_progress_after_active_effect_entry() -> anyhow::Result<()>
{
    let fixture = fixture()?;
    let binding = &fixture.grant.grant.binding;
    let lease =
        fixture
            .gate
            .authenticate(&fixture.authority, &fixture.feed_path, &fixture.grant)?;
    let token = fixture.authority.claim(&fixture.grant, binding)?;
    let admitted = lease.check_claim(&token)?;
    let original = fixture.authority.frontier()?;
    let owner = fixture.root.path().join("owner");
    let original_claims = fs::read(owner.join("authority.claims"))?;
    let current = fixture.root.path().join("current-owner");
    fs::create_dir(&current)?;
    fs::set_permissions(&current, fs::Permissions::from_mode(0o700))?;
    for name in ["authority.json", "authority.claims"] {
        fs::copy(owner.join(name), current.join(name))?;
    }
    let current = FinalUseAuthority::open_pq_state_dir_with_issuer_keys(
        &current,
        OWNER.into(),
        vec![fixture.issuer_trust.clone()],
        fixture.authority.revocation_head()?,
        fixture.clock.clone(),
        fixture.frontier.clone(),
    )?;
    let mut other = fixture.grant.clone();
    other.grant.grant_id = "other-grant".into();
    other.grant.nonce = [2; 32];
    other.signature = fixture
        .issuer_key
        .sign_exact_message(&other.grant.signing_bytes()?)?
        .to_vec();
    let mut contacted = false;
    let result = fixture.authority.with_verified_effect(token, binding, || {
        admitted.check()?;
        // A fresh confirmation works while the original effect guard is active.
        fixture
            .gate
            .authenticate(&fixture.authority, &fixture.feed_path, &fixture.grant)?
            .check()?;
        drop(current.claim(&other, binding)?);
        // Head and protected time stay valid; only the external nonce state moved.
        fixture
            .gate
            .authenticate(&fixture.authority, &fixture.feed_path, &fixture.grant)?
            .check()?;
        contacted = true;
        Ok::<_, anyhow::Error>(())
    })?;
    let Err(error) = result else {
        anyhow::bail!("external progress must refuse provider contact");
    };
    assert_eq!(
        error.downcast_ref::<FinalUseError>(),
        Some(&FinalUseError::AntiRollbackViolation)
    );
    assert!(!contacted);
    assert_eq!(
        fixture.authority.revocation_head()?,
        current.revocation_head()?
    );
    assert_eq!(fixture.authority.frontier()?, original);
    assert_ne!(fixture.frontier.load(OWNER)?, original);
    assert_eq!(fs::read(owner.join("authority.claims"))?, original_claims);
    assert_eq!(fixture.authority.capacity()?.used_nonces, 1);
    assert_eq!(current.capacity()?.used_nonces, 2);
    Ok(())
}

#[test]
fn final_contact_refuses_unavailable_frontier_without_replacing_local_state() -> anyhow::Result<()>
{
    let fixture = fixture()?;
    let binding = &fixture.grant.grant.binding;
    let token = fixture.authority.claim(&fixture.grant, binding)?;
    let original = fixture.authority.frontier()?;
    let result = fixture.authority.with_verified_effect(token, binding, || {
        fixture.frontier.unavailable.store(true, Ordering::SeqCst);
        fixture.gate.refresh(&fixture.authority, &fixture.feed_path)
    })?;
    let Err(error) = result else {
        anyhow::bail!("unavailable frontier must refuse the external lookup");
    };
    assert_eq!(
        error.downcast_ref::<AuthorityTrustError>(),
        Some(&AuthorityTrustError::Unavailable)
    );
    fixture.frontier.unavailable.store(false, Ordering::SeqCst);
    assert_eq!(fixture.authority.frontier()?, original);
    assert_eq!(fixture.frontier.load(OWNER)?, original);
    assert_eq!(fixture.authority.capacity()?.used_nonces, 1);
    Ok(())
}

struct ExpiringFeedFrontier {
    inner: Arc<TestFrontier>,
    clock: Arc<TestClock>,
}

impl AuthorityFrontierStore<FinalUseFrontier> for ExpiringFeedFrontier {
    fn load(&self, owner_id: &str) -> Result<FinalUseFrontier, AuthorityTrustError> {
        let frontier = self.inner.load(owner_id)?;
        self.clock.0.store(4_000, Ordering::SeqCst);
        Ok(frontier)
    }

    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &FinalUseFrontier,
        next: &FinalUseFrontier,
    ) -> Result<(), AuthorityTrustError> {
        self.inner.compare_and_set(owner_id, expected, next)
    }
}

#[test]
fn recovery_contact_refuses_feed_that_expires_during_frontier_observation() -> anyhow::Result<()> {
    let mut fixture = fixture()?;
    fixture.gate.frontier = Arc::new(ExpiringFeedFrontier {
        inner: fixture.frontier.clone(),
        clock: fixture.clock.clone(),
    });
    let original = fixture.authority.frontier()?;
    let Err(error) = fixture.gate.refresh(&fixture.authority, &fixture.feed_path) else {
        anyhow::bail!("feed expiry during trust I/O must refuse the external lookup");
    };
    assert_eq!(
        error.downcast_ref::<FinalUseError>(),
        Some(&FinalUseError::Expired)
    );
    assert_eq!(fixture.authority.frontier()?, original);
    assert_eq!(fixture.frontier.load(OWNER)?, original);
    assert_eq!(fixture.authority.capacity()?.used_nonces, 0);
    Ok(())
}
