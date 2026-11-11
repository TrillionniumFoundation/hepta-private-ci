//! Original Qualification publication, separate from evidence production.
//! The host transfers the publication file and independent witness, and lends
//! the actual fenced holdout and execution owners. This module creates no role,
//! trust, signer, holdout, estimator result, or independent B dataset.
//! Qualification/v2 uses current Unix seconds; longitudinal/v3 is not admitted.

use std::fs::File;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence_eval::EvaluationClaimScopeV1;
use codex_hepta_intelligence_eval::LockedFileFinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::LockedFileProductEvaluationExecutionStoreV1;
use codex_hepta_intelligence_eval::ProductEvaluationError;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionErrorV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionMaterialV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionRequestV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStateV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreV1;
use codex_hepta_intelligence_eval::ProductEvaluationRunnerV1;
use codex_hepta_intelligence_eval::ProductEvidenceSinkErrorV1;
use codex_hepta_intelligence_eval::ProductFrozenEvaluationPlanV1;
use codex_hepta_intelligence_eval::ProductProviderErrorV1;
use codex_hepta_intelligence_eval::ProductQualificationContextV1;
use codex_hepta_intelligence_eval::ProductQualificationEvidenceSinkV1;
use codex_hepta_intelligence_eval::ProductQualificationPublicationMaterialV1;
use codex_hepta_intelligence_eval::ProductQualificationReceiptV1;
use codex_hepta_intelligence_eval::ProductTimingEvidenceV1;
use codex_hepta_intelligence_eval::SignedEvaluationDecisionV1;
use codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;
use codex_hepta_intelligence_eval::TemporalEvaluationPlan;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;

use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;
use crate::learning_owner_journal::LearningOwnerJournalV1;

#[path = "product_qualification_owner_codec.rs"]
mod codec;

