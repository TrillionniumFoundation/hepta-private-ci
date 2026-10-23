use crate::capability_plan::FilesystemCapabilityPlan;
pub use crate::capability_registry::CapSids;
use crate::capability_registry::MAX_REGISTERED_ROOTS;
use crate::capability_registry::REGISTRY_VERSION;
use crate::path_normalization::canonical_path_key;
use crate::path_normalization::canonicalize_path;
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use rand::RngCore;
use rand::SeedableRng;
use rand::rngs::SmallRng;
use std::collections::HashMap;
use std::fs;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::os::windows::fs::MetadataExt;
use std::os::windows::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;

const MAX_REGISTRY_BYTES: u64 = 4 * 1024 * 1024;

pub fn cap_sid_file(codex_home: &Path) -> PathBuf {
    codex_home.join("cap_sid.v2.json")
}

fn make_random_cap_sid_string() -> String {
    let mut rng = SmallRng::from_entropy();
    let [a, b, c, d] = [
        rng.next_u32(),
        rng.next_u32(),
        rng.next_u32(),
        rng.next_u32(),
    ];
    format!("S-1-5-21-{a}-{b}-{c}-{d}")
}

fn require_absent(path: &Path) -> Result<()> {
    match fs::symlink_metadata(path) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error.into()),
        Ok(_) => anyhow::bail!(
            "occupied registry namespace {}; refusing adoption or cleanup",
            path.display()
        ),
    }
}

fn require_plain_file(path: &Path) -> Result<()> {
    let metadata = fs::symlink_metadata(path)?;
    ensure!(
        metadata.is_file() && metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT == 0,
        "registry object is not a plain file"
    );
    Ok(())
}

fn read_bytes(file: &mut fs::File) -> Result<Vec<u8>> {
    let mut bytes = Vec::new();
    Read::by_ref(file)
        .take(MAX_REGISTRY_BYTES + 1)
        .read_to_end(&mut bytes)?;
    ensure!(
        bytes.len() as u64 <= MAX_REGISTRY_BYTES,
        "capability registry byte capacity exceeded"
    );
    Ok(bytes)
}

fn read_caps(path: &Path, checkpoint: &mut fs::File) -> Result<CapSids> {
    require_plain_file(path)?;
    let mut file = fs::OpenOptions::new()
        .read(true)
        .share_mode(FILE_SHARE_READ)
        .open(path)?;
    let bytes = read_bytes(&mut file)?;
    checkpoint.seek(SeekFrom::Start(0))?;
    ensure!(
        bytes == read_bytes(checkpoint)?,
        "registry differs from its original checkpoint; refusing rollback or reset"
    );
    let caps: CapSids =
        serde_json::from_slice(&bytes).context("invalid capability registry; refusing reset")?;
    caps.validate()?;
    Ok(caps)
}

/// Rejects every old namespace object; never migrates or deletes prior state.
pub fn require_fresh_filesystem_namespace(codex_home: &Path) -> Result<()> {
    for relative in [
        "cap_sid",
        ".sandbox/setup_marker.json",
        ".sandbox/sandbox_users.json",
        ".sandbox-secrets/sandbox_users.json",
    ] {
        require_absent(&codex_home.join(relative))
            .context("legacy setup requires a fresh namespace; refusing migration or reset")?;
    }
    Ok(())
}

fn with_registry<T>(
    codex_home: &Path,
    change: impl FnOnce(&mut CapSids) -> Result<T>,
) -> Result<T> {
    require_fresh_filesystem_namespace(codex_home)?;
    fs::create_dir_all(codex_home)?;
    let path = cap_sid_file(codex_home);
    let stage_path = codex_home.join("cap_sid.v2.stage");
    require_absent(&stage_path).context("uncertain registry stage; refusing automatic recovery")?;
    let lock_path = codex_home.join("cap_sid.v2.lock");
    let (mut lock, fresh) = match fs::OpenOptions::new()
        .read(true)
        .write(true)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE)
        .create_new(true)
        .open(&lock_path)
    {
        Ok(lock) => (lock, true),
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            require_plain_file(&lock_path)?;
            (
                fs::OpenOptions::new()
                    .read(true)
                    .write(true)
                    .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE)
                    .open(&lock_path)?,
                false,
            )
        }
        Err(error) => return Err(error.into()),
    };
    lock.try_lock()
        .context("capability registry is busy or uncertain")?;
    require_absent(&stage_path)?;
    let mut caps = if fresh {
        require_absent(&path)
            .context("registry without its original checkpoint; refusing adoption")?;
        let mut rng = SmallRng::from_entropy();
        let generation = format!("{:016x}{:016x}", rng.next_u64(), rng.next_u64());
        CapSids {
            version: REGISTRY_VERSION,
            generation,
            workspace: make_random_cap_sid_string(),
            readonly: make_random_cap_sid_string(),
            workspace_by_cwd: HashMap::new(),
            writable_root_by_path: HashMap::new(),
        }
    } else {
        read_caps(&path, &mut lock)
            .context("missing, stale or invalid original registry; refusing history reset")?
    };
    let original = caps.clone();
    let result = change(&mut caps)?;
    caps.validate()?;
    if fresh || caps != original {
        let bytes = serde_json::to_vec(&caps)?;
        ensure!(
            bytes.len() as u64 <= MAX_REGISTRY_BYTES,
            "capability registry byte capacity exceeded"
        );
        let mut stage = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&stage_path)?;
        stage.write_all(&bytes)?;
        stage.sync_all()?;
        drop(stage);
        // One bounded byte vector binds both files. Any interrupted update or
        // leftover fixed stage refuses all later use; no rollback/cleanup guess.
        lock.seek(SeekFrom::Start(0))?;
        lock.set_len(0)?;
        lock.write_all(&bytes)?;
        lock.sync_all()?;
        fs::rename(&stage_path, &path)?;
    }
    Ok(result)
}

