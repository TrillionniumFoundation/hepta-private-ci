use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::net::SocketAddr;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::ArtifactOwnerTrustV1;
use crate::DatasetWithdrawalRegistry;
use crate::DatasetWithdrawalScopeV1;
use crate::DatasetWithdrawalSnapshotReceiptV1;
use crate::LearningArtifactOwnerServiceConfigV1;
use crate::RegistryHeadWitnessV1;
use crate::SignedArtifactWriterLeaseV1;
use crate::SignedCurrentArtifactHeadV1;
use crate::TrustedArtifactSignerV1;
use crate::durable_write_new_v1;
use crate::provision_private_root_v1;
use crate::read_dataset_withdrawal_snapshot;

use super::ArtifactOwnerActionV1;
use super::ArtifactOwnerClientGrantV1;
use super::ArtifactOwnerKeyringV1;

const CONFIG_SCHEMA: &str = "hepta.learning-artifactd.config.v1";
const AUTHZ_SCHEMA: &str = "hepta.learning-artifactd.authz.v1";
const CURRENT_HEAD_SCHEMA: &str = "hepta.learning-artifactd.current-head.v1";
const OWNER_SCHEMA_MAGIC: &[u8] = b"HEPTA-LEARNING-ARTIFACTD-SCHEMA-V1\nversion=1\n";
const MAX_CONFIG_BYTES: u64 = 256 * 1024;
const MAX_SIGNERS: usize = 32;
const MAX_CLIENTS: usize = 64;

#[derive(Clone, Debug)]
pub struct ArtifactOwnerBootstrapConfigV1 {
    pub config_path: PathBuf,
    pub now: u64,
}

#[derive(Clone, Debug)]
pub struct ArtifactOwnerRuntimeConfigV1 {
    pub listen_address: SocketAddr,
    pub authz_path: PathBuf,
    pub backup_root: PathBuf,
    pub service: LearningArtifactOwnerServiceConfigV1,
    pub maximum_request_bytes: usize,
}

#[derive(Clone, Debug)]
pub struct ArtifactOwnerBootstrapV1 {
    pub runtime: ArtifactOwnerRuntimeConfigV1,
    pub keyring: ArtifactOwnerKeyringV1,
}

