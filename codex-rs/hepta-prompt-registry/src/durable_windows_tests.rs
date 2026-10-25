//! Actual private namespace and existing V3 recovery, without path adoption.
use crate::DurablePromptRegistry;
use crate::DurableRegistryError;
use codex_hepta_contracts::windows_private_owner::ParentAnchor;
use codex_hepta_contracts::windows_private_owner::PrivateStoreDirectory;
use std::error::Error;
use std::fs;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

type Result<T = ()> = std::result::Result<T, Box<dyn Error>>;
static NEXT: AtomicU64 = AtomicU64::new(0);
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
            "hepta-registry-owner-{}-{nonce}-{sequence}",
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
            "registry.json",
            "registry.next",
            "registry.payloads",
            "registry.lock",
        ] {
            let _ = fs::remove_file(self.path(name));
        }
        let _ = fs::remove_dir(self.parent.join(&self.leaf));
    }
}

#[test]
fn native_registry_retains_os_lock_and_recovers_only_unselected_payload_tail() -> Result {
    let (fixture, input) = Fixture::new()?;
    let owner = DurablePromptRegistry::open_windows_private(input, 64)?;
    let digest = owner.registry()?.snapshot_digest();
    assert!(matches!(
        DurablePromptRegistry::open_windows_private(fixture.cold()?, 64),
        Err(DurableRegistryError::StateLocked)
    ));
    let metadata = fs::read(fixture.path("registry.json"))?;
    let committed = fs::read(fixture.path("registry.payloads"))?;
    drop(owner);
    let mut orphan = OpenOptions::new()
        .append(true)
        .open(fixture.path("registry.payloads"))?;
    orphan.write_all(b"unselected-tail")?;
    orphan.sync_all()?;
    drop(orphan);
    assert!(fs::metadata(fixture.path("registry.payloads"))?.len() > committed.len() as u64);
    let reopened = DurablePromptRegistry::open_windows_private(fixture.cold()?, 64)?;
    assert_eq!(reopened.registry()?.snapshot_digest(), digest);
    assert_eq!(fs::read(fixture.path("registry.payloads"))?, committed);
    assert_eq!(fs::read(fixture.path("registry.json"))?, metadata);
    Ok(())
}

#[test]
fn native_registry_corrupt_manifest_never_trims_or_rewrites_existing_state() -> Result {
    let (fixture, input) = Fixture::new()?;
    drop(DurablePromptRegistry::open_windows_private(input, 64)?);
    let payload = fs::read(fixture.path("registry.payloads"))?;
    let corrupt = b"{\"schema\":3,\"invalid\":true}";
    fs::write(fixture.path("registry.json"), corrupt)?;
    assert!(matches!(
        DurablePromptRegistry::open_windows_private(fixture.cold()?, 64),
        Err(DurableRegistryError::Corrupt)
    ));
    assert_eq!(fs::read(fixture.path("registry.json"))?, corrupt);
    assert_eq!(fs::read(fixture.path("registry.payloads"))?, payload);
    assert!(!fixture.path("registry.next").exists());
    Ok(())
}

#[test]
fn native_registry_existing_marker_with_missing_manifest_never_reinitializes() -> Result {
    let (fixture, input) = Fixture::new()?;
    drop(DurablePromptRegistry::open_windows_private(input, 64)?);
    let payload = fs::read(fixture.path("registry.payloads"))?;
    fs::remove_file(fixture.path("registry.json"))?;
    assert!(matches!(
        DurablePromptRegistry::open_windows_private(fixture.cold()?, 64),
        Err(DurableRegistryError::Corrupt)
    ));
    assert!(!fixture.path("registry.json").exists());
    assert_eq!(fs::read(fixture.path("registry.payloads"))?, payload);
    Ok(())
}
