use std::collections::BTreeMap;
use std::fs;
use std::fs::File;
#[cfg(unix)]
use std::os::unix::fs::DirBuilderExt;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;
use std::sync::Arc;

use codex_hepta_types::Digest32;

use crate::ArtifactOwnerDurabilityV1;
use crate::DatasetWithdrawalRegistry;
use crate::DatasetWithdrawalSnapshotReceiptV1;
use crate::DirectoryDurabilityProfileV1;
use crate::LearningArtifactOwnerService;
use crate::directory_durability_profile_v1;
use crate::read_dataset_withdrawal_snapshot;
use crate::sync_parent_directory;
use crate::write_dataset_withdrawal_snapshot_beneath;

use super::capability_validation::LearningArtifactHostAccessPolicyV1;
use super::capability_validation::LearningArtifactHostAccessVerifierV1;
use super::reconciliation::LearningArtifactAuditJournalV1;
use super::reconciliation::LearningArtifactHostLifecycleV1;
use super::reconciliation::LearningArtifactHostMetricsV1;
use super::reference_host::LearningArtifactReferenceHostConfigV1;
use super::reference_host::LearningArtifactReferenceHostError;
use super::reference_host::LearningArtifactReferenceHostV1;

const CONTROL_ROOT_NAME: &str = "host-control";
const POLICY_FILE_LIMIT: usize = 64;
const WITHDRAWAL_FILE_LIMIT: usize = 8_192;
const CONTROL_FILE_LIMIT: usize = 1024 * 1024;
const SCHEMA_MAGIC: &str = "HEPTA-LEARNING-ARTIFACT-HOST-SCHEMA-V1";
const WITHDRAWAL_RECEIPT_MAGIC: &str =
    "HEPTA-LEARNING-ARTIFACT-HOST-WITHDRAWAL-RECEIPT-V1";

impl LearningArtifactReferenceHostV1 {
    pub fn open(
        config: LearningArtifactReferenceHostConfigV1,
        durability: Arc<dyn ArtifactOwnerDurabilityV1>,
    ) -> Result<Self, LearningArtifactReferenceHostError> {
        if config.maximum_supported_control_schema_version == 0 {
            return Err(LearningArtifactReferenceHostError::SchemaGeneration);
        }
        if directory_durability_profile_v1()
            != DirectoryDurabilityProfileV1::UnixDirectorySync
        {
            return Err(LearningArtifactReferenceHostError::UnsupportedTarget);
        }
        let root = provision_private_root(&config.service.root, &durability)?;
        let owner_trust = config.service.trust.clone();
        let storage_binding = config.service.storage_binding;
        let withdrawal_registry = config.service.withdrawal_registry.clone();
        let access = LearningArtifactHostAccessVerifierV1::new(
            config.access_policy,
            &owner_trust,
        )?;
        let service = LearningArtifactOwnerService::open(config.service)?;
        let control_root = provision_control_directories(&root, &durability)?;
        validate_or_create_policy_anchor(
            &control_root,
            access.policy(),
            &durability,
        )?;
        let schema_version = validate_or_create_schema_anchor(
            &control_root,
            config.maximum_supported_control_schema_version,
            &durability,
        )?;
        let withdrawal_receipt = validate_or_create_withdrawal_anchor(
            &root,
            &control_root,
            &withdrawal_registry,
            storage_binding,
            &durability,
        )?;
        let audit = LearningArtifactAuditJournalV1::open(&control_root)?;
        let lifecycle = service.recovery_required().map_or(
            LearningArtifactHostLifecycleV1::Ready,
            |operation| LearningArtifactHostLifecycleV1::Recovering(operation.clone()),
        );
        let metrics = LearningArtifactHostMetricsV1 {
            audit_events: audit.len() as u64,
            ..LearningArtifactHostMetricsV1::default()
        };
        Ok(Self {
            root,
            control_root,
            storage_binding,
            owner_trust,
            service,
            access,
            durability,
            audit,
            lifecycle,
            metrics,
            schema_version,
            maximum_supported_control_schema_version: config.maximum_supported_control_schema_version,
            withdrawal_receipt,
        })
    }
}

