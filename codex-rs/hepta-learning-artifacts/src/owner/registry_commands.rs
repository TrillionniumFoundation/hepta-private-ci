use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::path::PathBuf;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::ArtifactKind;
use crate::DatasetWithdrawalSnapshotReceiptV1;
use crate::LearningArtifactManifestV2;
use crate::ProvenanceModeV1;
use crate::RegistryHeadWitnessV1;
use crate::SignedCurrentArtifactHeadV1;

const PUBLISH_SCHEMA: &str = "hepta.learning-artifactd.publish.v1";
const INSTALL_WITHDRAWAL_SCHEMA: &str =
    "hepta.learning-artifactd.install-withdrawal-snapshot.v1";
const MAX_COMMAND_BYTES: usize = 2 * 1024 * 1024;
const MAX_LIST_ITEMS: usize = 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactManifestCommandV1 {
    pub manifest: LearningArtifactManifestV2,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PublishArtifactCommandV1 {
    pub operation_id: StableId,
    pub expected_withdrawal_head: Digest32,
    pub expected_registry_predecessor_head: Digest32,
    pub manifest: ArtifactManifestCommandV1,
    pub payload: Vec<u8>,
    pub signed_current_head: SignedCurrentArtifactHeadV1,
    pub now: u64,
}

impl PublishArtifactCommandV1 {
    pub fn encode(&self) -> Result<Vec<u8>, ArtifactOwnerCommandDecodeError> {
        let manifest = &self.manifest.manifest;
        if manifest.encoded_size_bytes != self.payload.len() as u64 {
            return Err(ArtifactOwnerCommandDecodeError::PayloadLength);
        }
        if manifest.bytes_digest != Digest32::of_bytes(&self.payload) {
            return Err(ArtifactOwnerCommandDecodeError::PayloadDigest);
        }
        let head = &self.signed_current_head;
        let text = format!(
            concat!(
                "schema={PUBLISH_SCHEMA}\n",
                "operation_id={}\nexpected_withdrawal_head={}\n",
                "expected_registry_predecessor_head={}\nartifact_id={}\nkind={}\n",
                "generation={}\nprovenance_mode={}\nsource_dataset_digests={}\n",
                "lineage_digests={}\npredecessor_ids={}\nrollback_predecessor={}\n",
                "bytes_digest={}\nencoded_size_bytes={}\ntraining_code_digest={}\n",
                "runtime_tuple_digest={}\ndevice_profile_digest={}\n",
                "objective_class_digest={}\ncompatibility_digest={}\n",
                "schema_profile_digest={}\nnormalization_digest={}\nproducer_id={}\n",
                "created_at={}\nexpires_at={}\npayload_hex={}\n",
                "head_withdrawal_scope_digest={}\nhead_binding={}\nhead_registry_id={}\n",
                "head_generation={}\nhead_digest={}\nhead_predecessor_head_digest={}\n",
                "head_authority_epoch={}\nhead_signer_id={}\nhead_signing_key_digest={}\n",
                "head_issued_at={}\nhead_expires_at={}\nhead_signature={}\n"
            ),
            self.operation_id,
            self.expected_withdrawal_head,
            self.expected_registry_predecessor_head,
            manifest.artifact_id,
            kind_name(manifest.kind),
            manifest.generation.get(),
            provenance_name(manifest.provenance_mode),
            join_digests(&manifest.source_dataset_digests),
            join_digests(&manifest.lineage_digests),
            join_ids(&manifest.predecessor_ids),
            manifest
                .rollback_predecessor
                .as_ref()
                .map_or("-", StableId::as_str),
            manifest.bytes_digest,
            manifest.encoded_size_bytes,
            manifest.training_code_digest,
            manifest.runtime_tuple_digest,
            manifest.device_profile_digest,
            manifest.objective_class_digest,
            manifest.compatibility_digest,
            manifest.schema_profile_digest,
            manifest.normalization_digest,
            manifest.producer_id,
            manifest.created_at,
            manifest.expires_at,
            encode_hex(&self.payload),
            head.withdrawal_scope_digest,
            head.binding,
            head.witness.registry_id,
            head.witness.generation.get(),
            head.witness.head_digest,
            head.witness.predecessor_head_digest,
            head.witness.authority_epoch,
            head.witness.signer_id,
            head.witness.signing_key_digest,
            head.witness.issued_at,
            head.witness.expires_at,
            encode_hex(&head.signature),
        );
        if text.len() > MAX_COMMAND_BYTES {
            return Err(ArtifactOwnerCommandDecodeError::Capacity);
        }
        Ok(text.into_bytes())
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, ArtifactOwnerCommandDecodeError> {
        let values = parse_key_values(bytes, PUBLISH_SCHEMA)?;
        let payload = decode_hex(required(&values, "payload_hex")?)?;
        let encoded_size_bytes = parse_u64(required(&values, "encoded_size_bytes")?)?;
        if payload.len() as u64 != encoded_size_bytes {
            return Err(ArtifactOwnerCommandDecodeError::PayloadLength);
        }
        let manifest = LearningArtifactManifestV2 {
            artifact_id: parse_id(required(&values, "artifact_id")?)?,
            kind: parse_kind(required(&values, "kind")?)?,
            generation: parse_generation(required(&values, "generation")?)?,
            provenance_mode: parse_provenance(required(&values, "provenance_mode")?)?,
            source_dataset_digests: parse_digest_list(required(
                &values,
                "source_dataset_digests",
            )?)?,
            lineage_digests: parse_digest_list(required(&values, "lineage_digests")?)?,
            predecessor_ids: parse_id_list(required(&values, "predecessor_ids")?)?,
            rollback_predecessor: parse_optional_id(required(
                &values,
                "rollback_predecessor",
            )?)?,
            bytes_digest: parse_digest(required(&values, "bytes_digest")?)?,
            encoded_size_bytes,
            training_code_digest: parse_digest(required(
                &values,
                "training_code_digest",
            )?)?,
            runtime_tuple_digest: parse_digest(required(
                &values,
                "runtime_tuple_digest",
            )?)?,
            device_profile_digest: parse_digest(required(
                &values,
                "device_profile_digest",
            )?)?,
            objective_class_digest: parse_digest(required(
                &values,
                "objective_class_digest",
            )?)?,
            compatibility_digest: parse_digest(required(
                &values,
                "compatibility_digest",
            )?)?,
            schema_profile_digest: parse_digest(required(
                &values,
                "schema_profile_digest",
            )?)?,
            normalization_digest: parse_digest(required(
                &values,
                "normalization_digest",
            )?)?,
            producer_id: parse_id(required(&values, "producer_id")?)?,
            created_at: parse_u64(required(&values, "created_at")?)?,
            expires_at: parse_u64(required(&values, "expires_at")?)?,
        };
        if Digest32::of_bytes(&payload) != manifest.bytes_digest {
            return Err(ArtifactOwnerCommandDecodeError::PayloadDigest);
        }
        Ok(Self {
            operation_id: parse_id(required(&values, "operation_id")?)?,
            expected_withdrawal_head: parse_digest(required(
                &values,
                "expected_withdrawal_head",
            )?)?,
            expected_registry_predecessor_head: parse_digest(required(
                &values,
                "expected_registry_predecessor_head",
            )?)?,
            manifest: ArtifactManifestCommandV1 { manifest },
            payload,
            signed_current_head: parse_signed_head(&values)?,
            now: parse_u64(required(&values, "now")?)?,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InstallWithdrawalSnapshotCommandV1 {
    pub snapshot_path: PathBuf,
    pub receipt: DatasetWithdrawalSnapshotReceiptV1,
}

impl InstallWithdrawalSnapshotCommandV1 {
    #[must_use]
    pub fn encode(&self) -> Vec<u8> {
        format!(
            concat!(
                "schema={INSTALL_WITHDRAWAL_SCHEMA}\n",
                "snapshot_path={}\nbinding={}\nscope_digest={}\nhead_digest={}\n",
                "file_digest={}\nrecords={}\nencoded_bytes={}\n"
            ),
            self.snapshot_path.display(),
            self.receipt.binding,
            self.receipt.scope_digest,
            self.receipt.head_digest,
            self.receipt.file_digest,
            self.receipt.records,
            self.receipt.encoded_bytes,
        )
        .into_bytes()
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, ArtifactOwnerCommandDecodeError> {
        let values = parse_key_values(bytes, INSTALL_WITHDRAWAL_SCHEMA)?;
        let snapshot_path = PathBuf::from(required(&values, "snapshot_path")?);
        if !snapshot_path.is_absolute() {
            return Err(ArtifactOwnerCommandDecodeError::InvalidPath);
        }
        Ok(Self {
            snapshot_path,
            receipt: DatasetWithdrawalSnapshotReceiptV1 {
                binding: parse_digest(required(&values, "binding")?)?,
                scope_digest: parse_digest(required(&values, "scope_digest")?)?,
                head_digest: parse_digest(required(&values, "head_digest")?)?,
                file_digest: parse_digest(required(&values, "file_digest")?)?,
                records: parse_usize(required(&values, "records")?)?,
                encoded_bytes: parse_usize(required(&values, "encoded_bytes")?)?,
            },
        })
    }
}

fn parse_signed_head(
    values: &BTreeMap<String, String>,
) -> Result<SignedCurrentArtifactHeadV1, ArtifactOwnerCommandDecodeError> {
    Ok(SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: parse_digest(required(
            values,
            "head_withdrawal_scope_digest",
        )?)?,
        binding: parse_digest(required(values, "head_binding")?)?,
        witness: RegistryHeadWitnessV1 {
            registry_id: parse_id(required(values, "head_registry_id")?)?,
            generation: parse_generation(required(values, "head_generation")?)?,
            head_digest: parse_digest(required(values, "head_digest")?)?,
            predecessor_head_digest: parse_digest(required(
                values,
                "head_predecessor_head_digest",
            )?)?,
            authority_epoch: parse_u64(required(values, "head_authority_epoch")?)?,
            signer_id: parse_id(required(values, "head_signer_id")?)?,
            signing_key_digest: parse_digest(required(
                values,
                "head_signing_key_digest",
            )?)?,
            issued_at: parse_u64(required(values, "head_issued_at")?)?,
            expires_at: parse_u64(required(values, "head_expires_at")?)?,
        },
        signature: decode_fixed_hex::<64>(required(values, "head_signature")?)?,
    })
}

fn parse_key_values(
    bytes: &[u8],
    schema: &str,
) -> Result<BTreeMap<String, String>, ArtifactOwnerCommandDecodeError> {
    if bytes.is_empty() || bytes.len() > MAX_COMMAND_BYTES {
        return Err(ArtifactOwnerCommandDecodeError::Capacity);
    }
    let text = std::str::from_utf8(bytes)
        .map_err(|_| ArtifactOwnerCommandDecodeError::NonCanonical)?;
    if !text.ends_with('\n') {
        return Err(ArtifactOwnerCommandDecodeError::NonCanonical);
    }
    let mut values = BTreeMap::new();
    for line in text.lines() {
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let (name, value) = line
            .split_once('=')
            .ok_or(ArtifactOwnerCommandDecodeError::NonCanonical)?;
        if name.is_empty()
            || value.is_empty()
            || name.bytes().any(|byte| {
                !(byte.is_ascii_lowercase()
                    || byte.is_ascii_digit()
                    || matches!(byte, b'_' | b'.'))
            })
            || values.insert(name.to_owned(), value.to_owned()).is_some()
        {
            return Err(ArtifactOwnerCommandDecodeError::NonCanonical);
        }
    }
    if values.get("schema").map(String::as_str) != Some(schema) {
        return Err(ArtifactOwnerCommandDecodeError::WrongSchema);
    }
    Ok(values)
}

fn required<'a>(
    values: &'a BTreeMap<String, String>,
    name: &'static str,
) -> Result<&'a str, ArtifactOwnerCommandDecodeError> {
    values
        .get(name)
        .map(String::as_str)
        .ok_or(ArtifactOwnerCommandDecodeError::Missing(name))
}

fn parse_id(value: &str) -> Result<StableId, ArtifactOwnerCommandDecodeError> {
    StableId::new(value.to_owned()).map_err(|_| ArtifactOwnerCommandDecodeError::InvalidIdentifier)
}

fn parse_optional_id(
    value: &str,
) -> Result<Option<StableId>, ArtifactOwnerCommandDecodeError> {
    if value == "-" {
        Ok(None)
    } else {
        parse_id(value).map(Some)
    }
}

fn parse_digest(value: &str) -> Result<Digest32, ArtifactOwnerCommandDecodeError> {
    Digest32::from_str(value).map_err(|_| ArtifactOwnerCommandDecodeError::InvalidDigest)
}

fn parse_generation(value: &str) -> Result<Generation, ArtifactOwnerCommandDecodeError> {
    Generation::new(parse_u64(value)?)
        .map_err(|_| ArtifactOwnerCommandDecodeError::InvalidNumber)
}

fn parse_u64(value: &str) -> Result<u64, ArtifactOwnerCommandDecodeError> {
    value
        .parse::<u64>()
        .map_err(|_| ArtifactOwnerCommandDecodeError::InvalidNumber)
}

fn parse_usize(value: &str) -> Result<usize, ArtifactOwnerCommandDecodeError> {
    value
        .parse::<usize>()
        .map_err(|_| ArtifactOwnerCommandDecodeError::InvalidNumber)
}

fn parse_kind(value: &str) -> Result<ArtifactKind, ArtifactOwnerCommandDecodeError> {
    match value {
        "prompt" => Ok(ArtifactKind::Prompt),
        "policy" => Ok(ArtifactKind::Policy),
        "model" => Ok(ArtifactKind::Model),
        "workflow" => Ok(ArtifactKind::Workflow),
        "skill" => Ok(ArtifactKind::Skill),
        "parameters" => Ok(ArtifactKind::Parameters),
        "topology" => Ok(ArtifactKind::Topology),
        "code" => Ok(ArtifactKind::Code),
        "external_adapter" => Ok(ArtifactKind::ExternalAdapter),
        "sensor_core" => Ok(ArtifactKind::SensorCore),
        _ => Err(ArtifactOwnerCommandDecodeError::InvalidEnum),
    }
}

fn parse_provenance(
    value: &str,
) -> Result<ProvenanceModeV1, ArtifactOwnerCommandDecodeError> {
    match value {
        "dataset_derived" => Ok(ProvenanceModeV1::DatasetDerived),
        "dataset_independent" => Ok(ProvenanceModeV1::DatasetIndependent),
        _ => Err(ArtifactOwnerCommandDecodeError::InvalidEnum),
    }
}

fn parse_digest_list(
    value: &str,
) -> Result<Vec<Digest32>, ArtifactOwnerCommandDecodeError> {
    if value == "-" {
        return Ok(Vec::new());
    }
    let items: Vec<_> = value.split(',').collect();
    if items.len() > MAX_LIST_ITEMS || items.iter().any(|item| item.is_empty()) {
        return Err(ArtifactOwnerCommandDecodeError::Capacity);
    }
    items.into_iter().map(parse_digest).collect()
}

fn parse_id_list(value: &str) -> Result<Vec<StableId>, ArtifactOwnerCommandDecodeError> {
    if value == "-" {
        return Ok(Vec::new());
    }
    let items: Vec<_> = value.split(',').collect();
    if items.len() > MAX_LIST_ITEMS || items.iter().any(|item| item.is_empty()) {
        return Err(ArtifactOwnerCommandDecodeError::Capacity);
    }
    items.into_iter().map(parse_id).collect()
}

fn kind_name(value: ArtifactKind) -> &'static str {
    match value {
        ArtifactKind::Prompt => "prompt",
        ArtifactKind::Policy => "policy",
        ArtifactKind::Model => "model",
        ArtifactKind::Workflow => "workflow",
        ArtifactKind::Skill => "skill",
        ArtifactKind::Parameters => "parameters",
        ArtifactKind::Topology => "topology",
        ArtifactKind::Code => "code",
        ArtifactKind::ExternalAdapter => "external_adapter",
        ArtifactKind::SensorCore => "sensor_core",
    }
}

fn provenance_name(value: ProvenanceModeV1) -> &'static str {
    match value {
        ProvenanceModeV1::DatasetDerived => "dataset_derived",
        ProvenanceModeV1::DatasetIndependent => "dataset_independent",
    }
}

fn join_digests(values: &[Digest32]) -> String {
    if values.is_empty() {
        "-".to_owned()
    } else {
        values
            .iter()
            .map(ToString::to_string)
            .collect::<Vec<_>>()
            .join(",")
    }
}

fn join_ids(values: &[StableId]) -> String {
    if values.is_empty() {
        "-".to_owned()
    } else {
        values
            .iter()
            .map(StableId::as_str)
            .collect::<Vec<_>>()
            .join(",")
    }
}

fn encode_hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(DIGITS[(byte >> 4) as usize] as char);
        output.push(DIGITS[(byte & 0x0f) as usize] as char);
    }
    output
}

