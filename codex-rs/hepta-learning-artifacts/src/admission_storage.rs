//! Canonical, create-only persistence of the complete withdrawal-bound admission.
//!
//! V1 registry projections are deliberately insufficient for recovery of V2
//! provenance. Retain this sidecar's receipt in an independently authenticated
//! owner checkpoint. Recovery checks the historical admission instant; publication
//! must separately revalidate expiry and the current withdrawal registry.

use std::fs::File;
use std::path::Path;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::ArtifactKind;
use crate::ArtifactStorageError;
use crate::CreateOnlyArtifactFile;
use crate::LearningArtifactManifestV2;
use crate::ProvenanceModeV1;
use crate::ValidatedArtifactManifestV2;
use crate::WithdrawalBoundArtifactAdmissionV3;
use crate::storage::read_bounded;
use crate::storage::write_new;
use crate::validate_artifact_manifest_v2;
use crate::verify_artifact_admission_v3;

const MAGIC: &[u8; 8] = b"HEPTAA03";
pub(crate) const MAX_ARTIFACT_ADMISSION_BYTES: usize = 128 * 1024;

/// Exact historical admission bytes and withdrawal domain/frontier pin.
/// This public digest witness grants no authority. Authenticate it outside the
/// file; deriving an expected receipt from suspect bytes defeats verification.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ArtifactAdmissionReceiptV3 {
    pub manifest_digest: Digest32,
    pub admission_digest: Digest32,
    pub withdrawal_scope_digest: Digest32,
    pub withdrawal_head_digest: Digest32,
    pub file_digest: Digest32,
    pub encoded_bytes: usize,
}

/// Validate and fully encode before creating the contained target. The root and
/// all ancestors must remain trusted against replacement throughout this call.
/// Directory durability is the host's responsibility after successful return.
pub fn write_artifact_admission_beneath(
    root: impl AsRef<Path>,
    relative: impl AsRef<Path>,
    admission: &WithdrawalBoundArtifactAdmissionV3,
) -> Result<ArtifactAdmissionReceiptV3, ArtifactStorageError> {
    let bytes = encode_artifact_admission(admission)?;
    let receipt = receipt(admission, &bytes);
    write_new(
        CreateOnlyArtifactFile::create_beneath_trusted_root(root, relative)?,
        &bytes,
    )?;
    Ok(receipt)
}