fn provision_private_root(
    root: &Path,
    durability: &Arc<dyn ArtifactOwnerDurabilityV1>,
) -> Result<PathBuf, LearningArtifactReferenceHostError> {
    if !root.exists() {
        let mut builder = fs::DirBuilder::new();
        builder.recursive(true);
        #[cfg(unix)]
        builder.mode(0o700);
        builder.create(root)?;
        #[cfg(unix)]
        fs::set_permissions(root, fs::Permissions::from_mode(0o700))?;
        sync_parent_directory(root)?;
    }
    validate_private_directory(root)?;
    let canonical = fs::canonicalize(root)?;
    durability.sync_control_root(&canonical)?;
    Ok(canonical)
}

fn provision_control_directories(
    root: &Path,
    durability: &Arc<dyn ArtifactOwnerDurabilityV1>,
) -> Result<PathBuf, LearningArtifactReferenceHostError> {
    let control_root = root.join(CONTROL_ROOT_NAME);
    for path in [
        control_root.clone(),
        control_root.join("audit"),
        control_root.join("policy"),
        control_root.join("withdrawals"),
        control_root.join("backups"),
        control_root.join("schema"),
        control_root.join("shutdown"),
    ] {
        if !path.exists() {
            let mut builder = fs::DirBuilder::new();
            #[cfg(unix)]
            builder.mode(0o700);
            builder.create(&path)?;
            #[cfg(unix)]
            fs::set_permissions(&path, fs::Permissions::from_mode(0o700))?;
            sync_parent_directory(&path)?;
        }
        validate_private_directory(&path)?;
        durability.sync_control_root(&path)?;
    }
    durability.sync_control_root(root)?;
    Ok(control_root)
}

fn validate_private_directory(path: &Path) -> Result<(), LearningArtifactReferenceHostError> {
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(LearningArtifactReferenceHostError::InvalidRoot);
    }
    #[cfg(unix)]
    if metadata.permissions().mode() & 0o077 != 0 {
        return Err(LearningArtifactReferenceHostError::InsecureRoot);
    }
    Ok(())
}

fn validate_or_create_policy_anchor(
    control_root: &Path,
    policy: &LearningArtifactHostAccessPolicyV1,
    durability: &Arc<dyn ArtifactOwnerDurabilityV1>,
) -> Result<(), LearningArtifactReferenceHostError> {
    let policy_root = control_root.join("policy");
    let mut anchors = BTreeMap::new();
    for entry in fs::read_dir(&policy_root)? {
        let entry = entry?;
        let file_type = entry.file_type()?;
        if file_type.is_symlink() || !file_type.is_file() {
            return Err(LearningArtifactReferenceHostError::PolicyAnchorConflict);
        }
        let name = entry
            .file_name()
            .into_string()
            .map_err(|_| LearningArtifactReferenceHostError::PolicyAnchorConflict)?;
        let (generation, digest) = parse_policy_file_name(&name)?;
        if anchors.insert(generation, (digest, entry.path())).is_some() {
            return Err(LearningArtifactReferenceHostError::PolicyAnchorConflict);
        }
    }
    if anchors.len() > POLICY_FILE_LIMIT {
        return Err(LearningArtifactReferenceHostError::PolicyAnchorConflict);
    }
    let canonical = policy.canonical_bytes();
    let expected_digest = Digest32::of_bytes(&canonical);
    if let Some((generation, (digest, path))) = anchors.last_key_value() {
        if *generation != policy.generation || *digest != expected_digest {
            return Err(LearningArtifactReferenceHostError::PolicyAnchorConflict);
        }
        let bytes = read_bounded_control_file(path)?;
        if bytes != canonical || Digest32::of_bytes(&bytes) != *digest {
            return Err(LearningArtifactReferenceHostError::PolicyAnchorConflict);
        }
        return Ok(());
    }
    let relative = PathBuf::from("policy").join(format!(
        "{:020}-{}.policy",
        policy.generation, expected_digest
    ));
    durability.create_control_file(control_root, &relative, &canonical)?;
    durability.sync_control_root(&policy_root)?;
    durability.sync_control_root(control_root)?;
    Ok(())
}

