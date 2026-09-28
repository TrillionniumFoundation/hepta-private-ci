// Named product writer service for the immutable learning-artifact store.
//
// This is the single product caller of LearningArtifactOwnerHost. The service
// serializes publications under one writer fence, owns the in-process artifact
// registry and current withdrawal frontier, and blocks unrelated work while a
// prior operation has a non-terminal durable checkpoint.

use std::error::Error as StdError;
use std::fmt;
use std::path::PathBuf;
use std::time::Instant;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactOwnerHostError;
use crate::ArtifactOwnerTrustV1;
use crate::ArtifactPublicationError;
use crate::ArtifactPublicationPhaseV1;
use crate::ArtifactPublicationReceiptV1;
use crate::ArtifactPublicationTransactionV1;
use crate::ArtifactRegistry;
use crate::DatasetWithdrawalRegistry;
use crate::LearningArtifactOwnerHost;
use crate::SignedArtifactWriterLeaseV1;
use crate::SignedCurrentArtifactHeadV1;
use crate::VerifiedCurrentRegistryViewV1;
use crate::WithdrawalBoundArtifactAdmissionV3;

use durable_control::DurableDrain;
use durable_inputs::verify_durable_inputs;
use durable_withdrawals::DurableWithdrawalFloor;
use operational_state::OwnerOperationalState;
use publication_recovery::rebuild_transaction;
use publication_recovery::receipt_from_checkpoint;
use publication_recovery::validate_request_against_checkpoint;
use request_identity::RequestIdentityStore;

pub use operational_metrics::ArtifactOwnerOperationalMetricsV1;
pub use operational_metrics::ArtifactOwnerOperationalSnapshotV1;
pub use operational_metrics::ArtifactOwnerResourceUsageV1;
pub use operational_metrics::ArtifactOwnerStageLatencyV1;
pub use operational_metrics::ArtifactOwnerStageV1;

#[derive(Clone, Debug)]
pub struct LearningArtifactOwnerServiceConfigV1 {
    pub root: PathBuf,
    pub trust: ArtifactOwnerTrustV1,
    pub writer_lease: SignedArtifactWriterLeaseV1,
    pub required_current_head: Option<SignedCurrentArtifactHeadV1>,
    pub withdrawal_registry: DatasetWithdrawalRegistry,
    pub storage_binding: Digest32,
    pub now: u64,
}

#[derive(Clone, Debug)]
pub struct LearningArtifactPublishRequestV1 {
    pub operation_id: StableId,
    pub admission: WithdrawalBoundArtifactAdmissionV3,
    pub payload: Vec<u8>,
    pub signed_current_head: SignedCurrentArtifactHeadV1,
    pub expected_registry_predecessor_head: Digest32,
    pub now: u64,
}

pub struct LearningArtifactOwnerService {
    host: LearningArtifactOwnerHost,
    root: PathBuf,
    durable_drain: DurableDrain,
    durable_withdrawals: DurableWithdrawalFloor,
    withdrawal_registry: DatasetWithdrawalRegistry,
    registry: ArtifactRegistry,
    storage_binding: Digest32,
    request_identity: RequestIdentityStore,
    operational_state: OwnerOperationalState,
    metrics: ArtifactOwnerOperationalMetricsV1,
}

impl fmt::Debug for LearningArtifactOwnerService {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("LearningArtifactOwnerService")
            .field("host", &self.host)
            .field("registry_head", &self.registry.snapshot().head_digest)
            .field("withdrawal_head", &self.withdrawal_registry.head_digest())
            .field("storage_binding", &self.storage_binding)
            .field("operational_state", &self.operational_state)
            .finish()
    }
}
