//! Withdrawal-frontier-bound artifact admission.
//!
//! The stable V2 manifest and withdrawal registry remain source compatible.
//! This additive receipt binds admission to the exact withdrawal head and
//! authority domain observed during validation and requires both immediately
//! before publication. A product host must perform the final check while holding
//! its exclusive writer fence; a stale or cross-domain receipt is never
//! publication authority.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactClosureError;
use crate::DatasetWithdrawalRegistry;
use crate::LearningArtifactManifestV2;
use crate::ValidatedArtifactManifestV2;
use crate::validate_artifact_manifest_v2;

/// Host-authenticated identity of the withdrawal authority domain whose head is
/// used for admission. The scope is explicit so two registries with the same
/// digest frontier (including two empty registries) are not interchangeable.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WithdrawalAuthorityDomainV1 {
    pub registry_id: StableId,
    pub scope_digest: Digest32,
    pub authority_id: StableId,
    pub authority_epoch: u64,
}

impl WithdrawalAuthorityDomainV1 {
    fn validate(&self) -> Result<(), ArtifactAdmissionError> {
        if self.scope_digest.is_zero() || self.authority_epoch == 0 {
            return Err(ArtifactAdmissionError::WithdrawalDomainInvalid);
        }
        Ok(())
    }

    fn binding_digest(&self) -> Result<Digest32, ArtifactAdmissionError> {
        self.validate()?;
        let mut bytes = b"hepta.learning-artifacts.withdrawal-authority-domain.v1".to_vec();
        push_id(&mut bytes, &self.registry_id);
        bytes.extend_from_slice(self.scope_digest.as_array());
        push_id(&mut bytes, &self.authority_id);
        bytes.extend_from_slice(&self.authority_epoch.to_be_bytes());
        Ok(Digest32::of_bytes(&bytes))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WithdrawalBoundArtifactAdmissionV3 {
    pub validated_manifest: ValidatedArtifactManifestV2,
    pub withdrawal_domain: WithdrawalAuthorityDomainV1,
    pub withdrawal_domain_digest: Digest32,
    pub withdrawal_head_digest: Digest32,
    pub admitted_at: u64,
    pub admission_digest: Digest32,
    pub authority: AuthorityPosture,
}

pub fn admit_manifest_at_withdrawal_head_v3(
    registry: &DatasetWithdrawalRegistry,
    withdrawal_domain: WithdrawalAuthorityDomainV1,
    expected_withdrawal_head: Digest32,
    manifest: LearningArtifactManifestV2,
    now: u64,
) -> Result<WithdrawalBoundArtifactAdmissionV3, ArtifactAdmissionError> {
    let withdrawal_domain_digest = withdrawal_domain.binding_digest()?;
    let observed_head = registry.snapshot().head_digest;
    if observed_head != expected_withdrawal_head {
        return Err(ArtifactAdmissionError::WithdrawalHeadChanged);
    }
    let validated_manifest = registry.admit_manifest(manifest, now)?;
    let admission_digest = digest_admission(
        validated_manifest.manifest_digest,
        withdrawal_domain_digest,
        observed_head,
        now,
    );
    Ok(WithdrawalBoundArtifactAdmissionV3 {
        validated_manifest,
        withdrawal_domain,
        withdrawal_domain_digest,
        withdrawal_head_digest: observed_head,
        admitted_at: now,
        admission_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn verify_artifact_admission_v3(
    admission: &WithdrawalBoundArtifactAdmissionV3,
    current_withdrawal_domain: &WithdrawalAuthorityDomainV1,
    current_withdrawal_head: Digest32,
    now: u64,
) -> Result<(), ArtifactAdmissionError> {
    if admission.authority.grants_any() || admission.validated_manifest.authority.grants_any() {
        return Err(ArtifactAdmissionError::AuthorityGrant);
    }
    let current_domain_digest = current_withdrawal_domain.binding_digest()?;
    if admission.withdrawal_domain != *current_withdrawal_domain
        || admission.withdrawal_domain_digest != current_domain_digest
    {
        return Err(ArtifactAdmissionError::WithdrawalDomainMismatch);
    }
    if admission.withdrawal_head_digest != current_withdrawal_head {
        return Err(ArtifactAdmissionError::WithdrawalHeadChanged);
    }
    if admission.admitted_at > now {
        return Err(ArtifactAdmissionError::AdmissionTimeWindow);
    }
    let revalidated =
        validate_artifact_manifest_v2(admission.validated_manifest.manifest.clone(), now)?;
    if revalidated.manifest_digest != admission.validated_manifest.manifest_digest {
        return Err(ArtifactAdmissionError::ManifestDigestMismatch);
    }
    let expected = digest_admission(
        admission.validated_manifest.manifest_digest,
        admission.withdrawal_domain_digest,
        admission.withdrawal_head_digest,
        admission.admitted_at,
    );
    if expected != admission.admission_digest {
        return Err(ArtifactAdmissionError::AdmissionDigestMismatch);
    }
    Ok(())
}

pub fn validate_artifact_publication_v3(
    admission: &WithdrawalBoundArtifactAdmissionV3,
    registry: &DatasetWithdrawalRegistry,
    current_withdrawal_domain: &WithdrawalAuthorityDomainV1,
    now: u64,
) -> Result<(), ArtifactAdmissionError> {
    verify_artifact_admission_v3(
        admission,
        current_withdrawal_domain,
        registry.snapshot().head_digest,
        now,
    )
}

fn digest_admission(
    manifest_digest: Digest32,
    withdrawal_domain_digest: Digest32,
    withdrawal_head_digest: Digest32,
    admitted_at: u64,
) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.withdrawal-bound-admission.v3".to_vec();
    bytes.extend_from_slice(manifest_digest.as_array());
    bytes.extend_from_slice(withdrawal_domain_digest.as_array());
    bytes.extend_from_slice(withdrawal_head_digest.as_array());
    bytes.extend_from_slice(&admitted_at.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ArtifactAdmissionError {
    Manifest(ArtifactClosureError),
    WithdrawalDomainInvalid,
    WithdrawalDomainMismatch,
    WithdrawalHeadChanged,
    AuthorityGrant,
    AdmissionTimeWindow,
    ManifestDigestMismatch,
    AdmissionDigestMismatch,
}

impl fmt::Display for ArtifactAdmissionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ArtifactAdmissionError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Manifest(error) => Some(error),
            Self::WithdrawalDomainInvalid
            | Self::WithdrawalDomainMismatch
            | Self::WithdrawalHeadChanged
            | Self::AuthorityGrant
            | Self::AdmissionTimeWindow
            | Self::ManifestDigestMismatch
            | Self::AdmissionDigestMismatch => None,
        }
    }
}

impl From<ArtifactClosureError> for ArtifactAdmissionError {
    fn from(value: ArtifactClosureError) -> Self {
        Self::Manifest(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_types::Generation;

    use crate::ArtifactKind;
    use crate::DatasetWithdrawalNoticeV1;
    use crate::ProvenanceModeV1;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid test id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn domain(name: &str) -> WithdrawalAuthorityDomainV1 {
        WithdrawalAuthorityDomainV1 {
            registry_id: id(&format!("withdrawal-registry-{name}")),
            scope_digest: digest(&format!("withdrawal-scope-{name}")),
            authority_id: id(&format!("withdrawal-authority-{name}")),
            authority_epoch: 7,
        }
    }

    fn manifest(dataset: Digest32) -> LearningArtifactManifestV2 {
        LearningArtifactManifestV2 {
            artifact_id: id("artifact-v3"),
            kind: ArtifactKind::Model,
            generation: Generation::new(1).expect("valid generation"),
            provenance_mode: ProvenanceModeV1::DatasetDerived,
            source_dataset_digests: vec![dataset],
            lineage_digests: vec![digest("lineage")],
            predecessor_ids: Vec::new(),
            rollback_predecessor: None,
            bytes_digest: digest("bytes"),
            encoded_size_bytes: 512,
            training_code_digest: digest("training-code"),
            runtime_tuple_digest: digest("runtime"),
            device_profile_digest: digest("device"),
            objective_class_digest: digest("objective"),
            compatibility_digest: digest("compatibility"),
            schema_profile_digest: digest("schema"),
            normalization_digest: digest("normalization"),
            producer_id: id("producer"),
            created_at: 10,
            expires_at: 100,
        }
    }

    #[test]
    fn art_05_admission_binds_exact_withdrawal_head_and_domain() {
        let registry = DatasetWithdrawalRegistry::new();
        let withdrawal_domain = domain("primary");
        let head = registry.snapshot().head_digest;
        let admission = admit_manifest_at_withdrawal_head_v3(
            &registry,
            withdrawal_domain.clone(),
            head,
            manifest(digest("dataset")),
            20,
        )
        .expect("admission succeeds");
        validate_artifact_publication_v3(&admission, &registry, &withdrawal_domain, 20)
            .expect("unchanged domain/head remains valid");
        assert!(!admission.authority.grants_any());
    }

    #[test]
    fn art_05_cross_domain_zero_head_is_rejected() {
        let registry = DatasetWithdrawalRegistry::new();
        let primary = domain("primary");
        let foreign = domain("foreign");
        let admission = admit_manifest_at_withdrawal_head_v3(
            &registry,
            primary,
            Digest32::ZERO,
            manifest(digest("dataset")),
            20,
        )
        .expect("admission succeeds");
        assert_eq!(
            validate_artifact_publication_v3(&admission, &registry, &foreign, 20),
            Err(ArtifactAdmissionError::WithdrawalDomainMismatch)
        );
    }

    #[test]
    fn art_05_withdrawal_race_invalidates_admission() {
        let dataset = digest("dataset");
        let mut registry = DatasetWithdrawalRegistry::new();
        let withdrawal_domain = domain("primary");
        let admission = admit_manifest_at_withdrawal_head_v3(
            &registry,
            withdrawal_domain.clone(),
            registry.snapshot().head_digest,
            manifest(dataset),
            20,
        )
        .expect("initial admission succeeds");
        registry
            .append(DatasetWithdrawalNoticeV1 {
                notice_id: id("notice"),
                dataset_digest: dataset,
                source_tombstone_digest: digest("tombstone"),
                authority_id: id("authority"),
                credential_chain_digest: digest("credential"),
                signing_key_digest: digest("key"),
                authority_epoch: 1,
                issued_at: 21,
            })
            .expect("withdrawal appends");
        assert_eq!(
            validate_artifact_publication_v3(&admission, &registry, &withdrawal_domain, 21),
            Err(ArtifactAdmissionError::WithdrawalHeadChanged)
        );
    }
}