impl ArtifactOwnerBootstrapV1 {
    pub fn load(
        request: ArtifactOwnerBootstrapConfigV1,
    ) -> Result<Self, ArtifactOwnerConfigError> {
        let config = read_key_value_file(&request.config_path, CONFIG_SCHEMA)?;
        let root = required_absolute_path(&config, "root")?;
        let root = provision_private_root_v1(&root)
            .map_err(|error| ArtifactOwnerConfigError::Durability(error.to_string()))?;
        ensure_owner_schema(&root)?;

        let listen_address = required(&config, "listen")?
            .parse::<SocketAddr>()
            .map_err(|_| invalid_value("listen"))?;
        if !listen_address.ip().is_loopback() {
            return Err(ArtifactOwnerConfigError::NonLoopbackTransport);
        }
        let authz_path = required_absolute_path(&config, "authz_file")?;
        validate_secure_regular_file(&authz_path)?;
        let backup_root = required_absolute_path(&config, "backup_root")?;
        if backup_root.starts_with(&root) || root.starts_with(&backup_root) {
            return Err(invalid_value("backup_root"));
        }

        let registry_id = parse_id(required(&config, "registry_id")?)?;
        let withdrawal_scope_digest = parse_digest(required(
            &config,
            "withdrawal_scope_digest",
        )?)?;
        let trust = ArtifactOwnerTrustV1 {
            registry_id: registry_id.clone(),
            withdrawal_scope_digest,
            minimum_registry_generation: parse_generation(required(
                &config,
                "minimum_registry_generation",
            )?)?,
            genesis_predecessor_head_digest: parse_digest(required(
                &config,
                "genesis_predecessor_head_digest",
            )?)?,
            minimum_authority_epoch: parse_nonzero_u64(required(
                &config,
                "minimum_authority_epoch",
            )?)?,
            writer_signers: parse_signers(&config, "writer_signer.")?,
            head_signers: parse_signers(&config, "head_signer.")?,
        };
        let writer_lease = SignedArtifactWriterLeaseV1 {
            lease_id: parse_id(required(&config, "lease_id")?)?,
            producer_id: parse_id(required(&config, "producer_id")?)?,
            registry_id,
            withdrawal_scope_digest,
            signer_id: parse_id(required(&config, "lease_signer_id")?)?,
            signing_key_digest: parse_digest(required(
                &config,
                "lease_signing_key_digest",
            )?)?,
            authority_epoch: parse_nonzero_u64(required(
                &config,
                "lease_authority_epoch",
            )?)?,
            lease_generation: parse_nonzero_u64(required(
                &config,
                "lease_generation",
            )?)?,
            issued_at: parse_u64(required(&config, "lease_issued_at")?)?,
            expires_at: parse_u64(required(&config, "lease_expires_at")?)?,
            signature: decode_fixed_hex::<64>(required(&config, "lease_signature")?)?,
        };

        let storage_binding = parse_digest(required(&config, "storage_binding")?)?;
        if storage_binding.is_zero() {
            return Err(invalid_value("storage_binding"));
        }
        let withdrawal_registry = load_withdrawal_registry(&config)?;
        if withdrawal_registry.scope_digest() != Some(withdrawal_scope_digest) {
            return Err(ArtifactOwnerConfigError::WithdrawalScopeMismatch);
        }

        let required_current_head = match optional(&config, "required_current_head_file") {
            None | Some("-") => None,
            Some(path) => {
                let path = PathBuf::from(path);
                if !path.is_absolute() {
                    return Err(invalid_value(
                        "required_current_head_file",
                    ));
                }
                Some(load_current_head(&path)?)
            }
        };
        require_restart_anchor_when_published(&root, required_current_head.as_ref())?;

        let maximum_request_bytes = optional(&config, "maximum_request_bytes")
            .map(parse_usize)
            .transpose()?
            .unwrap_or(2 * 1024 * 1024);
        if !(4096..=4 * 1024 * 1024).contains(&maximum_request_bytes) {
            return Err(invalid_value(
                "maximum_request_bytes",
            ));
        }

        let keyring = load_keyring(&authz_path)?;
        Ok(Self {
            runtime: ArtifactOwnerRuntimeConfigV1 {
                listen_address,
                authz_path,
                backup_root,
                service: LearningArtifactOwnerServiceConfigV1 {
                    root,
                    trust,
                    writer_lease,
                    required_current_head,
                    withdrawal_registry,
                    storage_binding,
                    now: request.now,
                },
                maximum_request_bytes,
            },
            keyring,
        })
    }
}

pub(crate) fn load_keyring(
    path: &Path,
) -> Result<ArtifactOwnerKeyringV1, ArtifactOwnerConfigError> {
    validate_secure_regular_file(path)?;
    let values = read_key_value_file(path, AUTHZ_SCHEMA)?;
    let generation = parse_nonzero_u64(required(&values, "generation")?)?;
    let mut clients = Vec::new();
    for (name, value) in values
        .iter()
        .filter(|(name, _)| name.starts_with("client."))
    {
        if clients.len() >= MAX_CLIENTS {
            return Err(ArtifactOwnerConfigError::Capacity);
        }
        let fields: Vec<_> = value.split('|').collect();
        if fields.len() != 6 {
            return Err(ArtifactOwnerConfigError::InvalidEntry(name.clone()));
        }
        let actions = fields[5]
            .split(',')
            .map(ArtifactOwnerActionV1::parse)
            .collect::<Result<BTreeSet<_>, _>>()
            .map_err(|_| ArtifactOwnerConfigError::InvalidEntry(name.clone()))?;
        clients.push(ArtifactOwnerClientGrantV1 {
            client_id: parse_id(fields[0])?,
            verifying_key: decode_fixed_hex::<32>(fields[1])?,
            valid_from: parse_u64(fields[2])?,
            expires_at: parse_u64(fields[3])?,
            revoked_at: parse_optional_u64(fields[4])?,
            allowed_actions: actions,
        });
    }
    ArtifactOwnerKeyringV1::new(generation, clients)
        .map_err(|error| ArtifactOwnerConfigError::Keyring(error.to_string()))
}

