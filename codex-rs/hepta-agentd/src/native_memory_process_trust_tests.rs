use std::assert_eq;
use std::os::unix::fs::PermissionsExt;

use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::*;

fn fixture() -> (tempfile::TempDir, AgentdIdentity) {
    let (root, _, state) = crate::state::isolation_tests::fixture().unwrap();
    let identity = state.identity().clone();
    std::fs::set_permissions(&identity.home_root, std::fs::Permissions::from_mode(0o700)).unwrap();
    (root, identity)
}

fn pin(identity: &AgentdIdentity, name: &str, bytes: &[u8]) -> FilePin {
    let path = identity.home_root.join(name);
    std::fs::write(&path, bytes).unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
    FilePin {
        path,
        sha256: Digest32::of_bytes(bytes).to_string(),
    }
}

fn verifier(identity: &AgentdIdentity, expired: bool) -> ProcessSourceVerifier {
    let key = SigningKey::from_bytes(&[113; 32]);
    let now = SystemAuthorityClock.now_unix_ms().unwrap() / 1000;
    let payload = SourceLeasePayload {
        schema: "hepta.memory-cell.source-lease.v1".into(),
        signer_id: "process-host".into(),
        agent_id: identity.agent_id.clone(),
        authority_epoch: 7,
        owner_epoch: 9,
        expires_at_unix_seconds: if expired { now - 1 } else { now + 120 },
        opaque_token: "externally-issued-test-token".into(),
    };
    let signature = key
        .sign(&serde_json::to_vec(&payload).unwrap())
        .to_bytes()
        .to_vec();
    let bytes = serde_json::to_vec(&SignedSourceLease { payload, signature }).unwrap();
    ProcessSourceVerifier {
        identity: identity.clone(),
        grant: pin(identity, "source-grant.json", &bytes),
        signer_id: "process-host".into(),
        verifying_key: key.verifying_key().to_bytes(),
        poisoned: AtomicBool::new(false),
    }
}

#[test]
fn signed_source_revalidation_latches_withdrawal_and_refuses_another_owner() {
    let (_root, identity) = fixture();
    let verifier = verifier(&identity, /*expired*/ false);
    let lease = verifier.current().unwrap();
    assert_eq!((lease.authority_epoch, lease.owner_epoch), (7, 9));
    verifier.verify(&lease, &identity.agent_id).unwrap();
    let other = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2cee").unwrap();
    assert!(verifier.verify(&lease, &other).is_err());
    let retained = std::fs::read(&verifier.grant.path).unwrap();
    std::fs::write(&verifier.grant.path, b"revoked by external host").unwrap();
    assert_eq!(verifier.current().unwrap_err(), "pinned file drift");
    std::fs::write(&verifier.grant.path, retained).unwrap();
    assert_eq!(
        verifier.current().unwrap_err(),
        "source authority continuity lost"
    );
}

#[test]
fn expired_or_wrong_issuer_source_cannot_bootstrap_a_verified_lease() {
    let (_root, identity) = fixture();
    assert_eq!(
        verifier(&identity, /*expired*/ true).current().unwrap_err(),
        "source lease identity or time rejected"
    );
    let mut wrong = verifier(&identity, /*expired*/ false);
    wrong.verifying_key = SigningKey::from_bytes(&[114; 32])
        .verifying_key()
        .to_bytes();
    assert!(wrong.current().is_err());
    assert!(wrong.poisoned.load(Ordering::SeqCst));
}

#[test]
fn pin_rejects_links_widened_permissions_content_and_length() {
    let (_root, identity) = fixture();
    let file = pin(&identity, "pin.json", b"retained input");
    assert_eq!(
        file.read(&identity, /*limit*/ 128).unwrap(),
        b"retained input"
    );
    assert!(file.read(&identity, /*limit*/ 2).is_err());
    let link = identity.home_root.join("pin-link.json");
    std::os::unix::fs::symlink(&file.path, &link).unwrap();
    assert!(
        FilePin {
            path: link,
            sha256: file.sha256.clone()
        }
        .read(&identity, /*limit*/ 128)
        .is_err()
    );
    std::fs::set_permissions(&file.path, std::fs::Permissions::from_mode(0o644)).unwrap();
    assert!(file.read(&identity, /*limit*/ 128).is_err());
    std::fs::set_permissions(&file.path, std::fs::Permissions::from_mode(0o600)).unwrap();
    std::fs::hard_link(&file.path, identity.home_root.join("pin-hard.json")).unwrap();
    assert!(file.read(&identity, /*limit*/ 128).is_err());
}

#[test]
fn real_linux_clock_refuses_boot_change_and_latches_feed_drift() {
    let (_root, identity) = fixture();
    let feed = pin(
        &identity,
        "feed.json",
        b"clock-only fixture; signature checked by owner bootstrap",
    );
    let clock = ProcessClock {
        identity,
        feed,
        boot_id: kernel_text("/proc/sys/kernel/random/boot_id")
            .unwrap()
            .trim()
            .into(),
        last_wall: Mutex::new(0),
        poisoned: AtomicBool::new(false),
    };
    let before = clock.observe().unwrap();
    let after = clock.observe().unwrap();
    assert_eq!(before.domain, after.domain);
    assert!(after.monotonic_micros >= before.monotonic_micros);
    let retained = std::fs::read(&clock.feed.path).unwrap();
    std::fs::write(&clock.feed.path, b"new feed").unwrap();
    assert!(clock.observe().is_err());
    std::fs::write(&clock.feed.path, retained).unwrap();
    assert!(clock.now_unix_ms().is_err());
    let wrong_boot = ProcessClock {
        boot_id: "00000000-0000-0000-0000-000000000000".into(),
        last_wall: Mutex::new(0),
        poisoned: AtomicBool::new(false),
        ..clock
    };
    assert!(wrong_boot.observe().is_err());
}
