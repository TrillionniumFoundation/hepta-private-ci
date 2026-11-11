//! Actual Q24 training and original file/signature owners over synthetic
//! evaluator observations. These tests grant no production or science status.

use codex_hepta_intelligence_eval::IndependentEvaluationDispositionV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use crate::CellQ24ModelProposalErrorV1 as ProposalError;
use crate::CellQ24ModelProposalInputsV1;
use crate::CellQ24ModelProposalOwnerV1;
use crate::CellQ24ModelProposalReceiptV1;
use crate::neuron_cell_evaluation::tests::learning::LearningFixture;

use super::*;

#[path = "cell_q24_training_model_lane_tests.rs"]
mod training_lane;

struct ProposalFixture {
    trainer: CellQ24TrainingOwnerV1<FileAnchorWitnessStore>,
    dataset: LearningIterationSnapshotV1,
    evaluation: LearningFixture,
    signature: SignedLearningEvidenceV1,
    now: u64,
    clock: Arc<AtomicU64>,
    _directory: tempfile::TempDir,
}

impl ProposalFixture {
    fn new(disposition: IndependentEvaluationDispositionV1) -> anyhow::Result<Self> {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_secs();
        let evaluation = LearningFixture::new_at(disposition, now);
        let directory = tempfile::tempdir()?;
        let baseline = Arc::new(load(directory.path(), /*factor*/ 1)?);
        let selected = bundle(&baseline, /*prior*/ None)?;
        let data = batch(2 * Q)?;
        let rule = CellQ24SgdRuleV1 {
            epochs: 2,
            learning_rate_q24: Q / 2,
        };
        let (_, prefix) = plan(
            Arc::clone(&baseline),
            &selected,
            &data,
            CellQ24PrivateHeadV1::Drive { index: 0 },
            rule,
            "none",
        )?;
        let mut request = prefix.request;
        request.evaluation_profile = evaluation.snapshot.request.evaluation_profile;
        request.envelope.expiry_unix_seconds = now + 300;
        let mut coordinator =
            LearningIterationCoordinatorV1::new(request, evaluation.snapshot.owners.clone())?;
        for original in prefix.receipts {
            let receipt = LearningIterationReceiptV1 {
                operation_id: coordinator.snapshot().request.operation_id.clone(),
                predecessor: coordinator.snapshot().head_digest,
                actor_id: coordinator
                    .snapshot()
                    .owners
                    .owner(original.observation.stage())
                    .clone(),
                evidence_digest: original.evidence_digest,
                observed_unix_seconds: now - 5,
                observation: original.observation,
            };
            coordinator.record(receipt, now)?;
        }
        let dataset = coordinator.snapshot().clone();
        let mut trainer = CellQ24TrainingOwnerV1::create(
            opened(directory.path(), "job")?,
            witness(directory.path())?,
            original_plan(Arc::clone(&baseline), &dataset, &data, rule)?,
            data,
            rule,
        )?;
        let CellQ24TrainingOutcomeV1::Candidate(candidate) =
            trainer.fit_or_readback(&AtomicBool::new(false))?
        else {
            anyhow::bail!("expected changed quantized row");
        };
        let observation = trainer.read_learning_observation(&dataset)?;
        coordinator.record(
            LearningIterationReceiptV1 {
                operation_id: dataset.request.operation_id.clone(),
                predecessor: dataset.head_digest,
                actor_id: dataset.owners.trainer.clone(),
                evidence_digest: observation.evidence_digest(),
                observed_unix_seconds: now - 2,
                observation: observation.observation().clone(),
            },
            now,
        )?;
        let evaluation = evaluation.with_training(
            coordinator.snapshot().clone(),
            [
                configured(&candidate.model, &candidate.bundle)?.manifest,
                configured(&baseline, &selected)?.manifest,
            ],
            disposition,
        );
        let signature =
            evaluation.stage_attestation(evaluation.snapshot.receipts.last().expect("Training"));
        Ok(Self {
            trainer,
            dataset,
            evaluation,
            signature,
            now,
            clock: Arc::new(AtomicU64::new(now)),
            _directory: directory,
        })
    }

    fn clock_owner<W: AnchorWitnessStore>(&self, owner: &mut CellQ24ModelProposalOwnerV1<W>) {
        let clock = Arc::clone(&self.clock);
        owner.set_test_clock(move || Ok(clock.load(Ordering::SeqCst)));
    }