fn parse_signers(
    values: &BTreeMap<String, String>,
    prefix: &str,
) -> Result<Vec<TrustedArtifactSignerV1>, ArtifactOwnerConfigError> {
    let mut signers = Vec::new();
    for (name, value) in values.iter().filter(|(name, _)| name.starts_with(prefix)) {
        if signers.len() >= MAX_SIGNERS {
            return Err(ArtifactOwnerConfigError::Capacity);
        }
        let fields: Vec<_> = value.split('|').collect();
        if fields.len() != 7 {
            return Err(ArtifactOwnerConfigError::InvalidEntry(name.clone()));
        }
        signers.push(TrustedArtifactSignerV1 {
            signer_id: parse_id(fields[0])?,
            verifying_key: decode_fixed_hex::<32>(fields[1])?,
            minimum_authority_epoch: parse_nonzero_u64(fields[2])?,
            maximum_authority_epoch: parse_nonzero_u64(fields[3])?,
            valid_from: parse_u64(fields[4])?,
            expires_at: parse_u64(fields[5])?,
            revoked_at: parse_optional_u64(fields[6])?,
        });
    }
    if signers.is_empty() {
        return Err(invalid_value(prefix));
    }
    Ok(signers)
}

fn load_withdrawal_registry(
    values: &BTreeMap<String, String>,
) -> Result<DatasetWithdrawalRegistry, ArtifactOwnerConfigError> {
    match required(values, "withdrawal_mode")? {
        "genesis" => Ok(DatasetWithdrawalRegistry::new_scoped(
            DatasetWithdrawalScopeV1 {
                authority_domain_id: parse_id(required(
                    values,
                    "withdrawal_authority_domain_id",
                )?)?,
                registry_id: parse_id(required(values, "withdrawal_registry_id")?)?,
                scope_id: parse_id(required(values, "withdrawal_scope_id")?)?,
            },
        )),
        "snapshot" => {
            let path = required_absolute_path(values, "withdrawal_snapshot_path")?;
            validate_secure_regular_file(&path)?;
            let receipt = DatasetWithdrawalSnapshotReceiptV1 {
                binding: parse_digest(required(values, "withdrawal_receipt_binding")?)?,
                scope_digest: parse_digest(required(
                    values,
                    "withdrawal_receipt_scope_digest",
                )?)?,
                head_digest: parse_digest(required(
                    values,
                    "withdrawal_receipt_head_digest",
                )?)?,
                file_digest: parse_digest(required(
                    values,
                    "withdrawal_receipt_file_digest",
                )?)?,
                records: parse_usize(required(values, "withdrawal_receipt_records")?)?,
                encoded_bytes: parse_usize(required(
                    values,
                    "withdrawal_receipt_encoded_bytes",
                )?)?,
            };
            read_dataset_withdrawal_snapshot(File::open(path)?, receipt)
                .map_err(|error| ArtifactOwnerConfigError::Withdrawal(error.to_string()))
        }
        _ => Err(invalid_value("withdrawal_mode")),
    }
}

fn load_current_head(path: &Path) -> Result<SignedCurrentArtifactHeadV1, ArtifactOwnerConfigError> {
    validate_secure_regular_file(path)?;
    let values = read_key_value_file(path, CURRENT_HEAD_SCHEMA)?;
    Ok(SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: parse_digest(required(
            &values,
            "withdrawal_scope_digest",
        )?)?,
        binding: parse_digest(required(&values, "binding")?)?,
        witness: RegistryHeadWitnessV1 {
            registry_id: parse_id(required(&values, "registry_id")?)?,
            generation: parse_generation(required(&values, "generation")?)?,
            head_digest: parse_digest(required(&values, "head_digest")?)?,
            predecessor_head_digest: parse_digest(required(
                &values,
                "predecessor_head_digest",
            )?)?,
            authority_epoch: parse_nonzero_u64(required(
                &values,
                "authority_epoch",
            )?)?,
            signer_id: parse_id(required(&values, "signer_id")?)?,
            signing_key_digest: parse_digest(required(
                &values,
                "signing_key_digest",
            )?)?,
            issued_at: parse_u64(required(&values, "issued_at")?)?,
            expires_at: parse_u64(required(&values, "expires_at")?)?,
        },
        signature: decode_fixed_hex::<64>(required(&values, "signature")?)?,
    })
}

