//! Once-only authorization of an actual captured Dataset by its enrolled
//! Evaluator. This is freeze authorization, not independent B evaluation.
//! Files, witness, key and trust are supplied by their original host owners.

use std::fs::File;

use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::dataset_freeze_signing_payload_v2;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::CellQ24DatasetFreezePreparationV1;
use super::CellQ24LearningPreparationErrorV1;
use super::OriginalDatasetLedgerV1;
use super::OriginalFreezePreparationReadV1;
use crate::learning_owner_evidence;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;
use crate::learning_owner_journal::LearningOwnerJournalV1;

#[derive(Clone)]
pub struct OriginalCellQ24DatasetFreezeSigningConfigV1 {
    pub signer: TrustedLearningSignerV1,
    pub verifier: LearningEvidenceVerifierV1,
    pub maximum_signature_lifetime_seconds: u64,
}

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellQ24DatasetFreezeErrorV1 {
    #[error("original Dataset freeze owner: {0}")]
    Owner(#[from] LearningOriginalOwnerErrorV1),
    #[error("original Dataset preparation: {0}")]
    Preparation(#[from] CellQ24LearningPreparationErrorV1),
    #[error("original Evaluator capability: {0}")]
    Evidence(#[from] SignedEvidenceError),
}
type Error = OriginalCellQ24DatasetFreezeErrorV1;

pub struct OriginalCellQ24DatasetFreezeOwnerV1<W: AnchorWitnessStore> {
    journal: LearningOwnerJournalV1<W>,
    config: OriginalCellQ24DatasetFreezeSigningConfigV1,
    key: SigningKey,
    saved: ProductEvaluationExecutionKeyV1,
}

impl<W: AnchorWitnessStore> OriginalCellQ24DatasetFreezeOwnerV1<W> {
    pub fn create(
        file: File,
        witness: W,
        preparation: &CellQ24DatasetFreezePreparationV1,
        config: OriginalCellQ24DatasetFreezeSigningConfigV1,
        key: SigningKey,
    ) -> Result<Self, Error> {
        let (saved, journal) = CellQ24DatasetFreezePreparationV1::with_original_freeze_operation(
            preparation,
            |read| -> Result<_, Error> {
                OriginalFreezePreparationReadV1::original_signing_payload(read)?;
                let saved = validate_config(preparation, &config, &key, read)?;
                let journal = LearningOwnerJournalV1::create(file, witness, saved.binding_digest)?;
                Ok((saved, journal))
            },
        )??;
        Ok(Self {
            journal,
            config,
            key,
            saved,
        })
    }

    /// Reopen only the same retained journal and independent witness. Recovery
    /// cannot turn a Pending claim into a new signing attempt.
    pub fn recover(
        file: File,
        witness: W,
        preparation: &CellQ24DatasetFreezePreparationV1,
        config: OriginalCellQ24DatasetFreezeSigningConfigV1,
        key: SigningKey,
    ) -> Result<Self, Error> {
        let (saved, journal) = CellQ24DatasetFreezePreparationV1::with_original_freeze_operation(
            preparation,
            |read| -> Result<_, Error> {
                let saved = validate_config(preparation, &config, &key, read)?;
                let journal = LearningOwnerJournalV1::recover(file, witness, saved.binding_digest)?;
                Ok((saved, journal))
            },
        )??;
        Ok(Self {
            journal,
            config,
            key,
            saved,
        })
    }

    /// The typed original capture is the sole source of payload bytes. Completed
    /// signatures retain their original validity window; new work alone checks
    /// the request deadline and exact current freeze cut before durable claim.
    pub fn authorize_or_readback(
        &mut self,
        preparation: &CellQ24DatasetFreezePreparationV1,
    ) -> Result<SignedLearningEvidenceV1, Error> {
        CellQ24DatasetFreezePreparationV1::with_original_freeze_operation(preparation, |read| {
            self.authorize_in_operation(preparation, read)
        })?
    }

    fn authorize_in_operation(
        &mut self,
        preparation: &CellQ24DatasetFreezePreparationV1,
        read: &OriginalFreezePreparationReadV1<'_>,
    ) -> Result<SignedLearningEvidenceV1, Error> {
        if validate_config(preparation, &self.config, &self.key, read)? != self.saved {
            return Err(
                LearningOriginalOwnerErrorV1::Binding("original preparation identity").into(),
            );
        }
        let bytes = match self.journal.read(&self.saved) {
            Ok(bytes) => bytes,
            Err(LearningOriginalOwnerErrorV1::Store(
                ProductEvaluationExecutionStoreErrorV1::Missing,
            )) => {
                if preparation.observed_unix_seconds()?
                    >= preparation.config.request.envelope.expiry_unix_seconds
                {
                    return Err(LearningOriginalOwnerErrorV1::Binding(
                        "new freeze authorization deadline",
                    )
                    .into());
                }
                let payload = OriginalFreezePreparationReadV1::original_signing_payload(read)?;
                let config = &self.config;
                let key = &self.key;
                let saved = &self.saved;
                self.journal.commit_once(saved, || {
                    let observed = preparation
                        .observed_unix_seconds()
                        .map_err(|_| LearningOriginalOwnerErrorV1::Binding("freeze clock"))?;
                    if observed >= preparation.config.request.envelope.expiry_unix_seconds
                        || OriginalFreezePreparationReadV1::original_signing_payload(read).map_err(
                            |_| LearningOriginalOwnerErrorV1::Binding("original freeze changed"),
                        )? != payload
                    {
                        return Err(LearningOriginalOwnerErrorV1::Binding(
                            "original freeze admission",
                        ));
                    }
                    let signed =
                        sign_original(config, key, saved.binding_digest, &payload, observed)?;
                    OriginalFreezePreparationReadV1::validate_original_authorization(read, &signed)
                        .map_err(|_| {
                            LearningOriginalOwnerErrorV1::Binding(
                                "current original Dataset authorization",
                            )
                        })?;
                    if OriginalFreezePreparationReadV1::original_signing_payload(read).map_err(
                        |_| LearningOriginalOwnerErrorV1::Binding("original freeze changed"),
                    )? != payload
                    {
                        return Err(LearningOriginalOwnerErrorV1::Binding(
                            "original freeze changed before commit",
                        ));
                    }
                    learning_owner_evidence::encode(&payload, &signed)
                })?
            }
            Err(error) => return Err(error.into()),
        };
        self.authenticate(preparation, &bytes, read)
    }

    /// Read-only original completion, including after the iteration deadline.
    /// Missing or Pending is returned unchanged; no closure can run here.
    pub fn readback(
        &mut self,
        preparation: &CellQ24DatasetFreezePreparationV1,
    ) -> Result<SignedLearningEvidenceV1, Error> {
        CellQ24DatasetFreezePreparationV1::with_original_freeze_operation(preparation, |read| {
            if validate_config(preparation, &self.config, &self.key, read)? != self.saved {
                return Err(
                    LearningOriginalOwnerErrorV1::Binding("original preparation identity").into(),
                );
            }
            let bytes = self.journal.read(&self.saved)?;
            self.authenticate(preparation, &bytes, read)
        })?
    }

    fn authenticate(
        &mut self,
        preparation: &CellQ24DatasetFreezePreparationV1,
        bytes: &[u8],
        read: &OriginalFreezePreparationReadV1<'_>,
    ) -> Result<SignedLearningEvidenceV1, Error> {
        let (payload, signed) = learning_owner_evidence::decode(bytes)?;
        if payload
            != dataset_freeze_signing_payload_v2(&preparation.snapshot, &preparation.plan()?)
                .map_err(CellQ24LearningPreparationErrorV1::from)?
            || signed.evidence_id != evidence_id(self.saved.binding_digest)?
        {
            return Err(LearningOriginalOwnerErrorV1::Binding(
                "original freeze payload and signature identity",
            )
            .into());
        }
        let verified = self.config.verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &signed,
            &payload,
            preparation.observed_unix_seconds()?,
        )?;
        if verified.principal() != &self.config.signer.principal
            || verified.controller_id() != &self.config.signer.controller_id
        {
            return Err(LearningOriginalOwnerErrorV1::Binding("original freeze Evaluator").into());
        }
        OriginalFreezePreparationReadV1::validate_original_authorization(read, &signed)?;
        if validate_config(preparation, &self.config, &self.key, read)? != self.saved
            || self.journal.read(&self.saved)? != bytes
        {
            return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into());
        }
        Ok(signed)
    }
}

fn validate_config(
    preparation: &CellQ24DatasetFreezePreparationV1,
    config: &OriginalCellQ24DatasetFreezeSigningConfigV1,
    key: &SigningKey,
    read: &OriginalFreezePreparationReadV1<'_>,
) -> Result<ProductEvaluationExecutionKeyV1, Error> {
    OriginalFreezePreparationReadV1::require_original_preparation(read, preparation)?;
    if matches!(&preparation.ledger, OriginalDatasetLedgerV1::Historical(_)) {
        return Ok(OriginalFreezePreparationReadV1::original_freezer_key(
            read, config, key,
        )?);
    }
    let identity = preparation.identity()?;
    let ledger = preparation
        .ledger
        .original_writer()
        .map_err(CellQ24LearningPreparationErrorV1::from)?
        .lock()
        .map_err(|_| LearningOriginalOwnerErrorV1::Binding("original ledger lock"))?;
    let original = ledger.verifier();
    if config.verifier.trust_digest() != original.trust_digest()
        || config.verifier.scope_digest() != original.scope_digest()
        || config.verifier.objective_digest()
            != preparation.config.request.envelope.objective_digest
        || key.verifying_key().to_bytes() != config.signer.verifying_key
        || !(1..=86_400).contains(&config.maximum_signature_lifetime_seconds)
    {
        return Err(LearningOriginalOwnerErrorV1::Binding(
            "original Evaluator signing configuration",
        )
        .into());
    }
    original.require_signer_binding(
        LearningEvidenceRoleV1::Evaluator,
        &config.signer,
        preparation.observed_unix_seconds()?,
    )?;
    config.verifier.require_signer_binding(
        LearningEvidenceRoleV1::Evaluator,
        &config.signer,
        preparation.observed_unix_seconds()?,
    )?;
    Ok(crate::original_q24_dataset_freeze_execution_key_v1(
        &preparation.config.request.operation_id,
        identity,
        original.trust_digest(),
        &config.signer,
        config.maximum_signature_lifetime_seconds,
    ))
}

fn sign_original(
    config: &OriginalCellQ24DatasetFreezeSigningConfigV1,
    key: &SigningKey,
    identity: Digest32,
    payload: &[u8],
    issued_at: u64,
) -> Result<SignedLearningEvidenceV1, LearningOriginalOwnerErrorV1> {
    config.verifier.require_signer_binding(
        LearningEvidenceRoleV1::Evaluator,
        &config.signer,
        issued_at,
    )?;
    let expires_at = issued_at
        .checked_add(config.maximum_signature_lifetime_seconds)
        .ok_or(LearningOriginalOwnerErrorV1::Binding(
            "freeze expiry overflow",
        ))?
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
    config.verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        &signed,
        payload,
        issued_at,
    )?;
    Ok(signed)
}

fn evidence_id(identity: Digest32) -> Result<StableId, LearningOriginalOwnerErrorV1> {
    StableId::new(format!("original-dataset-freeze:{identity}"))
        .map_err(|_| LearningOriginalOwnerErrorV1::Binding("freeze evidence id"))
}
