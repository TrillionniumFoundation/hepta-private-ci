//! Product-owned registry restrictions with immutable signed frontier recovery.

use std::collections::BTreeSet;

use super::*;

use crate::ArtifactEvent;
use crate::ArtifactOwnerStateIntentV1;
use crate::ArtifactOwnerStatePublicationReceiptV1;
use crate::ArtifactOwnerStateTransitionV1;
use crate::ArtifactState;
use crate::LearningArtifactStatePublishRequestV1;
use crate::StateChange;

#[derive(Clone, Debug)]
pub struct LearningArtifactOwnerServiceConfigV2 {
    pub owner: LearningArtifactOwnerServiceConfigV1,
    /// An independently retained trusted frontier floor, never inferred from
    /// the files being recovered. Newer prefix extensions satisfy this floor.
    pub required_withdrawal_head_digest: Digest32,
}

impl LearningArtifactOwnerService {
    pub fn open_v2(
        config: LearningArtifactOwnerServiceConfigV2,
    ) -> Result<Self, LearningArtifactOwnerServiceError> {
        let floor = config.required_withdrawal_head_digest;
        if floor.is_zero() {
            return Err(LearningArtifactOwnerServiceError::InvalidConfiguration);
        }
        let service = Self::open(config.owner)?;
        let snapshot = service.withdrawal_registry.snapshot();
        let scoped_genesis = DatasetWithdrawalRegistry::new_scoped(
            service
                .withdrawal_registry
                .scope()
                .cloned()
                .ok_or(LearningArtifactOwnerServiceError::InvalidConfiguration)?,
        )
        .head_digest();
        if floor != scoped_genesis
            && floor != snapshot.head_digest
            && !snapshot
                .records()
                .iter()
                .any(|record| record.chain_digest == floor)
        {
            return Err(LearningArtifactOwnerServiceError::WithdrawalHeadRollback);
        }
        Ok(service)
    }

    /// Deterministically prepare the exact successor for the independent signer.
    /// Preparation performs no writes and grants no acknowledgement.
    pub fn prepare_state_registry(
        &self,
        intent: &ArtifactOwnerStateIntentV1,
    ) -> Result<ArtifactRegistry, LearningArtifactOwnerServiceError> {
        if intent.reason_digest.is_zero()
            || intent.next_withdrawal_registry.scope_digest()
                != self.withdrawal_registry.scope_digest()
        {
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }
        let existing = self.host.recover_state_publication(&intent.operation_id)?;
        if existing.is_none()
            && (intent.expected_registry_predecessor_head != self.registry.snapshot().head_digest
                || intent.expected_withdrawal_predecessor_head
                    != self.withdrawal_registry.head_digest())
        {
            return Err(LearningArtifactOwnerServiceError::WithdrawalFrontierConflict);
        }
        if existing.as_ref().is_some_and(|checkpoint| {
            checkpoint.expected_registry_predecessor_head
                != intent.expected_registry_predecessor_head
                || checkpoint.expected_withdrawal_predecessor_head
                    != intent.expected_withdrawal_predecessor_head
        }) {
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }
        let predecessor = self.host.recover_withdrawal_by_head(
            intent.expected_withdrawal_predecessor_head,
            &self.withdrawal_registry,
        )?;
        let previous = predecessor.snapshot();
        let next = intent.next_withdrawal_registry.snapshot();
        if next.records().len() < previous.records().len()
            || &next.records()[..previous.records().len()] != previous.records()
        {
            return Err(LearningArtifactOwnerServiceError::WithdrawalFrontierConflict);
        }
        let live = self.withdrawal_registry.snapshot();
        if next.records().len() < live.records().len()
            || &next.records()[..live.records().len()] != live.records()
        {
            return Err(LearningArtifactOwnerServiceError::WithdrawalFrontierConflict);
        }
        if !matches!(
            intent.transition,
            ArtifactOwnerStateTransitionV1::InstallWithdrawalFrontier
        ) && next.records() != previous.records()
        {
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }
        let base = self
            .host
            .recover_registry_by_head(intent.expected_registry_predecessor_head)?;
        let admissions = self
            .host
            .load_admissions_for_registry(&base, self.storage_binding)?;
        let mut targets = BTreeSet::new();
        match &intent.transition {
            ArtifactOwnerStateTransitionV1::InstallWithdrawalFrontier => {
                for admission in &admissions {
                    let manifest = &admission.validated_manifest.manifest;
                    if manifest
                        .source_dataset_digests
                        .iter()
                        .any(|dataset| intent.next_withdrawal_registry.is_withdrawn(*dataset))
                    {
                        targets.insert(manifest.artifact_id.clone());
                    }
                }
            }
            ArtifactOwnerStateTransitionV1::Revoke { artifact_id }
            | ArtifactOwnerStateTransitionV1::Quarantine { artifact_id } => {
                if base.manifest(artifact_id).is_none() {
                    return Err(LearningArtifactOwnerServiceError::RequestMismatch);
                }
                targets.insert(artifact_id.clone());
            }
        }
        // Registration order is a strict DAG order after the full admission
        // join; every parent must already exist and precede its descendants.
        crate::admission_closure::eligible_admission_closure(&base, &admissions, &predecessor, 0)
            .map_err(|_| ArtifactOwnerHostError::FullAdmissionRejected)?;
        for admission in &admissions {
            let manifest = &admission.validated_manifest.manifest;
            if manifest
                .predecessor_ids
                .iter()
                .any(|parent| targets.contains(parent))
            {
                targets.insert(manifest.artifact_id.clone());
            }
        }
        let quarantine = matches!(
            intent.transition,
            ArtifactOwnerStateTransitionV1::Quarantine { .. }
        );
        let mut staged = base;
        for target in targets {
            let state = staged.state(&target);
            if state == Some(ArtifactState::Revoked)
                || quarantine && state == Some(ArtifactState::Quarantined)
            {
                continue;
            }
            let mut identity = b"hepta.learning-artifacts.state-event.v1".to_vec();
            identity.extend_from_slice(intent.operation_id.as_str().as_bytes());
            identity.push(0);
            identity.extend_from_slice(target.as_str().as_bytes());
            identity.push(u8::from(quarantine));
            let change = StateChange {
                event_id: StableId::new(format!(
                    "artifact-state:{}",
                    Digest32::of_bytes(&identity)
                ))
                .map_err(|_| LearningArtifactOwnerServiceError::RequestMismatch)?,
                artifact_id: target,
                evaluator_id: intent.evaluator_id.clone(),
                reason_digest: intent.reason_digest,
            };
            staged
                .append(if quarantine {
                    ArtifactEvent::Quarantine(change)
                } else {
                    ArtifactEvent::Revoke(change)
                })
                .map_err(ArtifactOwnerHostError::from)?;
        }
        Ok(staged)
    }

