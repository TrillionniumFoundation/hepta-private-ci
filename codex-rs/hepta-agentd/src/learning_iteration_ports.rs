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

/// Original stage owners used with the registered checkpoint composition.
/// Implementations resolve actual work and attestations through their existing
/// owners; they receive no checkpoint writer or authority to register one.
/// The ordinary iteration worker still verifies every returned receipt against
/// its pinned trust, including after checkpoint recovery.
pub trait LearningIterationStageOwnerPortsV1: Send + Sync {
    /// Reconcile the exact recovered operation with the original owners and
    /// their independent current head, trust/revocation and withdrawal cuts.
    /// In particular, verify any Proposal against its original durable owner
    /// and anchor: that stage has no learning-signature role. This check also
    /// applies to empty, NoUpdate and completed snapshots. It must not rerun
    /// work, renew a deadline, manufacture attestations or replace historical
    /// bindings with the currently selected model. Completed work may reconcile
    /// after expiry. The worker still performs its own current-clock and signed
    /// receipt verification after this read-only check.
    fn validate_recovery<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, ()>;

    /// A scoped Selector may first return LocalDecisionV2 after a qualified
    /// proposal. The worker authenticates and checkpoints it, then calls
    /// Selection again for the original version owner's actual publication.
    /// Policy retention/deferral must never be reported as evaluator NoUpdate.
    fn execute_stage<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        stage: LearningIterationStageV1,
    ) -> LearningIterationOwnerFutureV1<'a, LearningIterationReceiptV1>;

    fn prepare_proposal<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, PreparedLearningIterationProposalV1>;

    fn receipt_attestation<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        receipt: &'a LearningIterationReceiptV1,
        now_unix_seconds: u64,
    ) -> LearningIterationOwnerFutureV1<'a, SignedLearningEvidenceV1>;
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
    /// Frozen scope held by the original protected checkpoint owner. None is
    /// the legacy profile; a stage provider cannot supply this custody binding.
    fn frozen_scope_binding(&self) -> Option<Digest32> {
        None
    }

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
