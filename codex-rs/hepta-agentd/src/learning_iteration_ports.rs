//! Explicit host-owned learning ports. There is no ambient trainer or dataset.

use std::future::Future;
use std::pin::Pin;

use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::TopologyPlasticityProductRequestV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationRequestV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;

use crate::LearningIterationRuntimeErrorV1;

pub type LearningIterationOwnerFutureV1<'a, T> =
    Pin<Box<dyn Future<Output = Result<T, LearningIterationRuntimeErrorV1>> + Send + 'a>>;

#[derive(Clone, Debug)]
pub enum LearningIterationProposalPayloadV1 {
    Parameter(Box<ParameterPlasticityProductRequestV1>),
    Topology(Box<TopologyPlasticityProductRequestV1>),
}

/// Resolved by the host from authenticated artifact/evaluation stores. The host
/// must prove that this bundle belongs to the exact signed proposal set.
#[derive(Clone, Debug)]
pub struct PreparedLearningIterationProposalV1 {
    pub iteration_head: Digest32,
    pub candidate_bundle: Digest32,
    pub evaluation_evidence: Digest32,
    pub payload: LearningIterationProposalPayloadV1,
}

/// Supplied only by an explicit control-owner bootstrap. Implementations must
/// authenticate the completed task, current deletion/revocation frontiers, fixed
/// dataset/model pins, independent evaluations and actual next-task receipts.
///
/// Each stage first reconciles its stable operation identity. Training obeys
/// separate job quotas and never mutates selected parameters. Cancellation or
/// timeout requires the same job to be reconciled, including any remote job
/// watchdog, rather than resubmitting under a fresh identity.
///
/// Selection and next-use are read-only observations of their existing owners.
/// A NoUpdate decision still needs a current baseline selection and committed
/// use by a distinct task; it does not authorize installing the rejected bundle.
/// Checkpoint restore authenticates the current head in an independent rollback
/// domain; checkpoint CAS must flush and anchor before acknowledgement. Any
/// ambiguous commit returns CommitUncertain. These are mandatory host duties,
/// not guarantees provided by an in-memory implementation.
pub trait LearningIterationOwnerPortsV1: Send + Sync {
    fn restore<'a>(
        &'a self,
        request: &'a LearningIterationRequestV1,
    ) -> LearningIterationOwnerFutureV1<'a, Option<LearningIterationSnapshotV1>>;

    fn execute_stage<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        stage: LearningIterationStageV1,
    ) -> LearningIterationOwnerFutureV1<'a, LearningIterationReceiptV1>;

    fn prepare_proposal<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, PreparedLearningIterationProposalV1>;

    /// Re-read the actual owner result and current signature. NextUse resolves
    /// the scoped committed state; it cannot just sign caller-supplied IDs.
    /// Agentd verifies this signature with its bootstrap-pinned trust snapshot.
    fn receipt_attestation<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        receipt: &'a LearningIterationReceiptV1,
        now_unix_seconds: u64,
    ) -> LearningIterationOwnerFutureV1<'a, SignedLearningEvidenceV1>;

    /// ZERO is permitted only for create-if-absent initial registration.
    fn checkpoint<'a>(
        &'a self,
        expected_head: Digest32,
        snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, Digest32>;
}
