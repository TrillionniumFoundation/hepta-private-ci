use crate::path_normalization::canonical_path_key;
use crate::path_normalization::canonicalize_path;
use anyhow::Context;
use anyhow::Result;
use rand::RngCore;
use rand::SeedableRng;
use rand::rngs::SmallRng;
use serde::Deserialize;
use serde::Serialize;
use std::collections::HashMap;
use std::fs;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct CapSids {
    pub workspace: String,
    pub readonly: String,
    /// Per-workspace capability SIDs keyed by canonicalized CWD string.
    ///
    /// This is used to isolate workspaces from other workspace sandbox writes and to
    /// apply per-workspace denies (e.g. protect `CWD/.codex`)
    /// without permanently affecting other workspaces.
    #[serde(default)]
    pub workspace_by_cwd: HashMap<String, String>,
    /// Per-write-root capability SIDs keyed by canonicalized write-root path.
    ///
    /// These are included in a workspace-write token only when the root is
    /// currently allowed, so stale ACLs from earlier extra roots do not expand
    /// later workspace sandboxes.
    #[serde(default)]
    pub writable_root_by_path: HashMap<String, String>,
    /// Read-only root capabilities occupy a separate namespace from every
    /// historical write/temporary capability and enter only matching read plans.
    #[serde(default)]
    pub readable_root_by_path: HashMap<String, String>,
}

pub fn cap_sid_file(codex_home: &Path) -> PathBuf {
    codex_home.join("cap_sid")
}

fn make_random_cap_sid_string() -> String {
    let mut rng = SmallRng::from_entropy();
    let a = rng.next_u32();
    let b = rng.next_u32();
    let c = rng.next_u32();
    let d = rng.next_u32();
    format!("S-1-5-21-{a}-{b}-{c}-{d}")
}

// Every capability-map update uses a separate, stable lock file. Locking the
// data file itself would not protect atomic replacement and would allow an old
// handle to race with later writers.
fn lock_cap_sids(codex_home: &Path) -> Result<fs::File> {
    fs::create_dir_all(codex_home)
        .with_context(|| format!("create cap sid dir {}", codex_home.display()))?;
    let lock_path = codex_home.join("cap_sid.lock");
    let lock = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(&lock_path)
        .with_context(|| format!("open cap sid lock {}", lock_path.display()))?;
    lock.lock()
        .with_context(|| format!("lock cap sid map {}", lock_path.display()))?;
    Ok(lock)
}

fn persist_caps(path: &Path, caps: &CapSids) -> Result<()> {
    persist_caps_before_replace(path, caps, |_| Ok(()))
}

fn persist_caps_before_replace(
    path: &Path,
    caps: &CapSids,
    before_replace: impl FnOnce(&Path) -> Result<()>,
) -> Result<()> {
    let directory = path.parent().context("cap sid file has no parent")?;
    fs::create_dir_all(directory)
        .with_context(|| format!("create cap sid dir {}", directory.display()))?;
    let mut staged = tempfile::Builder::new()
        .prefix(".cap-sid-")
        .tempfile_in(directory)
        .with_context(|| format!("stage cap sid map in {}", directory.display()))?;
    serde_json::to_writer(staged.as_file_mut(), caps)?;
    staged.as_file_mut().flush()?;
    staged.as_file().sync_all()?;
    // The callback is private and production supplies a no-op. Native controls
    // interrupt a real child here, after staging is synced and before publish.
    before_replace(staged.path())?;
    staged
        .persist(path)
        .map_err(|error| error.error)
        .with_context(|| format!("replace cap sid file {}", path.display()))?;
    Ok(())
}

fn native_sid_identity(value: &str) -> Result<Vec<u8>> {
    let sid = crate::token::LocalSid::from_string(value)?;
    // ConvertStringSidToSidW accepts SDDL aliases as well as numeric strings.
    // Persisted namespace separation therefore compares actual native SIDs.
    let size = unsafe { windows_sys::Win32::Security::GetLengthSid(sid.as_ptr()) };
    anyhow::ensure!(
        (8..=68).contains(&size),
        "invalid native capability SID size"
    );
    let mut bytes = vec![0; size as usize];
    let copied = unsafe {
        windows_sys::Win32::Security::CopySid(size, bytes.as_mut_ptr().cast(), sid.as_ptr())
    };
    if copied == 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(bytes)
}

