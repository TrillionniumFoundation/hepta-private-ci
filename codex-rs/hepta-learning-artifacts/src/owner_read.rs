//! Readback under the existing owner fence, with caller-retained publication pins.
//! A successful read is point-in-time evidence, never activation authority.

use std::fmt;

use codex_hepta_types::Digest32;

use super::LearningArtifactOwnerService;
use super::receipt_from_checkpoint;
use crate::ArtifactAdmissionError;
use crate::ArtifactClosureError;
use crate::ArtifactManifest;
use crate::ArtifactOwnerHostError;
use crate::ArtifactPublicationPhaseV1;
use crate::ArtifactPublicationReceiptV1;
use crate::LearningArtifactManifestV2;
use crate::LearningArtifactOwnerServiceError;
use crate::WithdrawalBoundArtifactAdmissionV3;
use crate::verify_artifact_admission_v3;

/// Pins retained independently of the files being read. An old publication can
/// remain eligible, but the caller must pin the current registry and withdrawal
/// frontiers and the exact original publication predecessor.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactReadPinsV1 {
    pub publication: ArtifactPublicationReceiptV1,
    pub admission: WithdrawalBoundArtifactAdmissionV3,
    pub expected_registry_predecessor_head: Digest32,
    pub current_registry_head: Digest32,
    pub current_withdrawal_head: Digest32,
}

/// Issued only by owner readback after checking CURRENT, durable acknowledgement,
/// complete admission, current source withdrawals, and persisted payload bytes.
/// Re-read before each consumption; retaining this value does not freeze time.
pub struct VerifiedArtifactReadV1 {
    pins: ArtifactReadPinsV1,
    trust_digest: Digest32,
    witness_digest: Digest32,
    bytes: Vec<u8>,
}

impl VerifiedArtifactReadV1 {
    pub fn manifest(&self) -> &LearningArtifactManifestV2 {
        &self.pins.admission.validated_manifest.manifest
    }

    pub fn publication(&self) -> &ArtifactPublicationReceiptV1 {
        &self.pins.publication
    }

    pub fn current_registry_head(&self) -> Digest32 {
        self.pins.current_registry_head
    }

    pub fn current_withdrawal_head(&self) -> Digest32 {
        self.pins.current_withdrawal_head
    }

    pub fn trust_digest(&self) -> Digest32 {
        self.trust_digest
    }

    pub fn witness_digest(&self) -> Digest32 {
        self.witness_digest
    }

    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }
}

impl fmt::Debug for VerifiedArtifactReadV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("VerifiedArtifactReadV1")
            .field("pins", &self.pins)
            .field("payload_bytes", &self.bytes.len())
            .finish_non_exhaustive()
    }
}

#[derive(Debug)]
pub enum ArtifactReadErrorV1 {
    Owner(LearningArtifactOwnerServiceError),
    Host(ArtifactOwnerHostError),
    Admission(ArtifactAdmissionError),
    Withdrawal(ArtifactClosureError),
    PinMismatch,
    RecoveryRequired,
}

impl fmt::Display for ArtifactReadErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for ArtifactReadErrorV1 {}

impl LearningArtifactOwnerService {
    pub fn read_current_artifact(
        &self,
        pins: &ArtifactReadPinsV1,
        now: u64,
    ) -> Result<VerifiedArtifactReadV1, ArtifactReadErrorV1> {
        if self.recovery_required.is_some() {
            return Err(ArtifactReadErrorV1::RecoveryRequired);
        }
        let admission = &pins.admission;
        verify_artifact_admission_v3(admission, admission.withdrawal_head_digest, now)
            .map_err(ArtifactReadErrorV1::Admission)?;
        if self.withdrawal_registry.head_digest() != pins.current_withdrawal_head
            || self.withdrawal_registry.scope_digest() != Some(admission.withdrawal_scope_digest)
        {
            return Err(ArtifactReadErrorV1::PinMismatch);
        }
        let validated = self
            .withdrawal_registry
            .admit_manifest(admission.validated_manifest.manifest.clone(), now)
            .map_err(ArtifactReadErrorV1::Withdrawal)?;
        if validated != admission.validated_manifest {
            return Err(ArtifactReadErrorV1::PinMismatch);
        }
        let recovered = self
            .host
            .recover_publication(&pins.publication.operation_id)
            .map_err(ArtifactReadErrorV1::Host)?
            .ok_or(ArtifactReadErrorV1::PinMismatch)?;
        let checkpoint = &recovered.checkpoint;
        if checkpoint.phase != ArtifactPublicationPhaseV1::Acknowledged
            || checkpoint.authority.grants_any()
            || checkpoint.admission_digest != admission.admission_digest
            || checkpoint.withdrawal_scope_digest != admission.withdrawal_scope_digest
            || checkpoint.withdrawal_head_digest != admission.withdrawal_head_digest
            || checkpoint.expected_registry_predecessor_head
                != pins.expected_registry_predecessor_head
            || receipt_from_checkpoint(checkpoint).map_err(ArtifactReadErrorV1::Owner)?
                != pins.publication
        {
            return Err(ArtifactReadErrorV1::PinMismatch);
        }
        let current = self
            .current_registry_view(now)
            .map_err(ArtifactReadErrorV1::Owner)?;
        let manifest = &validated.manifest;
        let expected = ArtifactManifest {
            artifact_id: manifest.artifact_id.clone(),
            kind: manifest.kind,
            generation: manifest.generation,
            predecessor_id: if manifest.predecessor_ids.len() == 1 {
                manifest.predecessor_ids.first().cloned()
            } else {
                None
            },
            content_digest: manifest.bytes_digest,
            objective_digest: manifest.objective_class_digest,
            support_digest: validated.manifest_digest,
            producer_id: manifest.producer_id.clone(),
            compatibility_digest: manifest.compatibility_digest,
            encoded_size_bytes: manifest.encoded_size_bytes,
        };
        if current.receipt().head_digest != pins.current_registry_head
            || current.receipt().binding != self.storage_binding
            || current.registry().manifest(&manifest.artifact_id) != Some(&expected)
        {
            return Err(ArtifactReadErrorV1::PinMismatch);
        }
        let bytes = self
            .host
            .read_current_payload(&current, &manifest.artifact_id)
            .map_err(ArtifactReadErrorV1::Host)?;
        Ok(VerifiedArtifactReadV1 {
            pins: pins.clone(),
            trust_digest: current.trust_digest(),
            witness_digest: current.witness_digest(),
            bytes,
        })
    }
}