fn decode_hex(value: &str) -> Result<Vec<u8>, ArtifactOwnerCommandDecodeError> {
    if !value.len().is_multiple_of(2) || value.len() / 2 > MAX_COMMAND_BYTES {
        return Err(ArtifactOwnerCommandDecodeError::Capacity);
    }
    let mut bytes = Vec::with_capacity(value.len() / 2);
    for pair in value.as_bytes().chunks_exact(2) {
        let high = decode_nibble(pair[0]).ok_or(ArtifactOwnerCommandDecodeError::InvalidHex)?;
        let low = decode_nibble(pair[1]).ok_or(ArtifactOwnerCommandDecodeError::InvalidHex)?;
        bytes.push((high << 4) | low);
    }
    Ok(bytes)
}

fn decode_fixed_hex<const N: usize>(
    value: &str,
) -> Result<[u8; N], ArtifactOwnerCommandDecodeError> {
    decode_hex(value)?
        .try_into()
        .map_err(|_| ArtifactOwnerCommandDecodeError::InvalidHex)
}

const fn decode_nibble(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        _ => None,
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ArtifactOwnerCommandDecodeError {
    WrongSchema,
    Missing(&'static str),
    NonCanonical,
    InvalidIdentifier,
    InvalidDigest,
    InvalidNumber,
    InvalidEnum,
    InvalidHex,
    InvalidPath,
    Capacity,
    PayloadLength,
    PayloadDigest,
}

impl fmt::Display for ArtifactOwnerCommandDecodeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ArtifactOwnerCommandDecodeError {}