    fn commit<W: AnchorWitnessStore>(
        &mut self,
        owner: &mut CellQ24ModelProposalOwnerV1<W>,
        now: u64,
    ) -> Result<CellQ24ModelProposalReceiptV1, ProposalError> {
        let request = self.evaluation.request(now);
        owner.commit_or_readback(
            &mut self.trainer,
            &CellQ24ModelProposalInputsV1 {
                training_cut: &self.evaluation.snapshot,
                training_attestation: &self.signature,
                runner: self.evaluation.runner(),
                evaluation: &self.evaluation.receipt,
                qualification: &self.evaluation.qualification,
                request: &request,
            },
        )
    }
    fn read<W: AnchorWitnessStore>(
        &mut self,
        owner: &mut CellQ24ModelProposalOwnerV1<W>,
        now: u64,
    ) -> Result<CellQ24ModelProposalReceiptV1, ProposalError> {
        let request = self.evaluation.request(now);
        owner.readback(
            &mut self.trainer,
            &CellQ24ModelProposalInputsV1 {
                training_cut: &self.evaluation.snapshot,
                training_attestation: &self.signature,
                runner: self.evaluation.runner(),
                evaluation: &self.evaluation.receipt,
                qualification: &self.evaluation.qualification,
                request: &request,
            },
        )
    }
}

#[test]
fn q24_model_proposal_original_training_commit_and_cold_readback() -> anyhow::Result<()> {
    let mut fixture =
        ProposalFixture::new(IndependentEvaluationDispositionV1::EligibleForIndependentSelection)?;
    let directory = tempfile::tempdir()?;
    let mut owner = CellQ24ModelProposalOwnerV1::create(
        opened(directory.path(), "proposal")?,
        witness(directory.path())?,
        &mut fixture.trainer,
        fixture.dataset.clone(),
    )?;
    fixture.clock_owner(&mut owner);
    let now = fixture.now;
    assert!(matches!(
        fixture.read(&mut owner, now),
        Err(ProposalError::Store(
            ProductEvaluationExecutionStoreErrorV1::Missing
        ))
    ));
    let receipt = fixture.commit(&mut owner, now)?;
    let saved = fs::read(directory.path().join("proposal"))?;
    assert_eq!(
        receipt.authority(),
        codex_hepta_types::AuthorityPosture::DENY_ALL
    );
    assert_eq!(fixture.commit(&mut owner, now + 1)?, receipt);
    assert_eq!(fs::read(directory.path().join("proposal"))?, saved);
    drop(owner);
    let mut recovered = CellQ24ModelProposalOwnerV1::recover(
        opened(directory.path(), "proposal")?,
        witness(directory.path())?,
        &mut fixture.trainer,
        fixture.dataset.clone(),
    )?;
    fixture.clock_owner(&mut recovered);
    // Expired work can only return its existing original bytes and timestamp.
    fixture.clock.store(now + 301, Ordering::SeqCst);
    assert_eq!(fixture.read(&mut recovered, now + 301)?, receipt);
    assert_eq!(fixture.commit(&mut recovered, now + 301)?, receipt);
    assert_eq!(fs::read(directory.path().join("proposal"))?, saved);
    assert!(witness(directory.path()).is_err());
    Ok(())
}

#[test]
fn q24_model_proposal_rejects_tampered_training_before_claim_and_on_readback() -> anyhow::Result<()>
{
    let mut fixture =
        ProposalFixture::new(IndependentEvaluationDispositionV1::EligibleForIndependentSelection)?;
    let directory = tempfile::tempdir()?;
    let mut owner = CellQ24ModelProposalOwnerV1::create(
        opened(directory.path(), "proposal")?,
        witness(directory.path())?,
        &mut fixture.trainer,
        fixture.dataset.clone(),
    )?;
    fixture.clock_owner(&mut owner);
    let saved = fs::read(directory.path().join("proposal"))?;
    let now = fixture.now;
    fixture.signature.signature[0] ^= 1;
    assert!(matches!(
        fixture.commit(&mut owner, now),
        Err(ProposalError::Evidence(_))
    ));
    fixture.signature.signature[0] ^= 1;
    assert_eq!(fs::read(directory.path().join("proposal"))?, saved);
    let original = fixture.evaluation.snapshot.clone();
    fixture
        .evaluation
        .snapshot
        .receipts
        .last_mut()
        .expect("Training")
        .evidence_digest = d("substituted-training");
    assert!(fixture.commit(&mut owner, now).is_err());
    fixture.evaluation.snapshot = original;
    assert_eq!(fs::read(directory.path().join("proposal"))?, saved);
    fixture.commit(&mut owner, now)?;
    fixture.signature.signature[0] ^= 1;
    assert!(fixture.read(&mut owner, now + 1).is_err());
    Ok(())
}