fn parse_policy_file_name(
    name: &str,
) -> Result<(u64, Digest32), LearningArtifactReferenceHostError> {
    let stem = name
        .strip_suffix(".policy")
        .ok_or(LearningArtifactReferenceHostError::PolicyAnchorConflict)?;
    let (generation, digest) = stem
        .split_once('-')
        .ok_or(LearningArtifactReferenceHostError::PolicyAnchorConflict)?;
    let generation = generation
        .parse()
        .map_err(|_| LearningArtifactReferenceHostError::PolicyAnchorConflict)?;
    let digest = Digest32::from_str(digest)
        .map_err(|_| LearningArtifactReferenceHostError::PolicyAnchorConflict)?;
    Ok((generation, digest))
}

fn validate_or_create_schema_anchor(
    control_root: &Path,
    maximum_supported_version: u32,
    durability: &Arc<dyn ArtifactOwnerDurabilityV1>,
) -> Result<u32, LearningArtifactReferenceHostError> {
    let schema_root = control_root.join("schema");
    let mut versions = BTreeMap::new();
    for entry in fs::read_dir(&schema_root)? {
        let entry = entry?;
        let file_type = entry.file_type()?;
        if file_type.is_symlink() || !file_type.is_file() {
            return Err(LearningArtifactReferenceHostError::SchemaAnchorConflict);
        }
        let name = entry
            .file_name()
            .into_string()
            .map_err(|_| LearningArtifactReferenceHostError::SchemaAnchorConflict)?;
        let version = name
            .strip_suffix(".anchor")
            .ok_or(LearningArtifactReferenceHostError::SchemaAnchorConflict)?
            .parse::<u32>()
            .map_err(|_| LearningArtifactReferenceHostError::SchemaAnchorConflict)?;
        if version == 0 {
            return Err(LearningArtifactReferenceHostError::SchemaAnchorConflict);
        }
        let path = entry.path();
        if versions.insert(version, path.clone()).is_some()
            || read_bounded_control_file(&path)? != schema_anchor_bytes(version)
        {
            return Err(LearningArtifactReferenceHostError::SchemaAnchorConflict);
        }
    }
    if let Some((version, _)) = versions.last_key_value() {
        if *version > maximum_supported_version {
            return Err(LearningArtifactReferenceHostError::SchemaAnchorConflict);
        }
        return Ok(*version);
    }
    let initial_version = 1;
    if initial_version > maximum_supported_version {
        return Err(LearningArtifactReferenceHostError::SchemaAnchorConflict);
    }
    let expected = schema_anchor_bytes(initial_version);
    let relative = PathBuf::from("schema").join(format!("{initial_version:010}.anchor"));
    durability.create_control_file(control_root, &relative, &expected)?;
    durability.sync_control_root(&schema_root)?;
    durability.sync_control_root(control_root)?;
    Ok(initial_version)
}

pub(super) fn schema_anchor_bytes(version: u32) -> Vec<u8> {
    format!("{SCHEMA_MAGIC}|{version}\n").into_bytes()
}

