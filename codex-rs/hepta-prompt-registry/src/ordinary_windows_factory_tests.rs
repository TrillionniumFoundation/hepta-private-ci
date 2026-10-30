//! Direct public-factory native regressions; no path or fixture grants authority.
//! Uses this crate's existing std assertion style without adding a dev dependency.

use crate::DurablePromptRegistry;
use crate::DurableRegistryError;
use codex_hepta_contracts::windows_private_owner::ParentAnchor;
use std::error::Error;
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

type Result<T = ()> = std::result::Result<T, Box<dyn Error>>;
static NEXT: AtomicU64 = AtomicU64::new(/*v*/ 0);

// Naming only: each positive test must obtain its owner from the public factory.
// No namespace is created here and no spelling, receipt or flag admits a store.
struct Fixture {
    parent: PathBuf,
    leaf: String,
}

impl Fixture {
    fn new() -> Result<Self> {
        let parent = PathBuf::from(format!(r"{}\", std::env::var("SystemDrive")?));
        let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
        let sequence = NEXT.fetch_add(/*val*/ 1, Ordering::Relaxed);
        let leaf = format!(
            "hepta-registry-owner-{}-{nonce}-{sequence}",
            std::process::id()
        );
        Ok(Self { parent, leaf })
    }

    fn root(&self) -> PathBuf {
        self.parent.join(&self.leaf)
    }

    fn path(&self, leaf: &str) -> PathBuf {
        self.root().join(leaf)
    }

    // Called only after the actual public store or native fresh-directory
    // producer succeeds. An unverified-created Err does not arm cleanup.
    fn cleanup_guard(&self) -> FixtureCleanup {
        FixtureCleanup { root: self.root() }
    }
}

struct FixtureCleanup {
    root: PathBuf,
}

impl Drop for FixtureCleanup {
    fn drop(&mut self) {
        for name in [
            "registry.json",
            "registry.next",
            "registry.payloads",
            "registry.lock",
        ] {
            let _ = fs::remove_file(self.root.join(name));
        }
        let _ = fs::remove_dir(&self.root);
    }
}

#[test]
fn native_registry_public_factory_creates_locks_and_cold_reopens_exact_state() -> Result {
    let fixture = Fixture::new()?;
    assert!(!fixture.root().try_exists()?);
    // Declare cleanup first so retained native owners close before it on unwind.
    let _cleanup;
    let owner =
        DurablePromptRegistry::open_state_dir(&fixture.root(), /*maximum_records*/ 64)?;
    _cleanup = fixture.cleanup_guard();
    let digest = owner.registry()?.snapshot_digest();
    let metadata = fs::read(fixture.path("registry.json"))?;
    let payloads = fs::read(fixture.path("registry.payloads"))?;
    let manifest: serde_json::Value = serde_json::from_slice(&metadata)?;
    assert!(matches!(manifest["schema"].as_u64(), Some(3)));
    assert!(matches!(
        DurablePromptRegistry::open_state_dir(&fixture.root(), /*maximum_records*/ 64),
        Err(DurableRegistryError::StateLocked)
    ));
    drop(owner);

    let reopened =
        DurablePromptRegistry::open_state_dir(&fixture.root(), /*maximum_records*/ 64)?;
    assert_eq!(
        (
            reopened.registry()?.snapshot_digest(),
            fs::read(fixture.path("registry.json"))?,
            fs::read(fixture.path("registry.payloads"))?,
        ),
        (digest, metadata, payloads)
    );
    drop(reopened);
    Ok(())
}

#[test]
fn native_registry_public_factory_refuses_bare_existing_directory_without_marker() -> Result {
    let fixture = Fixture::new()?;
    assert!(!fixture.root().try_exists()?);
    let _cleanup;
    let bare =
        ParentAnchor::for_create_only(&fixture.parent)?.create_private_directory(&fixture.leaf)?;
    _cleanup = fixture.cleanup_guard();
    drop(bare);

    assert!(matches!(
        DurablePromptRegistry::open_state_dir(&fixture.root(), /*maximum_records*/ 64),
        Err(DurableRegistryError::UnsafeStateDirectory)
    ));
    for name in [
        "registry.json",
        "registry.next",
        "registry.payloads",
        "registry.lock",
    ] {
        assert!(!fixture.path(name).try_exists()?);
    }
    Ok(())
}

#[test]
fn native_registry_public_factory_refuses_corrupt_manifest_without_rewriting_files() -> Result {
    let fixture = Fixture::new()?;
    assert!(!fixture.root().try_exists()?);
    let _cleanup;
    let owner =
        DurablePromptRegistry::open_state_dir(&fixture.root(), /*maximum_records*/ 64)?;
    _cleanup = fixture.cleanup_guard();
    drop(owner);
    let payloads = fs::read(fixture.path("registry.payloads"))?;
    let corrupt = br#"{"schema":3,"invalid":true}"#;
    fs::write(fixture.path("registry.json"), corrupt)?;

    assert!(matches!(
        DurablePromptRegistry::open_state_dir(&fixture.root(), /*maximum_records*/ 64),
        Err(DurableRegistryError::Corrupt)
    ));
    assert_eq!(
        (
            fs::read(fixture.path("registry.json"))?,
            fs::read(fixture.path("registry.payloads"))?,
        ),
        (corrupt.to_vec(), payloads)
    );
    assert!(!fixture.path("registry.next").try_exists()?);
    Ok(())
}
