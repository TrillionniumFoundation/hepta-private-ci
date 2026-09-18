//! Read-only operational snapshot for learning-artifact storage.
//!
//! The caller supplies the registry, withdrawal frontier and lifecycle journal
//! that it already considers current. This module does not discover a newer
//! head, mutate storage, select an artifact, activate a model or grant release
//! authority.

use codex_hepta_types::{AuthorityPosture, Digest32};

use crate::{
    ArtifactEvent, ArtifactLifecycleJournalV2, ArtifactRegistry, ArtifactState,
    DatasetWithdrawalRegistry, WithdrawalRegistryBindingV1,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ArtifactAdminSnapshotV1 {
    pub registry_head_digest: Digest32,
    pub registry_records: usize,
    pub registered_artifacts: usize,
    pub eligible_artifacts: usize,
    pub quarantined_artifacts: usize,
    pub revoked_artifacts: usize,
    pub withdrawal_binding_digest: Option<Digest32>,
    pub withdrawal_head_digest: Digest32,
    pub withdrawal_records: usize,
    pub lifecycle_head_digest: Digest32,
    pub lifecycle_records: usize,
    pub authority: AuthorityPosture,
}

/// Summarize already-supplied artifact state without acquiring any write or
/// selection capability.
#[must_use]
pub fn inspect_artifact_admin_state(
    registry: &ArtifactRegistry,
    withdrawal: &DatasetWithdrawalRegistry,
    lifecycle: &ArtifactLifecycleJournalV2,
) -> ArtifactAdminSnapshotV1 {
    let registry_snapshot = registry.snapshot();
    let withdrawal_snapshot = withdrawal.snapshot();
    let mut registered_artifacts = 0;
    let mut eligible_artifacts = 0;
    let mut quarantined_artifacts = 0;
    let mut revoked_artifacts = 0;

    for record in registry.records() {
        let ArtifactEvent::Register { manifest, .. } = &record.event else {
            continue;
        };
        registered_artifacts += 1;
        if registry.is_eligible(&manifest.artifact_id) {
            eligible_artifacts += 1;
        }
        match registry.state(&manifest.artifact_id) {
            Some(ArtifactState::Quarantined) => quarantined_artifacts += 1,
            Some(ArtifactState::Revoked) => revoked_artifacts += 1,
            Some(ArtifactState::Candidate) | None => {}
        }
    }

    ArtifactAdminSnapshotV1 {
        registry_head_digest: registry_snapshot.head_digest,
        registry_records: registry.records().len(),
        registered_artifacts,
        eligible_artifacts,
        quarantined_artifacts,
        revoked_artifacts,
        withdrawal_binding_digest: withdrawal
            .binding()
            .map(WithdrawalRegistryBindingV1::binding_digest),
        withdrawal_head_digest: withdrawal_snapshot.head_digest,
        withdrawal_records: withdrawal_snapshot.records().len(),
        lifecycle_head_digest: lifecycle.head_digest(),
        lifecycle_records: lifecycle.records().len(),
        authority: AuthorityPosture::DENY_ALL,
    }
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::{Digest32, Generation, StableId};

    use super::*;
    use crate::{ArtifactKind, ArtifactManifest};

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn admin_snapshot_is_read_only_and_deny_all() {
        let mut registry = ArtifactRegistry::new();
        registry
            .append(ArtifactEvent::Register {
                event_id: id("register-admin-fixture"),
                manifest: ArtifactManifest {
                    artifact_id: id("artifact-admin-fixture"),
                    kind: ArtifactKind::Model,
                    generation: Generation::new(1).expect("generation"),
                    predecessor_id: None,
                    content_digest: digest("content"),
                    objective_digest: digest("objective"),
                    support_digest: digest("dataset"),
                    producer_id: id("producer"),
                    compatibility_digest: digest("compatibility"),
                    encoded_size_bytes: 7,
                },
            })
            .expect("register fixture");

        let withdrawal = DatasetWithdrawalRegistry::new_scoped(
            WithdrawalRegistryBindingV1::new(id("withdrawal-registry"), digest("scope"))
                .expect("binding"),
        )
        .expect("scoped registry");
        let lifecycle = ArtifactLifecycleJournalV2::new();

        let before = registry.snapshot();
        let snapshot = inspect_artifact_admin_state(&registry, &withdrawal, &lifecycle);

        assert_eq!(snapshot.registry_head_digest, before.head_digest);
        assert_eq!(snapshot.registry_records, 1);
        assert_eq!(snapshot.registered_artifacts, 1);
        assert_eq!(snapshot.eligible_artifacts, 1);
        assert_eq!(snapshot.quarantined_artifacts, 0);
        assert_eq!(snapshot.revoked_artifacts, 0);
        assert!(snapshot.withdrawal_binding_digest.is_some());
        assert_eq!(snapshot.withdrawal_head_digest, Digest32::ZERO);
        assert_eq!(snapshot.withdrawal_records, 0);
        assert_eq!(snapshot.lifecycle_head_digest, Digest32::ZERO);
        assert_eq!(snapshot.lifecycle_records, 0);
        assert!(!snapshot.authority.grants_any());
        assert_eq!(registry.snapshot(), before);
    }
}