pub(super) fn validate_or_create_withdrawal_anchor(
    root: &Path,
    control_root: &Path,
    registry: &DatasetWithdrawalRegistry,
    binding: Digest32,
    durability: &Arc<dyn ArtifactOwnerDurabilityV1>,
) -> Result<DatasetWithdrawalSnapshotReceiptV1, LearningArtifactReferenceHostError> {
    let withdrawal_root = control_root.join("withdrawals");
    let mut snapshots = BTreeMap::new();
    let mut receipts = BTreeMap::new();
    let mut count = 0_usize;
    for entry in fs::read_dir(&withdrawal_root)? {
        count = count.saturating_add(1);
        if count > WITHDRAWAL_FILE_LIMIT {
            return Err(LearningArtifactReferenceHostError::WithdrawalAnchorConflict);
        }
        let entry = entry?;
        let file_type = entry.file_type()?;
        if file_type.is_symlink() || !file_type.is_file() {
            return Err(LearningArtifactReferenceHostError::WithdrawalAnchorConflict);
        }
        let name = entry
            .file_name()
            .into_string()
            .map_err(|_| LearningArtifactReferenceHostError::WithdrawalAnchorConflict)?;
        if let Some(stem) = name.strip_suffix(".snapshot") {
            if snapshots.insert(stem.to_owned(), entry.path()).is_some() {
                return Err(LearningArtifactReferenceHostError::WithdrawalAnchorConflict);
            }
        } else if let Some(stem) = name.strip_suffix(".receipt") {
            if receipts.insert(stem.to_owned(), entry.path()).is_some() {
                return Err(LearningArtifactReferenceHostError::WithdrawalAnchorConflict);
            }
        } else {
            return Err(LearningArtifactReferenceHostError::WithdrawalAnchorConflict);
        }
    }
    if snapshots.keys().ne(receipts.keys()) {
        return Err(LearningArtifactReferenceHostError::WithdrawalAnchorConflict);
    }
    if snapshots.is_empty() {
        return persist_withdrawal_anchor(root, control_root, registry, binding, durability);
    }
    let (stem, snapshot_path) = snapshots
        .last_key_value()
        .ok_or(LearningArtifactReferenceHostError::WithdrawalAnchorConflict)?;
    let receipt_path = receipts
        .get(stem)
        .ok_or(LearningArtifactReferenceHostError::WithdrawalAnchorConflict)?;
    let receipt = parse_withdrawal_receipt(&read_bounded_control_file(receipt_path)?)?;
    if stem != &withdrawal_stem(receipt)
        || receipt.binding != binding
        || receipt.scope_digest != registry.scope_digest().ok_or(
            LearningArtifactReferenceHostError::WithdrawalAnchorConflict,
        )?
        || receipt.head_digest != registry.head_digest()
        || receipt.records != registry.snapshot().records().len()
    {
        return Err(LearningArtifactReferenceHostError::WithdrawalAnchorConflict);
    }
    let recovered = read_dataset_withdrawal_snapshot(File::open(snapshot_path)?, receipt)?;
    if recovered.snapshot() != registry.snapshot() {
        return Err(LearningArtifactReferenceHostError::WithdrawalAnchorConflict);
    }
    Ok(receipt)
}

pub(super) fn persist_withdrawal_anchor(
    root: &Path,
    control_root: &Path,
    registry: &DatasetWithdrawalRegistry,
    binding: Digest32,
    durability: &Arc<dyn ArtifactOwnerDurabilityV1>,
) -> Result<DatasetWithdrawalSnapshotReceiptV1, LearningArtifactReferenceHostError> {
    let preliminary_stem = format!(
        "{:020}-{}",
        registry.snapshot().records().len(),
        registry.head_digest()
    );
    let snapshot_relative = PathBuf::from(CONTROL_ROOT_NAME)
        .join("withdrawals")
        .join(format!("{preliminary_stem}.snapshot"));
    let receipt = write_dataset_withdrawal_snapshot_beneath(
        root,
        &snapshot_relative,
        registry,
        binding,
    )?;
    let stem = withdrawal_stem(receipt);
    if stem != preliminary_stem {
        return Err(LearningArtifactReferenceHostError::WithdrawalAnchorConflict);
    }
    let receipt_relative = PathBuf::from("withdrawals").join(format!("{stem}.receipt"));
    durability.create_control_file(
        control_root,
        &receipt_relative,
        &withdrawal_receipt_bytes(receipt),
    )?;
    durability.sync_control_root(&control_root.join("withdrawals"))?;
    durability.sync_control_root(control_root)?;
    Ok(receipt)
}

fn withdrawal_stem(receipt: DatasetWithdrawalSnapshotReceiptV1) -> String {
    format!("{:020}-{}", receipt.records, receipt.head_digest)
}

