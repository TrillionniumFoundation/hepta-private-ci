//! Hardened process bootstrap wrapper for governed plasticity.
//!
//! The historical parser/reconstructor remains byte-for-byte in the sibling
//! `plasticity_process_bootstrap_legacy.rs`. This wrapper adds normalized-path
//! traversal, Linux `O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK` opens, pre/post device and
//! inode checks, parent-directory durability, and an optional target-host profile
//! binding device, mount and snapshot identities. It never turns a bootstrap
//! failure into permission to create fresh proposal history.

use std::collections::BTreeMap;
use std::ffi::OsString;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use serde::Deserialize;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::PlasticityRuntimeBootstrapV1;

#[path = "plasticity_process_bootstrap_legacy.rs"]
mod legacy;

const MAX_DESCRIPTOR_BYTES: u64 = 1_048_576;
const MAX_PROFILE_BYTES: u64 = 262_144;
const ROLLBACK_PROFILE_SCHEMA: &str = "hepta.agentd.plasticity-rollback-domain.v1";

#[cfg(target_os = "linux")]
const O_NOFOLLOW_FLAG: i32 = 0o400000;
#[cfg(target_os = "linux")]
const O_CLOEXEC_FLAG: i32 = 0o2000000;
#[cfg(target_os = "linux")]
const O_NONBLOCK_FLAG: i32 = 0o4000;
#[cfg(target_os = "linux")]
const O_DIRECTORY_FLAG: i32 = 0o200000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityPathIdentityV1 {
    pub logical_name: String,
    pub path: PathBuf,
    pub exists: bool,
    pub device_id: u64,
    pub inode: u64,
    pub link_count: u64,
    pub parent_device_id: u64,
    pub parent_inode: u64,
    pub mount_identity_digest: Digest32,
    pub snapshot_identity_digest: Option<Digest32>,
    pub identity_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityRollbackDomainReceiptV1 {
    pub descriptor_digest: Digest32,
    pub paths: Vec<PlasticityPathIdentityV1>,
    pub parameter_domains_independent: bool,
    pub topology_domains_independent: bool,
    pub receipt_digest: Digest32,
}

#[derive(Debug, Deserialize)]
struct BootstrapPathDescriptorV1 {
    artifacts: ArtifactPathV1,
    ledger: LedgerPathV1,
    ndu: NduPathV1,
    neuron: NeuronPathV1,
    parameter_registry: RegistryPathV1,
    topology_registry: RegistryPathV1,
}
#[derive(Debug, Deserialize)]
struct ArtifactPathV1 {
    path: PathBuf,
}
#[derive(Debug, Deserialize)]
struct LedgerPathV1 {
    path: PathBuf,
}
#[derive(Debug, Deserialize)]
struct NduPathV1 {
    journal_path: PathBuf,
}
#[derive(Debug, Deserialize)]
struct NeuronPathV1 {
    journal_path: PathBuf,
}
#[derive(Debug, Deserialize)]
struct RegistryPathV1 {
    registry_path: PathBuf,
    anchor_path: PathBuf,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RollbackDomainProfileV1 {
    schema: String,
    descriptor_digest: String,
    paths: Vec<RollbackDomainProfilePathV1>,
}
#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RollbackDomainProfilePathV1 {
    logical_name: String,
    device_id: u64,
    mount_identity_digest: String,
    snapshot_identity_digest: String,
}

/// Reconstruct the runtime owner only after all existing paths have passed a
/// no-follow open and identity capture. Existing identities are checked again
/// after reconstruction and all mutable parent directories are synced.
pub fn load_plasticity_process_bootstrap_v1(
    path: &Path,
    expected_descriptor_digest: Digest32,
    identity: &AgentdIdentity,
) -> Result<PlasticityRuntimeBootstrapV1, AgentdError> {
    let descriptor_bytes =
        secure_read_bounded(path, MAX_DESCRIPTOR_BYTES, "plasticity descriptor")?;
    if expected_descriptor_digest.is_zero()
        || Digest32::of_bytes(&descriptor_bytes) != expected_descriptor_digest
    {
        return invalid("plasticity bootstrap descriptor digest mismatch");
    }
    let descriptor: BootstrapPathDescriptorV1 = serde_json::from_slice(&descriptor_bytes)?;
    let before = inspect_paths(&descriptor, expected_descriptor_digest, None)?;
    let bootstrap = legacy::load_plasticity_process_bootstrap_v1(
        path,
        expected_descriptor_digest,
        identity,
    )?;
    let after = inspect_paths(&descriptor, expected_descriptor_digest, None)?;
    verify_stable_existing_identities(&before, &after)?;
    sync_mutable_parent_directories(&descriptor)?;
    Ok(bootstrap)
}

/// Verify deployment-owned device/mount/snapshot evidence. The expected profile
/// digest comes from target-host qualification, never from the descriptor itself.
pub fn verify_plasticity_rollback_domain_profile_v1(
    descriptor_path: &Path,
    expected_descriptor_digest: Digest32,
    profile_path: &Path,
    expected_profile_digest: Digest32,
) -> Result<PlasticityRollbackDomainReceiptV1, AgentdError> {
    let descriptor_bytes = secure_read_bounded(
        descriptor_path,
        MAX_DESCRIPTOR_BYTES,
        "plasticity descriptor",
    )?;
    if expected_descriptor_digest.is_zero()
        || Digest32::of_bytes(&descriptor_bytes) != expected_descriptor_digest
    {
        return invalid("plasticity bootstrap descriptor digest mismatch");
    }
    let profile_bytes = secure_read_bounded(
        profile_path,
        MAX_PROFILE_BYTES,
        "plasticity rollback-domain profile",
    )?;
    if expected_profile_digest.is_zero()
        || Digest32::of_bytes(&profile_bytes) != expected_profile_digest
    {
        return invalid("plasticity rollback-domain profile digest mismatch");
    }
    let profile: RollbackDomainProfileV1 = serde_json::from_slice(&profile_bytes)?;
    let profile_descriptor_digest = Digest32::from_str(&profile.descriptor_digest)
        .map_err(|error| AgentdError::Invalid(format!("invalid descriptor digest: {error}")))?;
    if profile.schema != ROLLBACK_PROFILE_SCHEMA
        || profile_descriptor_digest != expected_descriptor_digest
    {
        return invalid("plasticity rollback-domain profile context mismatch");
    }
    let descriptor: BootstrapPathDescriptorV1 = serde_json::from_slice(&descriptor_bytes)?;
    let snapshots = profile
        .paths
        .into_iter()
        .map(|entry| {
            let mount = Digest32::from_str(&entry.mount_identity_digest).map_err(|error| {
                AgentdError::Invalid(format!("invalid mount identity digest: {error}"))
            })?;
            let snapshot = Digest32::from_str(&entry.snapshot_identity_digest).map_err(|error| {
                AgentdError::Invalid(format!("invalid snapshot identity digest: {error}"))
            })?;
            if mount.is_zero() || snapshot.is_zero() {
                return invalid("rollback-domain identities must be non-zero");
            }
            Ok((entry.logical_name, (entry.device_id, mount, snapshot)))
        })
        .collect::<Result<BTreeMap<_, _>, AgentdError>>()?;
    inspect_paths(&descriptor, expected_descriptor_digest, Some(&snapshots))
}

fn inspect_paths(
    descriptor: &BootstrapPathDescriptorV1,
    descriptor_digest: Digest32,
    snapshots: Option<&BTreeMap<String, (u64, Digest32, Digest32)>>,
) -> Result<PlasticityRollbackDomainReceiptV1, AgentdError> {
    let entries = descriptor_entries(descriptor);
    let mut paths = Vec::with_capacity(entries.len());
    for (logical_name, path, required) in entries {
        let snapshot = snapshots.and_then(|values| values.get(logical_name));
        paths.push(inspect_path(logical_name, path, required, snapshot)?);
    }
    if let Some(expected) = snapshots
        && expected.len() != paths.len()
    {
        return invalid("rollback-domain profile path set is incomplete or unexpected");
    }
    let by_name = paths
        .iter()
        .map(|identity| (identity.logical_name.as_str(), identity))
        .collect::<BTreeMap<_, _>>();
    let parameter_domains_independent = domains_independent(
        by_name
            .get("parameter_registry")
            .ok_or_else(|| AgentdError::Invalid("parameter registry identity missing".to_string()))?,
        by_name
            .get("parameter_anchor")
            .ok_or_else(|| AgentdError::Invalid("parameter anchor identity missing".to_string()))?,
        snapshots.is_some(),
    );
    let topology_domains_independent = domains_independent(
        by_name
            .get("topology_registry")
            .ok_or_else(|| AgentdError::Invalid("topology registry identity missing".to_string()))?,
        by_name
            .get("topology_anchor")
            .ok_or_else(|| AgentdError::Invalid("topology anchor identity missing".to_string()))?,
        snapshots.is_some(),
    );
    if snapshots.is_some() && (!parameter_domains_independent || !topology_domains_independent) {
        return invalid("proposal registry and anchor are not in independent rollback domains");
    }
    let mut receipt_bytes = b"hepta.agentd.plasticity-rollback-domain-receipt.v1\0".to_vec();
    receipt_bytes.extend_from_slice(descriptor_digest.as_array());
    for identity in &paths {
        receipt_bytes.extend_from_slice(identity.identity_digest.as_array());
    }
    receipt_bytes.push(u8::from(parameter_domains_independent));
    receipt_bytes.push(u8::from(topology_domains_independent));
    let receipt_digest = Digest32::of_bytes(&receipt_bytes);
    Ok(PlasticityRollbackDomainReceiptV1 {
        descriptor_digest,
        paths,
        parameter_domains_independent,
        topology_domains_independent,
        receipt_digest,
    })
}

fn descriptor_entries(
    descriptor: &BootstrapPathDescriptorV1,
) -> [(&'static str, &Path, bool); 8] {
    [
        ("artifact_registry", &descriptor.artifacts.path, true),
        ("learning_ledger", &descriptor.ledger.path, true),
        ("ndu_journal", &descriptor.ndu.journal_path, true),
        ("neuron_journal", &descriptor.neuron.journal_path, true),
        (
            "parameter_registry",
            &descriptor.parameter_registry.registry_path,
            false,
        ),
        (
            "parameter_anchor",
            &descriptor.parameter_registry.anchor_path,
            false,
        ),
        (
            "topology_registry",
            &descriptor.topology_registry.registry_path,
            false,
        ),
        (
            "topology_anchor",
            &descriptor.topology_registry.anchor_path,
            false,
        ),
    ]
}

fn inspect_path(
    logical_name: &str,
    path: &Path,
    required: bool,
    snapshot: Option<&(u64, Digest32, Digest32)>,
) -> Result<PlasticityPathIdentityV1, AgentdError> {
    let (parent_path, leaf) = secure_parent(path)?;
    let parent_file = secure_open_directory(&parent_path)?;
    let parent_metadata = parent_file.metadata()?;
    #[cfg(unix)]
    use std::os::unix::fs::MetadataExt;
    #[cfg(unix)]
    let (parent_device_id, parent_inode) = (parent_metadata.dev(), parent_metadata.ino());
    #[cfg(not(unix))]
    let (parent_device_id, parent_inode) = (0, 0);

    let opened = secure_open_leaf(&parent_path, &leaf, false);
    let (exists, device_id, inode, link_count) = match opened {
        Ok(file) => {
            let metadata = file.metadata()?;
            if !metadata.is_file() {
                return invalid(&format!("{logical_name} must be a regular file"));
            }
            #[cfg(unix)]
            {
                let links = metadata.nlink();
                if links != 1 {
                    return invalid(&format!("{logical_name} must have exactly one hard link"));
                }
                (true, metadata.dev(), metadata.ino(), links)
            }
            #[cfg(not(unix))]
            {
                (true, 0, 0, 1)
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound && !required => {
            (false, parent_device_id, 0, 0)
        }
        Err(error) => return Err(error.into()),
    };
    let mut mount_bytes = b"hepta.agentd.plasticity-mount-identity.v1\0".to_vec();
    mount_bytes.extend_from_slice(&parent_device_id.to_be_bytes());
    mount_bytes.extend_from_slice(&parent_inode.to_be_bytes());
    mount_bytes.extend_from_slice(parent_path.as_os_str().as_encoded_bytes());
    let mount_identity_digest = Digest32::of_bytes(&mount_bytes);
    let snapshot_identity_digest = snapshot
        .map(|(expected_device, expected_mount, value)| {
            if *expected_device != device_id || *expected_mount != mount_identity_digest {
                return Err(AgentdError::Invalid(format!(
                    "{logical_name} device/mount identity does not match target-host profile"
                )));
            }
            Ok(*value)
        })
        .transpose()?;
    let mut identity_bytes = b"hepta.agentd.plasticity-path-identity.v1\0".to_vec();
    identity_bytes.extend_from_slice(logical_name.as_bytes());
    identity_bytes.extend_from_slice(path.as_os_str().as_encoded_bytes());
    identity_bytes.push(u8::from(exists));
    for value in [device_id, inode, link_count, parent_device_id, parent_inode] {
        identity_bytes.extend_from_slice(&value.to_be_bytes());
    }
    identity_bytes.extend_from_slice(mount_identity_digest.as_array());
    match snapshot_identity_digest {
        Some(value) => {
            identity_bytes.push(1);
            identity_bytes.extend_from_slice(value.as_array());
        }
        None => identity_bytes.push(0),
    }
    Ok(PlasticityPathIdentityV1 {
        logical_name: logical_name.to_string(),
        path: path.to_path_buf(),
        exists,
        device_id,
        inode,
        link_count,
        parent_device_id,
        parent_inode,
        mount_identity_digest,
        snapshot_identity_digest,
        identity_digest: Digest32::of_bytes(&identity_bytes),
    })
}

fn domains_independent(
    registry: &PlasticityPathIdentityV1,
    anchor: &PlasticityPathIdentityV1,
    strict: bool,
) -> bool {
    if registry.exists
        && anchor.exists
        && registry.device_id == anchor.device_id
        && registry.inode == anchor.inode
    {
        return false;
    }
    let snapshots_differ = match (
        registry.snapshot_identity_digest,
        anchor.snapshot_identity_digest,
    ) {
        (Some(left), Some(right)) => left != right,
        _ => false,
    };
    if strict {
        snapshots_differ
    } else {
        registry.device_id != anchor.device_id
            || registry.mount_identity_digest != anchor.mount_identity_digest
    }
}

fn verify_stable_existing_identities(
    before: &PlasticityRollbackDomainReceiptV1,
    after: &PlasticityRollbackDomainReceiptV1,
) -> Result<(), AgentdError> {
    let after_by_name = after
        .paths
        .iter()
        .map(|identity| (identity.logical_name.as_str(), identity))
        .collect::<BTreeMap<_, _>>();
    for prior in &before.paths {
        let current = after_by_name.get(prior.logical_name.as_str()).ok_or_else(|| {
            AgentdError::Invalid(format!("{} disappeared during bootstrap", prior.logical_name))
        })?;
        if prior.exists
            && (!current.exists
                || prior.device_id != current.device_id
                || prior.inode != current.inode)
        {
            return invalid(&format!(
                "{} changed identity during bootstrap",
                prior.logical_name
            ));
        }
    }
    Ok(())
}

fn sync_mutable_parent_directories(
    descriptor: &BootstrapPathDescriptorV1,
) -> Result<(), AgentdError> {
    for path in [
        &descriptor.parameter_registry.registry_path,
        &descriptor.parameter_registry.anchor_path,
        &descriptor.topology_registry.registry_path,
        &descriptor.topology_registry.anchor_path,
    ] {
        let (parent, _) = secure_parent(path)?;
        secure_open_directory(&parent)?.sync_all()?;
    }
    Ok(())
}

fn secure_read_bounded(path: &Path, maximum: u64, label: &str) -> Result<Vec<u8>, AgentdError> {
    let (parent, leaf) = secure_parent(path)?;
    let mut file = secure_open_leaf(&parent, &leaf, false)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.len() == 0 || metadata.len() > maximum {
        return invalid(&format!("{label} size/type is outside the allowed bound"));
    }
    let capacity = usize::try_from(metadata.len())
        .map_err(|_| AgentdError::Invalid(format!("{label} is too large")))?;
    let mut bytes = Vec::with_capacity(capacity);
    file.take(maximum + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 != metadata.len() {
        return invalid(&format!("{label} changed while being read"));
    }
    Ok(bytes)
}

fn secure_parent(path: &Path) -> Result<(PathBuf, OsString), AgentdError> {
    let mut components = normalized_components(path)?;
    let leaf = components
        .pop()
        .ok_or_else(|| AgentdError::Invalid("path must name a file".to_string()))?;
    let mut parent = PathBuf::from("/");
    for component in components {
        parent.push(component);
        let metadata = std::fs::symlink_metadata(&parent)?;
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            return invalid("plasticity owner path contains a symlink or non-directory component");
        }
    }
    Ok((parent, leaf))
}

fn secure_open_directory(path: &Path) -> std::io::Result<File> {
    let before = std::fs::symlink_metadata(path)?;
    if before.file_type().is_symlink() || !before.is_dir() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "directory path is not a non-symlink directory",
        ));
    }
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(O_NOFOLLOW_FLAG | O_CLOEXEC_FLAG | O_DIRECTORY_FLAG);
    }
    let file = options.open(path)?;
    verify_same_identity(&before, &file.metadata())?;
    Ok(file)
}

