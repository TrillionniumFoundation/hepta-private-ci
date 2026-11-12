//! The actual Root custodian and synchronous native callback boundary. All
//! primary reads, native work, client response material and Model callbacks are
//! inside one durable attempt covering the complete original Root context.

use std::io;
use std::marker::PhantomData;
use std::os::fd::OwnedFd;
use std::path::Path;
use std::rc::Rc;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;

use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;

use crate::HostAuthorityLearningProfileV1;
use crate::HostAuthorityRegistration;
use crate::HostAuthorityService;
use crate::HostAuthorityServiceConfig;
use crate::LearningIterationCheckpointOwnerV1;
use crate::authority_host_runtime::owner_alive;
use crate::authority_host_service::RegisteredHostLearningCheckpointV1;

use super::deployment::OriginalBInputs;
use super::execution::OriginalBCompleted;
use super::execution::OriginalBExecution;
use super::record::OriginalBEnrollment;
use super::record::OriginalBRecord;

#[path = "authority_host_q24_evaluation_operation.rs"]
mod operation;
#[path = "authority_host_q24_evaluation_prepare.rs"]
mod prepare;

#[path = "authority_host_q24_evaluation_registration.rs"]
mod registration;
#[path = "authority_host_q24_evaluation_route.rs"]
mod route;
pub(crate) use route::BoundRootIndependentBEvaluationV1;
pub(crate) use route::PreparedRootIndependentBEvaluationV1;
pub use route::RootIndependentBEvaluationOfferV1;
pub(crate) use route::RootIndependentBEvaluationRuntimeV1;
pub(crate) use route::serve_optional_until;

pub(crate) struct OriginalRootIndependentBEvaluationFilesV1 {
    record: OriginalBRecord,
    initial: LearningIterationSnapshotV1,
    backend: Arc<LearningIterationCheckpointOwnerV1>,
    profile: HostAuthorityLearningProfileV1,
    state: Mutex<OriginalBState>,
    end: Instant,
}

struct OriginalBState {
    files: OriginalBInputs,
    execution: Option<OriginalBExecution>,
}

impl OriginalRootIndependentBEvaluationFilesV1 {
    /// A data binding; all actual use still enters the retained Root attempt.
    pub(crate) fn original_binding(&self) -> Digest32 {
        Digest32::of_parts(&[
            b"hepta.root.independent-b.custodian.v1\0",
            self.initial.head_digest.as_array(),
        ])
    }

    pub(crate) fn require_original_learning(
        &self,
        learning: &RegisteredHostLearningCheckpointV1,
    ) -> io::Result<()> {
        if !Arc::ptr_eq(&self.backend, &learning.backend)
            || serde_json::to_vec(&self.profile).map_err(io::Error::other)?
                != serde_json::to_vec(&learning.profile).map_err(io::Error::other)?
        {
            return Err(io::Error::other(
                "B and Model require the same original learning capability",
            ));
        }
        Ok(())
    }
}

/// Native B material is lent synchronously within Root. No wire constructor,
/// clone, sender, journal handle or key is available from this view.
pub(crate) struct OriginalRootBEvaluationBorrowV1<'a> {
    initial: &'a LearningIterationSnapshotV1,
    writer_proof: &'a str,
    actual: &'a OriginalBExecution,
    completed: &'a OriginalBCompleted,
    verifier: &'a LearningEvidenceVerifierV1,
    not_send: PhantomData<Rc<()>>,
}

impl OriginalRootBEvaluationBorrowV1<'_> {
    pub(crate) fn initial_snapshot(&self) -> &LearningIterationSnapshotV1 {
        self.initial
    }
    pub(crate) fn writer_proof(&self) -> &str {
        self.writer_proof
    }
    pub(crate) fn training_snapshot(&self) -> &LearningIterationSnapshotV1 {
        &self.completed.training
    }
    pub(crate) fn training_attestation(&self) -> &SignedLearningEvidenceV1 {
        &self.completed.training_attestation
    }
    pub(crate) fn runner(
        &self,
    ) -> &crate::CellEvaluationRunnerV1<impl codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1>
    {
        &self.actual.runner
    }
    pub(crate) fn execution(&self) -> &crate::CellEvaluationReceiptV1 {
        &self.completed.execution
    }
    pub(crate) fn qualification(&self) -> &crate::CellEvaluationQualificationV1 {
        &self.completed.qualification
    }
    pub(crate) fn qualification_request(&self) -> crate::CellEvaluationQualificationRequestV1<'_> {
        crate::CellEvaluationQualificationRequestV1 {
            context: &self.completed.context,
            evidence: &self.completed.evidence,
            timing: codex_hepta_intelligence_eval::ProductTimingEvidenceV1::Qualification,
            verifier: self.verifier,
            now: self.completed.verified_at,
        }
    }
    pub(crate) fn receipt(&self) -> &codex_hepta_learning_artifacts::LearningIterationReceiptV1 {
        &self.completed.receipt
    }
    pub(crate) fn attestation(&self) -> &SignedLearningEvidenceV1 {
        &self.completed.attestation
    }
}

fn require_learning(
    initial: &LearningIterationSnapshotV1,
    actual: &LearningIterationSnapshotV1,
    learning: &RegisteredHostLearningCheckpointV1,
) -> io::Result<()> {
    if actual != initial
        || !initial.receipts.is_empty()
        || learning.backend.frozen_scope_binding()
            != Some(learning.profile.require_cell_scope(actual)?.binding())
    {
        return Err(io::Error::other("original B learning registration differs"));
    }
    Ok(())
}

fn require_files(
    files: &OriginalBInputs,
    enrollment: &OriginalBEnrollment,
    now: u64,
) -> io::Result<()> {
    if files.deployment_digest().into_array() != enrollment.deployment
        || files.protocol_statement_digest().into_array() != enrollment.protocol_statement
        || files.file_identities() != enrollment.files
        || now < enrollment.registered_at_seconds
        || now >= enrollment.expires_at_seconds
    {
        return Err(io::Error::other(
            "original B registered custody or time differs",
        ));
    }
    files.require_original_files()
}

fn training_prefix(
    current: &LearningIterationSnapshotV1,
) -> io::Result<LearningIterationSnapshotV1> {
    LearningIterationCoordinatorV1::from_snapshot(current.clone()).map_err(io::Error::other)?;
    let mut prefix =
        LearningIterationCoordinatorV1::new(current.request.clone(), current.owners.clone())
            .map_err(io::Error::other)?;
    for receipt in &current.receipts {
        prefix
            .record(receipt.clone(), receipt.observed_unix_seconds)
            .map_err(io::Error::other)?;
        if receipt.observation.stage() == LearningIterationStageV1::Training {
            return Ok(prefix.snapshot().clone());
        }
    }
    Err(io::Error::other("actual Root Training cut is absent"))
}
