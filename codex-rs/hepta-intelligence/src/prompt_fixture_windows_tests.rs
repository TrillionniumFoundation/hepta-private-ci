//! Native prompt fixtures use the existing private namespace capabilities.
//! The in-memory frontier below is test state, not production rollback trust.

use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::windows_private_owner::FreshPrivateDirectory;
use codex_hepta_contracts::windows_private_owner::ParentAnchor;
use codex_hepta_contracts::windows_private_owner::PrivateStoreDirectory;
use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

static NEXT: AtomicU64 = AtomicU64::new(0);

pub(crate) struct FixtureDirectory {
    path: PathBuf,
    directory: Option<FreshPrivateDirectory>,
}

impl FixtureDirectory {
    pub(crate) fn path(&self) -> &Path {
        &self.path
    }
}

impl Drop for FixtureDirectory {
    fn drop(&mut self) {
        // Original store owners must drop before this fixture, as with TempDir.
        // Release this final retained handle before removing our own namespace.
        drop(self.directory.take());
        let _ = fs::remove_dir_all(&self.path);
    }
}

pub(crate) fn fixture_directory() -> FixtureDirectory {
    // Do not assume the shared CI TEMP directory has a protected ancestry.
    // The existing capability still validates the real root and every ancestor.
    let parent = PathBuf::from(format!(
        r"{}\",
        std::env::var("SystemDrive").expect("SystemDrive for native prompt fixture")
    ));
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    let sequence = NEXT.fetch_add(/*val*/ 1, Ordering::Relaxed);
    let leaf = format!(
        "hepta-prompt-fixture-{}-{nonce}-{sequence}",
        std::process::id()
    );
    let directory = ParentAnchor::for_create_only(&parent)
        .expect("native prompt fixture root ancestry")
        .create_private_directory(&leaf)
        .expect("create fresh protected prompt fixture");
    FixtureDirectory {
        path: parent.join(leaf),
        directory: Some(directory),
    }
}

pub(super) fn fresh_directory(path: &Path) -> PrivateStoreDirectory {
    let parent = path.parent().expect("prompt owner parent");
    let leaf = path
        .file_name()
        .and_then(|name| name.to_str())
        .expect("literal prompt owner leaf");
    let directory = ParentAnchor::for_create_only(parent)
        .expect("native prompt owner ancestry")
        .create_private_directory(leaf)
        .expect("create fresh protected prompt owner");
    PrivateStoreDirectory::Fresh(directory)
}

pub(super) struct Frontier {
    pub(super) owner_id: String,
    pub(super) value: Mutex<FinalUseFrontier>,
}

impl AuthorityFrontierStore<FinalUseFrontier> for Frontier {
    fn load(&self, owner_id: &str) -> Result<FinalUseFrontier, AuthorityTrustError> {
        if owner_id != self.owner_id {
            return Err(AuthorityTrustError::Invalid);
        }
        self.value
            .lock()
            .map(|value| *value)
            .map_err(|_| AuthorityTrustError::Unavailable)
    }

    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &FinalUseFrontier,
        next: &FinalUseFrontier,
    ) -> Result<(), AuthorityTrustError> {
        if owner_id != self.owner_id {
            return Err(AuthorityTrustError::Invalid);
        }
        let mut held = self
            .value
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if &*held != expected {
            return Err(AuthorityTrustError::Conflict);
        }
        *held = *next;
        Ok(())
    }
}

#[test]
fn prompt_frontier_refuses_other_owner_and_stale_expected_state() {
    use codex_hepta_contracts::FinalUseRevocations;
    use pretty_assertions::assert_eq;
    use std::collections::BTreeSet;

    let initial = FinalUseFrontier::for_initial_head(&FinalUseRevocations {
        authority_epoch: 1,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    })
    .expect("initial frontier");
    let frontier = Frontier {
        owner_id: "prompt-fixture-owner".to_owned(),
        value: Mutex::new(initial),
    };
    let mut next = initial;
    next.state_sha256[0] ^= 1;
    assert_eq!(
        frontier.load("other-owner"),
        Err(AuthorityTrustError::Invalid)
    );
    assert_eq!(
        frontier.compare_and_set("other-owner", &initial, &next),
        Err(AuthorityTrustError::Invalid)
    );
    assert_eq!(frontier.load("prompt-fixture-owner"), Ok(initial));
    assert_eq!(
        frontier.compare_and_set("prompt-fixture-owner", &initial, &next),
        Ok(())
    );
    assert_eq!(
        frontier.compare_and_set("prompt-fixture-owner", &initial, &next),
        Err(AuthorityTrustError::Conflict)
    );
    assert_eq!(frontier.load("prompt-fixture-owner"), Ok(next));
}

#[test]
fn prompt_private_fixture_retains_registry_lock_and_cleans_owned_directory() {
    use codex_hepta_prompt_registry::DurablePromptRegistry;
    use codex_hepta_prompt_registry::DurableRegistryError;

    let fixture = fixture_directory();
    let path = fixture.path().to_owned();
    let owner = DurablePromptRegistry::open_windows_private(
        fresh_directory(&path.join("registry")),
        /*maximum_records*/ 64,
    )
    .expect("private registry owner");
    let candidate = ParentAnchor::for_create_only(&path)
        .expect("same protected fixture ancestry")
        .open_existing_candidate("registry")
        .expect("existing registry candidate");
    assert!(matches!(
        DurablePromptRegistry::open_windows_private(
            PrivateStoreDirectory::Existing(candidate),
            /*maximum_records*/ 64,
        ),
        Err(DurableRegistryError::StateLocked)
    ));
    drop(owner);
    drop(fixture);
    assert!(!path.exists());
}