pub fn load_or_create_cap_sids(codex_home: &Path) -> Result<CapSids> {
    with_registry(codex_home, |caps| Ok(caps.clone()))
}

#[derive(Clone, Copy)]
enum RootRole {
    Workspace,
    Additional,
}

fn register_root(caps: &mut CapSids, key: String, role: RootRole) -> Result<String> {
    let existing = if matches!(role, RootRole::Workspace) {
        caps.workspace_by_cwd.get(&key)
    } else {
        caps.writable_root_by_path.get(&key)
    };
    if let Some(sid) = existing {
        return Ok(sid.clone());
    }
    ensure!(
        caps.workspace_by_cwd
            .len()
            .saturating_add(caps.writable_root_by_path.len())
            < MAX_REGISTERED_ROOTS,
        "capability registry full; refusing live identity eviction"
    );
    let sid = make_random_cap_sid_string();
    if matches!(role, RootRole::Workspace) {
        caps.workspace_by_cwd.insert(key, sid.clone());
    } else {
        caps.writable_root_by_path.insert(key, sid.clone());
    }
    Ok(sid)
}

pub fn workspace_cap_sid_for_cwd(codex_home: &Path, cwd: &Path) -> Result<String> {
    with_registry(codex_home, |caps| {
        register_root(caps, canonical_path_key(cwd), RootRole::Workspace)
    })
}

pub fn writable_root_cap_sid_for_path(codex_home: &Path, root: &Path) -> Result<String> {
    with_registry(codex_home, |caps| {
        register_root(caps, canonical_path_key(root), RootRole::Additional)
    })
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

/// Declares bounded roles from actual registry identities; this is not ACL readiness.
pub fn filesystem_capability_plan(
    codex_home: &Path,
    cwd: &Path,
    read: &[PathBuf],
    write: &[PathBuf],
) -> Result<FilesystemCapabilityPlan> {
    let cwd = canonical_path_key(cwd);
    with_registry(codex_home, |caps| {
        let read: Vec<_> = read
            .iter()
            .map(|root| canonical_path_key(root))
            .collect::<std::collections::BTreeSet<_>>()
            .into_iter()
            .collect();
        let write: Vec<_> = write
            .iter()
            .map(|root| canonical_path_key(root))
            .collect::<std::collections::BTreeSet<_>>()
            .into_iter()
            .collect();
        for root in &write {
            register_root(
                caps,
                root.clone(),
                if root == &cwd {
                    RootRole::Workspace
                } else {
                    RootRole::Additional
                },
            )?;
        }
        FilesystemCapabilityPlan::declare(caps, cwd, read, write)
    })
}

/// Read-only validation cannot create a registry or a prepared ACL context.
pub fn validate_filesystem_capability_plan(
    codex_home: &Path,
    plan: &FilesystemCapabilityPlan,
) -> Result<()> {
    require_fresh_filesystem_namespace(codex_home)?;
    require_absent(&codex_home.join("cap_sid.v2.stage"))?;
    let checkpoint_path = codex_home.join("cap_sid.v2.lock");
    require_plain_file(&checkpoint_path)?;
    let mut checkpoint = fs::OpenOptions::new()
        .read(true)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE)
        .open(checkpoint_path)?;
    checkpoint
        .try_lock_shared()
        .context("capability registry is busy or uncertain")?;
    require_absent(&codex_home.join("cap_sid.v2.stage"))?;
    let caps = read_caps(&cap_sid_file(codex_home), &mut checkpoint)?;
    plan.validate_registry(&caps)
}

/// Checks the complete declared root set against the actual setup request.
pub fn validate_filesystem_capability_plan_roots(
    codex_home: &Path,
    cwd: &Path,
    read: &[PathBuf],
    write: &[PathBuf],
    plan: &FilesystemCapabilityPlan,
) -> Result<()> {
    validate_filesystem_capability_plan(codex_home, plan)?;
    let keys = |roots: &[PathBuf]| {
        roots
            .iter()
            .map(|root| canonical_path_key(root))
            .collect::<std::collections::BTreeSet<_>>()
            .into_iter()
            .collect::<Vec<_>>()
    };
    ensure!(
        plan.matches_roots(&canonical_path_key(cwd), &keys(read), &keys(write)),
        "filesystem role roots differ from setup request"
    );
    Ok(())
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
}

#[cfg(test)]
#[path = "cap_registry_tests.rs"]
mod registry_tests;
