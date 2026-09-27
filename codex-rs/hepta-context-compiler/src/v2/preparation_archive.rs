use serde::Deserialize;
use serde::Serialize;

use super::ContextAttachmentV2;
use super::ContextCompilerV2Error;
use super::ContextDeliveryPreparationV2;
use super::ContextModelProfileV2;
use super::SerializedContextV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use std::str::FromStr;

const PREPARATION_ARCHIVE_SCHEMA: &str = "hepta.context-delivery-preparation-archive.v2";

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct PreparationArchiveV2 {
    schema: String,
    preparation_id: String,
    attachment_digest: String,
    serialization_receipt_digest: String,
    payload_digest: String,
    model_profile_digest: String,
    provider_id_digest: String,
    provider_model_digest: String,
    admission_verifier_digest: String,
    admission_snapshot_digest: String,
    admission_snapshot_verification_digest: String,
    admission_snapshot_observed_unix_ms: u64,
    revocation_epoch: u64,
    preparation_digest: String,
}

impl ContextDeliveryPreparationV2 {
    /// Serializes the construction-closed preparation without raw context
    /// bytes. The archive is suitable for durable crash reconciliation but is
    /// not itself dispatch authority.
    pub fn canonical_archive_bytes(&self) -> Result<Vec<u8>, ContextCompilerV2Error> {
        serde_json::to_vec(&PreparationArchiveV2 {
            schema: PREPARATION_ARCHIVE_SCHEMA.to_owned(),
            preparation_id: self.preparation_id.as_str().to_owned(),
            attachment_digest: self.attachment_digest.to_string(),
            serialization_receipt_digest: self.serialization_receipt_digest.to_string(),
            payload_digest: self.payload_digest.to_string(),
            model_profile_digest: self.model_profile_digest.to_string(),
            provider_id_digest: self.provider_id_digest.to_string(),
            provider_model_digest: self.provider_model_digest.to_string(),
            admission_verifier_digest: self.admission_verifier_digest.to_string(),
            admission_snapshot_digest: self.admission_snapshot_digest.to_string(),
            admission_snapshot_verification_digest: self
                .admission_snapshot_verification_digest
                .to_string(),
            admission_snapshot_observed_unix_ms: self.admission_snapshot_observed_unix_ms,
            revocation_epoch: self.revocation_epoch,
            preparation_digest: self.preparation_digest.to_string(),
        })
        .map_err(|_| ContextCompilerV2Error::DeliveryEvidenceEncodingFailed)
    }

    /// Reopens a durable archive only when it still validates against the exact
    /// restaged attachment, serialized bytes, and execution profile. This is a
    /// crash-recovery constructor, not a generic proof-object decoder.
    pub fn reopen_canonical_archive(
        bytes: &[u8],
        attachment: &ContextAttachmentV2,
        serialization: &SerializedContextV2,
        profile: &ContextModelProfileV2,
    ) -> Result<Self, ContextCompilerV2Error> {
        let archive: PreparationArchiveV2 = serde_json::from_slice(bytes)
            .map_err(|_| ContextCompilerV2Error::DeliveryEvidenceEncodingFailed)?;
        if archive.schema != PREPARATION_ARCHIVE_SCHEMA {
            return Err(ContextCompilerV2Error::DeliveryMismatch);
        }
        let preparation = Self {
            preparation_id: StableId::new(archive.preparation_id)
                .map_err(|_| ContextCompilerV2Error::DeliveryMismatch)?,
            attachment_digest: parse_digest(&archive.attachment_digest)?,
            serialization_receipt_digest: parse_digest(&archive.serialization_receipt_digest)?,
            payload_digest: parse_digest(&archive.payload_digest)?,
            model_profile_digest: parse_digest(&archive.model_profile_digest)?,
            provider_id_digest: parse_digest(&archive.provider_id_digest)?,
            provider_model_digest: parse_digest(&archive.provider_model_digest)?,
            admission_verifier_digest: parse_digest(&archive.admission_verifier_digest)?,
            admission_snapshot_digest: parse_digest(&archive.admission_snapshot_digest)?,
            admission_snapshot_verification_digest: parse_digest(
                &archive.admission_snapshot_verification_digest,
            )?,
            admission_snapshot_observed_unix_ms: archive.admission_snapshot_observed_unix_ms,
            revocation_epoch: archive.revocation_epoch,
            preparation_digest: parse_digest(&archive.preparation_digest)?,
            authority: AuthorityPosture::DENY_ALL,
        };
        preparation.validate_for(attachment, serialization, profile)?;
        Ok(preparation)
    }
}

fn parse_digest(value: &str) -> Result<Digest32, ContextCompilerV2Error> {
    let digest = Digest32::from_str(value)
        .map_err(|_| ContextCompilerV2Error::DeliveryMismatch)?;
    if digest.is_zero() {
        return Err(ContextCompilerV2Error::DeliveryMismatch);
    }
    Ok(digest)
}
