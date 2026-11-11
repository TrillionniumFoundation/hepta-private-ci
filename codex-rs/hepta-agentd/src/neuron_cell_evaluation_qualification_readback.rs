//! Original Completed readback. The sink adapter only reads existing bytes.
//! The original runner reconstructs its private seal from its original signed
//! material; this module never deserializes a seal or performs a journal effect.
use codex_hepta_intelligence_eval::ProductEvidenceSinkErrorV1;
use codex_hepta_intelligence_eval::ProductQualificationEvidenceSinkV1;
use codex_hepta_intelligence_eval::SignedEvaluationDecisionV1;
use codex_hepta_intelligence_eval::revalidate_product_qualification_v1;
use codex_hepta_types::Digest32;

use super::*;

impl<W: AnchorWitnessStore> OriginalCellEvaluationQualificationOwnerV1<W> {
    /// Work expiry never renews or erases an original completed publication.
    /// Readback requires all original signatures to remain valid now, and the
    /// actual raw execution, holdout, Cell journals and Trainer to still agree.
    pub async fn readback(
        &mut self,
        mut source: OriginalCellEvaluationQualificationSourcesV1<
            '_,
            impl AnchorWitnessStore,
            impl AnchorWitnessStore,
            impl AnchorWitnessStore,
        >,
    ) -> Result<CellEvaluationQualificationV1, Error> {
        let started_at = binding::now()?;
        let bytes = self.completed_bytes()?;
        self.read_completed(&mut source, &bytes, started_at).await
    }

    pub(super) async fn read_completed(
        &mut self,
        source: &mut OriginalCellEvaluationQualificationSourcesV1<
            '_,
            impl AnchorWitnessStore,
            impl AnchorWitnessStore,
            impl AnchorWitnessStore,
        >,
        bytes: &[u8],
        started_at: u64,
    ) -> Result<CellEvaluationQualificationV1, Error> {
        let result = async {
            let prepared = source.prepare(&self.config, started_at).await?;
            self.finish_readback(source, &prepared, bytes, started_at, false)
                .await
        }
        .await;
        if result.is_err() {
            self.fenced = true;
        }
        result
    }

    pub(super) async fn finish_readback(
        &mut self,
        source: &mut OriginalCellEvaluationQualificationSourcesV1<
            '_,
            impl AnchorWitnessStore,
            impl AnchorWitnessStore,
            impl AnchorWitnessStore,
        >,
        prepared: &Prepared,
        bytes: &[u8],
        started_at: u64,
        new_publication: bool,
    ) -> Result<CellEvaluationQualificationV1, Error> {
        let current = binding::now()?;
        binding::clock_time(started_at, current)?;
        binding::authenticate(&self.config, prepared, current)?;
        let mut sink = ReadbackPort {
            journal: &mut self.journal,
            key: &self.saved,
            bytes,
            execution_digest: prepared.evaluation.temporal().execution_digest,
            error: None,
        };
        let runner: &CellEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1> = source.runner;
        let result = runner.qualify_and_persist(
            &prepared.evaluation,
            CellEvaluationQualificationRequestV1 {
                context: &self.config.context,
                evidence: &self.config.product_evidence,
                timing: ProductTimingEvidenceV1::Qualification,
                verifier: &self.config.verifier,
                now: current,
            },
            &mut sink,
        );
        if let Some(error) = sink.error.take() {
            return Err(error);
        }
        let qualification = result?;
        drop(sink);
        source.read_trainer(&self.config).await?;
        source.verify_current(&self.config, prepared)?;
        if self.completed_bytes()? != bytes {
            return Err(Error::CommitUncertain);
        }
        let current = binding::now()?;
        binding::clock_time(started_at, current)?;
        if new_publication {
            binding::new_work_time(&self.config, started_at, current)?;
        }
        binding::authenticate(&self.config, prepared, current)?;
        let decision = revalidate_product_qualification_v1(
            qualification.product(),
            prepared.bundle.clone(),
            self.config.plan.product_plan().metric_roles.clone(),
            &self.config.product_evidence,
            ProductTimingEvidenceV1::Qualification,
            &self.config.verifier,
            current,
        )?;
        if qualification.product().decision != decision {
            return Err(Error::CommitUncertain);
        }
        // No physical or peer I/O follows the final verification of every
        // original signature and its unchanged validity window.
        Ok(qualification)
    }
}

struct ReadbackPort<'a, W: AnchorWitnessStore> {
    journal: &'a mut OriginalCellEvaluationExecutionStoreV1<W>,
    key: &'a ProductEvaluationExecutionKeyV1,
    bytes: &'a [u8],
    execution_digest: Digest32,
    error: Option<Error>,
}

impl<W: AnchorWitnessStore> ReadbackPort<'_, W> {
    fn read_original(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, Error> {
        if execution_digest != self.execution_digest {
            return Err(Error::Binding("original completed Qualification execution"));
        }
        let expected = binding::decision_bytes(self.key, execution_digest, decision)?;
        if expected != self.bytes {
            return Err(Error::Binding("original completed Qualification decision"));
        }
        match ProductEvaluationExecutionStoreV1::readback(self.journal, self.key)? {
            State::Pending => return Err(Error::Pending),
            State::Completed(original) if original == self.bytes => {}
            State::Completed(_) => return Err(Error::CommitUncertain),
        }
        Ok(binding::publication_digest(self.key, self.bytes))
    }
}

impl<W: AnchorWitnessStore> ProductQualificationEvidenceSinkV1 for ReadbackPort<'_, W> {
    fn persist(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        match self.read_original(execution_digest, decision) {
            Ok(digest) => Ok(digest),
            Err(error) => {
                self.error = Some(error);
                Err(ProductEvidenceSinkErrorV1::Rejected)
            }
        }
    }
}
