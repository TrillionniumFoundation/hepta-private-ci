//! Original evaluator execution signatures, persisted before acknowledgement.
//! The host transfers an already authorized key, frozen plan, execution namespace
//! and independent witness. This owner neither invents trust nor accepts arbitrary
//! signing bytes: the execution request is constructed by the native runner only.

use std::fs::File;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence_eval::ProductEvaluationExecutionAttestationRequestV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionAttestorV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_intelligence_eval::ProductFrozenEvaluationPlanV1;
use codex_hepta_intelligence_eval::ProductProviderErrorV1;
use codex_hepta_intelligence_eval::product_evaluation_execution_key_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::learning_owner_evidence;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1 as Error;
use crate::learning_owner_journal::LearningOwnerJournalV1;

/// The original host freezes this before constructing the runner's signing port.
/// A key from a submitted candidate or returned execution is never used as trust.
#[derive(Clone)]
pub struct OriginalCellEvaluationSigningConfigV1 {
    pub plan: ProductFrozenEvaluationPlanV1,
    pub execution_namespace: Digest32,
    pub signer: TrustedLearningSignerV1,
    pub verifier: LearningEvidenceVerifierV1,
    pub maximum_signature_lifetime_seconds: u64,
}

pub struct OriginalCellEvaluationExecutionOwnerV1<W: AnchorWitnessStore> {
    journal: LearningOwnerJournalV1<W>,
    config: OriginalCellEvaluationSigningConfigV1,
    key: SigningKey,
    execution: ProductEvaluationExecutionKeyV1,
    saved: ProductEvaluationExecutionKeyV1,
}

impl<W: AnchorWitnessStore> OriginalCellEvaluationExecutionOwnerV1<W> {
    pub fn create(
        file: File,
        witness: W,
        config: OriginalCellEvaluationSigningConfigV1,
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

    /// Reopen the exact original signature owner. Pending never signs again;
    /// complete readback preserves the original issue time and expiration.
    pub fn recover(
        file: File,
        witness: W,
        config: OriginalCellEvaluationSigningConfigV1,
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

    /// Read only the original signed payload, with current signature validation.
    /// This does not execute the holdout, create a claim or renew validity.
    pub fn readback(&mut self) -> Result<(Vec<u8>, SignedLearningEvidenceV1), Error> {
        let bytes = self.journal.read(&self.saved)?;
        self.decode(&bytes)
    }

    fn attest(
        &mut self,
        request: &ProductEvaluationExecutionAttestationRequestV1<'_>,
    ) -> Result<SignedLearningEvidenceV1, Error> {
        let executed = request.execution();
        if request.key() != &self.execution
            || executed.product_plan != self.config.plan
            || executed.execution_digest.is_zero()
            || executed.authority != AuthorityPosture::DENY_ALL
            || executed.holdout.sequence == 0
            || executed.holdout.head_digest.is_zero()
        {
            return Err(Error::Binding("original sealed evaluation execution"));
        }
        let config = &self.config;
        let key = &self.key;
        let saved_key = &self.saved;
        let payload = request.signing_payload();
        let bytes = self.journal.commit_once(saved_key, || {
            let signed = sign_original(config, key, payload, saved_key.binding_digest, now()?)?;
            learning_owner_evidence::encode(payload, &signed)
        })?;
        let (saved_payload, signed) = self.decode(&bytes)?;
        if saved_payload != payload {
            return Err(Error::Binding("changed execution under original identity"));
        }
        Ok(signed)
    }

    fn decode(&self, bytes: &[u8]) -> Result<(Vec<u8>, SignedLearningEvidenceV1), Error> {
        let (payload, signed) = learning_owner_evidence::decode(bytes)?;
        let verified = self.config.verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &signed,
            &payload,
            now()?,
        )?;
        if verified.principal() != &self.config.signer.principal
            || verified.controller_id() != &self.config.signer.controller_id
            || signed.evidence_id != evidence_id(self.saved.binding_digest)?
        {
            return Err(Error::Binding("original evaluator and evidence identity"));
        }
        Ok((payload, signed))
    }
}

impl<W: AnchorWitnessStore> ProductEvaluationExecutionAttestorV1
    for OriginalCellEvaluationExecutionOwnerV1<W>
{
    fn attest_execution(
        &mut self,
        request: &ProductEvaluationExecutionAttestationRequestV1<'_>,
    ) -> Result<SignedLearningEvidenceV1, ProductProviderErrorV1> {
        self.attest(request).map_err(|error| match error {
            Error::Binding(_) | Error::Evidence(_) => ProductProviderErrorV1::Rejected,
            _ => ProductProviderErrorV1::Indeterminate,
        })
    }
}

fn validate_config(
    config: &OriginalCellEvaluationSigningConfigV1,
    key: &SigningKey,
) -> Result<
    (
        ProductEvaluationExecutionKeyV1,
        ProductEvaluationExecutionKeyV1,
    ),
    Error,
> {
    if key.verifying_key().to_bytes() != config.signer.verifying_key
        || !config
            .signer
            .roles
            .contains(&LearningEvidenceRoleV1::Evaluator)
        || !(1..=86_400).contains(&config.maximum_signature_lifetime_seconds)
        || config.plan.frozen_plan.objective_digest != config.verifier.objective_digest()
    {
        return Err(Error::Binding("original evaluator capability"));
    }
    let execution = product_evaluation_execution_key_v1(
        &config.plan,
        config.execution_namespace,
        &config.signer.principal,
    )
    .map_err(|_| Error::Binding("original execution identity"))?;
    let binding = Digest32::of_parts(&[
        b"hepta.agentd.original-evaluation-signatures.v1\0",
        execution.binding_digest.as_array(),
        config.verifier.trust_digest().as_array(),
        &config.maximum_signature_lifetime_seconds.to_be_bytes(),
    ]);
    config.verifier.require_signer_binding(
        LearningEvidenceRoleV1::Evaluator,
        &config.signer,
        now()?,
    )?;
    Ok((
        execution,
        ProductEvaluationExecutionKeyV1 {
            plan_id: config.plan.frozen_plan.plan_id.clone(),
            binding_digest: binding,
        },
    ))
}

fn sign_original(
    config: &OriginalCellEvaluationSigningConfigV1,
    key: &SigningKey,
    payload: &[u8],
    identity: Digest32,
    issued_at: u64,
) -> Result<SignedLearningEvidenceV1, Error> {
    let expires_at = issued_at
        .checked_add(config.maximum_signature_lifetime_seconds)
        .ok_or(Error::Binding("signature deadline overflow"))?
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
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    let verified = config.verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        &signed,
        payload,
        issued_at,
    )?;
    if verified.principal() != &config.signer.principal
        || verified.controller_id() != &config.signer.controller_id
    {
        return Err(Error::Binding("original evaluator enrollment"));
    }
    Ok(signed)
}

fn evidence_id(identity: Digest32) -> Result<StableId, Error> {
    StableId::new(format!("original-evaluation:{identity}"))
        .map_err(|_| Error::Binding("evidence id"))
}

fn now() -> Result<u64, Error> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .map_err(|_| Error::Binding("original owner clock"))
}
