//! Shared implementation for independent receipt calls and the closed host's
//! private operation. Independent calls always read the original Trainer; only
//! an actual host observation can cover reads inside its own before/after pair.
use super::*;

impl<W: AnchorWitnessStore> OriginalCellEvaluationReceiptOwnerV1<W> {
    pub(crate) async fn attest_with_training<
        S: FinalHoldoutCasStoreV1,
        C: AnchorWitnessStore,
        F: AnchorWitnessStore,
        E: ProductEvaluationExecutionStoreV1,
    >(
        &mut self,
        mut source: OriginalCellEvaluationReceiptSourcesV1<'_, S, C, F, E>,
        training: TrainingRead<'_>,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        // Any original attestation attempt consumes the host's fresh brand,
        // including a known failure before signing.
        self.host_origin = HostOrigin::ReadbackOnly;
        if now()? >= self.config.training.request.envelope.expiry_unix_seconds {
            return Err(OwnerError::Binding("new Evaluation attestation after deadline").into());
        }
        let prepared = self.prepare(&mut source)?;
        let observed_training = training
            .receipt_evidence(source.trainer, source.snapshot, &self.config)
            .await?;
        self.authenticate_roles(&source, &prepared.1, &observed_training)?;
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
        self.authenticate_completed(&mut source, prepared, &bytes, training)
            .await
    }

    pub(crate) async fn readback_with_training<
        S: FinalHoldoutCasStoreV1,
        C: AnchorWitnessStore,
        F: AnchorWitnessStore,
        E: ProductEvaluationExecutionStoreV1,
    >(
        &mut self,
        mut source: OriginalCellEvaluationReceiptSourcesV1<'_, S, C, F, E>,
        training: TrainingRead<'_>,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let prepared = self.prepare(&mut source)?;
        let bytes = self.journal.read(&self.saved)?;
        self.authenticate_completed(&mut source, prepared, &bytes, training)
            .await
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
        training: TrainingRead<'_>,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let (payload, signed) = learning_owner_evidence::decode(bytes)?;
        if payload != learning_iteration_receipt_signing_bytes_v1(&prepared.0)? {
            return Err(OwnerError::Binding("changed original Evaluation payload").into());
        }
        let observed_training = training
            .receipt_evidence(source.trainer, source.snapshot, &self.config)
            .await?;
        if self.prepare(source)? != prepared {
            return Err(OwnerError::CommitUncertain.into());
        }
        self.authenticate_roles(source, &prepared.1, &observed_training)?;
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
