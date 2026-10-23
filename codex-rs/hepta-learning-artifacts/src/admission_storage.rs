//! Canonical, create-only storage of complete withdrawal-bound V3 admissions.
//!
//! A sidecar preserves every V2 source, predecessor, identity and expiry field;
//! it is not a flattened V1 manifest or selection capability. Recovery verifies
//! historical validity at admission time. Publication and use must separately
//! check the live withdrawal frontier and current manifest expiry.

use std::fs::File;
use std::path::Path;
use std::str::FromStr;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::ArtifactKind;
use crate::ArtifactManifest;
use crate::ArtifactStorageError;
use crate::CreateOnlyArtifactFile;
use crate::LearningArtifactManifestV2;
use crate::ProvenanceModeV1;
use crate::ValidatedArtifactManifestV2;
use crate::WithdrawalBoundArtifactAdmissionV3;
use crate::closure_v2::MAX_DATASET_INPUTS;
use crate::closure_v2::MAX_LINEAGE_DIGESTS;
use crate::closure_v2::MAX_PREDECESSORS;
use crate::storage::read_bounded;
use crate::storage::write_new;
use crate::validate_artifact_manifest_v2;
use crate::verify_artifact_admission_v3;

/// Hard byte ceiling for a complete canonical V3 admission sidecar.
pub const MAX_ARTIFACT_ADMISSION_SNAPSHOT_BYTES: usize = 128 * 1024;
const MAGIC: &str = "HEPTAA03";

/// Exact canonical sidecar receipt. Retain it independently of the suspect file.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ArtifactAdmissionSnapshotReceiptV3 {
    pub binding: Digest32,
    pub withdrawal_scope_digest: Digest32,
    pub manifest_digest: Digest32,
    pub admission_digest: Digest32,
    pub file_digest: Digest32,
    pub encoded_bytes: usize,
}

/// Derive a receipt from a trusted complete admission, never from suspect bytes.
/// This lets a fenced host reconcile an exact create-only retry without changing
/// the independently witnessed V1 registry or checkpoint format.
pub fn admission_snapshot_receipt_v3(
    admission: &WithdrawalBoundArtifactAdmissionV3,
    binding: Digest32,
) -> Result<ArtifactAdmissionSnapshotReceiptV3, ArtifactStorageError> {
    let bytes = encode_admission_snapshot_v3(admission, binding)?;
    Ok(receipt(admission, binding, &bytes))
}

/// Validate and encode before creating a final component beneath a trusted root.
/// The host prevents concurrent path replacement and syncs the containing
/// directory before acknowledging durability. Existing targets are never reused
/// without a separate receipt-bound read and host durability reconciliation.
pub fn write_artifact_admission_snapshot_beneath(
    root: impl AsRef<Path>,
    relative: impl AsRef<Path>,
    admission: &WithdrawalBoundArtifactAdmissionV3,
    binding: Digest32,
) -> Result<ArtifactAdmissionSnapshotReceiptV3, ArtifactStorageError> {
    let bytes = encode_admission_snapshot_v3(admission, binding)?;
    let expected = receipt(admission, binding, &bytes);
    write_new(
        CreateOnlyArtifactFile::create_beneath_trusted_root(root, relative)?,
        &bytes,
    )?;
    Ok(expected)
}

/// Recover exact historical admission bytes using an independently retained
/// receipt. Expiry after admission does not destroy recoverable provenance.
pub fn read_artifact_admission_snapshot(
    file: File,
    expected: ArtifactAdmissionSnapshotReceiptV3,
) -> Result<WithdrawalBoundArtifactAdmissionV3, ArtifactStorageError> {
    validate_pins(
        expected.binding,
        expected.withdrawal_scope_digest,
        expected.manifest_digest,
        expected.admission_digest,
    )?;
    if expected.file_digest.is_zero()
        || expected.encoded_bytes == 0
        || expected.encoded_bytes > MAX_ARTIFACT_ADMISSION_SNAPSHOT_BYTES
    {
        return Err(ArtifactStorageError::InvalidReceipt);
    }
    let bytes = read_bounded(
        file,
        MAX_ARTIFACT_ADMISSION_SNAPSHOT_BYTES,
        expected.encoded_bytes as u64,
        ArtifactStorageError::Corrupt,
    )?;
    if Digest32::of_bytes(&bytes) != expected.file_digest {
        return Err(ArtifactStorageError::Corrupt);
    }
    decode_pinned(
        &bytes,
        expected.binding,
        expected.withdrawal_scope_digest,
        expected.manifest_digest,
        expected.admission_digest,
    )
}