fn require_restart_anchor_when_published(
    root: &Path,
    anchor: Option<&SignedCurrentArtifactHeadV1>,
) -> Result<(), ArtifactOwnerConfigError> {
    let heads = root.join("heads");
    let published = match fs::read_dir(&heads) {
        Ok(mut entries) => entries.try_fold(false, |seen, entry| {
            let entry = entry?;
            let metadata = fs::symlink_metadata(entry.path())?;
            if metadata.file_type().is_symlink() || !metadata.is_file() {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::InvalidData,
                    "invalid current-head entry",
                ));
            }
            Ok(seen
                || entry.path().extension().and_then(|value| value.to_str()) == Some("head"))
        })?,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => false,
        Err(error) => return Err(error.into()),
    };
    if published && anchor.is_none() {
        return Err(ArtifactOwnerConfigError::RestartAnchorRequired);
    }
    Ok(())
}

fn ensure_owner_schema(root: &Path) -> Result<(), ArtifactOwnerConfigError> {
    let host = root.join("host");
    if !host.exists() {
        fs::create_dir(&host)?;
        crate::sync_directory_v1(root)
            .map_err(|error| ArtifactOwnerConfigError::Durability(error.to_string()))?;
    }
    let marker = host.join("schema-v1");
    match fs::read(&marker) {
        Ok(bytes) if bytes == OWNER_SCHEMA_MAGIC => Ok(()),
        Ok(_) => Err(ArtifactOwnerConfigError::UnsupportedSchema),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            let has_legacy_state = [
                "transactions",
                "payloads",
                "registries",
                "witnesses",
                "heads",
            ]
            .iter()
            .any(|name| root.join(name).exists());
            if has_legacy_state {
                return Err(ArtifactOwnerConfigError::MigrationRequired);
            }
            durable_write_new_v1(marker, OWNER_SCHEMA_MAGIC)
                .map_err(|error| ArtifactOwnerConfigError::Durability(error.to_string()))
        }
        Err(error) => Err(error.into()),
    }
}

fn read_key_value_file(
    path: &Path,
    expected_schema: &str,
) -> Result<BTreeMap<String, String>, ArtifactOwnerConfigError> {
    validate_secure_regular_file(path)?;
    let metadata = fs::metadata(path)?;
    if metadata.len() == 0 || metadata.len() > MAX_CONFIG_BYTES {
        return Err(ArtifactOwnerConfigError::Capacity);
    }
    let text = fs::read_to_string(path)?;
    if !text.ends_with('\n') {
        return Err(ArtifactOwnerConfigError::NonCanonical);
    }
    let mut values = BTreeMap::new();
    for line in text.lines() {
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let (name, value) = line
            .split_once('=')
            .ok_or(ArtifactOwnerConfigError::NonCanonical)?;
        if name.is_empty()
            || value.is_empty()
            || name.bytes().any(|byte| !(byte.is_ascii_lowercase()
                || byte.is_ascii_digit()
                || matches!(byte, b'_' | b'.')))
            || values.insert(name.to_owned(), value.to_owned()).is_some()
        {
            return Err(ArtifactOwnerConfigError::NonCanonical);
        }
    }
    if values.get("schema").map(String::as_str) != Some(expected_schema) {
        return Err(ArtifactOwnerConfigError::WrongSchema);
    }
    Ok(values)
}

fn validate_secure_regular_file(path: &Path) -> Result<(), ArtifactOwnerConfigError> {
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(ArtifactOwnerConfigError::InvalidPath);
    }
    #[cfg(unix)]
    if metadata.permissions().mode() & 0o022 != 0 {
        return Err(ArtifactOwnerConfigError::InsecurePermissions);
    }
    Ok(())
}

fn required<'a>(
    values: &'a BTreeMap<String, String>,
    name: &str,
) -> Result<&'a str, ArtifactOwnerConfigError> {
    values
        .get(name)
        .map(String::as_str)
        .ok_or_else(|| ArtifactOwnerConfigError::Missing(name.to_owned()))
}

fn optional<'a>(values: &'a BTreeMap<String, String>, name: &str) -> Option<&'a str> {
    values.get(name).map(String::as_str)
}

