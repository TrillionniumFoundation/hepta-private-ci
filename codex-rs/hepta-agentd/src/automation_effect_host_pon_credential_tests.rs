//! Synthetic credentials exercise byte handoff and the original child owner.
use super::*;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::process::Command;
use std::time::Duration;

fn fixture() -> anyhow::Result<(tempfile::TempDir, CredentialPin, Vec<u8>)> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let source = root.join("client-secret");
    let bytes = "2a".repeat(32).into_bytes();
    fs::write(&source, &bytes)?;
    fs::set_permissions(&source, fs::Permissions::from_mode(0o600))?;
    let snapshot_root = root.join("snapshots");
    fs::create_dir(&snapshot_root)?;
    fs::set_permissions(&snapshot_root, fs::Permissions::from_mode(0o700))?;
    let pin = CredentialPin {
        source,
        sha256: Sha256Digest::for_bytes(&bytes),
        public_key: ed25519_dalek::SigningKey::from_bytes(&[42; 32])
            .verifying_key()
            .to_bytes(),
        snapshot_root,
    };
    Ok((directory, pin, bytes))
}

#[test]
fn credential_snapshot_pins_fd_bytes_across_source_replacement() -> anyhow::Result<()> {
    let (_directory, pin, expected) = fixture()?;
    let snapshot = pin.prepare(Instant::now() + Duration::from_secs(2))?;
    let path = snapshot.path().to_owned();
    assert_eq!(fs::metadata(&path)?.mode() & 0o777, 0o600);
    assert_eq!(fs::metadata(path.parent().unwrap())?.mode() & 0o777, 0o700);
    let replacement = pin.source.with_extension("replacement");
    fs::write(&replacement, "55".repeat(32))?;
    fs::set_permissions(&replacement, fs::Permissions::from_mode(0o600))?;
    fs::rename(replacement, &pin.source)?;
    assert_eq!(fs::read(&path)?, expected);
    assert!(
        pin.prepare(Instant::now() + Duration::from_secs(2))
            .is_err()
    );
    drop(snapshot);
    assert!(!path.exists());
    assert_eq!(fs::read_dir(&pin.snapshot_root)?.count(), 0);
    Ok(())
}

#[test]
fn credential_refuses_wrong_key_digest_permissions_aliases_and_expired_deadline()
-> anyhow::Result<()> {
    let (_directory, pin, _) = fixture()?;
    let deadline = Instant::now() + Duration::from_secs(2);
    let mut changed = pin.clone();
    changed.public_key = [0; 32];
    assert!(changed.prepare(deadline).is_err());
    changed = pin.clone();
    changed.sha256 = Sha256Digest::for_bytes(b"different");
    assert!(changed.prepare(deadline).is_err());
    assert!(pin.prepare(Instant::now()).is_err());
    fs::set_permissions(&pin.source, fs::Permissions::from_mode(0o640))?;
    assert!(pin.prepare(deadline).is_err());
    fs::set_permissions(&pin.source, fs::Permissions::from_mode(0o600))?;
    let alias = pin.source.with_extension("alias");
    std::os::unix::fs::symlink(&pin.source, &alias)?;
    changed = pin.clone();
    changed.source = alias.clone();
    assert!(changed.prepare(deadline).is_err());
    fs::remove_file(alias)?;
    fs::hard_link(&pin.source, pin.source.with_extension("hardlink"))?;
    assert!(pin.prepare(deadline).is_err());
    assert_eq!(fs::read_dir(&pin.snapshot_root)?.count(), 0);
    Ok(())
}

#[tokio::test]
async fn credential_owner_cleans_only_after_actual_child_reap() -> anyhow::Result<()> {
    let (_directory, pin, expected) = fixture()?;
    let snapshot = pin.prepare(Instant::now() + Duration::from_secs(2))?;
    let mut command = Command::new("/bin/cat");
    command.arg(snapshot.path());
    let outcome = super::super::run_with_credential(
        command,
        b"",
        Instant::now() + Duration::from_secs(2),
        /*output_limit*/ 128,
        snapshot,
    )
    .await;
    match outcome {
        super::super::Outcome::Complete(bytes) => assert_eq!(bytes, expected),
        _ => panic!("synthetic credential child did not complete"),
    }
    assert_eq!(fs::read_dir(&pin.snapshot_root)?.count(), 0);
    for program in ["/bin/false", "/bin/sleep"] {
        let snapshot = pin.prepare(Instant::now() + Duration::from_secs(2))?;
        let mut command = Command::new(program);
        if program == "/bin/sleep" {
            command.arg("5");
        }
        let outcome = super::super::run_with_credential(
            command,
            b"",
            Instant::now() + Duration::from_millis(100),
            /*output_limit*/ 128,
            snapshot,
        )
        .await;
        assert!(matches!(outcome, super::super::Outcome::Unknown));
        assert_eq!(fs::read_dir(&pin.snapshot_root)?.count(), 0);
    }
    // This is the exceptional unobserved-reap guard state, not a simulated
    // successful reap. Retaining the private path cannot acknowledge or retry.
    let mut retained = pin.prepare(Instant::now() + Duration::from_secs(2))?;
    let path = retained.path().to_owned();
    retained.child_started();
    drop(retained);
    assert!(path.is_file());
    Ok(())
}

#[tokio::test]
async fn credential_expired_owner_does_not_start_a_child_and_removes_snapshot() -> anyhow::Result<()>
{
    let (_directory, pin, _) = fixture()?;
    let snapshot = pin.prepare(Instant::now() + Duration::from_secs(2))?;
    let outcome = super::super::run_with_credential(
        Command::new("/bin/false"),
        b"",
        Instant::now(),
        /*output_limit*/ 128,
        snapshot,
    )
    .await;
    assert!(matches!(outcome, super::super::Outcome::BeforeStart));
    assert_eq!(fs::read_dir(&pin.snapshot_root)?.count(), 0);
    Ok(())
}