#[derive(Debug, thiserror::Error)]
pub enum OriginalProductQualificationErrorV1 {
    #[error("original qualification binding: {0}")]
    Binding(&'static str),
    #[error("original qualification publication: {0}")]
    Owner(#[from] LearningOriginalOwnerErrorV1),
    #[error("original qualification execution: {0}")]
    Execution(#[from] ProductEvaluationExecutionErrorV1),
    #[error("original qualification evaluation: {0}")]
    Evaluation(#[from] ProductEvaluationError),
    #[error("original qualification source store: {0}")]
    Store(#[from] ProductEvaluationExecutionStoreErrorV1),
}
type Error = OriginalProductQualificationErrorV1;

/// Host-pinned original plans and current trust. There is no caller clock.
pub struct OriginalProductQualificationSourceV1<'a> {
    pub plan: &'a ProductFrozenEvaluationPlanV1,
    pub candidate_plan: &'a TemporalEvaluationPlan,
    pub baseline_plan: &'a TemporalEvaluationPlan,
    pub evaluator: &'a AuthenticatedPrincipalV1,
    pub verifier: &'a LearningEvidenceVerifierV1,
}

impl OriginalProductQualificationSourceV1<'_> {
    fn execution(&self) -> ProductEvaluationExecutionRequestV1<'_> {
        ProductEvaluationExecutionRequestV1 {
            plan: self.plan,
            candidate_plan: self.candidate_plan,
            baseline_plan: self.baseline_plan,
            evaluator: self.evaluator,
            verifier: self.verifier,
            clock: &execution_clock,
        }
    }
}

/// Acknowledged complete material, never an ordinary append file or a signer.
/// The host retains directory durability and independent rollback custody for
/// the witness. Original source owners must retain their exclusive file custody.
pub struct OriginalProductQualificationOwnerV1<W: AnchorWitnessStore> {
    journal: LearningOwnerJournalV1<W>,
    binding: Digest32,
}

impl<W: AnchorWitnessStore> OriginalProductQualificationOwnerV1<W> {
    pub fn create(file: File, witness: W, namespace: Digest32) -> Result<Self, Error> {
        let binding = owner_binding(namespace)?;
        Ok(Self {
            journal: LearningOwnerJournalV1::create(file, witness, binding)?,
            binding,
        })
    }

    pub fn recover(file: File, witness: W, namespace: Digest32) -> Result<Self, Error> {
        let binding = owner_binding(namespace)?;
        Ok(Self {
            journal: LearningOwnerJournalV1::recover(file, witness, binding)?,
            binding,
        })
    }

    pub fn publish(
        &mut self,
        runner: &mut ProductEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1>,
        executions: &mut LockedFileProductEvaluationExecutionStoreV1,
        source: &OriginalProductQualificationSourceV1<'_>,
        context: &ProductQualificationContextV1,
        evidence: &SignedEvaluationEvidenceV1,
    ) -> Result<ProductQualificationReceiptV1, Error> {
        self.run(
            runner,
            executions,
            source,
            Operation::Publish { context, evidence },
        )
    }

    /// Reopen material from this original journal. No caller qualification
    /// receipt, decision, old context, old signatures, provider, or signer is
    /// needed. Host-pinned source plans and current trust remain required.
    pub fn readback(
        &mut self,
        runner: &mut ProductEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1>,
        executions: &mut LockedFileProductEvaluationExecutionStoreV1,
        source: &OriginalProductQualificationSourceV1<'_>,
    ) -> Result<ProductQualificationReceiptV1, Error> {
        self.run(runner, executions, source, Operation::Readback)
    }

    fn run(
        &mut self,
        runner: &mut ProductEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1>,
        executions: &mut LockedFileProductEvaluationExecutionStoreV1,
        source: &OriginalProductQualificationSourceV1<'_>,
        operation: Operation<'_>,
    ) -> Result<ProductQualificationReceiptV1, Error> {
        if source.plan.frozen_plan.claim_scope != EvaluationClaimScopeV1::Qualification {
            return Err(Error::Binding("Qualification/v2 scope"));
        }
        let material: ProductEvaluationExecutionMaterialV1 =
            runner.readback_temporal_comparison_material(&source.execution(), executions)?;
        let key = publication_key(self.binding, material.key());
        let retained = match self.journal.read(&key) {
            Ok(bytes) => Some(bytes),
            Err(LearningOriginalOwnerErrorV1::Store(
                ProductEvaluationExecutionStoreErrorV1::Missing,
            )) if matches!(&operation, Operation::Publish { .. }) => None,
            Err(error) => return Err(error.into()),
        };
        let saved = retained.as_deref().map(codec::decode).transpose()?;
        if saved
            .as_ref()
            .is_some_and(|saved| saved.binding != self.binding)
        {
            return Err(Error::Binding("publication namespace"));
        }
        let current_time = now()?;
        let recorded_at = saved
            .as_ref()
            .map_or(current_time, |saved| saved.recorded_at);
        if recorded_at > current_time {
            return Err(Error::Binding("original publication time"));
        }
        let (context, evidence, mode) = match operation {
            Operation::Publish { context, evidence } => (context, evidence, Mode::Publish),
            Operation::Readback => {
                let saved = saved
                    .as_ref()
                    .ok_or(Error::Binding("missing publication"))?;
                (&saved.context, &saved.evidence, Mode::Readback)
            }
        };
        if &context.evaluator != source.evaluator {
            return Err(Error::Binding("original evaluator context"));
        }
        let bundle = runner.qualification_bundle(material.execution(), context)?;
        let expected = runner.original_qualification_decision(
            &material,
            context,
            evidence,
            source.verifier,
            current_time,
        )?;
        let full_material =
            material.qualification_record_bytes(&ProductQualificationPublicationMaterialV1 {
                candidate_plan: source.candidate_plan,
                baseline_plan: source.baseline_plan,
                bundle: &bundle,
                evidence,
                decision: &expected,
                publication_binding: self.binding,
                recorded_at,
            })?;
        // Both the inner and outer complete encodings must fit before any claim.
        let bytes = codec::encode(recorded_at, self.binding, context, evidence, &full_material)?;
        if retained.as_ref().is_some_and(|retained| retained != &bytes) {
            return Err(Error::Binding(
                "conflicting complete qualification material",
            ));
        }
        if runner.readback_temporal_comparison_material(&source.execution(), executions)?
            != material
        {
            return Err(Error::Binding("source changed before publication"));
        }
        let mut sink = OriginalQualificationSink {
            journal: &mut self.journal,
            runner: &*runner,
            executions: &mut *executions,
            material: &material,
            context,
            evidence,
            verifier: source.verifier,
            key: &key,
            bytes: &bytes,
            expected: &expected,
            mode,
            failure: None,
        };
        let result = runner.qualify_and_persist(
            material.execution(),
            context,
            evidence,
            ProductTimingEvidenceV1::Qualification,
            source.verifier,
            now()?,
            &mut sink,
        );
        let failure = sink.failure.take();
        drop(sink);
        if let Some(error) = failure {
            return Err(error);
        }
        let receipt = result?;
        let after =
            runner.readback_temporal_comparison_material(&source.execution(), executions)?;
        if after != material
            || runner.original_qualification_decision(
                &after,
                context,
                evidence,
                source.verifier,
                now()?,
            )? != receipt.decision
        {
            return Err(Error::Binding("source changed during publication"));
        }
        // Last: a source readback may have crossed an independent witness change.
        if self.journal.read(&key)? != bytes {
            return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into());
        }
        Ok(receipt)
    }
}

enum Operation<'a> {
    Publish {
        context: &'a ProductQualificationContextV1,
        evidence: &'a SignedEvaluationEvidenceV1,
    },
    Readback,
}
#[derive(Clone, Copy)]
enum Mode {
    Publish,
    Readback,
}

