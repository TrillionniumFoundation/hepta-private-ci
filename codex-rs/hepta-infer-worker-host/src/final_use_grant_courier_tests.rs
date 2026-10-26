use super::*;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::collections::BTreeSet;
use std::fs;
use std::io::Write;
use std::os::unix::fs::FileTypeExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error + Send + Sync>>;

struct Clock(AtomicU64);
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}

struct Fixture {
    temp: tempfile::TempDir,
    authority: FinalUseAuthority,
    clock: Arc<Clock>,
    signed: SignedFinalUseGrant,
    path: PathBuf,
}

impl Fixture {
    fn new() -> TestResult<Self> {
        let temp = tempfile::tempdir()?;
        let state = temp.path().join("authority");
        fs::create_dir(&state)?;
        fs::set_permissions(&state, fs::Permissions::from_mode(0o700))?;
        let key = SigningKey::from_bytes(&[137; 32]);
        let clock = Arc::new(Clock(AtomicU64::new(1_000)));
        let authority = FinalUseAuthority::open_state_dir_with_clock(
            &state,
            "external-courier-issuer".to_owned(),
            key.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 1,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
            clock.clone(),
        )?;
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "external-courier-issuer".to_owned(),
            authority_epoch: 1,
            grant_id: "external-courier-grant".to_owned(),
            nonce: [41; 32],
            binding: FinalUseBinding {
                subject_id: "courier-agent".to_owned(),
                destination_id: "courier-destination".to_owned(),
                request_sha256: [1; 32],
                scope_sha256: [2; 32],
                payload_sha256: [3; 32],
            },
            not_before_unix_ms: 900,
            expires_at_unix_ms: 2_000,
        };
        let signature = key.sign(&grant.signing_bytes()?).to_bytes().to_vec();
        let signed = SignedFinalUseGrant { grant, signature };
        let path = temp.path().join("signed-grant.json");
        let mut file = fs::OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(&path)?;
        file.write_all(&serde_json::to_vec(&signed)?)?;
        file.sync_all()?;
        Ok(Self {
            temp,
            authority,
            clock,
            signed,
            path,
        })
    }

    fn courier(&self) -> Result<SignedFinalUseGrantCourier, AgentdError> {
        SignedFinalUseGrantCourier::open(
            &self.path,
            rustix::process::geteuid().as_raw(),
            self.authority.clone(),
            &self.signed.grant.binding,
        )
    }
}

#[test]
fn courier_readiness_is_non_consuming_and_original_claim_remains_one_shot() -> TestResult {
    let fixture = Fixture::new()?;
    let before = fixture.authority.capacity()?;
    let claims = fs::read(fixture.temp.path().join("authority/authority.claims"))?;
    let courier = fixture.courier()?;
    for _ in 0..3 {
        assert_eq!(
            courier.signed_grant(&fixture.signed.grant.binding)?,
            fixture.signed
        );
    }
    assert_eq!(fixture.authority.capacity()?, before);
    assert_eq!(
        fs::read(fixture.temp.path().join("authority/authority.claims"))?,
        claims
    );
    let token = fixture
        .authority
        .claim(&fixture.signed, &fixture.signed.grant.binding)?;
    assert!(courier.signed_grant(&fixture.signed.grant.binding).is_err());
    assert!(fixture.courier().is_err());
    assert_eq!(fixture.authority.capacity()?.used_nonces, 1);
    drop(token);
    Ok(())
}

#[test]
fn courier_rereads_current_revocation_expiry_and_exact_binding() -> TestResult {
    let fixture = Fixture::new()?;
    let courier = fixture.courier()?;
    for index in 0..5 {
        let mut binding = fixture.signed.grant.binding.clone();
        match index {
            0 => binding.subject_id.push('x'),
            1 => binding.destination_id.push('x'),
            2 => binding.request_sha256[0] ^= 1,
            3 => binding.scope_sha256[0] ^= 1,
            4 => binding.payload_sha256[0] ^= 1,
            _ => unreachable!(),
        }
        assert!(courier.signed_grant(&binding).is_err());
    }
    fixture.clock.0.store(2_000, Ordering::SeqCst);
    assert!(courier.signed_grant(&fixture.signed.grant.binding).is_err());
    fixture.clock.0.store(1_000, Ordering::SeqCst);
    fixture.authority.update_revocations(FinalUseRevocations {
        authority_epoch: 1,
        revision: 2,
        revoked_grant_ids: BTreeSet::from([fixture.signed.grant.grant_id.clone()]),
    })?;
    assert!(courier.signed_grant(&fixture.signed.grant.binding).is_err());
    assert_eq!(fixture.authority.capacity()?.used_nonces, 0);
    Ok(())
}

#[test]
fn courier_refuses_untrusted_signature_epoch_or_multiple_frames() -> TestResult {
    let fixture = Fixture::new()?;
    let mut wrong = fixture.signed.clone();
    wrong.signature[0] ^= 1;
    fs::write(&fixture.path, serde_json::to_vec(&wrong)?)?;
    assert!(fixture.courier().is_err());
    wrong = fixture.signed.clone();
    wrong.grant.authority_epoch = 2;
    wrong.signature = SigningKey::from_bytes(&[137; 32])
        .sign(&wrong.grant.signing_bytes()?)
        .to_bytes()
        .to_vec();
    fs::write(&fixture.path, serde_json::to_vec(&wrong)?)?;
    assert!(fixture.courier().is_err());
    let frame = serde_json::to_vec(&fixture.signed)?;
    fs::write(&fixture.path, [frame.clone(), frame].concat())?;
    assert!(fixture.courier().is_err());
    fs::write(&fixture.path, vec![b' '; MAX_SIGNED_GRANT_FILE_BYTES + 1])?;
    assert!(fixture.courier().is_err());
    assert_eq!(fixture.authority.capacity()?.used_nonces, 0);
    Ok(())
}

#[test]
fn courier_refuses_symlink_hardlink_fifo_wrong_owner_and_shared_write() -> TestResult {
    let fixture = Fixture::new()?;
    let uid = rustix::process::geteuid().as_raw();
    assert!(
        SignedFinalUseGrantCourier::open(
            &fixture.path,
            uid.wrapping_add(1),
            fixture.authority.clone(),
            &fixture.signed.grant.binding
        )
        .is_err()
    );
    let link = fixture.temp.path().join("symlink");
    std::os::unix::fs::symlink(&fixture.path, &link)?;
    assert!(
        SignedFinalUseGrantCourier::open(
            &link,
            uid,
            fixture.authority.clone(),
            &fixture.signed.grant.binding
        )
        .is_err()
    );
    fs::hard_link(&fixture.path, fixture.temp.path().join("hardlink"))?;
    assert!(fixture.courier().is_err());
    fs::remove_file(fixture.temp.path().join("hardlink"))?;
    fs::set_permissions(&fixture.path, fs::Permissions::from_mode(0o620))?;
    assert!(fixture.courier().is_err());
    let fifo = fixture.temp.path().join("fifo");
    let status = std::process::Command::new("mkfifo")
        .args(["-m", "600"])
        .arg(&fifo)
        .status()?;
    assert!(status.success());
    assert!(fs::symlink_metadata(&fifo)?.file_type().is_fifo());
    let start = std::time::Instant::now();
    assert!(
        SignedFinalUseGrantCourier::open(
            &fifo,
            uid,
            fixture.authority.clone(),
            &fixture.signed.grant.binding
        )
        .is_err()
    );
    assert!(
        start.elapsed() < std::time::Duration::from_secs(1),
        "FIFO must be refused without waiting for a writer"
    );
    Ok(())
}
