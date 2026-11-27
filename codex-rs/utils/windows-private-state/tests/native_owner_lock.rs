#![cfg(windows)]

use codex_utils_windows_private_state::parent_anchor::FreshPrivateDirectory;
use codex_utils_windows_private_state::parent_anchor::OwnerLockError;
use codex_utils_windows_private_state::parent_anchor::OwnerLockOrigin;
use codex_utils_windows_private_state::parent_anchor::ParentAnchor;
use codex_utils_windows_private_state::primary_owner::CapturedPrimaryOwner;
use std::error::Error;
use std::fs;
use std::io;
use std::io::Read;
use std::io::Write;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::thread;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

type Result<T = ()> = std::result::Result<T, Box<dyn Error>>;
static NEXT_FIXTURE: AtomicU64 = AtomicU64::new(0);
const CHILD_MODE: &str = "HEPTA_NATIVE_OWNER_LOCK_MODE";
const CHILD_PARENT: &str = "HEPTA_NATIVE_OWNER_LOCK_PARENT";
const CHILD_LEAF: &str = "HEPTA_NATIVE_OWNER_LOCK_LEAF";

struct Fixture {
    parent: PathBuf,
    leaf: String,
}
impl Fixture {
    fn new() -> Result<(Self, FreshPrivateDirectory)> {
        let parent = PathBuf::from(format!(r"{}\", std::env::var("SystemDrive")?));
        let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
        let sequence = NEXT_FIXTURE.fetch_add(1, Ordering::Relaxed);
        let leaf = format!("hepta-owner-lock-{}-{nonce}-{sequence}", std::process::id());
        let directory = ParentAnchor::for_create_only(&parent)?.create_private_directory(&leaf)?;
        Ok((Self { parent, leaf }, directory))
    }
    fn child(&self, mode: &str) -> io::Result<Child> {
        Command::new(std::env::current_exe()?)
            .args([
                "--exact",
                "native_owner_lock_child",
                "--nocapture",
                "--test-threads=1",
            ])
            .env(CHILD_MODE, mode)
            .env(CHILD_PARENT, &self.parent)
            .env(CHILD_LEAF, &self.leaf)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_file(self.parent.join(&self.leaf).join("authority.lock"));
        let _ = fs::remove_dir(self.parent.join(&self.leaf));
    }
}
fn wait(child: &mut Child, deadline: Instant) -> Result {
    loop {
        if let Some(status) = child.try_wait()? {
            assert!(status.success(), "native lock child failed: {status}");
            return Ok(());
        }
        if Instant::now() >= deadline {
            return Err(io::Error::other("original eight-second child deadline").into());
        }
        thread::sleep(Duration::from_millis(10));
    }
}

#[test]
fn native_owner_lock_child() -> Result {
    let Ok(mode) = std::env::var(CHILD_MODE) else {
        CapturedPrimaryOwner::capture()?.revalidate()?;
        return Ok(());
    };
    let parent = PathBuf::from(std::env::var(CHILD_PARENT)?);
    let leaf = std::env::var(CHILD_LEAF)?;
    let mut candidate = ParentAnchor::for_create_only(&parent)?.open_existing_candidate(&leaf)?;
    match mode.as_str() {
        "contended" => {
            assert!(
                matches!(
                    candidate.lock_existing_owner("authority.lock"),
                    Err(OwnerLockError::StateLocked)
                ),
                "only real OS lock contention may report StateLocked"
            );
            println!("STATE_LOCKED_OBSERVED");
        }
        "exit-held" => {
            let mut owner = candidate.lock_existing_owner("authority.lock")?;
            assert_eq!(owner.origin(), &OwnerLockOrigin::Existing);
            owner.revalidate()?;
            println!("OWNER_LOCK_HELD");
            io::stdout().flush()?;
            let mut release = [0];
            io::stdin().read_exact(&mut release)?;
            assert_eq!(release, [b'X']);
            // Natural process exit with the real owner live: no Drop/unlock.
            std::process::exit(0);
        }
        other => return Err(io::Error::other(format!("unknown child mode {other}")).into()),
    }
    Ok(())
}

#[test]
fn actual_second_process_reports_state_locked_then_owner_drop_releases() -> Result {
    let deadline = Instant::now() + Duration::from_secs(8);
    let (fixture, mut directory) = Fixture::new()?;
    let owner = directory.lock_owner("authority.lock")?;
    assert_eq!(owner.origin(), &OwnerLockOrigin::Created);
    let mut child = fixture.child("contended")?;
    wait(&mut child, deadline)?;
    let mut output = Vec::new();
    child
        .stdout
        .take()
        .ok_or_else(|| io::Error::other("missing child stdout"))?
        .take(65_537)
        .read_to_end(&mut output)?;
    assert!(output.len() <= 65_536);
    let output = String::from_utf8(output)?;
    assert!(output.contains("STATE_LOCKED_OBSERVED"));
    assert!(output.contains("1 passed; 0 failed"));
    drop(owner);
    let mut candidate =
        ParentAnchor::for_create_only(&fixture.parent)?.open_existing_candidate(&fixture.leaf)?;
    let mut next = candidate.lock_existing_owner("authority.lock")?;
    assert_eq!(next.origin(), &OwnerLockOrigin::Existing);
    next.revalidate()?;
    assert_eq!(
        fs::metadata(fixture.parent.join(&fixture.leaf).join("authority.lock"))?.len(),
        0
    );
    Ok(())
}

#[test]
fn actual_natural_process_exit_releases_original_os_lock_without_destructor() -> Result {
    let deadline = Instant::now() + Duration::from_secs(8);
    let (fixture, mut directory) = Fixture::new()?;
    drop(directory.lock_owner("authority.lock")?);
    let mut child = fixture.child("exit-held")?;
    let mut stdout = child
        .stdout
        .take()
        .ok_or_else(|| io::Error::other("missing child stdout"))?;
    let (tx, rx) = mpsc::sync_channel(1);
    let reader = thread::spawn(move || -> io::Result<()> {
        let mut bytes = Vec::new();
        for _ in 0..65_536 {
            let mut byte = [0];
            stdout.read_exact(&mut byte)?;
            bytes.push(byte[0]);
            if bytes.ends_with(b"OWNER_LOCK_HELD\n") || bytes.ends_with(b"OWNER_LOCK_HELD\r\n") {
                return tx
                    .send(())
                    .map_err(|_| io::Error::other("readiness receiver closed"));
            }
        }
        Err(io::Error::other("bounded readiness output exhausted"))
    });
    rx.recv_timeout(deadline.saturating_duration_since(Instant::now()))?;
    let mut blocked =
        ParentAnchor::for_create_only(&fixture.parent)?.open_existing_candidate(&fixture.leaf)?;
    assert!(matches!(
        blocked.lock_existing_owner("authority.lock"),
        Err(OwnerLockError::StateLocked)
    ));
    child
        .stdin
        .take()
        .ok_or_else(|| io::Error::other("missing child stdin"))?
        .write_all(b"X")?;
    wait(&mut child, deadline)?;
    reader
        .join()
        .map_err(|_| io::Error::other("readiness reader panicked"))??;
    let mut candidate =
        ParentAnchor::for_create_only(&fixture.parent)?.open_existing_candidate(&fixture.leaf)?;
    candidate
        .lock_existing_owner("authority.lock")?
        .revalidate()?;
    Ok(())
}

#[test]
fn actual_cold_missing_marker_and_nonempty_marker_never_reset() -> Result {
    let (fixture, mut directory) = Fixture::new()?;
    let mut missing =
        ParentAnchor::for_create_only(&fixture.parent)?.open_existing_candidate(&fixture.leaf)?;
    assert!(matches!(
        missing.lock_existing_owner("authority.lock"),
        Err(OwnerLockError::Rejected(_))
    ));
    assert!(
        !fixture
            .parent
            .join(&fixture.leaf)
            .join("authority.lock")
            .exists()
    );
    drop(directory.lock_owner("authority.lock")?);
    let marker = fixture.parent.join(&fixture.leaf).join("authority.lock");
    fs::write(&marker, b"must-not-truncate")?;
    assert!(matches!(
        directory.lock_owner("authority.lock"),
        Err(OwnerLockError::Rejected(_))
    ));
    assert_eq!(fs::read(marker)?, b"must-not-truncate");
    Ok(())
}
