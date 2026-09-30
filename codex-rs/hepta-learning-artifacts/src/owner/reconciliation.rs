use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::io::Read;
#[cfg(unix)]
use std::os::unix::fs::DirBuilderExt;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::HostDurabilityError;
use crate::durable_write_new_v1;
use crate::provision_private_root_v1;
use crate::sync_directory_v1;

const BACKUP_MANIFEST_MAGIC: &str = "HEPTA-LEARNING-ARTIFACTD-BACKUP-V1";
const BACKUP_COMPLETE_MAGIC: &str = "HEPTA-LEARNING-ARTIFACTD-BACKUP-COMPLETE-V1";
const OWNER_SCHEMA_MAGIC: &[u8] = b"HEPTA-LEARNING-ARTIFACTD-SCHEMA-V1\nversion=1\n";
const MAX_BACKUP_FILES: usize = 16_384;
const MAX_BACKUP_FILE_BYTES: u64 = 64 * 1024 * 1024;
const MAX_BACKUP_TOTAL_BYTES: u64 = 16 * 1024 * 1024 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactOwnerBackupReceiptV1 {
    pub backup_id: StableId,
    pub manifest_digest: Digest32,
    pub file_count: usize,
    pub total_bytes: u64,
    pub authority: codex_hepta_types::AuthorityPosture,
}

pub fn backup_owner_root_v1(
    owner_root: impl AsRef<Path>,
    backup_root: impl AsRef<Path>,
    backup_id: StableId,
) -> Result<ArtifactOwnerBackupReceiptV1, ArtifactOwnerReconciliationError> {
    let owner_root = fs::canonicalize(owner_root)?;
    let backup_root = provision_private_root_v1(backup_root)
        .map_err(ArtifactOwnerReconciliationError::Durability)?;
    if backup_root.starts_with(&owner_root) || owner_root.starts_with(&backup_root) {
        return Err(ArtifactOwnerReconciliationError::PathBoundary);
    }
    let destination = backup_root.join(backup_id.as_str());
    if destination.exists() {
        return verify_backup(&destination, &backup_id);
    }
    create_directory(&destination)?;

    let mut entries = Vec::new();
    collect_files(&owner_root, &owner_root, &mut entries)?;
    entries.sort();
    let mut records = Vec::with_capacity(entries.len());
    let mut total_bytes = 0u64;
    for relative in entries {
        let source = owner_root.join(&relative);
        let metadata = fs::symlink_metadata(&source)?;
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(ArtifactOwnerReconciliationError::PathBoundary);
        }
        if metadata.len() > MAX_BACKUP_FILE_BYTES {
            return Err(ArtifactOwnerReconciliationError::Capacity);
        }
        total_bytes = total_bytes
            .checked_add(metadata.len())
            .ok_or(ArtifactOwnerReconciliationError::Capacity)?;
        if total_bytes > MAX_BACKUP_TOTAL_BYTES {
            return Err(ArtifactOwnerReconciliationError::Capacity);
        }
        let bytes = read_bounded_file(&source, MAX_BACKUP_FILE_BYTES)?;
        let target = destination.join(&relative);
        ensure_parent_directories(&destination, &target)?;
        durable_write_new_v1(&target, &bytes)
            .map_err(ArtifactOwnerReconciliationError::Durability)?;
        records.push(BackupRecordV1 {
            relative,
            bytes: bytes.len() as u64,
            digest: Digest32::of_bytes(&bytes),
        });
    }
    let manifest = encode_manifest(&backup_id, &records, total_bytes)?;
    let manifest_digest = Digest32::of_bytes(&manifest);
    durable_write_new_v1(destination.join("BACKUP.manifest"), &manifest)
        .map_err(ArtifactOwnerReconciliationError::Durability)?;
    let complete = format!(
        "{BACKUP_COMPLETE_MAGIC}\n{backup_id}\n{manifest_digest}\n{}\n{total_bytes}\n",
        records.len()
    );
    durable_write_new_v1(destination.join("BACKUP.complete"), complete.as_bytes())
        .map_err(ArtifactOwnerReconciliationError::Durability)?;
    sync_directory_v1(&destination).map_err(ArtifactOwnerReconciliationError::Durability)?;
    Ok(ArtifactOwnerBackupReceiptV1 {
        backup_id,
        manifest_digest,
        file_count: records.len(),
        total_bytes,
        authority: codex_hepta_types::AuthorityPosture::DENY_ALL,
    })
}

