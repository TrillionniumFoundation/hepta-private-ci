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
use codex_hepta_types::Generation;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NeuronEffectBootstrapErrorV1 {
    InvalidPath,
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
    use std::os::unix::fs::MetadataExt as _;
    use std::os::unix::fs::PermissionsExt as _;
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
    let checked_inode = match fs::symlink_metadata(path) {
        Ok(metadata) => {
            if !metadata.is_file()
                || metadata.permissions().mode() & 0o077 != 0
                || metadata.nlink() != 1
            {
                return Err(NeuronEffectBootstrapErrorV1::UnsafeFile);
            }
            Some(metadata)
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => None,
        Err(error) => return Err(error.into()),
    };
    // The checked filename is not an authority by itself: a peer could
    // replace it between the preflight metadata read and the actual open.
    let file = open_checked_neuron_effect_file_v1(path, checked_inode.as_ref())?;
    let mut owner = DurableNeuronEffectIntentV1::open(file, scope, generation, max_records)?;
    owner.bind_owner_path(path)?;
    // The file fsync inside open makes its header durable; the directory fsync
    // makes the pathname recoverable after first creation. Failure blocks
    // serving even though opening/replaying the file succeeded.
    fs::File::open(parent)?.sync_all()?;
    owner.verify_bound_owner_path()?;
    Ok(owner)
}

/// Open the same inode observed before the filesystem race window.
/// For first publication, create_new makes racing publication ambiguous
/// rather than silently adopting a competitor's durable journal.
#[cfg(unix)]
fn open_checked_neuron_effect_file_v1(
    path: &Path,
    checked_inode: Option<&std::fs::Metadata>,
) -> Result<std::fs::File, NeuronEffectBootstrapErrorV1> {
    use std::fs;
    use std::fs::OpenOptions;
    use std::os::unix::fs::MetadataExt as _;
    use std::os::unix::fs::OpenOptionsExt as _;
    use std::os::unix::fs::PermissionsExt as _;

    let mut options = OpenOptions::new();
    options.read(true).write(true).mode(0o600);
    if checked_inode.is_none() {
        options.create_new(true);
    }
    let file = options.open(path).map_err(|error| {
        if checked_inode.is_none() && error.kind() == io::ErrorKind::AlreadyExists {
            NeuronEffectBootstrapErrorV1::UnsafeFile
        } else {
            NeuronEffectBootstrapErrorV1::Io(error.kind())
        }
    })?;
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
        || checked_inode.is_some_and(|previous| {
            previous.dev() != opened.dev() || previous.ino() != opened.ino()
        })
    {
        return Err(NeuronEffectBootstrapErrorV1::UnsafeFile);
    }
    Ok(file)
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