/// Concrete production sink, constructible only while the actual original
/// runner is immutably borrowed and its exclusive source stores stay held.
struct OriginalQualificationSink<'a, W: AnchorWitnessStore> {
    journal: &'a mut LearningOwnerJournalV1<W>,
    runner: &'a ProductEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1>,
    executions: &'a mut LockedFileProductEvaluationExecutionStoreV1,
    material: &'a ProductEvaluationExecutionMaterialV1,
    context: &'a ProductQualificationContextV1,
    evidence: &'a SignedEvaluationEvidenceV1,
    verifier: &'a LearningEvidenceVerifierV1,
    key: &'a ProductEvaluationExecutionKeyV1,
    bytes: &'a [u8],
    expected: &'a SignedEvaluationDecisionV1,
    mode: Mode,
    failure: Option<Error>,
}

impl<W: AnchorWitnessStore> OriginalQualificationSink<'_, W> {
    fn persist_original(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, Error> {
        if execution_digest != self.material.execution().execution_digest
            || decision != self.expected
        {
            return Err(Error::Binding("original execution and complete decision"));
        }
        let derived = self.runner.original_qualification_decision(
            self.material,
            self.context,
            self.evidence,
            self.verifier,
            now()?,
        )?;
        if &derived != decision {
            return Err(Error::Binding("current original signed decision"));
        }
        match self.executions.readback(self.material.key())? {
            ProductEvaluationExecutionStateV1::Completed(bytes)
                if bytes == self.material.envelope() => {}
            ProductEvaluationExecutionStateV1::Pending => {
                return Err(ProductEvaluationExecutionErrorV1::Pending.into());
            }
            ProductEvaluationExecutionStateV1::Completed(_) => {
                return Err(Error::Binding("original execution bytes"));
            }
        }
        let saved = match self.mode {
            Mode::Publish => self
                .journal
                .commit_once(self.key, || Ok(self.bytes.to_vec()))?,
            Mode::Readback => self.journal.read(self.key)?,
        };
        if saved != self.bytes {
            return Err(Error::Binding("conflicting publication bytes"));
        }
        // The original runner constructs its receipt only after this durable ack.
        Ok(Digest32::of_bytes(&saved))
    }
}

impl<W: AnchorWitnessStore> ProductQualificationEvidenceSinkV1
    for OriginalQualificationSink<'_, W>
{
    fn persist(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        self.persist_original(execution_digest, decision)
            .map_err(|error| {
                let mapped = match &error {
                    Error::Owner(
                        LearningOriginalOwnerErrorV1::Pending
                        | LearningOriginalOwnerErrorV1::CommitUncertain,
                    )
                    | Error::Execution(ProductEvaluationExecutionErrorV1::Pending) => {
                        ProductEvidenceSinkErrorV1::Indeterminate
                    }
                    Error::Store(ProductEvaluationExecutionStoreErrorV1::Unavailable) => {
                        ProductEvidenceSinkErrorV1::Unavailable
                    }
                    _ => ProductEvidenceSinkErrorV1::Rejected,
                };
                self.failure = Some(error); // Preserve the original typed error at the owner API.
                mapped
            })
    }
}

fn owner_binding(namespace: Digest32) -> Result<Digest32, Error> {
    if namespace.is_zero() {
        return Err(Error::Binding("publication namespace"));
    }
    let mut bytes = b"hepta.original-product-qualification-owner.v1".to_vec();
    bytes.extend_from_slice(namespace.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

fn publication_key(
    binding: Digest32,
    original: &ProductEvaluationExecutionKeyV1,
) -> ProductEvaluationExecutionKeyV1 {
    let mut bytes = b"hepta.original-product-qualification-key.v1".to_vec();
    bytes.extend_from_slice(binding.as_array());
    bytes.extend_from_slice(original.binding_digest.as_array());
    ProductEvaluationExecutionKeyV1 {
        plan_id: original.plan_id.clone(),
        binding_digest: Digest32::of_bytes(&bytes),
    }
}

fn now() -> Result<u64, Error> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|time| time.as_secs())
        .map_err(|_| Error::Binding("current qualification clock"))
}

fn execution_clock() -> Result<u64, ProductProviderErrorV1> {
    now().map_err(|_| ProductProviderErrorV1::Unavailable)
}
