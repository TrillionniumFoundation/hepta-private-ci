//! An already accepted B fact and unchanged original files, never a revived
//! native evaluator, holdout release, private signer or current qualification.

use std::cell::Cell;
use std::io;
use std::path::Path;
use std::sync::Arc;
use std::time::Instant;

use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionAnchorV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStateV1;
use codex_hepta_intelligence_eval::decode_original_product_evaluation_execution_records_v1;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::observe_original_file_anchor_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use super::deployment::OriginalBInputs;
use super::record::OriginalBEnrollment;
use super::record::OriginalBRecord;
use crate::HostAuthorityService;
use crate::authority_host_runtime::OriginalCompletedLearningContextV1;
use crate::learning_iteration_auth::OriginalReceiptVerificationV1;
use crate::learning_owner_evidence;

pub(crate) struct OriginalCompletedBDataV1 {
    pub(crate) acceptance: Digest32,
    pub(crate) evaluation_attestation: SignedLearningEvidenceV1,
    pub(crate) plan_attestation: Digest32,
}

pub(crate) struct OriginalCompletedBReadV1<'a> {
    files: &'a OriginalBInputs,
    enrollment: &'a OriginalBEnrollment,
    initial: &'a LearningIterationSnapshotV1,
    scope: &'a FrozenLearningScopeV2,
    service: &'a HostAuthorityService,
    end: Instant,
    used: Cell<bool>,
    refused: Cell<bool>,
}

pub(crate) fn with_original_completed_b<T>(
    path: &Path,
    root: Arc<RootAuthorityDirectory>,
    initial: &LearningIterationSnapshotV1,
    scope: &FrozenLearningScopeV2,
    service: &HostAuthorityService,
    end: Instant,
    action: impl FnOnce(&OriginalCompletedBReadV1<'_>) -> io::Result<T>,
) -> io::Result<T> {
    require_end(end)?;
    let record = OriginalBRecord::open(root, initial)?;
    OriginalBRecord::inspect(&record, end, |enrollment| {
        let original = enrollment.clone();
        enrollment.completed_history_fact(scope)?;
        // No OwnerWriter is opened, even when a first terminal acceptance runs
        // while the original B process still retains its exclusive writers.
        let files = OriginalBInputs::open_completed_readonly(path)?;
        require_images(&files, enrollment, initial)?;
        let original_inputs = input_images(&files)?;
        let read = OriginalCompletedBReadV1 {
            files: &files,
            enrollment,
            initial,
            scope,
            service,
            end,
            used: Cell::new(false),
            refused: Cell::new(false),
        };
        let value = action(&read);
        let observed = read.used.get() && !read.refused.get();
        require_images(&files, enrollment, initial)?;
        require_end(end)?;
        if !observed || enrollment != &original || input_images(&files)? != original_inputs {
            return Err(io::Error::other("completed B read was absent or refused"));
        }
        value
    })
}

impl OriginalCompletedBReadV1<'_> {
    pub(crate) fn observe(
        &self,
        context: &OriginalCompletedLearningContextV1<'_>,
    ) -> io::Result<OriginalCompletedBDataV1> {
        if self.used.replace(true) || self.refused.get() {
            self.refused.set(true);
            return Err(io::Error::other("completed B read already consumed"));
        }
        let result = self.observe_once(context);
        if result.is_err() {
            self.refused.set(true);
        }
        result
    }

    fn observe_once(
        &self,
        context: &OriginalCompletedLearningContextV1<'_>,
    ) -> io::Result<OriginalCompletedBDataV1> {
        context.require_original_publication_context(self.service, self.end)?;
        if context.initial() != self.initial || context.frozen_scope() != self.scope {
            return Err(io::Error::other("completed B original scope differs"));
        }
        let (accepted_at, acceptance, signature_digest) =
            self.enrollment.completed_history_fact(self.scope)?;
        self.files
            .require_completed_protocol(context, accepted_at)?;
        let training = context
            .terminal()
            .receipts
            .iter()
            .find(|receipt| receipt.observation.stage() == LearningIterationStageV1::Training)
            .ok_or_else(|| io::Error::other("completed B original Training missing"))?;
        let evaluation = context
            .terminal()
            .receipts
            .iter()
            .find(|receipt| receipt.observation.stage() == LearningIterationStageV1::Evaluation)
            .ok_or_else(|| io::Error::other("completed B original Evaluation missing"))?;
        let codex_hepta_learning_artifacts::LearningIterationObservationV1::Training {
            candidate,
            ..
        } = &training.observation
        else {
            return Err(io::Error::other(
                "completed B requires actual candidate Training",
            ));
        };
        self.files
            .candidate_data
            .require_digest(candidate.components.heads, 32_780)?;
        let original_training = self
            .enrollment
            .original_training_attestation
            .as_ref()
            .ok_or_else(|| io::Error::other("completed B Training attestation missing"))?;
        let (payload, signed) =
            learning_owner_evidence::decode(original_training).map_err(io::Error::other)?;
        if payload
            != learning_iteration_receipt_signing_bytes_v1(training).map_err(io::Error::other)?
        {
            return Err(io::Error::other("completed B Training bytes differ"));
        }
        verify(context, training, &signed, accepted_at)?;
        let bytes = completed_receipt(self.files, self.enrollment, context.initial())?;
        let (payload, signed) =
            learning_owner_evidence::decode(&bytes).map_err(io::Error::other)?;
        if Digest32::of_bytes(&bytes) != signature_digest
            || self.enrollment.completed_receipt != Some(Digest32::of_bytes(&payload).into_array())
            || payload
                != learning_iteration_receipt_signing_bytes_v1(evaluation)
                    .map_err(io::Error::other)?
            || self.enrollment.realized_training_head != Some(evaluation.predecessor.into_array())
        {
            return Err(io::Error::other("completed B Evaluation bytes differ"));
        }
        verify(context, evaluation, &signed, accepted_at)?;
        require_end(self.end)?;
        Ok(OriginalCompletedBDataV1 {
            acceptance,
            evaluation_attestation: signed,
            plan_attestation: Digest32::from_array(
                self.enrollment.realized_plan_statement.ok_or_else(|| {
                    io::Error::other("completed B original plan signature missing")
                })?,
            ),
        })
    }
}

