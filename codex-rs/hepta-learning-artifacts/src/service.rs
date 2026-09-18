//! Read-only owner status for administration and reconciliation.
//!
//! This surface reports already-owned state. It does not discover newest files,
//! authenticate remote callers, delete orphans, select artifacts, activate a
//! generation, or grant mutation authority.

use codex_hepta_types::{AuthorityPosture, Digest32};

use crate::{
    ArtifactAdmissionError, ArtifactLifecycleJournalV2, ArtifactRegistry,
    DatasetWithdrawalRegistry, MAX_DURABLE_ARTIFACT_RECORDS, WithdrawalAuthorityDomainV1,
    withdrawal_head_digest_v3,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ArtifactOwnerStatusV1 {
    pub registry_head_digest: Digest32,
    pub registry_records: usize,
    pub registry_remaining_records: usize,
    pub withdrawal_head_digest: Digest32,
    pub withdrawal_records: usize,
    pub withdrawal_remaining_records: usize,
    pub lifecycle_head_digest: Digest32,
    pub lifecycle_records: usize,
    pub lifecycle_remaining_records: usize,
    pub status_digest: Digest32,
    pub authority: AuthorityPosture,
}

pub fn inspect_artifact_owner_status_v1(
    registry: &ArtifactRegistry,
    withdrawal: &DatasetWithdrawalRegistry,
    withdrawal_domain: &WithdrawalAuthorityDomainV1,
    lifecycle: &ArtifactLifecycleJournalV2,
) -> Result<ArtifactOwnerStatusV1, ArtifactAdmissionError> {
    let registry_head_digest = registry.head_digest();
    let registry_records = registry.records().len();
    let withdrawal_records = withdrawal.record_count();
    let withdrawal_head_digest = withdrawal_head_digest_v3(withdrawal, withdrawal_domain)?;
    let lifecycle_head_digest = lifecycle.head_digest();
    let lifecycle_records = lifecycle.records().len();

    let registry_remaining_records =
        MAX_DURABLE_ARTIFACT_RECORDS.saturating_sub(registry_records);
    let withdrawal_remaining_records =
        MAX_DURABLE_ARTIFACT_RECORDS.saturating_sub(withdrawal_records);
    let lifecycle_remaining_records =
        MAX_DURABLE_ARTIFACT_RECORDS.saturating_sub(lifecycle_records);

    let status_digest = digest_status(
        registry_head_digest,
        registry_records,
        withdrawal_head_digest,
        withdrawal_records,
        lifecycle_head_digest,
        lifecycle_records,
    );

    Ok(ArtifactOwnerStatusV1 {
        registry_head_digest,
        registry_records,
        registry_remaining_records,
        withdrawal_head_digest,
        withdrawal_records,
        withdrawal_remaining_records,
        lifecycle_head_digest,
        lifecycle_records,
        lifecycle_remaining_records,
        status_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn digest_status(
    registry_head_digest: Digest32,
    registry_records: usize,
    withdrawal_head_digest: Digest32,
    withdrawal_records: usize,
    lifecycle_head_digest: Digest32,
    lifecycle_records: usize,
) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.owner-status.v1".to_vec();
    bytes.extend_from_slice(registry_head_digest.as_array());
    bytes.extend_from_slice(
        &u64::try_from(registry_records)
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(withdrawal_head_digest.as_array());
    bytes.extend_from_slice(
        &u64::try_from(withdrawal_records)
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(lifecycle_head_digest.as_array());
    bytes.extend_from_slice(
        &u64::try_from(lifecycle_records)
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::StableId;

    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid test id")
    }

    fn domain(scope: &str) -> WithdrawalAuthorityDomainV1 {
        WithdrawalAuthorityDomainV1 {
            registry_id: id("withdrawal-registry"),
            scope_digest: Digest32::of_bytes(scope.as_bytes()),
            authority_id: id("withdrawal-authority"),
            authority_epoch: 7,
        }
    }

    #[test]
    fn status_is_bounded_deny_all_and_domain_specific() {
        let registry = ArtifactRegistry::new();
        let withdrawal = DatasetWithdrawalRegistry::new();
        let lifecycle = ArtifactLifecycleJournalV2::new();

        let a = inspect_artifact_owner_status_v1(
            &registry,
            &withdrawal,
            &domain("tenant-a"),
            &lifecycle,
        )
        .expect("valid status");
        let b = inspect_artifact_owner_status_v1(
            &registry,
            &withdrawal,
            &domain("tenant-b"),
            &lifecycle,
        )
        .expect("valid status");

        assert_eq!(a.registry_remaining_records, MAX_DURABLE_ARTIFACT_RECORDS);
        assert_eq!(a.withdrawal_remaining_records, MAX_DURABLE_ARTIFACT_RECORDS);
        assert_eq!(a.lifecycle_remaining_records, MAX_DURABLE_ARTIFACT_RECORDS);
        assert!(!a.authority.grants_any());
        assert_ne!(a.withdrawal_head_digest, b.withdrawal_head_digest);
        assert_ne!(a.status_digest, b.status_digest);
    }
}