#[test]
fn q24_model_proposal_evaluation_no_update_never_creates_a_proposal() -> anyhow::Result<()> {
    for disposition in [
        IndependentEvaluationDispositionV1::Ineligible,
        IndependentEvaluationDispositionV1::InsufficientEvidence,
    ] {
        let mut fixture = ProposalFixture::new(disposition)?;
        let directory = tempfile::tempdir()?;
        let mut owner = CellQ24ModelProposalOwnerV1::create(
            opened(directory.path(), "proposal")?,
            witness(directory.path())?,
            &mut fixture.trainer,
            fixture.dataset.clone(),
        )?;
        fixture.clock_owner(&mut owner);
        let saved = fs::read(directory.path().join("proposal"))?;
        let now = fixture.now;
        assert!(matches!(
            fixture.commit(&mut owner, now),
            Err(ProposalError::Binding("NoUpdate has no model proposal"))
        ));
        assert_eq!(fs::read(directory.path().join("proposal"))?, saved);
    }
    Ok(())
}

#[test]
fn q24_model_proposal_pending_and_lost_ack_recover_without_new_commit() -> anyhow::Result<()> {
    for sequence in [2, 3] {
        for fault in [LostAck::BeforeWrite, LostAck::AfterWrite] {
            let mut fixture = ProposalFixture::new(
                IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
            )?;
            let directory = tempfile::tempdir()?;
            let mut owner = CellQ24ModelProposalOwnerV1::create(
                opened(directory.path(), "proposal")?,
                FaultWitness {
                    inner: witness(directory.path())?,
                    sequence,
                    fault,
                },
                &mut fixture.trainer,
                fixture.dataset.clone(),
            )?;
            fixture.clock_owner(&mut owner);
            let now = fixture.now;
            assert!(matches!(
                fixture.commit(&mut owner, now),
                Err(ProposalError::CommitUncertain)
            ));
            assert!(matches!(
                fixture.read(&mut owner, now),
                Err(ProposalError::CommitUncertain)
            ));
            let saved = fs::read(directory.path().join("proposal"))?;
            drop(owner);
            let mut recovered = CellQ24ModelProposalOwnerV1::recover(
                opened(directory.path(), "proposal")?,
                witness(directory.path())?,
                &mut fixture.trainer,
                fixture.dataset.clone(),
            )?;
            fixture.clock_owner(&mut recovered);
            fixture.clock.store(now + 1, Ordering::SeqCst);
            if sequence == 2 {
                assert!(matches!(
                    fixture.commit(&mut recovered, now),
                    Err(ProposalError::Pending)
                ));
                assert!(matches!(
                    fixture.read(&mut recovered, now),
                    Err(ProposalError::Pending)
                ));
            } else {
                let receipt = fixture.read(&mut recovered, now + 1)?;
                assert_eq!(receipt.learning_receipt().observed_unix_seconds, now);
                assert_eq!(fixture.commit(&mut recovered, now + 2)?, receipt);
            }
            assert_eq!(fs::read(directory.path().join("proposal"))?, saved);
        }
    }
    Ok(())
}

struct ReadFaultWitness {
    inner: FileAnchorWitnessStore,
    reads: Arc<AtomicU64>,
    refuse_at: Arc<AtomicU64>,
}

#[test]
fn q24_model_proposal_trainer_no_update_refuses_before_file_initialization() -> anyhow::Result<()> {
    let training_root = tempfile::tempdir()?;
    let proposal_root = tempfile::tempdir()?;
    let baseline = Arc::new(load(training_root.path(), /*factor*/ 1)?);
    let selected = bundle(&baseline, /*prior*/ None)?;
    let data = batch(Q)?;
    let rule = CellQ24SgdRuleV1 {
        epochs: 2,
        learning_rate_q24: Q / 2,
    };
    let (plan, dataset) = plan(
        baseline,
        &selected,
        &data,
        CellQ24PrivateHeadV1::Drive { index: 0 },
        rule,
        "none",
    )?;
    let mut trainer = CellQ24TrainingOwnerV1::create(
        opened(training_root.path(), "job")?,
        witness(training_root.path())?,
        plan,
        data,
        rule,
    )?;
    assert!(matches!(
        trainer.fit_or_readback(&AtomicBool::new(false))?,
        CellQ24TrainingOutcomeV1::NoUpdate { .. }
    ));
    assert!(matches!(
        CellQ24ModelProposalOwnerV1::create(
            opened(proposal_root.path(), "proposal")?,
            witness(proposal_root.path())?,
            &mut trainer,
            dataset,
        ),
        Err(ProposalError::Binding("NoUpdate has no model proposal"))
    ));
    assert_eq!(
        fs::metadata(proposal_root.path().join("proposal"))?.len(),
        0
    );
    Ok(())
}
impl AnchorWitnessStore for ReadFaultWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        let read = self.reads.fetch_add(1, Ordering::SeqCst) + 1;
        if read == self.refuse_at.load(Ordering::SeqCst) {
            return Ok(None);
        }
        self.inner.current()
    }
    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.inner.compare_and_swap(expected, next)
    }
}