fn secure_open_leaf(parent: &Path, leaf: &OsString, writable: bool) -> std::io::Result<File> {
    let path = parent.join(leaf);
    let before = std::fs::symlink_metadata(&path)?;
    if before.file_type().is_symlink() || !before.is_file() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "file path is not a non-symlink regular file",
        ));
    }
    let mut options = OpenOptions::new();
    options.read(true).write(writable);
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(O_NOFOLLOW_FLAG | O_CLOEXEC_FLAG | O_NONBLOCK_FLAG);
    }
    let file = options.open(&path)?;
    verify_same_identity(&before, &file.metadata())?;
    Ok(file)
}

fn verify_same_identity(
    before: &std::fs::Metadata,
    after: &std::fs::Metadata,
) -> std::io::Result<()> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if before.dev() != after.dev() || before.ino() != after.ino() {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                "filesystem identity changed while opening",
            ));
        }
    }
    Ok(())
}

fn normalized_components(path: &Path) -> Result<Vec<OsString>, AgentdError> {
    if !path.is_absolute() {
        return invalid("plasticity owner paths must be absolute");
    }
    path.components()
        .filter_map(|component| match component {
            Component::RootDir => None,
            Component::Normal(value) => Some(Ok(value.to_os_string())),
            Component::CurDir | Component::ParentDir | Component::Prefix(_) => {
                Some(invalid("plasticity owner paths must be normalized"))
            }
        })
        .collect()
}

fn invalid<T>(message: &str) -> Result<T, AgentdError> {
    Err(AgentdError::Invalid(message.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn component_walk_rejects_parent_traversal() {
        assert!(normalized_components(Path::new("/tmp/../secret")).is_err());
        assert!(normalized_components(Path::new("relative/file")).is_err());
    }

    #[cfg(unix)]
    #[test]
    fn secure_leaf_rejects_symbolic_link() {
        use std::os::unix::fs::symlink;

        let directory = tempfile::tempdir().expect("tempdir");
        let target = directory.path().join("target");
        let link = directory.path().join("link");
        std::fs::write(&target, b"value").expect("write");
        symlink(&target, &link).expect("symlink");
        let (parent, leaf) = secure_parent(&link).expect("parent");
        assert!(secure_open_leaf(&parent, &leaf, false).is_err());
    }
}