/// Recover from semantic pins independently authenticated by the registry,
/// publication checkpoint and owner scope. These pins bind every field of the
/// canonical file, so its complete receipt may safely be issued after recovery.
/// The observed file length is used only as a read budget, never as a trust pin.
pub fn read_artifact_admission_snapshot_bound(
    file: File,
    binding: Digest32,
    scope_digest: Digest32,
    manifest_digest: Digest32,
    admission_digest: Digest32,
) -> Result<
    (
        WithdrawalBoundArtifactAdmissionV3,
        ArtifactAdmissionSnapshotReceiptV3,
    ),
    ArtifactStorageError,
> {
    validate_pins(binding, scope_digest, manifest_digest, admission_digest)?;
    let observed_bytes = file.metadata()?.len();
    let bytes = read_bounded(
        file,
        MAX_ARTIFACT_ADMISSION_SNAPSHOT_BYTES,
        observed_bytes,
        ArtifactStorageError::Corrupt,
    )?;
    let admission = decode_pinned(
        &bytes,
        binding,
        scope_digest,
        manifest_digest,
        admission_digest,
    )?;
    let receipt = receipt(&admission, binding, &bytes);
    Ok((admission, receipt))
}

/// Validate all fields represented by the owner's V1 compatibility projection.
/// State changes do not alter the immutable projection. All V2 predecessors
/// remain in the sidecar even when V1 can represent only a single predecessor.
pub fn validate_admission_registry_projection_v3(
    manifest: &ArtifactManifest,
    admission: &WithdrawalBoundArtifactAdmissionV3,
) -> Result<(), ArtifactStorageError> {
    validate_historical_admission(admission)?;
    let v2 = &admission.validated_manifest.manifest;
    let predecessor = if v2.predecessor_ids.len() == 1 {
        v2.predecessor_ids.first()
    } else {
        None
    };
    if manifest.artifact_id != v2.artifact_id
        || manifest.kind != v2.kind
        || manifest.generation != v2.generation
        || manifest.predecessor_id.as_ref() != predecessor
        || manifest.content_digest != v2.bytes_digest
        || manifest.objective_digest != v2.objective_class_digest
        || manifest.support_digest != admission.validated_manifest.manifest_digest
        || manifest.producer_id != v2.producer_id
        || manifest.compatibility_digest != v2.compatibility_digest
        || manifest.encoded_size_bytes != v2.encoded_size_bytes
    {
        return Err(ArtifactStorageError::Semantic);
    }
    Ok(())
}

pub(crate) fn encode_admission_snapshot_v3(
    admission: &WithdrawalBoundArtifactAdmissionV3,
    binding: Digest32,
) -> Result<Vec<u8>, ArtifactStorageError> {
    if binding.is_zero() {
        return Err(ArtifactStorageError::InvalidBinding);
    }
    validate_historical_admission(admission)?;
    let manifest = &admission.validated_manifest.manifest;
    let provenance = match manifest.provenance_mode {
        ProvenanceModeV1::DatasetDerived => 0,
        ProvenanceModeV1::DatasetIndependent => 1,
    };
    let mut text = format!(
        "{MAGIC}\n{binding}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{provenance}\n{}\n",
        admission.withdrawal_scope_digest,
        admission.withdrawal_head_digest,
        admission.admitted_at,
        admission.admission_digest,
        admission.validated_manifest.manifest_digest,
        manifest.artifact_id,
        manifest.kind.tag(),
        manifest.generation.get(),
        manifest.source_dataset_digests.len(),
    );
    for digest in &manifest.source_dataset_digests {
        text.push_str(&format!("{digest}\n"));
    }
    text.push_str(&format!("{}\n", manifest.lineage_digests.len()));
    for digest in &manifest.lineage_digests {
        text.push_str(&format!("{digest}\n"));
    }
    text.push_str(&format!("{}\n", manifest.predecessor_ids.len()));
    for predecessor in &manifest.predecessor_ids {
        text.push_str(&format!("{predecessor}\n"));
    }
    match &manifest.rollback_predecessor {
        Some(predecessor) => text.push_str(&format!("1\n{predecessor}\n")),
        None => text.push_str("0\n"),
    }
    text.push_str(&format!(
        "{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\nDENY_ALL\n",
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
    ));
    if text.len() > MAX_ARTIFACT_ADMISSION_SNAPSHOT_BYTES {
        return Err(ArtifactStorageError::Capacity);
    }
    Ok(text.into_bytes())
}