pub fn restore_owner_root_v1(
    backup: impl AsRef<Path>,
    target_root: impl AsRef<Path>,
) -> Result<ArtifactOwnerBackupReceiptV1, ArtifactOwnerReconciliationError> {
    let backup = fs::canonicalize(backup)?;
    let complete = decode_complete(&read_bounded_file(
        &backup.join("BACKUP.complete"),
        16 * 1024,
    )?)?;
    let receipt = verify_backup(&backup, &complete.backup_id)?;
    let target = target_root.as_ref();
    if target.exists() {
        let metadata = fs::symlink_metadata(target)?;
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            return Err(ArtifactOwnerReconciliationError::PathBoundary);
        }
        if fs::read_dir(target)?.next().is_some() {
            return Err(ArtifactOwnerReconciliationError::RestoreTargetNotEmpty);
        }
    }
    let target = provision_private_root_v1(target)
        .map_err(ArtifactOwnerReconciliationError::Durability)?;
    if target.starts_with(&backup) || backup.starts_with(&target) {
        return Err(ArtifactOwnerReconciliationError::PathBoundary);
    }
    let manifest_bytes = read_bounded_file(&backup.join("BACKUP.manifest"), 8 * 1024 * 1024)?;
    let manifest = decode_manifest(&manifest_bytes)?;
    for record in &manifest.records {
        let source = backup.join(&record.relative);
        let bytes = read_bounded_file(&source, MAX_BACKUP_FILE_BYTES)?;
        if bytes.len() as u64 != record.bytes || Digest32::of_bytes(&bytes) != record.digest {
            return Err(ArtifactOwnerReconciliationError::CorruptBackup);
        }
        let destination = target.join(&record.relative);
        ensure_parent_directories(&target, &destination)?;
        durable_write_new_v1(destination, &bytes)
            .map_err(ArtifactOwnerReconciliationError::Durability)?;
    }
    let restore_receipt = format!(
        "HEPTA-LEARNING-ARTIFACTD-RESTORE-V1\n{}\n{}\n{}\n{}\n",
        receipt.backup_id,
        receipt.manifest_digest,
        receipt.file_count,
        receipt.total_bytes
    );
    let host = target.join("host");
    if !host.exists() {
        create_directory(&host)?;
    }
    durable_write_new_v1(host.join("RESTORE.complete"), restore_receipt.as_bytes())
        .map_err(ArtifactOwnerReconciliationError::Durability)?;
    Ok(receipt)
}

/// Admit a legacy owner root into schema V1 without rewriting artifact bytes.
///
/// Migration is offline and additive: required directories are inspected for
/// symlinks/non-directories and then one create-only schema marker is published.
/// Unknown existing markers fail closed.
pub fn migrate_owner_root_v1(
    root: impl AsRef<Path>,
) -> Result<(), ArtifactOwnerReconciliationError> {
    let root = provision_private_root_v1(root)
        .map_err(ArtifactOwnerReconciliationError::Durability)?;
    for directory in [
        "writer",
        "transactions",
        "payloads",
        "registries",
        "witnesses",
        "heads",
    ] {
        let path = root.join(directory);
        if path.exists() {
            let metadata = fs::symlink_metadata(&path)?;
            if metadata.file_type().is_symlink() || !metadata.is_dir() {
                return Err(ArtifactOwnerReconciliationError::PathBoundary);
            }
        }
    }
    let host = root.join("host");
    if !host.exists() {
        create_directory(&host)?;
    }
    let marker = host.join("schema-v1");
    match fs::read(&marker) {
        Ok(bytes) if bytes == OWNER_SCHEMA_MAGIC => Ok(()),
        Ok(_) => Err(ArtifactOwnerReconciliationError::UnsupportedSchema),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            durable_write_new_v1(marker, OWNER_SCHEMA_MAGIC)
                .map_err(ArtifactOwnerReconciliationError::Durability)
        }
        Err(error) => Err(error.into()),
    }
}

