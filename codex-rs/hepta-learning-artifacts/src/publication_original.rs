//! Persist the fresh writer/independent HEAD protocol in the original intent.
//! Its cold evidence can be authenticated without becoming a legacy resume
//! capability. Legacy publication digests and recovery remain unchanged.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::ArtifactPublicationError;
use super::ArtifactPublicationTransactionSnapshotV1;
use super::ArtifactPublicationTransactionV1;
use super::digest_intent;
use crate::ArtifactRegistry;
use crate::DatasetWithdrawalRegistry;
use crate::WithdrawalBoundArtifactAdmissionV3;

impl ArtifactPublicationTransactionV1 {
    pub(crate) fn begin_original_registry(
        operation_id: StableId,
        admission: WithdrawalBoundArtifactAdmissionV3,
        withdrawals: &DatasetWithdrawalRegistry,
        registry: &ArtifactRegistry,
        predecessor: Digest32,
        now: u64,
    ) -> Result<Self, ArtifactPublicationError> {
        let mut transaction = Self::begin(
            operation_id,
            admission,
            withdrawals,
            registry,
            predecessor,
            now,
        )?;
        transaction.intent.intent_digest = digest_original_registry_intent(
            &transaction.intent.operation_id,
            &transaction.intent.admission,
            transaction.intent.expected_registry_predecessor_head,
        );
        transaction.refresh_state_digest();
        Ok(transaction)
    }

    // Only the original physical reader and its authenticated source decoder
    // use this internal reconstruction. No public resume path accepts it.
    pub(crate) fn from_original_registry_snapshot(
        snapshot: ArtifactPublicationTransactionSnapshotV1,
    ) -> Result<Self, ArtifactPublicationError> {
        let expected_intent = digest_original_registry_intent(
            &snapshot.intent.operation_id,
            &snapshot.intent.admission,
            snapshot.intent.expected_registry_predecessor_head,
        );
        Self::from_snapshot_with_intent_digest(snapshot, expected_intent)
    }
}

pub(crate) fn digest_original_registry_intent(
    operation_id: &StableId,
    admission: &WithdrawalBoundArtifactAdmissionV3,
    predecessor: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.original-registry-preparation-intent.v1".to_vec();
    bytes.extend_from_slice(digest_intent(operation_id, admission, predecessor).as_array());
    Digest32::of_bytes(&bytes)
}