fn verify(
    context: &OriginalCompletedLearningContextV1<'_>,
    receipt: &codex_hepta_learning_artifacts::LearningIterationReceiptV1,
    signed: &SignedLearningEvidenceV1,
    accepted_at: u64,
) -> io::Result<()> {
    context.require_current_signer(signed)?;
    let verification =
        OriginalReceiptVerificationV1::new(context.current_verifier(), context.terminal(), receipt)
            .map_err(io::Error::other)?;
    // This value came from first Root Complete's persisted fact, never a peer
    // timestamp. The result is discarded and cannot become native authority.
    OriginalReceiptVerificationV1::verify(&verification, signed, accepted_at)
        .map_err(io::Error::other)?;
    Ok(())
}

fn completed_receipt(
    files: &OriginalBInputs,
    enrollment: &OriginalBEnrollment,
    initial: &LearningIterationSnapshotV1,
) -> io::Result<Vec<u8>> {
    let bytes = files.receipt.journal.read_completed_image()?;
    let binding = Digest32::from_array(
        bytes
            .get(8..40)
            .ok_or_else(|| io::Error::other("completed B receipt header missing"))?
            .try_into()
            .map_err(io::Error::other)?,
    );
    let witness = files.receipt.witness.original_readonly()?;
    let anchor = observe_original_file_anchor_v1(
        &witness,
        JournalScope {
            scope_digest: binding,
            objective_digest: initial.request.envelope.objective_digest,
        },
        Generation::new(enrollment.original_generation).map_err(io::Error::other)?,
        128,
    )
    .map_err(io::Error::other)?
    .ok_or_else(|| io::Error::other("completed B receipt witness missing"))?;
    let records = decode_original_product_evaluation_execution_records_v1(
        &bytes,
        binding,
        ProductEvaluationExecutionAnchorV1 {
            sequence: anchor
                .sequence
                .checked_sub(1)
                .ok_or_else(|| io::Error::other("completed B receipt sequence"))?,
            history_digest: anchor.checkpoint_digest,
        },
    )
    .map_err(io::Error::other)?;
    let [(_, ProductEvaluationExecutionStateV1::Completed(saved))] = records.as_slice() else {
        return Err(io::Error::other(
            "one originally completed B receipt required",
        ));
    };
    Ok(saved.clone())
}

fn require_images(
    files: &OriginalBInputs,
    enrollment: &OriginalBEnrollment,
    initial: &LearningIterationSnapshotV1,
) -> io::Result<()> {
    files.require_original_files()?;
    if files.deployment_digest().into_array() != enrollment.deployment
        || files.protocol_statement_digest().into_array() != enrollment.protocol_statement
        || files.file_identities() != enrollment.files
        || initial.head_digest.into_array() != enrollment.initial_head
        || initial.owners.evidence_trust_digest.into_array() != enrollment.trust
    {
        return Err(io::Error::other("completed B fixed files differ"));
    }
    let cells = [
        &files.candidate.journal,
        &files.candidate.witness,
        &files.fixed_expert.journal,
        &files.fixed_expert.witness,
    ]
    .into_iter()
    .map(|file| file.observe_owned_output().map(Digest32::into_array))
    .collect::<io::Result<Vec<_>>>()?;
    let outputs = [
        &files.holdout,
        &files.executions,
        &files.execution_signature.journal,
        &files.execution_signature.witness,
        &files.qualification_signature.journal,
        &files.qualification_signature.witness,
        &files.publication.journal,
        &files.publication.witness,
        &files.receipt.journal,
        &files.receipt.witness,
    ]
    .into_iter()
    .map(|file| file.observe_owned_output().map(Digest32::into_array))
    .collect::<io::Result<Vec<_>>>()?;
    if enrollment.cell_images.as_ref() != Some(&cells) || enrollment.output_images != outputs {
        return Err(io::Error::other("completed B physical cut changed"));
    }
    enrollment
        .released_source
        .as_ref()
        .ok_or_else(|| io::Error::other("completed B original source missing"))?
        .require_original(files)?;
    files.realized_plan_statement.require_digest(
        Digest32::from_array(
            enrollment
                .realized_plan_statement
                .ok_or_else(|| io::Error::other("completed B original plan signature missing"))?,
        ),
        65_536,
    )?;
    files.require_original_files()
}

fn require_end(end: Instant) -> io::Result<()> {
    if Instant::now() >= end {
        return Err(io::Error::other("completed B original deadline elapsed"));
    }
    Ok(())
}

fn input_images(files: &OriginalBInputs) -> io::Result<Vec<Digest32>> {
    let mut images = files
        .model
        .all_files()
        .into_iter()
        .map(|file| {
            file.read_stable(65_536)
                .map(|bytes| Digest32::of_bytes(&bytes))
        })
        .collect::<io::Result<Vec<_>>>()?;
    images.push(Digest32::of_bytes(
        &files.candidate_data.read_completed_image()?,
    ));
    Ok(images)
}