fn verify_backup(
    destination: &Path,
    expected_backup_id: &StableId,
) -> Result<ArtifactOwnerBackupReceiptV1, ArtifactOwnerReconciliationError> {
    let metadata = fs::symlink_metadata(destination)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(ArtifactOwnerReconciliationError::PathBoundary);
    }
    let complete = decode_complete(&read_bounded_file(
        &destination.join("BACKUP.complete"),
        16 * 1024,
    )?)?;
    if complete.backup_id != *expected_backup_id {
        return Err(ArtifactOwnerReconciliationError::CorruptBackup);
    }
    let manifest_bytes = read_bounded_file(&destination.join("BACKUP.manifest"), 8 * 1024 * 1024)?;
    if Digest32::of_bytes(&manifest_bytes) != complete.manifest_digest {
        return Err(ArtifactOwnerReconciliationError::CorruptBackup);
    }
    let manifest = decode_manifest(&manifest_bytes)?;
    if manifest.backup_id != complete.backup_id
        || manifest.records.len() != complete.file_count
        || manifest.total_bytes != complete.total_bytes
    {
        return Err(ArtifactOwnerReconciliationError::CorruptBackup);
    }
    let mut observed = BTreeSet::new();
    for record in &manifest.records {
        if !observed.insert(record.relative.clone()) {
            return Err(ArtifactOwnerReconciliationError::CorruptBackup);
        }
        let bytes = read_bounded_file(&destination.join(&record.relative), MAX_BACKUP_FILE_BYTES)?;
        if bytes.len() as u64 != record.bytes || Digest32::of_bytes(&bytes) != record.digest {
            return Err(ArtifactOwnerReconciliationError::CorruptBackup);
        }
    }
    Ok(ArtifactOwnerBackupReceiptV1 {
        backup_id: complete.backup_id,
        manifest_digest: complete.manifest_digest,
        file_count: complete.file_count,
        total_bytes: complete.total_bytes,
        authority: codex_hepta_types::AuthorityPosture::DENY_ALL,
    })
}

