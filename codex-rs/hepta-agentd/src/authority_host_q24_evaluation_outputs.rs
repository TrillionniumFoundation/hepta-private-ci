//! Private original B output custody. Only this host's concrete file store is
//! shared with its native runner; no generic store or signing port crosses the
//! daemon boundary. Create and recover are chosen from the Root retained record.

use std::io;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_intelligence_eval::FinalHoldoutCasRecordV1;
use codex_hepta_intelligence_eval::FinalHoldoutCasStoreError;
use codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::LockedFileFinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::learning_owner_evidence;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;
use crate::learning_owner_journal::LearningOwnerJournalV1;

use super::admission::OriginalBAuthorities;
use super::deployment::OriginalBJournalFiles;
use super::record::OriginalBEnrollment;

#[derive(Clone, Copy)]
pub(super) enum OriginalBOpenMode {
    Create,
    Recover,
}

/// This concrete wrapper has no public constructor and never leaves Root.
#[derive(Clone)]
pub(super) struct OriginalBCas(pub(super) Arc<Mutex<LockedFileFinalHoldoutCasStoreV1>>);

impl FinalHoldoutCasStoreV1 for OriginalBCas {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<FinalHoldoutCasRecordV1>, FinalHoldoutCasStoreError> {
        let mut store = self
            .0
            .try_lock()
            .map_err(|_| FinalHoldoutCasStoreError::Indeterminate)?;
        FinalHoldoutCasStoreV1::load(&mut *store, binding)
    }

    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<Digest32>,
        next: &FinalHoldoutCasRecordV1,
    ) -> Result<(), FinalHoldoutCasStoreError> {
        let mut store = self
            .0
            .try_lock()
            .map_err(|_| FinalHoldoutCasStoreError::Indeterminate)?;
        FinalHoldoutCasStoreV1::compare_and_swap(&mut *store, binding, expected, next)
    }
}

pub(super) fn original_witness(
    files: &mut OriginalBJournalFiles,
    enrollment: &OriginalBEnrollment,
    binding: Digest32,
    objective: Digest32,
    mode: OriginalBOpenMode,
) -> io::Result<(std::fs::File, FileAnchorWitnessStore)> {
    match mode {
        OriginalBOpenMode::Create => {
            files.journal.require_empty()?;
            files.witness.require_empty()?;
        }
        OriginalBOpenMode::Recover => {
            // A missing independent witness is not an initialization request.
            files.journal.require_nonempty()?;
            files.witness.require_nonempty()?;
        }
    }
    let witness = FileAnchorWitnessStore::open(
        files.witness.take_original_writer()?,
        JournalScope {
            scope_digest: binding,
            objective_digest: objective,
        },
        Generation::new(enrollment.original_generation).map_err(io::Error::other)?,
        /*max_records*/ 128,
    )
    .map_err(io::Error::other)?;
    Ok((files.journal.take_original_writer()?, witness))
}

pub(super) struct OriginalBJournal {
    journal: LearningOwnerJournalV1<FileAnchorWitnessStore>,
    key: ProductEvaluationExecutionKeyV1,
}

impl OriginalBJournal {
    pub(super) fn open(
        files: &mut OriginalBJournalFiles,
        enrollment: &OriginalBEnrollment,
        execution: &ProductEvaluationExecutionKeyV1,
        purpose: &[u8],
        authorities: &OriginalBAuthorities,
        mode: OriginalBOpenMode,
    ) -> io::Result<Self> {
        let binding = Digest32::of_parts(&[
            b"hepta.root.independent-b.output.v1\0",
            purpose,
            execution.binding_digest.as_array(),
            authorities.verifier.trust_digest().as_array(),
            &enrollment.initial_head,
        ]);
        let (file, witness) = original_witness(
            files,
            enrollment,
            binding,
            authorities.verifier.objective_digest(),
            mode,
        )?;
        let journal = match mode {
            OriginalBOpenMode::Create => LearningOwnerJournalV1::create(file, witness, binding),
            OriginalBOpenMode::Recover => LearningOwnerJournalV1::recover(file, witness, binding),
        }
        .map_err(io::Error::other)?;
        Ok(Self {
            journal,
            key: ProductEvaluationExecutionKeyV1 {
                plan_id: execution.plan_id.clone(),
                binding_digest: binding,
            },
        })
    }

    pub(super) fn original_bytes(
        &mut self,
        bytes: &[u8],
        mode: OriginalBResultMode,
    ) -> io::Result<Vec<u8>> {
        let saved = match mode {
            OriginalBResultMode::Complete => {
                self.journal.commit_once(&self.key, || Ok(bytes.to_vec()))
            }
            OriginalBResultMode::Readback => self.journal.read(&self.key),
        }
        .map_err(io::Error::other)?;
        if saved != bytes {
            return Err(io::Error::other("original B durable output changed"));
        }
        Ok(saved)
    }

    pub(super) fn original_signature(
        &mut self,
        payload: &[u8],
        authorities: &OriginalBAuthorities,
        signing: &SigningKey,
        issued_at: u64,
        expires_at: u64,
        mode: OriginalBResultMode,
    ) -> io::Result<SignedLearningEvidenceV1> {
        let identity = self.key.binding_digest;
        let saved = match mode {
            OriginalBResultMode::Complete => self.journal.commit_once(&self.key, || {
                let principal = &authorities.evaluator.principal;
                let mut evidence = SignedLearningEvidenceV1 {
                    evidence_id: StableId::new(format!("original-root-b:{identity}")).map_err(
                        |_| LearningOriginalOwnerErrorV1::Binding("original B evidence id"),
                    )?,
                    principal_id: principal.principal_id.clone(),
                    role: LearningEvidenceRoleV1::Evaluator,
                    trust_digest: authorities.verifier.trust_digest(),
                    scope_digest: authorities.verifier.scope_digest(),
                    objective_digest: authorities.verifier.objective_digest(),
                    authority_epoch: principal.authority_epoch,
                    issued_at,
                    expires_at: expires_at.min(principal.expires_at),
                    payload_digest: Digest32::of_bytes(payload),
                    signature: [0; 64],
                };
                if signing.verifying_key().to_bytes() != authorities.evaluator.verifying_key {
                    return Err(LearningOriginalOwnerErrorV1::Binding(
                        "original B evaluator key",
                    ));
                }
                evidence.signature = signing.sign(&evidence.signing_bytes()).to_bytes();
                authorities.verifier.verify(
                    LearningEvidenceRoleV1::Evaluator,
                    &evidence,
                    payload,
                    issued_at,
                )?;
                learning_owner_evidence::encode(payload, &evidence)
            }),
            OriginalBResultMode::Readback => self.journal.read(&self.key),
        }
        .map_err(io::Error::other)?;
        let (original, evidence) =
            learning_owner_evidence::decode(&saved).map_err(io::Error::other)?;
        let actual = authorities
            .verifier
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &evidence,
                &original,
                issued_at,
            )
            .map_err(io::Error::other)?;
        if original != payload
            || actual.principal() != &authorities.evaluator.principal
            || actual.controller_id() != &authorities.evaluator.controller_id
        {
            return Err(io::Error::other("original B signature differs"));
        }
        Ok(evidence)
    }
}

#[derive(Clone, Copy)]
pub(super) enum OriginalBResultMode {
    Complete,
    Readback,
}