fn required_absolute_path(
    values: &BTreeMap<String, String>,
    name: &str,
) -> Result<PathBuf, ArtifactOwnerConfigError> {
    let path = PathBuf::from(required(values, name)?);
    if !path.is_absolute() {
        return Err(invalid_value(name));
    }
    Ok(path)
}

fn invalid_value(name: &str) -> ArtifactOwnerConfigError {
    ArtifactOwnerConfigError::InvalidValue(name.to_owned())
}

fn parse_id(value: &str) -> Result<StableId, ArtifactOwnerConfigError> {
    StableId::new(value.to_owned()).map_err(|_| ArtifactOwnerConfigError::InvalidIdentifier)
}

fn parse_digest(value: &str) -> Result<Digest32, ArtifactOwnerConfigError> {
    Digest32::from_str(value).map_err(|_| ArtifactOwnerConfigError::InvalidDigest)
}

fn parse_generation(value: &str) -> Result<Generation, ArtifactOwnerConfigError> {
    Generation::new(parse_nonzero_u64(value)?)
        .map_err(|_| ArtifactOwnerConfigError::InvalidNumber)
}

fn parse_nonzero_u64(value: &str) -> Result<u64, ArtifactOwnerConfigError> {
    let value = parse_u64(value)?;
    if value == 0 {
        return Err(ArtifactOwnerConfigError::InvalidNumber);
    }
    Ok(value)
}

fn parse_u64(value: &str) -> Result<u64, ArtifactOwnerConfigError> {
    value
        .parse::<u64>()
        .map_err(|_| ArtifactOwnerConfigError::InvalidNumber)
}

fn parse_usize(value: &str) -> Result<usize, ArtifactOwnerConfigError> {
    value
        .parse::<usize>()
        .map_err(|_| ArtifactOwnerConfigError::InvalidNumber)
}

fn parse_optional_u64(value: &str) -> Result<Option<u64>, ArtifactOwnerConfigError> {
    if value == "-" {
        Ok(None)
    } else {
        parse_u64(value).map(Some)
    }
}

fn decode_fixed_hex<const N: usize>(
    value: &str,
) -> Result<[u8; N], ArtifactOwnerConfigError> {
    if value.len() != N * 2 {
        return Err(ArtifactOwnerConfigError::InvalidHex);
    }
    let mut bytes = [0; N];
    for (index, output) in bytes.iter_mut().enumerate() {
        let raw = value.as_bytes();
        let high = decode_nibble(raw[index * 2]).ok_or(ArtifactOwnerConfigError::InvalidHex)?;
        let low = decode_nibble(raw[index * 2 + 1])
            .ok_or(ArtifactOwnerConfigError::InvalidHex)?;
        *output = (high << 4) | low;
    }
    Ok(bytes)
}

const fn decode_nibble(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        _ => None,
    }
}

#[derive(Debug)]
pub enum ArtifactOwnerConfigError {
    Io(std::io::Error),
    Missing(String),
    InvalidValue(String),
    InvalidEntry(String),
    InvalidPath,
    InsecurePermissions,
    WrongSchema,
    NonCanonical,
    InvalidIdentifier,
    InvalidDigest,
    InvalidNumber,
    InvalidHex,
    Capacity,
    NonLoopbackTransport,
    WithdrawalScopeMismatch,
    Withdrawal(String),
    Keyring(String),
    RestartAnchorRequired,
    MigrationRequired,
    UnsupportedSchema,
    Durability(String),
}

impl fmt::Display for ArtifactOwnerConfigError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ArtifactOwnerConfigError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Io(error) => Some(error),
            Self::Missing(_)
            | Self::InvalidValue(_)
            | Self::InvalidEntry(_)
            | Self::InvalidPath
            | Self::InsecurePermissions
            | Self::WrongSchema
            | Self::NonCanonical
            | Self::InvalidIdentifier
            | Self::InvalidDigest
            | Self::InvalidNumber
            | Self::InvalidHex
            | Self::Capacity
            | Self::NonLoopbackTransport
            | Self::WithdrawalScopeMismatch
            | Self::Withdrawal(_)
            | Self::Keyring(_)
            | Self::RestartAnchorRequired
            | Self::MigrationRequired
            | Self::UnsupportedSchema
            | Self::Durability(_) => None,
        }
    }
}

impl From<std::io::Error> for ArtifactOwnerConfigError {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value)
    }
}