fn collect_files(
    root: &Path,
    current: &Path,
    output: &mut Vec<PathBuf>,
) -> Result<(), ArtifactOwnerReconciliationError> {
    for entry in fs::read_dir(current)? {
        let entry = entry?;
        let path = entry.path();
        let metadata = fs::symlink_metadata(&path)?;
        if metadata.file_type().is_symlink() {
            return Err(ArtifactOwnerReconciliationError::PathBoundary);
        }
        let relative = path
            .strip_prefix(root)
            .map_err(|_| ArtifactOwnerReconciliationError::PathBoundary)?
            .to_path_buf();
        validate_relative(&relative)?;
        if relative == Path::new("writer/owner.lock")
            || relative.starts_with("host/status")
            || relative.starts_with("host/backups")
        {
            continue;
        }
        if metadata.is_dir() {
            collect_files(root, &path, output)?;
        } else if metadata.is_file() {
            if output.len() >= MAX_BACKUP_FILES {
                return Err(ArtifactOwnerReconciliationError::Capacity);
            }
            output.push(relative);
        } else {
            return Err(ArtifactOwnerReconciliationError::PathBoundary);
        }
    }
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct BackupRecordV1 {
    relative: PathBuf,
    bytes: u64,
    digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct BackupManifestV1 {
    backup_id: StableId,
    total_bytes: u64,
    records: Vec<BackupRecordV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct BackupCompleteV1 {
    backup_id: StableId,
    manifest_digest: Digest32,
    file_count: usize,
    total_bytes: u64,
}

fn encode_manifest(
    backup_id: &StableId,
    records: &[BackupRecordV1],
    total_bytes: u64,
) -> Result<Vec<u8>, ArtifactOwnerReconciliationError> {
    let mut output = format!(
        "{BACKUP_MANIFEST_MAGIC}\n{backup_id}\n{}\n{total_bytes}\n",
        records.len()
    );
    for record in records {
        let relative = record
            .relative
            .to_str()
            .ok_or(ArtifactOwnerReconciliationError::PathBoundary)?;
        if relative.contains(['\n', '\r', '|']) {
            return Err(ArtifactOwnerReconciliationError::PathBoundary);
        }
        output.push_str(&format!(
            "{relative}|{}|{}\n",
            record.bytes, record.digest
        ));
    }
    Ok(output.into_bytes())
}

fn decode_manifest(bytes: &[u8]) -> Result<BackupManifestV1, ArtifactOwnerReconciliationError> {
    let text = std::str::from_utf8(bytes)
        .map_err(|_| ArtifactOwnerReconciliationError::CorruptBackup)?;
    if !text.ends_with('\n') {
        return Err(ArtifactOwnerReconciliationError::CorruptBackup);
    }
    let mut lines = text.lines();
    if lines.next() != Some(BACKUP_MANIFEST_MAGIC) {
        return Err(ArtifactOwnerReconciliationError::CorruptBackup);
    }
    let backup_id = StableId::new(
        lines
            .next()
            .ok_or(ArtifactOwnerReconciliationError::CorruptBackup)?
            .to_owned(),
    )
    .map_err(|_| ArtifactOwnerReconciliationError::CorruptBackup)?;
    let count = parse_usize(lines.next())?;
    let total_bytes = parse_u64(lines.next())?;
    if count > MAX_BACKUP_FILES || total_bytes > MAX_BACKUP_TOTAL_BYTES {
        return Err(ArtifactOwnerReconciliationError::Capacity);
    }
    let mut records = Vec::with_capacity(count);
    for _ in 0..count {
        let line = lines
            .next()
            .ok_or(ArtifactOwnerReconciliationError::CorruptBackup)?;
        let fields: Vec<_> = line.split('|').collect();
        if fields.len() != 3 {
            return Err(ArtifactOwnerReconciliationError::CorruptBackup);
        }
        let relative = PathBuf::from(fields[0]);
        validate_relative(&relative)?;
        records.push(BackupRecordV1 {
            relative,
            bytes: fields[1]
                .parse()
                .map_err(|_| ArtifactOwnerReconciliationError::CorruptBackup)?,
            digest: Digest32::from_str(fields[2])
                .map_err(|_| ArtifactOwnerReconciliationError::CorruptBackup)?,
        });
    }
    if lines.next().is_some()
        || records.iter().map(|record| record.bytes).sum::<u64>() != total_bytes
    {
        return Err(ArtifactOwnerReconciliationError::CorruptBackup);
    }
    Ok(BackupManifestV1 {
        backup_id,
        total_bytes,
        records,
    })
}

fn decode_complete(bytes: &[u8]) -> Result<BackupCompleteV1, ArtifactOwnerReconciliationError> {
    let text = std::str::from_utf8(bytes)
        .map_err(|_| ArtifactOwnerReconciliationError::CorruptBackup)?;
    let lines: Vec<_> = text.lines().collect();
    if lines.len() != 5 || lines[0] != BACKUP_COMPLETE_MAGIC || !text.ends_with('\n') {
        return Err(ArtifactOwnerReconciliationError::CorruptBackup);
    }
    Ok(BackupCompleteV1 {
        backup_id: StableId::new(lines[1].to_owned())
            .map_err(|_| ArtifactOwnerReconciliationError::CorruptBackup)?,
        manifest_digest: Digest32::from_str(lines[2])
            .map_err(|_| ArtifactOwnerReconciliationError::CorruptBackup)?,
        file_count: lines[3]
            .parse()
            .map_err(|_| ArtifactOwnerReconciliationError::CorruptBackup)?,
        total_bytes: lines[4]
            .parse()
            .map_err(|_| ArtifactOwnerReconciliationError::CorruptBackup)?,
    })
}

fn read_bounded_file(
    path: &Path,
    maximum: u64,
) -> Result<Vec<u8>, ArtifactOwnerReconciliationError> {
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() || metadata.len() > maximum {
        return Err(ArtifactOwnerReconciliationError::PathBoundary);
    }
    let mut bytes = Vec::with_capacity(metadata.len() as usize);
    File::open(path)?
        .take(maximum + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > maximum {
        return Err(ArtifactOwnerReconciliationError::Capacity);
    }
    Ok(bytes)
}

fn ensure_parent_directories(
    trusted_root: &Path,
    file: &Path,
) -> Result<(), ArtifactOwnerReconciliationError> {
    let parent = file
        .parent()
        .ok_or(ArtifactOwnerReconciliationError::PathBoundary)?;
    let relative = parent
        .strip_prefix(trusted_root)
        .map_err(|_| ArtifactOwnerReconciliationError::PathBoundary)?;
    let mut current = trusted_root.to_path_buf();
    for component in relative.components() {
        let Component::Normal(name) = component else {
            return Err(ArtifactOwnerReconciliationError::PathBoundary);
        };
        current.push(name);
        if current.exists() {
            let metadata = fs::symlink_metadata(&current)?;
            if metadata.file_type().is_symlink() || !metadata.is_dir() {
                return Err(ArtifactOwnerReconciliationError::PathBoundary);
            }
        } else {
            create_directory(&current)?;
        }
    }
    Ok(())
}

fn create_directory(path: &Path) -> Result<(), ArtifactOwnerReconciliationError> {
    let parent = path
        .parent()
        .ok_or(ArtifactOwnerReconciliationError::PathBoundary)?;
    let mut builder = fs::DirBuilder::new();
    #[cfg(unix)]
    builder.mode(0o700);
    builder.create(path)?;
    sync_directory_v1(parent).map_err(ArtifactOwnerReconciliationError::Durability)
}

fn validate_relative(path: &Path) -> Result<(), ArtifactOwnerReconciliationError> {
    if path.as_os_str().is_empty()
        || path.is_absolute()
        || path.components().any(|component| !matches!(component, Component::Normal(_)))
    {
        return Err(ArtifactOwnerReconciliationError::PathBoundary);
    }
    Ok(())
}

fn parse_usize(value: Option<&str>) -> Result<usize, ArtifactOwnerReconciliationError> {
    value
        .ok_or(ArtifactOwnerReconciliationError::CorruptBackup)?
        .parse()
        .map_err(|_| ArtifactOwnerReconciliationError::CorruptBackup)
}

fn parse_u64(value: Option<&str>) -> Result<u64, ArtifactOwnerReconciliationError> {
    value
        .ok_or(ArtifactOwnerReconciliationError::CorruptBackup)?
        .parse()
        .map_err(|_| ArtifactOwnerReconciliationError::CorruptBackup)
}

#[derive(Debug)]
pub enum ArtifactOwnerReconciliationError {
    Io(std::io::Error),
    Durability(HostDurabilityError),
    PathBoundary,
    Capacity,
    CorruptBackup,
    RestoreTargetNotEmpty,
    UnsupportedSchema,
}

impl fmt::Display for ArtifactOwnerReconciliationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ArtifactOwnerReconciliationError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Io(error) => Some(error),
            Self::Durability(error) => Some(error),
            Self::PathBoundary
            | Self::Capacity
            | Self::CorruptBackup
            | Self::RestoreTargetNotEmpty
            | Self::UnsupportedSchema => None,
        }
    }
}

impl From<std::io::Error> for ArtifactOwnerReconciliationError {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value)
    }
}
