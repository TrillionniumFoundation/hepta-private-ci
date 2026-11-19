//! Actual native B owners, opened from the Root-retained original descriptors.
//! This object and its keys never leave Root. An interrupted outer Root attempt
//! prevents recovery even if primary bytes are later restored.

use std::io;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_intelligence_eval::*;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_types::Digest32;
use ed25519_dalek::SigningKey;

use crate::CellEvaluationPlanV1;
use crate::CellEvaluationRunnerV1;
use crate::OriginalCellEvaluationExecutionOwnerV1;
use crate::OriginalCellEvaluationSigningConfigV1;
use crate::neuron_cell_evaluation::OriginalCellEvaluationObserversV1;

use super::admission::OriginalBAuthorities;
use super::deployment::OriginalBInputs;
use super::outputs::OriginalBCas;
use super::outputs::OriginalBJournal;
use super::outputs::OriginalBOpenMode;
use super::outputs::original_witness;
use super::protocol::OriginalBProtocolData;
use super::record::OriginalBEnrollment;
use super::record::OriginalBOutputHeads;

#[path = "authority_host_q24_evaluation_execute.rs"]
mod execute;

pub(super) struct OriginalBCompleted {
    pub(super) training: LearningIterationSnapshotV1,
    pub(super) training_attestation: codex_hepta_learning_ledger::SignedLearningEvidenceV1,
    pub(super) execution: crate::CellEvaluationReceiptV1,
    pub(super) qualification: crate::CellEvaluationQualificationV1,
    pub(super) context: ProductQualificationContextV1,
    pub(super) evidence: SignedEvaluationEvidenceV1,
    pub(super) receipt: codex_hepta_learning_artifacts::LearningIterationReceiptV1,
    pub(super) attestation: codex_hepta_learning_ledger::SignedLearningEvidenceV1,
    pub(super) verified_at: u64,
}

pub(super) struct OriginalBExecution {
    pub(super) observers: OriginalCellEvaluationObserversV1,
    pub(super) plan: CellEvaluationPlanV1,
    pub(super) candidate_plan: TemporalEvaluationPlan,
    pub(super) baseline_plan: TemporalEvaluationPlan,
    pub(super) runner: CellEvaluationRunnerV1<OriginalBCas>,
    holdout: OriginalBCas,
    pub(super) executions: LockedFileProductEvaluationExecutionStoreV1,
    pub(super) attestor: OriginalCellEvaluationExecutionOwnerV1<FileAnchorWitnessStore>,
    pub(super) qualification: OriginalBJournal,
    pub(super) publication: OriginalBJournal,
    pub(super) receipt: OriginalBJournal,
    pub(super) signing: SigningKey,
    pub(super) key: ProductEvaluationExecutionKeyV1,
}