    pub fn publish_state(
        &mut self,
        request: LearningArtifactStatePublishRequestV1,
    ) -> Result<ArtifactOwnerStatePublicationReceiptV1, LearningArtifactOwnerServiceError> {
        let operation = request.intent.operation_id.clone();
        if let Some(blocked) = &self.recovery_required
            && blocked != &operation
        {
            return Err(LearningArtifactOwnerServiceError::RecoveryRequired(
                blocked.clone(),
            ));
        }
        if request.signed_current_head.binding != self.storage_binding {
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }
        let existing = self.host.recover_state_publication(&operation)?;
        if existing
            .as_ref()
            .is_some_and(super::super::owner_host::state::StateCheckpoint::is_acknowledged)
        {
            return Ok(self.host.publish_state_snapshots(
                &request,
                &self.registry,
                &self.withdrawal_registry,
            )?);
        }
        let predecessor = self.host.recover_withdrawal_by_head(
            request.intent.expected_withdrawal_predecessor_head,
            &self.withdrawal_registry,
        )?;
        let registry = self.prepare_state_registry(&request.intent)?;
        match self
            .host
            .publish_state_snapshots(&request, &registry, &predecessor)
        {
            Ok(receipt) => {
                self.registry = registry;
                self.withdrawal_registry = request.intent.next_withdrawal_registry;
                self.recovery_required = None;
                Ok(receipt)
            }
            Err(error) => {
                if self
                    .host
                    .recover_state_publication(&operation)?
                    .is_some_and(|checkpoint| !checkpoint.is_acknowledged())
                {
                    self.recovery_required = Some(operation);
                    self.withdrawal_registry = self.host.recover_durable_withdrawal_frontier(
                        self.withdrawal_registry.clone(),
                        self.storage_binding,
                    )?;
                }
                Err(error.into())
            }
        }
    }

    pub fn backfill_artifact_admission(
        &self,
        admission: &WithdrawalBoundArtifactAdmissionV3,
        now: u64,
    ) -> Result<crate::ArtifactAdmissionSnapshotReceiptV3, LearningArtifactOwnerServiceError> {
        Ok(self.host.backfill_artifact_admission(
            admission,
            &self.registry,
            self.storage_binding,
            now,
        )?)
    }
}
