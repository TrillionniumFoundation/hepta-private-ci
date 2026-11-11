//! Real Candidate, signed execution and Qualification publication mechanisms.
//! Product declarations, credentials and cohorts remain explicit fixtures;
//! empty retention evidence does not establish B or an old-capability panel.
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

use super::*;
use crate::OriginalCellEvaluationExecutionStoreErrorV1;
use crate::OriginalCellEvaluationQualificationConfigV1;
use crate::OriginalCellEvaluationQualificationErrorV1;
use crate::OriginalCellEvaluationQualificationOwnerV1;

type Owner = OriginalCellEvaluationQualificationOwnerV1<FileAnchorWitnessStore>;
type Error = OriginalCellEvaluationQualificationErrorV1;
type StoreError = ProductEvaluationExecutionStoreErrorV1;

fn namespace(
    original: &OriginalCellEvaluationQualificationConfigV1,
    name: &str,
) -> OriginalCellEvaluationQualificationConfigV1 {
    let mut config = original.clone();
    config.qualification_namespace = Digest32::of_bytes(name.as_bytes());
    config
}

#[derive(Clone, Copy)]
enum LostAck {
    BeforeWrite,
    AfterWrite,
}
struct FaultWitness {
    original: FileAnchorWitnessStore,
    sequence: u64,
    fault: LostAck,
}
impl AnchorWitnessStore for FaultWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.original.current()
    }
    fn compare_and_swap(
        &mut self,
        before: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        if next.sequence == self.sequence {
            if matches!(self.fault, LostAck::AfterWrite) {
                self.original.compare_and_swap(before, next)?;
            }
            return Err(WitnessStoreError::Indeterminate);
        }
        self.original.compare_and_swap(before, next)
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_qualification_publishes_and_recovers_exact_completed_decision()
-> anyhow::Result<()> {
    let mut f = PositiveFixture::ready().await?;
    let before = f.predecessor_bytes()?;
    let original = f.evaluation.qualification.clone();
    let config = f.evaluation.qualification_configuration();
    let original_execution_signature = f.evaluation.original_signature()?;
    let (trainer, thread) = f.evaluation.qualification_peer(config.training_evidence.clone())?;
    assert_eq!(f.evaluation.read_original_qualification(&trainer).await?, original);
    f.evaluation.recover_original_qualification()?;
    assert_eq!(f.evaluation.read_original_qualification(&trainer).await?, original);
    assert_eq!(original.authority(), AuthorityPosture::DENY_ALL);
    assert_eq!(original.product().authority, AuthorityPosture::DENY_ALL);
    assert_eq!(original.product().decision.decision.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(f.evaluation.original_signature()?, original_execution_signature);
    assert_eq!(f.predecessor_bytes()?, before);
    assert_eq!(f.evaluation.qualification_provider_counts(), (1, 1));
    drop(trainer);
    assert_eq!(thread.join().expect("original Qualification Trainer")?, 4);
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_qualification_missing_and_pending_never_publish_during_recovery()
-> anyhow::Result<()> {
    let mut f = PositiveFixture::ready().await?;
    let original = f.evaluation.qualification_configuration();
    let config = namespace(&original, "qualification-empty");
    let (raw, witness) = f.evaluation.qualification_files("qualification-empty", true)?;
    let mut owner = Owner::create(raw, witness, config.clone())?;
    let empty = f.evaluation.qualification_bytes("qualification-empty")?;
    let (trainer, thread) = f.evaluation.qualification_peer(original.training_evidence.clone())?;
    assert!(matches!(
        f.evaluation.read_qualification(&mut owner, &trainer).await,
        Err(Error::Store(StoreError::Missing))
    ));
    drop(owner);
    let (raw, witness) = f.evaluation.qualification_files("qualification-empty", false)?;
    let mut recovered = Owner::recover(raw, witness, config)?;
    assert!(matches!(
        f.evaluation.publish_qualification(&mut recovered, &trainer).await,
        Err(Error::Store(StoreError::Missing))
    ));
    assert!(matches!(
        f.evaluation.read_qualification(&mut recovered, &trainer).await,
        Err(Error::Store(StoreError::Missing))
    ));
    assert_eq!(f.evaluation.qualification_bytes("qualification-empty")?, empty);
    drop(recovered);
    drop(trainer);
    assert_eq!(thread.join().expect("unused original Trainer")?, 0);

    for (name, fault) in [
        ("qualification-claim-before-ack", LostAck::BeforeWrite),
        ("qualification-claim-after-ack", LostAck::AfterWrite),
    ] {
        let config = namespace(&original, name);
        let (raw, witness) = f.evaluation.qualification_files(name, true)?;
        let mut owner = OriginalCellEvaluationQualificationOwnerV1::create(
            raw, FaultWitness { original: witness, sequence: 2, fault }, config.clone(),
        )?;
        let before = f.evaluation.qualification_bytes(name)?;
        let (trainer, thread) = f.evaluation.qualification_peer(original.training_evidence.clone())?;
        assert!(matches!(
            f.evaluation.publish_qualification(&mut owner, &trainer).await,
            Err(Error::Store(StoreError::Indeterminate))
        ));
        let uncertain = f.evaluation.qualification_bytes(name)?;
        assert_ne!(uncertain[0], before[0]);
        assert!(matches!(
            f.evaluation.publish_qualification(&mut owner, &trainer).await,
            Err(Error::CommitUncertain)
        ));
        assert!(matches!(
            f.evaluation.read_qualification(&mut owner, &trainer).await,
            Err(Error::CommitUncertain)
        ));
        drop(owner);
        let (raw, witness) = f.evaluation.qualification_files(name, false)?;
        match fault {
            LostAck::BeforeWrite => {
                assert_eq!(uncertain[1], before[1]);
                assert!(matches!(
                    Owner::recover(raw, witness, config),
                    Err(Error::Owner(OriginalCellEvaluationExecutionStoreErrorV1::CommitUncertain))
                ));
            }
            LostAck::AfterWrite => {
                assert_ne!(uncertain[1], before[1]);
                let mut recovered = Owner::recover(raw, witness, config)?;
                assert!(matches!(
                    f.evaluation.read_qualification(&mut recovered, &trainer).await,
                    Err(Error::Pending)
                ));
                assert!(matches!(
                    f.evaluation.publish_qualification(&mut recovered, &trainer).await,
                    Err(Error::Pending)
                ));
            }
        }
        assert_eq!(f.evaluation.qualification_bytes(name)?, uncertain);
        drop(trainer);
        assert_eq!(thread.join().expect("original Trainer before claim")?, 1);
    }
    assert_eq!(f.evaluation.qualification_provider_counts(), (1, 1));
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_qualification_lost_completion_ack_preserves_uncertainty_and_exact_recovery()
-> anyhow::Result<()> {
    let mut f = PositiveFixture::ready().await?;
    let original = f.evaluation.qualification_configuration();
    for (name, fault) in [
        ("qualification-complete-before-ack", LostAck::BeforeWrite),
        ("qualification-complete-after-ack", LostAck::AfterWrite),
    ] {
        let config = namespace(&original, name);
        let (raw, witness) = f.evaluation.qualification_files(name, true)?;
        let mut owner = OriginalCellEvaluationQualificationOwnerV1::create(
            raw, FaultWitness { original: witness, sequence: 3, fault }, config.clone(),
        )?;
        let before = f.evaluation.qualification_bytes(name)?;
        let (trainer, thread) = f.evaluation.qualification_peer(original.training_evidence.clone())?;
        assert!(matches!(
            f.evaluation.publish_qualification(&mut owner, &trainer).await,
            Err(Error::Store(StoreError::Indeterminate))
        ));
        let uncertain = f.evaluation.qualification_bytes(name)?;
        assert_ne!(uncertain[0], before[0]);
        assert!(matches!(
            f.evaluation.publish_qualification(&mut owner, &trainer).await,
            Err(Error::CommitUncertain)
        ));
        assert!(matches!(
            f.evaluation.read_qualification(&mut owner, &trainer).await,
            Err(Error::CommitUncertain)
        ));
        drop(owner);
        let (raw, witness) = f.evaluation.qualification_files(name, false)?;
        let expected_reads = match fault {
            LostAck::BeforeWrite => {
                assert!(matches!(
                    Owner::recover(raw, witness, config),
                    Err(Error::Owner(OriginalCellEvaluationExecutionStoreErrorV1::CommitUncertain))
                ));
                1
            }
            LostAck::AfterWrite => {
                let mut recovered = Owner::recover(raw, witness, config)?;
                let retained = f.evaluation.read_qualification(&mut recovered, &trainer).await?;
                assert_eq!(
                    retained.product().decision,
                    f.evaluation.qualification.product().decision
                );
                assert_eq!(retained.authority(), AuthorityPosture::DENY_ALL);
                assert_eq!(
                    f.evaluation.publish_qualification(&mut recovered, &trainer).await?,
                    retained
                );
                5
            }
        };
        assert_eq!(f.evaluation.qualification_bytes(name)?, uncertain);
        drop(trainer);
        assert_eq!(thread.join().expect("original Trainer during uncertain completion")?, expected_reads);
    }
    assert_eq!(f.evaluation.qualification_provider_counts(), (1, 1));
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_qualification_rejects_context_and_valid_signature_renewal()
-> anyhow::Result<()> {
    let mut f = PositiveFixture::ready().await?;
    let original = f.evaluation.qualification_configuration();
    let renewed_training = f.evaluation.renewed_qualification_training()?;
    let mut replacements = Vec::new();
    let mut training = original.clone();
    training.training_evidence = renewed_training.clone();
    replacements.push(training);
    for generator in [true, false] {
        let mut product = original.clone();
        product.product_evidence = f.evaluation.renewed_qualification_product(generator)?;
        replacements.push(product);
    }
    let mut context = original.clone();
    context.context.unlearning_receipt_digest = Digest32::of_bytes(b"another-original-context");
    replacements.push(context);
    replacements.push(namespace(&original, "another-qualification-namespace"));
    f.evaluation.drop_original_qualification();
    let before = f.evaluation.qualification_bytes("positive-qualification")?;
    for config in replacements {
        let (raw, witness) = f.evaluation.qualification_files("positive-qualification", false)?;
        assert!(Owner::recover(raw, witness, config).is_err());
        assert_eq!(f.evaluation.qualification_bytes("positive-qualification")?, before);
    }

    let config = namespace(&original, "qualification-live-original-signature");
    let (raw, witness) = f.evaluation.qualification_files("qualification-live-original-signature", true)?;
    let mut owner = Owner::create(raw, witness, config)?;
    let empty = f.evaluation.qualification_bytes("qualification-live-original-signature")?;
    let (trainer, thread) = f.evaluation.qualification_peer(renewed_training)?;
    assert!(matches!(
        f.evaluation.publish_qualification(&mut owner, &trainer).await,
        Err(Error::Binding("changed original Qualification Training signature"))
    ));
    assert_eq!(f.evaluation.qualification_bytes("qualification-live-original-signature")?, empty);
    assert!(matches!(
        f.evaluation.publish_qualification(&mut owner, &trainer).await,
        Err(Error::CommitUncertain)
    ));
    drop(owner);
    drop(trainer);
    assert_eq!(thread.join().expect("valid renewed Trainer negative")?, 1);

    f.evaluation.recover_original_qualification()?;
    let (trainer, thread) = f.evaluation.qualification_peer(original.training_evidence)?;
    assert_eq!(
        f.evaluation.read_original_qualification(&trainer).await?,
        f.evaluation.qualification
    );
    assert_eq!(f.evaluation.qualification_bytes("positive-qualification")?, before);
    drop(trainer);
    assert_eq!(thread.join().expect("retained original Trainer")?, 2);
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_qualification_current_corruption_stays_fenced_after_restore()
-> anyhow::Result<()> {
    let mut f = PositiveFixture::ready().await?;
    let before = f.predecessor_bytes()?;
    let original = f.evaluation.qualification_bytes("positive-qualification")?;
    let mut changed = original[0].clone();
    changed[0] ^= 1;
    f.evaluation.qualification_overwrite("positive-qualification", &changed)?;
    let config = f.evaluation.qualification_configuration();
    let (trainer, thread) = f.evaluation.qualification_peer(config.training_evidence)?;
    assert!(matches!(
        f.evaluation.read_original_qualification(&trainer).await,
        Err(Error::Store(StoreError::Indeterminate))
    ));
    f.evaluation.qualification_overwrite("positive-qualification", &original[0])?;
    assert!(matches!(
        f.evaluation.read_original_qualification(&trainer).await,
        Err(Error::CommitUncertain)
    ));
    f.evaluation.recover_original_qualification()?;
    assert_eq!(
        f.evaluation.read_original_qualification(&trainer).await?,
        f.evaluation.qualification
    );
    assert_eq!(f.predecessor_bytes()?, before);
    drop(trainer);
    assert_eq!(thread.join().expect("only cold exact original readback")?, 2);
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_qualification_requires_physical_execution_and_holdout_before_claim()
-> anyhow::Result<()> {
    for predecessor in ["positive-executions", "holdout"] {
        let mut f = PositiveFixture::ready().await?;
        let config = namespace(
            &f.evaluation.qualification_configuration(), "qualification-invalid-predecessor",
        );
        let (raw, witness) = f.evaluation.qualification_files("qualification-invalid-predecessor", true)?;
        let mut owner = Owner::create(raw, witness, config.clone())?;
        let empty = f.evaluation.qualification_bytes("qualification-invalid-predecessor")?;
        let original = f.evaluation.qualification_original_file(predecessor)?;
        let mut changed = original.clone();
        changed[0] ^= 1;
        f.evaluation.qualification_overwrite(predecessor, &changed)?;
        let (trainer, thread) = f.evaluation.qualification_peer(config.training_evidence)?;
        assert!(matches!(
            f.evaluation.publish_qualification(&mut owner, &trainer).await,
            Err(Error::Cell(_))
        ));
        assert_eq!(f.evaluation.qualification_bytes("qualification-invalid-predecessor")?, empty);
        f.evaluation.qualification_overwrite(predecessor, &original)?;
        assert!(matches!(
            f.evaluation.publish_qualification(&mut owner, &trainer).await,
            Err(Error::CommitUncertain)
        ));
        assert!(matches!(
            f.evaluation.read_original_qualification(&trainer).await,
            Err(Error::Cell(_))
        ));
        assert_eq!(f.evaluation.qualification_original_file(predecessor)?, original);
        assert_eq!(f.evaluation.qualification_bytes("qualification-invalid-predecessor")?, empty);
        assert_eq!(f.evaluation.qualification_provider_counts(), (1, 1));
        drop(owner);
        drop(trainer);
        assert_eq!(thread.join().expect("no Trainer read after physical rejection")?, 0);
        f.finish().await?;
    }
    Ok(())
}