fn withdrawal_receipt_bytes(receipt: DatasetWithdrawalSnapshotReceiptV1) -> Vec<u8> {
    format!(
        "{WITHDRAWAL_RECEIPT_MAGIC}|{}|{}|{}|{}|{}|{}\n",
        receipt.binding,
        receipt.scope_digest,
        receipt.head_digest,
        receipt.file_digest,
        receipt.records,
        receipt.encoded_bytes,
    )
    .into_bytes()
}

fn parse_withdrawal_receipt(
    bytes: &[u8],
) -> Result<DatasetWithdrawalSnapshotReceiptV1, LearningArtifactReferenceHostError> {
    let text = std::str::from_utf8(bytes)
        .map_err(|_| LearningArtifactReferenceHostError::WithdrawalAnchorConflict)?;
    if !text.ends_with('\n') || text[..text.len() - 1].contains('\n') {
        return Err(LearningArtifactReferenceHostError::WithdrawalAnchorConflict);
    }
    let parts: Vec<&str> = text[..text.len() - 1].split('|').collect();
    if parts.len() != 7 || parts[0] != WITHDRAWAL_RECEIPT_MAGIC {
        return Err(LearningArtifactReferenceHostError::WithdrawalAnchorConflict);
    }
    let receipt = DatasetWithdrawalSnapshotReceiptV1 {
        binding: Digest32::from_str(parts[1])
            .map_err(|_| LearningArtifactReferenceHostError::WithdrawalAnchorConflict)?,
        scope_digest: Digest32::from_str(parts[2])
            .map_err(|_| LearningArtifactReferenceHostError::WithdrawalAnchorConflict)?,
        head_digest: Digest32::from_str(parts[3])
            .map_err(|_| LearningArtifactReferenceHostError::WithdrawalAnchorConflict)?,
        file_digest: Digest32::from_str(parts[4])
            .map_err(|_| LearningArtifactReferenceHostError::WithdrawalAnchorConflict)?,
        records: parts[5]
            .parse()
            .map_err(|_| LearningArtifactReferenceHostError::WithdrawalAnchorConflict)?,
        encoded_bytes: parts[6]
            .parse()
            .map_err(|_| LearningArtifactReferenceHostError::WithdrawalAnchorConflict)?,
    };
    if withdrawal_receipt_bytes(receipt) != bytes {
        return Err(LearningArtifactReferenceHostError::WithdrawalAnchorConflict);
    }
    Ok(receipt)
}

fn read_bounded_control_file(
    path: &Path,
) -> Result<Vec<u8>, LearningArtifactReferenceHostError> {
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.len() == 0
        || metadata.len() > CONTROL_FILE_LIMIT as u64
    {
        return Err(LearningArtifactReferenceHostError::InvalidRoot);
    }
    Ok(fs::read(path)?)
}

pub(super) fn persist_policy_anchor(
    control_root: &Path,
    policy: &LearningArtifactHostAccessPolicyV1,
    durability: &Arc<dyn ArtifactOwnerDurabilityV1>,
) -> Result<(), LearningArtifactReferenceHostError> {
    let canonical = policy.canonical_bytes();
    let digest = Digest32::of_bytes(&canonical);
    let relative = PathBuf::from("policy").join(format!(
        "{:020}-{digest}.policy",
        policy.generation
    ));
    durability.create_control_file(control_root, &relative, &canonical)?;
    durability.sync_control_root(&control_root.join("policy"))?;
    durability.sync_control_root(control_root)?;
    Ok(())
}

pub(super) fn persist_schema_anchor(
    control_root: &Path,
    version: u32,
    durability: &Arc<dyn ArtifactOwnerDurabilityV1>,
) -> Result<(), LearningArtifactReferenceHostError> {
    let relative = PathBuf::from("schema").join(format!("{version:010}.anchor"));
    durability.create_control_file(control_root, &relative, &schema_anchor_bytes(version))?;
    durability.sync_control_root(&control_root.join("schema"))?;
    durability.sync_control_root(control_root)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn schema_anchor_is_canonical() {
        assert_eq!(
            schema_anchor_bytes(1),
            b"HEPTA-LEARNING-ARTIFACT-HOST-SCHEMA-V1|1\n"
        );
    }
}