fn validate_historical_admission(
    admission: &WithdrawalBoundArtifactAdmissionV3,
) -> Result<(), ArtifactStorageError> {
    let manifest = &admission.validated_manifest.manifest;
    if manifest.source_dataset_digests.len() > MAX_DATASET_INPUTS
        || manifest.lineage_digests.len() > MAX_LINEAGE_DIGESTS
        || manifest.predecessor_ids.len() > MAX_PREDECESSORS
    {
        return Err(ArtifactStorageError::Capacity);
    }
    if admission.withdrawal_head_digest.is_zero() {
        return Err(ArtifactStorageError::Semantic);
    }
    verify_artifact_admission_v3(
        admission,
        admission.withdrawal_head_digest,
        admission.admitted_at,
    )
    .map_err(|_| ArtifactStorageError::Semantic)?;
    let canonical = validate_artifact_manifest_v2(manifest.clone(), admission.admitted_at)
        .map_err(|_| ArtifactStorageError::Semantic)?;
    if canonical != admission.validated_manifest {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(())
}

fn validate_pins(
    binding: Digest32,
    scope: Digest32,
    manifest: Digest32,
    admission: Digest32,
) -> Result<(), ArtifactStorageError> {
    if binding.is_zero() || scope.is_zero() || manifest.is_zero() || admission.is_zero() {
        return Err(ArtifactStorageError::InvalidReceipt);
    }
    Ok(())
}

fn receipt(
    admission: &WithdrawalBoundArtifactAdmissionV3,
    binding: Digest32,
    bytes: &[u8],
) -> ArtifactAdmissionSnapshotReceiptV3 {
    ArtifactAdmissionSnapshotReceiptV3 {
        binding,
        withdrawal_scope_digest: admission.withdrawal_scope_digest,
        manifest_digest: admission.validated_manifest.manifest_digest,
        admission_digest: admission.admission_digest,
        file_digest: Digest32::of_bytes(bytes),
        encoded_bytes: bytes.len(),
    }
}

fn decode_pinned(
    bytes: &[u8],
    binding: Digest32,
    scope_digest: Digest32,
    manifest_digest: Digest32,
    admission_digest: Digest32,
) -> Result<WithdrawalBoundArtifactAdmissionV3, ArtifactStorageError> {
    if bytes.is_empty() || bytes.len() > MAX_ARTIFACT_ADMISSION_SNAPSHOT_BYTES {
        return Err(ArtifactStorageError::Corrupt);
    }
    let text = std::str::from_utf8(bytes).map_err(|_| ArtifactStorageError::Corrupt)?;
    let mut fields = Fields(text.lines());
    if fields.line()? != MAGIC || fields.digest()? != binding {
        return Err(ArtifactStorageError::Corrupt);
    }
    let withdrawal_scope_digest = fields.digest()?;
    if withdrawal_scope_digest != scope_digest {
        return Err(ArtifactStorageError::ScopeMismatch);
    }
    let withdrawal_head_digest = fields.digest()?;
    let admitted_at = fields.number()?;
    if fields.digest()? != admission_digest || fields.digest()? != manifest_digest {
        return Err(ArtifactStorageError::Corrupt);
    }
    let artifact_id = fields.id()?;
    let kind = match fields.line()? {
        "0" => ArtifactKind::Prompt,
        "1" => ArtifactKind::Policy,
        "2" => ArtifactKind::Model,
        "3" => ArtifactKind::Workflow,
        "4" => ArtifactKind::Skill,
        "5" => ArtifactKind::Parameters,
        "6" => ArtifactKind::Topology,
        "7" => ArtifactKind::Code,
        "8" => ArtifactKind::ExternalAdapter,
        "9" => ArtifactKind::SensorCore,
        _ => return Err(ArtifactStorageError::Corrupt),
    };
    let generation =
        Generation::new(fields.number()?).map_err(|_| ArtifactStorageError::Corrupt)?;
    let provenance_mode = match fields.line()? {
        "0" => ProvenanceModeV1::DatasetDerived,
        "1" => ProvenanceModeV1::DatasetIndependent,
        _ => return Err(ArtifactStorageError::Corrupt),
    };
    let source_dataset_digests = fields.digests(MAX_DATASET_INPUTS)?;
    let lineage_digests = fields.digests(MAX_LINEAGE_DIGESTS)?;
    let predecessor_count = fields.count(MAX_PREDECESSORS)?;
    let predecessor_ids = (0..predecessor_count)
        .map(|_| fields.id())
        .collect::<Result<Vec<_>, _>>()?;
    let rollback_predecessor = match fields.line()? {
        "0" => None,
        "1" => Some(fields.id()?),
        _ => return Err(ArtifactStorageError::Corrupt),
    };
    let manifest = LearningArtifactManifestV2 {
        artifact_id,
        kind,
        generation,
        provenance_mode,
        source_dataset_digests,
        lineage_digests,
        predecessor_ids,
        rollback_predecessor,
        bytes_digest: fields.digest()?,
        encoded_size_bytes: fields.number()?,
        training_code_digest: fields.digest()?,
        runtime_tuple_digest: fields.digest()?,
        device_profile_digest: fields.digest()?,
        objective_class_digest: fields.digest()?,
        compatibility_digest: fields.digest()?,
        schema_profile_digest: fields.digest()?,
        normalization_digest: fields.digest()?,
        producer_id: fields.id()?,
        created_at: fields.number()?,
        expires_at: fields.number()?,
    };
    if fields.line()? != "DENY_ALL" || fields.0.next().is_some() {
        return Err(ArtifactStorageError::Corrupt);
    }
    let admission = WithdrawalBoundArtifactAdmissionV3 {
        validated_manifest: ValidatedArtifactManifestV2 {
            manifest,
            manifest_digest,
            authority: AuthorityPosture::DENY_ALL,
        },
        withdrawal_scope_digest,
        withdrawal_head_digest,
        admitted_at,
        admission_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    if encode_admission_snapshot_v3(&admission, binding)? != bytes {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(admission)
}

struct Fields<'a>(std::str::Lines<'a>);

impl<'a> Fields<'a> {
    fn line(&mut self) -> Result<&'a str, ArtifactStorageError> {
        self.0
            .next()
            .filter(|value| value.len() <= 128)
            .ok_or(ArtifactStorageError::Corrupt)
    }

    fn digest(&mut self) -> Result<Digest32, ArtifactStorageError> {
        Digest32::from_str(self.line()?).map_err(|_| ArtifactStorageError::Corrupt)
    }

    fn id(&mut self) -> Result<StableId, ArtifactStorageError> {
        StableId::new(self.line()?).map_err(|_| ArtifactStorageError::Corrupt)
    }

    fn number(&mut self) -> Result<u64, ArtifactStorageError> {
        self.line()?
            .parse()
            .map_err(|_| ArtifactStorageError::Corrupt)
    }

    fn count(&mut self, maximum: usize) -> Result<usize, ArtifactStorageError> {
        let count = usize::try_from(self.number()?).map_err(|_| ArtifactStorageError::Capacity)?;
        if count > maximum {
            return Err(ArtifactStorageError::Capacity);
        }
        Ok(count)
    }

    fn digests(&mut self, maximum: usize) -> Result<Vec<Digest32>, ArtifactStorageError> {
        let count = self.count(maximum)?;
        (0..count).map(|_| self.digest()).collect()
    }
}

#[cfg(test)]
#[path = "admission_storage_tests.rs"]
mod tests;
