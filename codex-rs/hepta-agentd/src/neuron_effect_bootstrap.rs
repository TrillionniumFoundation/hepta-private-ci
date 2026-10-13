//! Fail-closed Agentd bootstrap for a durable Neuron model-effect intent.
//!
//! A caller-supplied File alone cannot attest safe path ownership or durable
//! directory publication. This host boundary checks the protected file name,
//! exclusive journal replay and the parent directory fsync before any effect.
//! An unresolved Prepare remains quarantined by the journal; no caller digest
//! can reconcile it and no new Final-use nonce can replay its business tick.

use std::io;
use std::path::Path;

use codex_hepta_neuron::DurableNeuronEffectIntentV1;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::NeuronEffectIntentErrorV1;
#[cfg(unix)]
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NeuronEffectBootstrapErrorV1 {
    InvalidPath,
    /// The local durable intent identity was lost or replaced. A fresh nonce
    /// cannot replace historical effect deduplication; do not recreate it.
    ContinuityLost,
    ScopeMismatch,
    UnsafeDirectory,
    UnsafeFile,
    UnsupportedPlatform,
    Journal(NeuronEffectIntentErrorV1),
    Io(io::ErrorKind),
}

impl std::fmt::Display for NeuronEffectBootstrapErrorV1 {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for NeuronEffectBootstrapErrorV1 {}

impl From<io::Error> for NeuronEffectBootstrapErrorV1 {
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

impl From<NeuronEffectIntentErrorV1> for NeuronEffectBootstrapErrorV1 {
    fn from(error: NeuronEffectIntentErrorV1) -> Self {
        Self::Journal(error)
    }
}

/// Require the independently recovered sparse journal to have the same
/// subject/objective as the separate durable model-effect intent. Validate
/// before creating or opening the intent journal, not after effect admission.
pub(crate) fn verify_neuron_effect_scope_v1(
    runtime_scope: JournalScope,
    intent_scope: JournalScope,
) -> Result<(), NeuronEffectBootstrapErrorV1> {
    if runtime_scope != intent_scope
        || runtime_scope.scope_digest.is_zero()
        || runtime_scope.objective_digest.is_zero()
    {
        return Err(NeuronEffectBootstrapErrorV1::ScopeMismatch);
    }
    Ok(())
}

/// Local continuity evidence against one-file deletion or inode replacement.
/// This is an unkeyed, same-host marker, NOT independently administered
/// anti-rollback proof: restoring/deleting both files still requires the
/// external monotonic owner and its signed checkpoint.
#[cfg(unix)]
const EFFECT_MARKER_DOMAIN_V1: &[u8] = b"hepta.neuron.effect-intent.bootstrap-continuity.v1\0";
#[cfg(unix)]
const MAX_EFFECT_MARKER_BYTES_V1: u64 = 256;

#[cfg(unix)]
fn effect_marker_path_v1(path: &Path) -> Result<std::path::PathBuf, NeuronEffectBootstrapErrorV1> {
    let mut name = path
        .file_name()
        .ok_or(NeuronEffectBootstrapErrorV1::InvalidPath)?
        .to_os_string();
    name.push(".hepta-effect-owner-v1");
    Ok(path.with_file_name(name))
}

#[cfg(unix)]
fn effect_marker_bytes_v1(
    path: &Path,
    scope: JournalScope,
    generation: Generation,
    original_file: &std::fs::Metadata,
) -> Vec<u8> {
    use std::os::unix::ffi::OsStrExt as _;
    use std::os::unix::fs::MetadataExt as _;

    let mut bytes = Vec::with_capacity(MAX_EFFECT_MARKER_BYTES_V1 as usize);
    bytes.extend_from_slice(EFFECT_MARKER_DOMAIN_V1);
    bytes.extend_from_slice(scope.scope_digest.as_array());
    bytes.extend_from_slice(scope.objective_digest.as_array());
    bytes.extend_from_slice(&generation.get().to_be_bytes());
    bytes.extend_from_slice(&original_file.dev().to_be_bytes());
    bytes.extend_from_slice(&original_file.ino().to_be_bytes());
    bytes.extend_from_slice(Digest32::of_bytes(path.as_os_str().as_bytes()).as_array());
    let digest = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(digest.as_array());
    bytes
}

/// Read only a regular, owner-private, single-link marker. Both descriptor
/// and pathname must still name the same inode after the bounded read.
#[cfg(unix)]
fn read_effect_marker_v1(
    path: &Path,
) -> Result<Option<Vec<u8>>, NeuronEffectBootstrapErrorV1> {
    use std::io::Read as _;
    use std::os::unix::fs::MetadataExt as _;
    use std::os::unix::fs::PermissionsExt as _;

    let before = match std::fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    if !before.is_file()
        || before.nlink() != 1
        || before.permissions().mode() & 0o077 != 0
        || before.len() == 0
        || before.len() > MAX_EFFECT_MARKER_BYTES_V1
    {
        return Err(NeuronEffectBootstrapErrorV1::ContinuityLost);
    }
    let file = std::fs::OpenOptions::new().read(true).open(path)?;
    let opened = file.metadata()?;
    if !opened.is_file()
        || opened.dev() != before.dev()
        || opened.ino() != before.ino()
        || opened.nlink() != 1
    {
        return Err(NeuronEffectBootstrapErrorV1::ContinuityLost);
    }
    let mut bytes = Vec::with_capacity(before.len() as usize);
    file.take(MAX_EFFECT_MARKER_BYTES_V1 + 1)
        .read_to_end(&mut bytes)?;
    let after = std::fs::symlink_metadata(path)
        .map_err(|_| NeuronEffectBootstrapErrorV1::ContinuityLost)?;
    if bytes.len() as u64 != before.len()
        || !after.is_file()
        || after.dev() != opened.dev()
        || after.ino() != opened.ino()
        || after.nlink() != 1
        || after.permissions().mode() & 0o077 != 0
    {
        return Err(NeuronEffectBootstrapErrorV1::ContinuityLost);
    }
    Ok(Some(bytes))
}

/// Reopen or create one scope/generation-specific intent journal. A new file
/// is named durably before the returned owner may serve; a recovered Prepare
/// continues to reject every new tick until independent reconciliation.
///
/// The host must supply an already provisioned owner-only directory. This
/// path intentionally does not create directories, follow symlinks or
/// downgrade to an in-memory journal on unsupported platforms.
#[cfg(unix)]
pub fn bootstrap_durable_neuron_effect_intent_v1(
    path: &Path,
    scope: JournalScope,
    generation: Generation,
    max_records: usize,
) -> Result<DurableNeuronEffectIntentV1, NeuronEffectBootstrapErrorV1> {
    use std::fs;
    use std::fs::OpenOptions;
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;
    use std::os::unix::fs::PermissionsExt;
    use std::path::Component;

    if !path.is_absolute()
        || path.file_name().is_none()
        || path.components().any(|component| {
            matches!(component, Component::CurDir | Component::ParentDir)
        })
        || scope.scope_digest.is_zero()
        || scope.objective_digest.is_zero()
    {
        return Err(NeuronEffectBootstrapErrorV1::InvalidPath);
    }
    let parent = path.parent().ok_or(NeuronEffectBootstrapErrorV1::InvalidPath)?;
    let directory = fs::symlink_metadata(parent)?;
    if !directory.is_dir()
        || directory.file_type().is_symlink()
        || directory.permissions().mode() & 0o077 != 0
    {
        return Err(NeuronEffectBootstrapErrorV1::UnsafeDirectory);
    }
    let marker = effect_marker_path_v1(path)?;
    let original_marker = read_effect_marker_v1(&marker)?;
    let journal_exists = match fs::symlink_metadata(path) {
        Ok(metadata) => {
            if !metadata.is_file()
                || metadata.permissions().mode() & 0o077 != 0
                || metadata.nlink() != 1
            {
                return Err(NeuronEffectBootstrapErrorV1::UnsafeFile);
            }
            true
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => false,
        Err(error) => return Err(error.into()),
    };
    // First initialization requires BOTH paths to be absent. Any asymmetry
    // means the original effect history might have been lost; never silently
    // adopt an old unsealed file or mint an empty history after deletion.
    if journal_exists != original_marker.is_some() {
        return Err(NeuronEffectBootstrapErrorV1::ContinuityLost);
    }
    let mut options = OpenOptions::new();
    options.read(true).write(true).mode(0o600);
    if !journal_exists {
        options.create_new(true);
    }
    let file = options.open(path)?;
    // Reject an inode switch, hardlink or symlink at the exact opened path.
    // Requiring an owner-only parent excludes untrusted directory renames.
    let opened = file.metadata()?;
    let on_path = fs::symlink_metadata(path)?;
    if !opened.is_file()
        || !on_path.is_file()
        || opened.dev() != on_path.dev()
        || opened.ino() != on_path.ino()
        || opened.nlink() != 1
        || on_path.nlink() != 1
        || opened.permissions().mode() & 0o077 != 0
        || on_path.permissions().mode() & 0o077 != 0
    {
        return Err(NeuronEffectBootstrapErrorV1::UnsafeFile);
    }
    // A sealed prior owner cannot be allowed to recreate a zero-length
    // journal in place. This catches complete truncation without changing the
    // inode; a valid-looking older prefix still needs external anti-rollback.
    if journal_exists && opened.len() == 0 {
        return Err(NeuronEffectBootstrapErrorV1::ContinuityLost);
    }
    let expected_marker = effect_marker_bytes_v1(path, scope, generation, &opened);
    if expected_marker.len() as u64 > MAX_EFFECT_MARKER_BYTES_V1 {
        return Err(NeuronEffectBootstrapErrorV1::ContinuityLost);
    }
    if original_marker
        .as_ref()
        .is_some_and(|stored| stored != &expected_marker)
    {
        return Err(NeuronEffectBootstrapErrorV1::ContinuityLost);
    }
    let mut owner = DurableNeuronEffectIntentV1::open(file, scope, generation, max_records)?;
    owner.bind_owner_path(path)?;
    // The journal header and path must survive independently of the
    // continuity marker: a crash between these two publications leaves an
    // orphan that the next bootstrap will reject, never a fresh tick window.
    fs::File::open(parent)?.sync_all()?;
    if original_marker.is_none() {
        let mut seal = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&marker)?;
        use std::io::Write as _;
        seal.write_all(&expected_marker)?;
        seal.sync_all()?;
        fs::File::open(parent)?.sync_all()?;
    }
    if read_effect_marker_v1(&marker)?.as_deref() != Some(expected_marker.as_slice()) {
        return Err(NeuronEffectBootstrapErrorV1::ContinuityLost);
    }
    owner.verify_bound_owner_path()?;
    Ok(owner)
}

/// No audited owner-only directory and directory-entry durability contract
/// exists here for non-Unix platforms. Reject instead of pretending ready.
#[cfg(not(unix))]
pub fn bootstrap_durable_neuron_effect_intent_v1(
    _path: &Path,
    _scope: JournalScope,
    _generation: Generation,
    _max_records: usize,
) -> Result<DurableNeuronEffectIntentV1, NeuronEffectBootstrapErrorV1> {
    Err(NeuronEffectBootstrapErrorV1::UnsupportedPlatform)
}

#[cfg(test)]
#[path = "neuron_effect_bootstrap_tests.rs"]
mod tests;
