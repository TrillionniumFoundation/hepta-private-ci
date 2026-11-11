//! Original learning Evaluation receipts over the existing signed execution.
//! The host supplies an already enrolled Evaluator key, original files, witness
//! and Trainer connection. No key, role, holdout, Root or CURRENT is provisioned.
//! Qualification remains signed material: this owner does not establish its
//! publication sink's custody or assemble the production learning stage ports.

use std::fs::File;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionClaimV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionRequestV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStateV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreV1;
use codex_hepta_intelligence_eval::ProductProviderErrorV1;
use codex_hepta_intelligence_eval::ProductQualificationContextV1;
use codex_hepta_intelligence_eval::ProductTimingEvidenceV1;
use codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;
use codex_hepta_intelligence_eval::TemporalEvaluationPlan;
use codex_hepta_intelligence_eval::evaluation_signing_payload_v2;
use codex_hepta_intelligence_eval::product_evaluation_execution_key_v1;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::CellEvaluationErrorV1;
use crate::CellEvaluationJournalsV1;
use crate::CellEvaluationPlanV1;
use crate::CellEvaluationQualificationRequestV1;
use crate::CellEvaluationQualificationV1;
use crate::CellEvaluationReceiptV1;
use crate::CellEvaluationRunnerV1;
use crate::CellLearningEvaluationErrorV1;
use crate::LearningIterationEvidenceClientV1;
use crate::LearningIterationRuntimeErrorV1;
use crate::OriginalCellEvaluationSigningConfigV1;
use crate::learning_owner_evidence;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1 as OwnerError;
use crate::learning_owner_journal::LearningOwnerJournalV1;
use crate::prepare_cell_learning_evaluation_v1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellEvaluationReceiptErrorV1 {
    #[error("original Evaluation owner: {0}")]
    Owner(#[from] OwnerError),
    #[error("original Cell execution: {0}")]
    Cell(#[from] CellEvaluationErrorV1),
    #[error("original qualification: {0}")]
    Preparation(#[from] CellLearningEvaluationErrorV1),
    #[error("original iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original Trainer connection: {0}")]
    Trainer(#[from] LearningIterationRuntimeErrorV1),
    #[error("original role evidence: {0}")]
    Evidence(#[from] SignedEvidenceError),
}
type Error = OriginalCellEvaluationReceiptErrorV1;

/// Fixed by the original host before giving this owner its signing capability.
/// The Training cut, Cell comparison and original execution namespace are exact.
#[derive(Clone)]
pub struct OriginalCellEvaluationReceiptConfigV1 {
    pub training: LearningIterationSnapshotV1,
    pub scope: FrozenLearningScopeV2,
    pub plan: CellEvaluationPlanV1,
    pub signing: OriginalCellEvaluationSigningConfigV1,
}

/// Borrow the original owners for this read. No provider, attestor, arbitrary
/// receipt, caller clock or replacement trust is accepted. The full recovered
/// history is retained when asking the Trainer for its original attestation.
pub struct OriginalCellEvaluationReceiptSourcesV1<
    'a,
    S,
    C: AnchorWitnessStore,
    F: AnchorWitnessStore,
    E,
> {
    pub snapshot: &'a LearningIterationSnapshotV1,
    pub runner: &'a mut CellEvaluationRunnerV1<S>,
    pub journals: CellEvaluationJournalsV1<'a, C, F>,
    pub candidate_plan: &'a TemporalEvaluationPlan,
    pub baseline_plan: &'a TemporalEvaluationPlan,
    pub executions: &'a mut E,
    pub qualification: &'a CellEvaluationQualificationV1,
    pub context: &'a ProductQualificationContextV1,
    pub evidence: &'a SignedEvaluationEvidenceV1,
    pub timing: ProductTimingEvidenceV1<'a>,
    pub trainer: &'a LearningIterationEvidenceClientV1,
}

pub struct OriginalCellEvaluationReceiptOwnerV1<W: AnchorWitnessStore> {
    journal: LearningOwnerJournalV1<W>,
    config: OriginalCellEvaluationReceiptConfigV1,
    key: SigningKey,
    execution: ProductEvaluationExecutionKeyV1,
    saved: ProductEvaluationExecutionKeyV1,
}

impl<W: AnchorWitnessStore> OriginalCellEvaluationReceiptOwnerV1<W> {
    pub fn create(
        file: File,
        witness: W,
        config: OriginalCellEvaluationReceiptConfigV1,
        key: SigningKey,
    ) -> Result<Self, Error> {
        let (execution, saved) = validate_config(&config, &key)?;
        let journal = LearningOwnerJournalV1::create(file, witness, saved.binding_digest)?;
        Ok(Self {
            journal,
            config,
            key,
            execution,
            saved,
        })
    }

    /// Reopen the same file and independent witness. This never signs or
    /// resolves Pending, and cannot renew an original validity window.
    pub fn recover(
        file: File,
        witness: W,
        config: OriginalCellEvaluationReceiptConfigV1,
        key: SigningKey,
    ) -> Result<Self, Error> {
        let (execution, saved) = validate_config(&config, &key)?;
        let journal = LearningOwnerJournalV1::recover(file, witness, saved.binding_digest)?;
        Ok(Self {
            journal,
            config,
            key,
            execution,
            saved,
        })
    }

    /// Sign only the exact Evaluation reconstructed from the original completed
    /// execution and current, independent Trainer evidence. The durable claim
    /// precedes signing; ambiguous claims never retry the signing closure.
    pub async fn attest_original_completion<
        S: FinalHoldoutCasStoreV1,
        C: AnchorWitnessStore,
        F: AnchorWitnessStore,
        E: ProductEvaluationExecutionStoreV1,
    >(
        &mut self,
        mut source: OriginalCellEvaluationReceiptSourcesV1<'_, S, C, F, E>,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        if now()? >= self.config.training.request.envelope.expiry_unix_seconds {
            return Err(OwnerError::Binding("new Evaluation attestation after deadline").into());
        }
        let prepared = self.prepare(&mut source)?;
        let trainer: &LearningIterationEvidenceClientV1 = source.trainer;
        let training = trainer.readback(source.snapshot, self.training()?).await?;
        self.authenticate_roles(&source, &prepared.1, &training)?;
        if self.prepare(&mut source)? != prepared {
            return Err(OwnerError::CommitUncertain.into());
        }
        let payload = learning_iteration_receipt_signing_bytes_v1(&prepared.0)?;
        let config = &self.config.signing;
        let key = &self.key;
        let identity = self.saved.binding_digest;
        let bytes = self.journal.commit_once(&self.saved, || {
            let issued_at = now()?;
            if issued_at >= self.config.training.request.envelope.expiry_unix_seconds {
                return Err(OwnerError::Binding(
                    "new Evaluation attestation after deadline",
                ));
            }
            let expires_at = issued_at
                .checked_add(config.maximum_signature_lifetime_seconds)
                .ok_or(OwnerError::Binding("signature deadline overflow"))?
                .min(config.signer.principal.expires_at);
            let mut signed = SignedLearningEvidenceV1 {
                evidence_id: evidence_id(identity)?,
                principal_id: config.signer.principal.principal_id.clone(),
                role: LearningEvidenceRoleV1::Evaluator,
                trust_digest: config.verifier.trust_digest(),
                scope_digest: config.verifier.scope_digest(),
                objective_digest: config.verifier.objective_digest(),
                authority_epoch: config.signer.principal.authority_epoch,
                issued_at,
                expires_at,
                payload_digest: Digest32::of_bytes(&payload),
                signature: [0; 64],
            };
            signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
            config.verifier.verify(
                LearningEvidenceRoleV1::Evaluator,
                &signed,
                &payload,
                issued_at,
            )?;
            learning_owner_evidence::encode(&payload, &signed)
        })?;
        self.authenticate_completed(&mut source, prepared, &bytes)
            .await
    }

    /// Read the original signature, including after the work deadline while all
    /// original evidence remains current. No claim, signature or holdout release
    /// occurs. Missing, Pending and invalid evidence are errors, never NoUpdate.
    pub async fn readback<
        S: FinalHoldoutCasStoreV1,
        C: AnchorWitnessStore,
        F: AnchorWitnessStore,
        E: ProductEvaluationExecutionStoreV1,
    >(
        &mut self,
        mut source: OriginalCellEvaluationReceiptSourcesV1<'_, S, C, F, E>,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let prepared = self.prepare(&mut source)?;
        let bytes = self.journal.read(&self.saved)?;
        self.authenticate_completed(&mut source, prepared, &bytes)
            .await
    }

    fn training(&self) -> Result<&LearningIterationReceiptV1, Error> {
        // Construction validates this exact, nonempty Training cut.
        self.config
            .training
            .receipts
            .last()
            .ok_or(OwnerError::Binding("original Training cut").into())
    }

    fn prepare<
        S: FinalHoldoutCasStoreV1,
        C: AnchorWitnessStore,
        F: AnchorWitnessStore,
        E: ProductEvaluationExecutionStoreV1,
    >(
        &self,
        source: &mut OriginalCellEvaluationReceiptSourcesV1<'_, S, C, F, E>,
    ) -> Result<(LearningIterationReceiptV1, CellEvaluationReceiptV1), Error> {
        LearningIterationCoordinatorV1::from_snapshot(source.snapshot.clone())?;
        self.config.scope.validate_snapshot(source.snapshot)?;
        if source.snapshot.request != self.config.training.request
            || source.snapshot.owners != self.config.training.owners
            || !source
                .snapshot
                .receipts
                .starts_with(&self.config.training.receipts)
            || source.context.evaluator != self.config.signing.signer.principal
        {
            return Err(OwnerError::Binding("original Evaluation scope and principal").into());
        }
        let clock = || now().map_err(|_| ProductProviderErrorV1::Unavailable);
        let runner: &mut CellEvaluationRunnerV1<S> = source.runner;
        let evaluation = runner.readback_completed(
            &self.config.plan,
            CellEvaluationJournalsV1 {
                candidate: source.journals.candidate,
                fixed_expert: source.journals.fixed_expert,
            },
            &ProductEvaluationExecutionRequestV1 {
                plan: self.config.plan.product_plan(),
                candidate_plan: source.candidate_plan,
                baseline_plan: source.baseline_plan,
                evaluator: &self.config.signing.signer.principal,
                verifier: &self.config.signing.verifier,
                clock: &clock,
            },
            &mut OriginalExecution {
                inner: source.executions,
                key: &self.execution,
            },
        )?;
        let timing = match &source.timing {
            ProductTimingEvidenceV1::Qualification => ProductTimingEvidenceV1::Qualification,
            ProductTimingEvidenceV1::SystemLongitudinal {
                timing,
                minimum_window_micros,
            } => ProductTimingEvidenceV1::SystemLongitudinal {
                timing,
                minimum_window_micros: *minimum_window_micros,
            },
        };
        let receipt = prepare_cell_learning_evaluation_v1(
            source.runner,
            &self.config.training,
            &evaluation,
            source.qualification,
            &CellEvaluationQualificationRequestV1 {
                context: source.context,
                evidence: source.evidence,
                timing,
                verifier: &self.config.signing.verifier,
                now: now()?,
            },
        )?;
        if source
            .snapshot
            .receipts
            .get(self.config.training.receipts.len())
            .is_some_and(|saved| saved != &receipt)
        {
            return Err(OwnerError::Binding("original retained Evaluation receipt").into());
        }
        Ok((receipt, evaluation))
    }

    fn authenticate_roles<
        S: FinalHoldoutCasStoreV1,
        C: AnchorWitnessStore,
        F: AnchorWitnessStore,
        E,
    >(
        &self,
        source: &OriginalCellEvaluationReceiptSourcesV1<'_, S, C, F, E>,
        execution: &CellEvaluationReceiptV1,
        training: &SignedLearningEvidenceV1,
    ) -> Result<(), Error> {
        let config = &self.config.signing;
        let now = now()?;
        config.verifier.require_signer_binding(
            LearningEvidenceRoleV1::Evaluator,
            &config.signer,
            now,
        )?;
        let generator = config.verifier.verify(
            LearningEvidenceRoleV1::Generator,
            training,
            &learning_iteration_receipt_signing_bytes_v1(self.training()?)?,
            now,
        )?;
        let bundle = source
            .runner
            .qualification_bundle(execution, source.context)?;
        let payload = evaluation_signing_payload_v2(&bundle, &config.plan.metric_roles)
            .map_err(|_| OwnerError::Binding("original qualification payload"))?;
        let evaluator = config.verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &source.evidence.evaluator_bundle,
            &payload,
            now,
        )?;
        if generator.principal() != &source.context.generator
            || generator.principal().principal_id != self.config.training.owners.trainer
            || evaluator.principal() != &config.signer.principal
            || evaluator.controller_id() != &config.signer.controller_id
        {
            return Err(OwnerError::Binding("original Training and Evaluation principals").into());
        }
        verify_signed_actor_separation(&generator, &evaluator, now)?;
        Ok(())
    }

    async fn authenticate_completed<
        S: FinalHoldoutCasStoreV1,
        C: AnchorWitnessStore,
        F: AnchorWitnessStore,
        E: ProductEvaluationExecutionStoreV1,
    >(
        &mut self,
        source: &mut OriginalCellEvaluationReceiptSourcesV1<'_, S, C, F, E>,
        prepared: (LearningIterationReceiptV1, CellEvaluationReceiptV1),
        bytes: &[u8],
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let (payload, signed) = learning_owner_evidence::decode(bytes)?;
        if payload != learning_iteration_receipt_signing_bytes_v1(&prepared.0)? {
            return Err(OwnerError::Binding("changed original Evaluation payload").into());
        }
        let trainer: &LearningIterationEvidenceClientV1 = source.trainer;
        let training = trainer.readback(source.snapshot, self.training()?).await?;
        if self.prepare(source)? != prepared {
            return Err(OwnerError::CommitUncertain.into());
        }
        self.authenticate_roles(source, &prepared.1, &training)?;
        let config = &self.config.signing;
        let verified =
            config
                .verifier
                .verify(LearningEvidenceRoleV1::Evaluator, &signed, &payload, now()?)?;
        if verified.principal() != &config.signer.principal
            || verified.controller_id() != &config.signer.controller_id
            || signed.evidence_id != evidence_id(self.saved.binding_digest)?
        {
            return Err(OwnerError::Binding("original Evaluation signature identity").into());
        }
        if self.journal.read(&self.saved)? != bytes {
            return Err(OwnerError::CommitUncertain.into());
        }
        Ok((prepared.0, signed))
    }
}

fn validate_config(
    config: &OriginalCellEvaluationReceiptConfigV1,
    key: &SigningKey,
) -> Result<
    (
        ProductEvaluationExecutionKeyV1,
        ProductEvaluationExecutionKeyV1,
    ),
    Error,
> {
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(config.training.clone())?;
    config.scope.validate_snapshot(&config.training)?;
    let signing = &config.signing;
    if coordinator.next_stage() != Some(LearningIterationStageV1::Evaluation)
        || key.verifying_key().to_bytes() != signing.signer.verifying_key
        || signing.signer.principal.principal_id != config.training.owners.evaluator
        || config.training.owners.evidence_trust_digest != signing.verifier.trust_digest()
        || config.training.request.envelope.objective_digest != signing.verifier.objective_digest()
        || config.plan.product_plan() != &signing.plan
        || config.plan.record().learning_evaluation_profile
            != Some(config.training.request.evaluation_profile.into_array())
        || !(1..=86_400).contains(&signing.maximum_signature_lifetime_seconds)
    {
        return Err(OwnerError::Binding("original Evaluation signing capability").into());
    }
    signing.verifier.require_signer_binding(
        LearningEvidenceRoleV1::Evaluator,
        &signing.signer,
        now()?,
    )?;
    let execution = product_evaluation_execution_key_v1(
        &signing.plan,
        signing.execution_namespace,
        &signing.signer.principal,
    )
    .map_err(|_| OwnerError::Binding("original execution identity"))?;
    let saved = ProductEvaluationExecutionKeyV1 {
        plan_id: config.training.request.operation_id.clone(),
        binding_digest: Digest32::of_parts(&[
            b"hepta.agentd.original-evaluation-receipt.v1\0",
            config.training.head_digest.as_array(),
            config.scope.binding().as_array(),
            execution.binding_digest.as_array(),
            signing.verifier.trust_digest().as_array(),
            &signing.maximum_signature_lifetime_seconds.to_be_bytes(),
        ]),
    };
    Ok((execution, saved))
}

// Restrict the original store to the host-pinned execution key. The runner
// derives that key from its actual holdout namespace, not from caller metadata.
struct OriginalExecution<'a, E> {
    inner: &'a mut E,
    key: &'a ProductEvaluationExecutionKeyV1,
}
impl<E: ProductEvaluationExecutionStoreV1> ProductEvaluationExecutionStoreV1
    for OriginalExecution<'_, E>
{
    fn claim(
        &mut self,
        _: &ProductEvaluationExecutionKeyV1,
    ) -> Result<ProductEvaluationExecutionClaimV1, ProductEvaluationExecutionStoreErrorV1> {
        Err(ProductEvaluationExecutionStoreErrorV1::Rejected)
    }
    fn complete(
        &mut self,
        _: &ProductEvaluationExecutionKeyV1,
        _: &[u8],
    ) -> Result<(), ProductEvaluationExecutionStoreErrorV1> {
        Err(ProductEvaluationExecutionStoreErrorV1::Rejected)
    }
    fn readback(
        &mut self,
        key: &ProductEvaluationExecutionKeyV1,
    ) -> Result<ProductEvaluationExecutionStateV1, ProductEvaluationExecutionStoreErrorV1> {
        if key != self.key {
            return Err(ProductEvaluationExecutionStoreErrorV1::Conflict);
        }
        ProductEvaluationExecutionStoreV1::readback(self.inner, key)
    }
}
fn evidence_id(identity: Digest32) -> Result<StableId, OwnerError> {
    StableId::new(format!("original-evaluation-receipt:{identity}"))
        .map_err(|_| OwnerError::Binding("evidence id"))
}
fn now() -> Result<u64, OwnerError> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .map_err(|_| OwnerError::Binding("original owner clock"))
}