/// Recover the entire admission using an independently authenticated receipt and
/// independently opened, initially unlocked regular file. Recovery retains an
/// expired historical manifest; it does not authorize publishing that manifest.
pub fn read_artifact_admission(
    file: File,
    expected: ArtifactAdmissionReceiptV3,
) -> Result<WithdrawalBoundArtifactAdmissionV3, ArtifactStorageError> {
    if expected.manifest_digest.is_zero()
        || expected.admission_digest.is_zero()
        || expected.withdrawal_scope_digest.is_zero()
        || expected.withdrawal_head_digest.is_zero()
        || expected.file_digest.is_zero()
        || expected.encoded_bytes == 0
        || expected.encoded_bytes > MAX_ARTIFACT_ADMISSION_BYTES
    {
        return Err(ArtifactStorageError::InvalidReceipt);
    }
    let bytes = read_bounded(
        file,
        MAX_ARTIFACT_ADMISSION_BYTES,
        expected.encoded_bytes as u64,
        ArtifactStorageError::Corrupt,
    )?;
    if Digest32::of_bytes(&bytes) != expected.file_digest {
        return Err(ArtifactStorageError::Corrupt);
    }
    let admission = decode_canonical_admission(&bytes)?;
    if receipt(&admission, &bytes) != expected {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(admission)
}

/// Recover against an admission digest committed by an authenticated owner
/// checkpoint. File length is only a bounded read hint; the independent semantic
/// commitment and canonical encoding authenticate the recovered admission.
pub fn read_artifact_admission_by_digest(
    file: File,
    expected_admission_digest: Digest32,
) -> Result<WithdrawalBoundArtifactAdmissionV3, ArtifactStorageError> {
    read_semantically_pinned(file, SemanticPin::Admission(expected_admission_digest))
}

/// Recover immutable parent provenance against the V2 manifest digest committed
/// by trusted registry history. The admission frontier returned alongside it is
/// historical bookkeeping and must never substitute for a trusted current head.
pub fn read_artifact_admission_by_manifest_digest(
    file: File,
    expected_manifest_digest: Digest32,
) -> Result<WithdrawalBoundArtifactAdmissionV3, ArtifactStorageError> {
    read_semantically_pinned(file, SemanticPin::Manifest(expected_manifest_digest))
}

enum SemanticPin {
    Admission(Digest32),
    Manifest(Digest32),
}

fn read_semantically_pinned(
    file: File,
    pin: SemanticPin,
) -> Result<WithdrawalBoundArtifactAdmissionV3, ArtifactStorageError> {
    let expected = match pin {
        SemanticPin::Admission(digest) | SemanticPin::Manifest(digest) => digest,
    };
    if expected.is_zero() {
        return Err(ArtifactStorageError::InvalidReceipt);
    }
    let observed_length = file.metadata()?.len();
    if observed_length == 0 {
        return Err(ArtifactStorageError::Corrupt);
    }
    let bytes = read_bounded(
        file,
        MAX_ARTIFACT_ADMISSION_BYTES,
        observed_length,
        ArtifactStorageError::Corrupt,
    )?;
    let admission = decode_canonical_admission(&bytes)?;
    let observed = match pin {
        SemanticPin::Admission(_) => admission.admission_digest,
        SemanticPin::Manifest(_) => admission.validated_manifest.manifest_digest,
    };
    if observed != expected {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(admission)
}

fn decode_canonical_admission(
    bytes: &[u8],
) -> Result<WithdrawalBoundArtifactAdmissionV3, ArtifactStorageError> {
    let admission = decode_admission(bytes)?;
    if encode_artifact_admission(&admission).map_err(|_| ArtifactStorageError::Corrupt)? != bytes {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(admission)
}

fn receipt(
    admission: &WithdrawalBoundArtifactAdmissionV3,
    bytes: &[u8],
) -> ArtifactAdmissionReceiptV3 {
    ArtifactAdmissionReceiptV3 {
        manifest_digest: admission.validated_manifest.manifest_digest,
        admission_digest: admission.admission_digest,
        withdrawal_scope_digest: admission.withdrawal_scope_digest,
        withdrawal_head_digest: admission.withdrawal_head_digest,
        file_digest: Digest32::of_bytes(bytes),
        encoded_bytes: bytes.len(),
    }
}

pub(crate) fn encode_artifact_admission(
    admission: &WithdrawalBoundArtifactAdmissionV3,
) -> Result<Vec<u8>, ArtifactStorageError> {
    let manifest = &admission.validated_manifest.manifest;
    if manifest.source_dataset_digests.len() > 64
        || manifest.lineage_digests.is_empty()
        || manifest.lineage_digests.len() > 1024
        || manifest.predecessor_ids.len() > 64
    {
        return Err(ArtifactStorageError::Semantic);
    }
    verify_artifact_admission_v3(
        admission,
        admission.withdrawal_head_digest,
        admission.admitted_at,
    )
    .map_err(|_| ArtifactStorageError::Semantic)?;
    let validated = validate_artifact_manifest_v2(
        admission.validated_manifest.manifest.clone(),
        admission.admitted_at,
    )
    .map_err(|_| ArtifactStorageError::Semantic)?;
    if validated != admission.validated_manifest
        || admission.authority != AuthorityPosture::DENY_ALL
        || admission.withdrawal_head_digest.is_zero()
    {
        return Err(ArtifactStorageError::Semantic);
    }
    let m = &validated.manifest;
    let mut bytes = MAGIC.to_vec();
    push_id(&mut bytes, &m.artifact_id);
    bytes.push(m.kind.tag());
    bytes.extend_from_slice(&m.generation.get().to_be_bytes());
    bytes.push(match m.provenance_mode {
        ProvenanceModeV1::DatasetDerived => 0,
        ProvenanceModeV1::DatasetIndependent => 1,
    });
    for values in [&m.source_dataset_digests, &m.lineage_digests] {
        push_count(&mut bytes, values.len());
        for value in values {
            bytes.extend_from_slice(value.as_array());
        }
    }
    push_count(&mut bytes, m.predecessor_ids.len());
    for id in &m.predecessor_ids {
        push_id(&mut bytes, id);
    }
    match &m.rollback_predecessor {
        Some(id) => {
            bytes.push(1);
            push_id(&mut bytes, id);
        }
        None => bytes.push(0),
    }
    for digest in [
        m.bytes_digest,
        m.training_code_digest,
        m.runtime_tuple_digest,
        m.device_profile_digest,
        m.objective_class_digest,
        m.compatibility_digest,
        m.schema_profile_digest,
        m.normalization_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&m.encoded_size_bytes.to_be_bytes());
    push_id(&mut bytes, &m.producer_id);
    bytes.extend_from_slice(&m.created_at.to_be_bytes());
    bytes.extend_from_slice(&m.expires_at.to_be_bytes());
    for digest in [
        validated.manifest_digest,
        admission.withdrawal_scope_digest,
        admission.withdrawal_head_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&admission.admitted_at.to_be_bytes());
    bytes.extend_from_slice(admission.admission_digest.as_array());
    // Both admission and normalized manifest are explicitly authority-free.
    bytes.extend_from_slice(&[0, 0]);
    if bytes.len() > MAX_ARTIFACT_ADMISSION_BYTES {
        return Err(ArtifactStorageError::Capacity);
    }
    Ok(bytes)
}

fn push_count(bytes: &mut Vec<u8>, count: usize) {
    // Semantic validation bounds every collection and StableId before encoding.
    bytes.extend_from_slice(&(count as u32).to_be_bytes());
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    push_count(bytes, id.as_str().len());
    bytes.extend_from_slice(id.as_str().as_bytes());
}

fn decode_admission(
    bytes: &[u8],
) -> Result<WithdrawalBoundArtifactAdmissionV3, ArtifactStorageError> {
    let mut input = Input(bytes);
    if input.take(MAGIC.len())? != MAGIC {
        return Err(ArtifactStorageError::Corrupt);
    }
    let manifest = LearningArtifactManifestV2 {
        artifact_id: input.id()?,
        kind: match input.byte()? {
            0 => ArtifactKind::Prompt,
            1 => ArtifactKind::Policy,
            2 => ArtifactKind::Model,
            3 => ArtifactKind::Workflow,
            4 => ArtifactKind::Skill,
            5 => ArtifactKind::Parameters,
            6 => ArtifactKind::Topology,
            7 => ArtifactKind::Code,
            8 => ArtifactKind::ExternalAdapter,
            9 => ArtifactKind::SensorCore,
            _ => return Err(ArtifactStorageError::Corrupt),
        },
        generation: Generation::new(input.number()?).map_err(|_| ArtifactStorageError::Corrupt)?,
        provenance_mode: match input.byte()? {
            0 => ProvenanceModeV1::DatasetDerived,
            1 => ProvenanceModeV1::DatasetIndependent,
            _ => return Err(ArtifactStorageError::Corrupt),
        },
        source_dataset_digests: input.digests(64)?,
        lineage_digests: input.digests(1024)?,
        predecessor_ids: (0..input.count(64)?)
            .map(|_| input.id())
            .collect::<Result<_, _>>()?,
        rollback_predecessor: match input.byte()? {
            0 => None,
            1 => Some(input.id()?),
            _ => return Err(ArtifactStorageError::Corrupt),
        },
        bytes_digest: input.digest()?,
        training_code_digest: input.digest()?,
        runtime_tuple_digest: input.digest()?,
        device_profile_digest: input.digest()?,
        objective_class_digest: input.digest()?,
        compatibility_digest: input.digest()?,
        schema_profile_digest: input.digest()?,
        normalization_digest: input.digest()?,
        encoded_size_bytes: input.number()?,
        producer_id: input.id()?,
        created_at: input.number()?,
        expires_at: input.number()?,
    };
    let manifest_digest = input.digest()?;
    let withdrawal_scope_digest = input.digest()?;
    let withdrawal_head_digest = input.digest()?;
    let admitted_at = input.number()?;
    let admission_digest = input.digest()?;
    let manifest_authority = AuthorityPosture::try_from_wire_bytes(input.take(1)?)
        .map_err(|_| ArtifactStorageError::Corrupt)?;
    let authority = AuthorityPosture::try_from_wire_bytes(input.take(1)?)
        .map_err(|_| ArtifactStorageError::Corrupt)?;
    if !input.0.is_empty() {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(WithdrawalBoundArtifactAdmissionV3 {
        validated_manifest: ValidatedArtifactManifestV2 {
            manifest,
            manifest_digest,
            authority: manifest_authority,
        },
        withdrawal_scope_digest,
        withdrawal_head_digest,
        admitted_at,
        admission_digest,
        authority,
    })
}

struct Input<'a>(&'a [u8]);

impl<'a> Input<'a> {
    fn take(&mut self, size: usize) -> Result<&'a [u8], ArtifactStorageError> {
        if size > self.0.len() {
            return Err(ArtifactStorageError::Corrupt);
        }
        let (head, tail) = self.0.split_at(size);
        self.0 = tail;
        Ok(head)
    }

    fn byte(&mut self) -> Result<u8, ArtifactStorageError> {
        Ok(self.take(1)?[0])
    }

    fn number(&mut self) -> Result<u64, ArtifactStorageError> {
        Ok(u64::from_be_bytes(
            self.take(8)?
                .try_into()
                .map_err(|_| ArtifactStorageError::Corrupt)?,
        ))
    }

    fn count(&mut self, maximum: usize) -> Result<usize, ArtifactStorageError> {
        let count = u32::from_be_bytes(
            self.take(4)?
                .try_into()
                .map_err(|_| ArtifactStorageError::Corrupt)?,
        ) as usize;
        if count > maximum {
            return Err(ArtifactStorageError::Corrupt);
        }
        Ok(count)
    }

    fn id(&mut self) -> Result<StableId, ArtifactStorageError> {
        let size = self.count(128)?;
        let raw =
            std::str::from_utf8(self.take(size)?).map_err(|_| ArtifactStorageError::Corrupt)?;
        StableId::new(raw).map_err(|_| ArtifactStorageError::Corrupt)
    }

    fn digest(&mut self) -> Result<Digest32, ArtifactStorageError> {
        Ok(Digest32::from_array(
            self.take(32)?
                .try_into()
                .map_err(|_| ArtifactStorageError::Corrupt)?,
        ))
    }

    fn digests(&mut self, maximum: usize) -> Result<Vec<Digest32>, ArtifactStorageError> {
        (0..self.count(maximum)?).map(|_| self.digest()).collect()
    }
}

#[cfg(test)]
#[path = "admission_storage_tests.rs"]
mod tests;
