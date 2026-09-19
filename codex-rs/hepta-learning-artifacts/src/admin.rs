//! Read-only operational status for the learning-artifact owner.
//!
//! This surface reports state already supplied by the authoritative owner. It
//! does not discover newer files, mutate durable state, select artifacts,
//! activate models, repair storage, or grant release authority.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::ArtifactLifecycleJournalV2;
use crate::ArtifactRegistry;
use crate::DatasetWithdrawalRegistry;
use crate::MAX_DURABLE_ARTIFACT_RECORDS;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ArtifactOwnerStatusV1 {
    pub registry_head_digest: Digest32,
    pub registry_records: usize,
    pub registry_remaining_records: usize,
    pub withdrawal_scope_digest: Option<Digest32>,
    pub withdrawal_head_digest: Digest32,
    pub withdrawal_records: usize,
    pub withdrawal_remaining_records: usize,
    pub lifecycle_head_digest: Digest32,
    pub lifecycle_records: usize,
    pub lifecycle_remaining_records: usize,
    pub status_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[must_use]
pub fn inspect_artifact_owner_status_v1(
    registry: &ArtifactRegistry,
    withdrawal: &DatasetWithdrawalRegistry,
    lifecycle: &ArtifactLifecycleJournalV2,
) -> ArtifactOwnerStatusV1 {
    let registry_head_digest = registry.snapshot().head_digest;
    let registry_records = registry.records().len();
    let withdrawal_snapshot = withdrawal.snapshot();
    let withdrawal_scope_digest = withdrawal.scope_digest();
    let withdrawal_head_digest = withdrawal.head_digest();
    let withdrawal_records = withdrawal_snapshot.records().len();
    let lifecycle_head_digest = lifecycle.head_digest();
    let lifecycle_records = lifecycle.records().len();

    let status_digest = digest_status(
        registry_head_digest,
        registry_records,
        withdrawal_scope_digest,
        withdrawal_head_digest,
        withdrawal_records,
        lifecycle_head_digest,
        lifecycle_records,
    );

    ArtifactOwnerStatusV1 {
        registry_head_digest,
        registry_records,
        registry_remaining_records: MAX_DURABLE_ARTIFACT_RECORDS.saturating_sub(registry_records),
        withdrawal_scope_digest,
        withdrawal_head_digest,
        withdrawal_records,
        withdrawal_remaining_records: MAX_DURABLE_ARTIFACT_RECORDS
            .saturating_sub(withdrawal_records),
        lifecycle_head_digest,
        lifecycle_records,
        lifecycle_remaining_records: MAX_DURABLE_ARTIFACT_RECORDS
            .saturating_sub(lifecycle_records),
        status_digest,
        authority: AuthorityPosture::DENY_ALL,
    }
}

fn digest_status(
    registry_head_digest: Digest32,
    registry_records: usize,
    withdrawal_scope_digest: Option<Digest32>,
    withdrawal_head_digest: Digest32,
    withdrawal_records: usize,
    lifecycle_head_digest: Digest32,
    lifecycle_records: usize,
) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.owner-status.v1".to_vec();
    bytes.extend_from_slice(registry_head_digest.as_array());
    bytes.extend_from_slice(&usize_digest_value(registry_records).to_be_bytes());
    match withdrawal_scope_digest {
        Some(scope_digest) => {
            bytes.push(1);
            bytes.extend_from_slice(scope_digest.as_array());
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(withdrawal_head_digest.as_array());
    bytes.extend_from_slice(&usize_digest_value(withdrawal_records).to_be_bytes());
    bytes.extend_from_slice(lifecycle_head_digest.as_array());
    bytes.extend_from_slice(&usize_digest_value(lifecycle_records).to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn usize_digest_value(value: usize) -> u64 {
    u64::try_from(value).unwrap_or(u64::MAX)
}

#[cfg(test)]
mod tests {
    use super::*;

    use codex_hepta_types::StableId;

    use crate::DatasetWithdrawalScopeV1;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid test id")
    }

    fn scope(name: &str) -> DatasetWithdrawalScopeV1 {
        DatasetWithdrawalScopeV1 {
            authority_domain_id: id(&format!("authority-{name}")),
            registry_id: id(&format!("registry-{name}")),
            scope_id: id(&format!("scope-{name}")),
        }
    }

    #[test]
    fn owner_status_is_bounded_read_only_and_scope_specific() {
        let registry = ArtifactRegistry::new();
        let lifecycle = ArtifactLifecycleJournalV2::new();
        let withdrawal_a = DatasetWithdrawalRegistry::new_scoped(scope("a"));
        let withdrawal_b = DatasetWithdrawalRegistry::new_scoped(scope("b"));

        let status_a = inspect_artifact_owner_status_v1(&registry, &withdrawal_a, &lifecycle);
        let status_b = inspect_artifact_owner_status_v1(&registry, &withdrawal_b, &lifecycle);

        assert_eq!(
            status_a.registry_remaining_records,
            MAX_DURABLE_ARTIFACT_RECORDS
        );
        assert_eq!(
            status_a.withdrawal_remaining_records,
            MAX_DURABLE_ARTIFACT_RECORDS
        );
        assert_eq!(
            status_a.lifecycle_remaining_records,
            MAX_DURABLE_ARTIFACT_RECORDS
        );
        assert!(!status_a.authority.grants_any());
        assert_ne!(
            status_a.withdrawal_scope_digest,
            status_b.withdrawal_scope_digest
        );
        assert_ne!(status_a.withdrawal_head_digest, status_b.withdrawal_head_digest);
        assert_ne!(status_a.status_digest, status_b.status_digest);
    }
}