impl OriginalBExecution {
    pub(super) fn open(
        files: &mut OriginalBInputs,
        enrollment: &OriginalBEnrollment,
        training: &LearningIterationSnapshotV1,
        protocol: &OriginalBProtocolData,
        authorities: &OriginalBAuthorities,
        now: u64,
    ) -> io::Result<Self> {
        files.require_original_files()?;
        let observers = OriginalCellEvaluationObserversV1::from_original_observers(
            files.candidate.observer()?,
            files.candidate.manifest().clone(),
            files.fixed_expert.observer()?,
            files.fixed_expert.manifest().clone(),
        )
        .map_err(io::Error::other)?;
        let actual_work =
            super::benchmark::read_original_b_training_work(files, enrollment, training)?;
        let (registration, candidate_plan, baseline_plan) =
            protocol.plans(training, &actual_work)?;
        let plan = observers
            .freeze_original_learning_plan(
                registration,
                &candidate_plan,
                &baseline_plan,
                training.request.evaluation_profile,
            )
            .map_err(io::Error::other)?;
        // Generator attests the actual frozen comparison, not caller metrics.
        authorities.require_statement(
            &files.realized_plan_statement,
            LearningEvidenceRoleV1::Generator,
            plan.product_plan().frozen_plan.plan_digest.as_array(),
            now,
        )?;
        let namespace = Digest32::from_array(enrollment.namespace);
        let fence = HoldoutWriterFenceV1 {
            owner_id: authorities.evaluator.principal.principal_id.clone(),
            generation: enrollment.original_generation,
            lease_digest: Digest32::from_array(enrollment.original_lease),
        };
        let mode = if enrollment.heads.is_some() {
            OriginalBOpenMode::Recover
        } else {
            OriginalBOpenMode::Create
        };
        let cas = match &enrollment.heads {
            None => LockedFileFinalHoldoutCasStoreV1::create(
                files.holdout.take_original_writer()?,
                namespace,
            ),
            Some(head) => LockedFileFinalHoldoutCasStoreV1::recover(
                files.holdout.take_original_writer()?,
                namespace,
                Some(FinalHoldoutCasAnchorV1 {
                    fence_generation: head.holdout_generation,
                    record_count: head.holdout_records,
                    state_digest: Digest32::from_array(head.holdout_state),
                }),
            ),
        }
        .map_err(io::Error::other)?;
        let holdout = OriginalBCas(Arc::new(Mutex::new(cas)));
        let owner = match mode {
            OriginalBOpenMode::Create => {
                FencedFinalHoldoutOwnerV1::initialize(holdout.clone(), namespace, fence)
            }
            OriginalBOpenMode::Recover => {
                FencedFinalHoldoutOwnerV1::recover(holdout.clone(), namespace, fence)
            }
        }
        .map_err(io::Error::other)?;
        let runner = CellEvaluationRunnerV1::new(ProductEvaluationRunnerV1::new(owner));
        let execution_binding = Digest32::of_parts(&[
            b"hepta.root.independent-b.executions.v1\0",
            namespace.as_array(),
        ]);
        let executions = match &enrollment.heads {
            None => LockedFileProductEvaluationExecutionStoreV1::create(
                files.executions.take_original_writer()?,
                execution_binding,
            ),
            Some(head) => LockedFileProductEvaluationExecutionStoreV1::recover(
                files.executions.take_original_writer()?,
                execution_binding,
                ProductEvaluationExecutionAnchorV1 {
                    sequence: head.execution_sequence,
                    history_digest: Digest32::from_array(head.execution_history),
                },
            ),
        }
        .map_err(io::Error::other)?;
        let key = product_evaluation_execution_key_v1(
            plan.product_plan(),
            namespace,
            &authorities.evaluator.principal,
        )
        .map_err(io::Error::other)?;
        let signing = authorities.original_key(&files.evaluator_key)?;
        let signing_config = OriginalCellEvaluationSigningConfigV1 {
            plan: plan.product_plan().clone(),
            execution_namespace: namespace,
            signer: authorities.evaluator.clone(),
            verifier: authorities.verifier.clone(),
            maximum_signature_lifetime_seconds: files.maximum_signature_lifetime_seconds,
        };
        let witness_binding = Digest32::of_parts(&[
            b"hepta.root.independent-b.execution-witness.v1\0",
            key.binding_digest.as_array(),
        ]);
        let (file, witness) = original_witness(
            &mut files.execution_signature,
            enrollment,
            witness_binding,
            authorities.verifier.objective_digest(),
            mode,
        )?;
        let attestor = match mode {
            OriginalBOpenMode::Create => OriginalCellEvaluationExecutionOwnerV1::create(
                file,
                witness,
                signing_config,
                signing.clone(),
            ),
            OriginalBOpenMode::Recover => OriginalCellEvaluationExecutionOwnerV1::recover(
                file,
                witness,
                signing_config,
                signing.clone(),
            ),
        }
        .map_err(io::Error::other)?;
        let qualification = OriginalBJournal::open(
            &mut files.qualification_signature,
            enrollment,
            &key,
            b"qualification",
            authorities,
            mode,
        )?;
        let publication = OriginalBJournal::open(
            &mut files.publication,
            enrollment,
            &key,
            b"publication",
            authorities,
            mode,
        )?;
        let receipt = OriginalBJournal::open(
            &mut files.receipt,
            enrollment,
            &key,
            b"receipt",
            authorities,
            mode,
        )?;
        let mut actual = Self {
            observers,
            plan,
            candidate_plan,
            baseline_plan,
            runner,
            holdout,
            executions,
            attestor,
            qualification,
            publication,
            receipt,
            signing,
            key,
        };
        if enrollment
            .realized_training_head
            .is_some_and(|head| head != training.head_digest.into_array())
            || enrollment.realized_plan.is_some_and(|plan| {
                plan != actual
                    .plan
                    .product_plan()
                    .frozen_plan
                    .plan_digest
                    .into_array()
            })
        {
            return Err(io::Error::other(
                "original B realized Training or plan changed",
            ));
        }
        if let Some(head) = &enrollment.heads
            && (actual.original_heads(namespace)? != *head
                || actual.output_images(files)? != enrollment.output_images)
        {
            return Err(io::Error::other("original B output rollback or rewrite"));
        }
        files.require_original_files()?;
        Ok(actual)
    }

    pub(super) fn original_heads(
        &mut self,
        namespace: Digest32,
    ) -> io::Result<OriginalBOutputHeads> {
        let mut store = self
            .holdout
            .0
            .try_lock()
            .map_err(|_| io::Error::other("original B holdout busy"))?;
        FinalHoldoutCasStoreV1::load(&mut *store, namespace).map_err(io::Error::other)?;
        let holdout = store
            .anchor()
            .ok_or_else(|| io::Error::other("original B holdout is missing"))?;
        // Reading a known completed execution forces actual physical replay.
        ProductEvaluationExecutionStoreV1::readback(&mut self.executions, &self.key)
            .map_err(io::Error::other)?;
        let execution = self.executions.anchor();
        Ok(OriginalBOutputHeads {
            holdout_generation: holdout.fence_generation,
            holdout_records: holdout.record_count,
            holdout_state: holdout.state_digest.into_array(),
            execution_sequence: execution.sequence,
            execution_history: execution.history_digest.into_array(),
        })
    }

    pub(super) fn output_images(&self, files: &OriginalBInputs) -> io::Result<Vec<[u8; 32]>> {
        [
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
        .collect()
    }
}