#[test]
fn q24_model_proposal_rechecks_original_witness_after_final_receipt_decode() -> anyhow::Result<()> {
    let mut fixture =
        ProposalFixture::new(IndependentEvaluationDispositionV1::EligibleForIndependentSelection)?;
    let directory = tempfile::tempdir()?;
    let reads = Arc::new(AtomicU64::new(0));
    let refuse_at = Arc::new(AtomicU64::new(u64::MAX));
    let mut owner = CellQ24ModelProposalOwnerV1::create(
        opened(directory.path(), "proposal")?,
        ReadFaultWitness {
            inner: witness(directory.path())?,
            reads: Arc::clone(&reads),
            refuse_at: Arc::clone(&refuse_at),
        },
        &mut fixture.trainer,
        fixture.dataset.clone(),
    )?;
    fixture.clock_owner(&mut owner);
    let now = fixture.now;
    fixture.commit(&mut owner, now)?;
    let saved = fs::read(directory.path().join("proposal"))?;
    // Both admission checks read witness/physical/witness successfully. The
    // independent witness read after final receipt decoding must still fail.
    refuse_at.store(reads.load(Ordering::SeqCst) + 6, Ordering::SeqCst);
    assert!(matches!(
        fixture.read(&mut owner, now + 1),
        Err(ProposalError::CommitUncertain)
    ));
    // Restoring the witness cannot clear the owner's indeterminate fence.
    refuse_at.store(u64::MAX, Ordering::SeqCst);
    assert!(matches!(
        fixture.commit(&mut owner, now + 1),
        Err(ProposalError::CommitUncertain)
    ));
    assert_eq!(fs::read(directory.path().join("proposal"))?, saved);
    Ok(())
}

#[test]
fn q24_model_proposal_host_clock_rejects_request_backdating_and_expired_evidence()
-> anyhow::Result<()> {
    let mut fixture =
        ProposalFixture::new(IndependentEvaluationDispositionV1::EligibleForIndependentSelection)?;
    // Keep the original Training attestation valid longer than the signed
    // evaluation evidence, exercising both admission clock uses separately.
    fixture.signature.expires_at = fixture.now + 850;
    fixture.signature.signature = SigningKey::from_bytes(&[41; 32])
        .sign(&fixture.signature.signing_bytes())
        .to_bytes();
    let directory = tempfile::tempdir()?;
    let mut owner = CellQ24ModelProposalOwnerV1::create(
        opened(directory.path(), "proposal")?,
        witness(directory.path())?,
        &mut fixture.trainer,
        fixture.dataset.clone(),
    )?;
    fixture.clock_owner(&mut owner);
    let now = fixture.now;
    let stale_request = now - 60;
    let receipt = fixture.commit(&mut owner, stale_request)?;
    assert_eq!(receipt.learning_receipt().observed_unix_seconds, now);
    let saved = fs::read(directory.path().join("proposal"))?;
    fixture.clock.store(now + 301, Ordering::SeqCst);
    assert_eq!(fixture.read(&mut owner, stale_request)?, receipt);

    let expired_directory = tempfile::tempdir()?;
    let mut expired = CellQ24ModelProposalOwnerV1::create(
        opened(expired_directory.path(), "proposal")?,
        witness(expired_directory.path())?,
        &mut fixture.trainer,
        fixture.dataset.clone(),
    )?;
    fixture.clock_owner(&mut expired);
    let empty = fs::read(expired_directory.path().join("proposal"))?;
    assert!(matches!(
        fixture.commit(&mut expired, stale_request),
        Err(ProposalError::Binding("original proposal deadline"))
    ));
    assert_eq!(fs::read(expired_directory.path().join("proposal"))?, empty);

    fixture.clock.store(now + 601, Ordering::SeqCst);
    assert!(matches!(
        fixture.read(&mut owner, stale_request),
        Err(ProposalError::Evaluation(_))
    ));
    fixture.clock.store(now + 851, Ordering::SeqCst);
    assert!(matches!(
        fixture.commit(&mut owner, stale_request),
        Err(ProposalError::Evidence(_))
    ));
    assert_eq!(fs::read(directory.path().join("proposal"))?, saved);
    Ok(())
}