fn validate_caps(caps: &CapSids) -> Result<()> {
    let writes = std::iter::once(caps.workspace.as_str())
        .chain(std::iter::once(caps.readonly.as_str()))
        .chain(caps.workspace_by_cwd.values().map(String::as_str))
        .chain(caps.writable_root_by_path.values().map(String::as_str))
        .map(native_sid_identity)
        .collect::<Result<std::collections::HashSet<_>>>()
        .context("invalid persisted write capability SID")?;
    let mut reads = std::collections::HashSet::new();
    for sid in caps.readable_root_by_path.values() {
        let identity = native_sid_identity(sid).context("invalid persisted read capability SID")?;
        anyhow::ensure!(
            !writes.contains(&identity) && reads.insert(identity),
            "persisted read capability aliases another capability namespace"
        );
    }
    Ok(())
}

pub fn load_or_create_cap_sids(codex_home: &Path) -> Result<CapSids> {
    let _lock = lock_cap_sids(codex_home)?;
    load_or_create_cap_sids_locked(codex_home)
}

fn load_or_create_cap_sids_locked(codex_home: &Path) -> Result<CapSids> {
    let path = cap_sid_file(codex_home);
    match fs::read_to_string(&path) {
        Ok(text) => {
            let trimmed = text.trim();
            if trimmed.starts_with('{') {
                let caps = serde_json::from_str::<CapSids>(trimmed)
                    .with_context(|| format!("invalid cap sid map {}", path.display()))?;
                validate_caps(&caps)?;
                return Ok(caps);
            }
            // A legacy single-SID file is migrated only after native SID
            // validation. Empty, partial or malformed maps never mint new IDs.
            crate::token::LocalSid::from_string(trimmed)
                .with_context(|| format!("invalid legacy cap sid file {}", path.display()))?;
            let caps = CapSids {
                workspace: trimmed.to_owned(),
                readonly: make_random_cap_sid_string(),
                workspace_by_cwd: HashMap::new(),
                writable_root_by_path: HashMap::new(),
                readable_root_by_path: HashMap::new(),
            };
            persist_caps(&path, &caps)?;
            return Ok(caps);
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => {
            return Err(error).with_context(|| format!("read cap sid file {}", path.display()));
        }
    }
    let caps = CapSids {
        workspace: make_random_cap_sid_string(),
        readonly: make_random_cap_sid_string(),
        workspace_by_cwd: HashMap::new(),
        writable_root_by_path: HashMap::new(),
        readable_root_by_path: HashMap::new(),
    };
    persist_caps(&path, &caps)?;
    Ok(caps)
}

/// Returns the workspace-specific capability SID for `cwd`, creating and persisting it if missing.
pub fn workspace_cap_sid_for_cwd(codex_home: &Path, cwd: &Path) -> Result<String> {
    let path = cap_sid_file(codex_home);
    let _lock = lock_cap_sids(codex_home)?;
    let mut caps = load_or_create_cap_sids_locked(codex_home)?;
    let key = canonical_path_key(cwd);
    if let Some(sid) = caps.workspace_by_cwd.get(&key) {
        return Ok(sid.clone());
    }
    let sid = make_random_cap_sid_string();
    caps.workspace_by_cwd.insert(key, sid.clone());
    persist_caps(&path, &caps)?;
    Ok(sid)
}

/// Returns the capability SID for an additional writable root, creating and persisting it if missing.
pub fn writable_root_cap_sid_for_path(codex_home: &Path, root: &Path) -> Result<String> {
    let path = cap_sid_file(codex_home);
    let _lock = lock_cap_sids(codex_home)?;
    let mut caps = load_or_create_cap_sids_locked(codex_home)?;
    let key = canonical_path_key(root);
    if let Some(sid) = caps.writable_root_by_path.get(&key) {
        return Ok(sid.clone());
    }
    let sid = make_random_cap_sid_string();
    caps.writable_root_by_path.insert(key, sid.clone());
    persist_caps(&path, &caps)?;
    Ok(sid)
}

/// Reuses only the dedicated read capability for this exact normalized root.
/// Existing legacy `readonly` capabilities may have temporary write grants and
/// must never enter this namespace.
pub(crate) fn readable_root_cap_sid_for_path(codex_home: &Path, root: &Path) -> Result<String> {
    let path = cap_sid_file(codex_home);
    let _lock = lock_cap_sids(codex_home)?;
    let mut caps = load_or_create_cap_sids_locked(codex_home)?;
    let key = canonical_path_key(root);
    if let Some(sid) = caps.readable_root_by_path.get(&key) {
        return Ok(sid.clone());
    }
    let mut rng = rand::rngs::OsRng;
    let a = rng.next_u32();
    let b = rng.next_u32();
    let c = rng.next_u32();
    let d = rng.next_u32();
    let sid = format!("S-1-5-21-{a}-{b}-{c}-{d}");
    caps.readable_root_by_path.insert(key, sid.clone());
    persist_caps(&path, &caps)?;
    Ok(sid)
}

pub fn workspace_write_cap_sid_for_root(
    codex_home: &Path,
    cwd: &Path,
    root: &Path,
) -> Result<String> {
    if canonical_path_key(root) == canonical_path_key(cwd) {
        workspace_cap_sid_for_cwd(codex_home, cwd)
    } else {
        writable_root_cap_sid_for_path(codex_home, root)
    }
}

pub fn workspace_write_root_contains_path(root: &Path, path: &Path) -> bool {
    canonicalize_path(path).starts_with(canonicalize_path(root))
}

pub fn workspace_write_root_overlaps_path(root: &Path, path: &Path) -> bool {
    workspace_write_root_contains_path(root, path) || workspace_write_root_contains_path(path, root)
}

pub fn workspace_write_root_specificity(root: &Path) -> usize {
    canonicalize_path(root).components().count()
}

#[cfg(test)]
mod tests {
    use super::load_or_create_cap_sids;
    use super::readable_root_cap_sid_for_path;
    use super::workspace_cap_sid_for_cwd;
    use super::workspace_write_cap_sid_for_root;
    use super::writable_root_cap_sid_for_path;
    use pretty_assertions::assert_eq;
    use std::path::PathBuf;

    #[test]
    fn equivalent_cwd_spellings_share_workspace_sid_key() {
        let temp = tempfile::tempdir().expect("tempdir");
        let codex_home = temp.path().join("codex-home");
        std::fs::create_dir_all(&codex_home).expect("create codex home");

        let workspace = temp.path().join("WorkspaceRoot");
        std::fs::create_dir_all(&workspace).expect("create workspace root");

        let canonical = dunce::canonicalize(&workspace).expect("canonical workspace root");
        let alt_spelling = PathBuf::from(
            canonical
                .to_string_lossy()
                .replace('\\', "/")
                .to_ascii_uppercase(),
        );

        let first_sid =
            workspace_cap_sid_for_cwd(&codex_home, canonical.as_path()).expect("first sid");
        let second_sid =
            workspace_cap_sid_for_cwd(&codex_home, alt_spelling.as_path()).expect("second sid");

        assert_eq!(first_sid, second_sid);

        let caps = load_or_create_cap_sids(&codex_home).expect("load caps");
        assert_eq!(caps.workspace_by_cwd.len(), 1);
    }

    #[test]
    fn write_roots_get_path_scoped_sids() {
        let temp = tempfile::tempdir().expect("tempdir");
        let codex_home = temp.path().join("codex-home");
        std::fs::create_dir_all(&codex_home).expect("create codex home");

        let workspace = temp.path().join("workspace");
        let extra_root = temp.path().join("extra-root");
        std::fs::create_dir_all(&workspace).expect("create workspace");
        std::fs::create_dir_all(&extra_root).expect("create extra root");

        let workspace_sid = workspace_write_cap_sid_for_root(&codex_home, &workspace, &workspace)
            .expect("workspace sid");
        let extra_sid = workspace_write_cap_sid_for_root(&codex_home, &workspace, &extra_root)
            .expect("extra root sid");

        assert_ne!(workspace_sid, extra_sid);
        assert_eq!(
            extra_sid,
            writable_root_cap_sid_for_path(&codex_home, &extra_root).expect("extra root sid again")
        );

        let caps = load_or_create_cap_sids(&codex_home).expect("load caps");
        assert_eq!(caps.workspace_by_cwd.len(), 1);
        assert_eq!(caps.writable_root_by_path.len(), 1);
    }
    #[test]
    fn persisted_read_root_sids_cannot_reuse_legacy_write_capabilities() {
        let temp = tempfile::tempdir().expect("capability fixture");
        let home = temp.path().join("home");
        let first = temp.path().join("first");
        let second = temp.path().join("second");
        std::fs::create_dir_all(&first).expect("first root");
        std::fs::create_dir_all(&second).expect("second root");
        let legacy = load_or_create_cap_sids(&home).expect("legacy identities");
        let write =
            workspace_write_cap_sid_for_root(&home, &first, &first).expect("write identity");
        let read_first =
            readable_root_cap_sid_for_path(&home, &first).expect("first read identity");
        let read_second =
            readable_root_cap_sid_for_path(&home, &second).expect("second read identity");
        assert_eq!(
            read_first,
            readable_root_cap_sid_for_path(&home, &first).expect("persisted first read identity"),
        );
        assert_ne!(read_first, read_second);
        for read in [&read_first, &read_second] {
            for write in [&write, &legacy.workspace, &legacy.readonly] {
                assert_ne!(read, write);
            }
        }
        let stored = load_or_create_cap_sids(&home).expect("reopen identities");
        assert_eq!(stored.readable_root_by_path.len(), 2);
    }

    #[test]
    fn concurrent_read_and_write_root_registration_preserves_every_mapping() {
        let temp = tempfile::tempdir().expect("capability fixture");
        let home = temp.path().join("home");
        let shared = temp.path().join("shared");
        std::fs::create_dir_all(&shared).expect("shared root");
        let start = std::sync::Arc::new(std::sync::Barrier::new(8));
        let results = std::thread::scope(|scope| {
            let workers = (0..8)
                .map(|index| {
                    let start = std::sync::Arc::clone(&start);
                    let home = &home;
                    let shared = &shared;
                    let root = temp.path().join(format!("root-{index}"));
                    std::fs::create_dir_all(&root).expect("worker root");
                    scope.spawn(move || {
                        start.wait();
                        let read = readable_root_cap_sid_for_path(home, &root)
                            .expect("concurrent read root");
                        let write = writable_root_cap_sid_for_path(home, &root)
                            .expect("concurrent write root");
                        let shared_read =
                            readable_root_cap_sid_for_path(home, shared).expect("shared read root");
                        (root, read, write, shared_read)
                    })
                })
                .collect::<Vec<_>>();
            workers
                .into_iter()
                .map(|worker| worker.join().expect("worker"))
                .collect::<Vec<_>>()
        });
        let reopened = load_or_create_cap_sids(&home).expect("reopen concurrent map");
        assert_eq!(reopened.readable_root_by_path.len(), 9);
        assert_eq!(reopened.writable_root_by_path.len(), 8);
        for (root, read, write, shared_read) in &results {
            assert_eq!(
                &readable_root_cap_sid_for_path(&home, root).expect("read identity"),
                read
            );
            assert_eq!(
                &writable_root_cap_sid_for_path(&home, root).expect("write identity"),
                write
            );
            assert_eq!(shared_read, &results[0].3);
            assert_ne!(read, write);
        }
    }

    #[test]
    fn corrupt_capability_maps_are_refused_without_rewriting_evidence() -> anyhow::Result<()> {
        for corrupt in [
            b"".as_slice(),
            b"{".as_slice(),
            br#"{"workspace":"unfinished"#.as_slice(),
            br#"{"workspace":0}"#.as_slice(),
            b"not a SID".as_slice(),
        ] {
            let temp = tempfile::tempdir()?;
            let path = super::cap_sid_file(temp.path());
            load_or_create_cap_sids(temp.path())?;
            std::fs::write(&path, corrupt)?;
            assert!(load_or_create_cap_sids(temp.path()).is_err());
            assert_eq!(std::fs::read(&path)?, corrupt);
        }
        Ok(())
    }

    #[test]
    fn persisted_read_capability_alias_is_refused_without_rewriting() -> anyhow::Result<()> {
        let temp = tempfile::tempdir()?;
        let path = super::cap_sid_file(temp.path());
        let mut caps = load_or_create_cap_sids(temp.path())?;
        caps.readable_root_by_path
            .insert("read-root".to_owned(), caps.workspace.clone());
        let corrupt = serde_json::to_vec(&caps)?;
        std::fs::write(&path, &corrupt)?;
        assert!(load_or_create_cap_sids(temp.path()).is_err());
        assert_eq!(std::fs::read(&path)?, corrupt);
        Ok(())
    }

    #[test]
    fn native_sid_aliases_are_refused_across_capability_namespaces() -> anyhow::Result<()> {
        let numeric = "S-1-5-32-544";
        let alias = "BA";
        let numeric_sid = crate::token::LocalSid::from_string(numeric)?;
        let alias_sid = crate::token::LocalSid::from_string(alias)?;
        assert_ne!(
            unsafe {
                windows_sys::Win32::Security::EqualSid(numeric_sid.as_ptr(), alias_sid.as_ptr())
            },
            0,
            "the regression must use equal native SIDs with different strings"
        );
        for cross_write_namespace in [true, false] {
            let temp = tempfile::tempdir()?;
            let path = super::cap_sid_file(temp.path());
            let mut caps = load_or_create_cap_sids(temp.path())?;
            if cross_write_namespace {
                caps.workspace = numeric.to_owned();
            } else {
                caps.readable_root_by_path
                    .insert("first-read-root".to_owned(), numeric.to_owned());
            }
            caps.readable_root_by_path
                .insert("aliased-read-root".to_owned(), alias.to_owned());
            let corrupt = serde_json::to_vec(&caps)?;
            std::fs::write(&path, &corrupt)?;
            assert!(load_or_create_cap_sids(temp.path()).is_err());
            assert_eq!(std::fs::read(&path)?, corrupt);
        }
        Ok(())
    }

    #[test]
    fn interrupted_capability_publication_keeps_prior_map_and_releases_lock() -> anyhow::Result<()>
    {
        const CHILD_ROOT: &str = "HEPTA_CAP_MAP_INTERRUPTION_CHILD_ROOT";
        if let Some(root) = std::env::var_os(CHILD_ROOT) {
            let root = PathBuf::from(root);
            let _lock = super::lock_cap_sids(&root)?;
            let mut caps = super::load_or_create_cap_sids_locked(&root)?;
            caps.readable_root_by_path.insert(
                "uncommitted-read-root".to_owned(),
                super::make_random_cap_sid_string(),
            );
            return super::persist_caps_before_replace(
                &super::cap_sid_file(&root),
                &caps,
                |staged| {
                    let mut ready = tempfile::Builder::new()
                        .prefix(".cap-ready-")
                        .tempfile_in(&root)?;
                    std::io::Write::write_all(
                        ready.as_file_mut(),
                        staged.to_string_lossy().as_bytes(),
                    )?;
                    ready.as_file().sync_all()?;
                    ready.persist(root.join("stage-synced"))?;
                    loop {
                        std::thread::park();
                    }
                },
            );
        }
        struct Child(std::process::Child);
        impl Drop for Child {
            fn drop(&mut self) {
                let _ = self.0.kill();
                let _ = self.0.wait();
            }
        }
        let temp = tempfile::tempdir()?;
        let original = load_or_create_cap_sids(temp.path())?;
        let path = super::cap_sid_file(temp.path());
        let prior_bytes = std::fs::read(&path)?;
        let module = module_path!()
            .split_once("::")
            .map_or(module_path!(), |(_, module)| module);
        let name = format!(
            "{module}::interrupted_capability_publication_keeps_prior_map_and_releases_lock"
        );
        let mut child = Child(
            std::process::Command::new(std::env::current_exe()?)
                .args(["--exact", &name, "--nocapture"])
                .env(CHILD_ROOT, temp.path())
                .stdin(std::process::Stdio::null())
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .spawn()?,
        );
        let marker = temp.path().join("stage-synced");
        let started = std::time::Instant::now();
        while !marker.exists() {
            anyhow::ensure!(
                child.0.try_wait()?.is_none(),
                "publication child exited before synced staging"
            );
            anyhow::ensure!(
                started.elapsed() < std::time::Duration::from_secs(30),
                "publication child did not reach synced staging"
            );
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        let staged = PathBuf::from(std::fs::read_to_string(&marker)?);
        assert!(staged.is_file());
        child.0.kill()?;
        assert!(!child.0.wait()?.success());
        assert_eq!(std::fs::read(&path)?, prior_bytes);
        let reopened = load_or_create_cap_sids(temp.path())?;
        assert_eq!(reopened.workspace, original.workspace);
        assert!(reopened.readable_root_by_path.is_empty());
        // A new write acquires the original stable OS lock after the real child
        // is terminated, and replaces the map despite the abandoned stage.
        readable_root_cap_sid_for_path(temp.path(), temp.path())?;
        assert_eq!(
            load_or_create_cap_sids(temp.path())?
                .readable_root_by_path
                .len(),
            1
        );
        Ok(())
    }
}
