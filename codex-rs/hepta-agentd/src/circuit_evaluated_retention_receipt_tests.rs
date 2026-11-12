//! Actual same-A Candidate/B/publication and original Selector custody.
//! Role enrollment, measurement and transport remain explicit fixtures. These
//! cases confer no ordinary-loop, independent operator or daemon qualification.

use super::*;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use crate::OriginalCircuitEvaluatedSelectionReceiptConfigV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptSourcesV1;
use crate::OriginalCircuitSelectionReceiptConfigV1;
use crate::OriginalCircuitSelectionReceiptErrorV1 as SelectionError;
use crate::OriginalCircuitSelectionReceiptOwnerV1;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1 as OwnerError;

type Selector = OriginalCircuitSelectionReceiptOwnerV1<FileAnchorWitnessStore>;

enum OpenReceipt {
    Fresh,
    Readback,
}

struct SelectorFiles(tempfile::TempDir);

impl SelectorFiles {
    fn new() -> anyhow::Result<Self> {
        Ok(Self(tempfile::tempdir()?))
    }

    fn files(
        &self,
        f: &PublicationFixture,
        mode: &OpenReceipt,
    ) -> anyhow::Result<(File, FileAnchorWitnessStore)> {
        use std::os::unix::fs::OpenOptionsExt as _;
        let open = |name| -> anyhow::Result<File> {
            let mut options = OpenOptions::new();
            options.read(true).write(true).mode(0o600);
            if matches!(mode, OpenReceipt::Fresh) {
                options.create_new(true);
            }
            Ok(options.open(self.0.path().join(name))?)
        };
        let journal = open("journal")?;
        let witness = FileAnchorWitnessStore::open(
            open("witness")?,
            JournalScope {
                scope_digest: f.host.config.scope.binding(),
                objective_digest: f.host.config.signing.verifier.objective_digest(),
            },
            Generation::new(/*value*/ 1)?,
            /*max_records*/ 16,
        )?;
        Ok((journal, witness))
    }

    fn owner(&self, f: &PublicationFixture, mode: OpenReceipt) -> anyhow::Result<Selector> {
        let (journal, witness) = self.files(f, &mode)?;
        let config = OriginalCircuitEvaluatedSelectionReceiptConfigV1 {
            // Deliberately supply Fresh even to recovery. The owner must
            // attenuate its output pins before a later C can consume them.
            context: f.context()?,
            signer: f.host.original.credentials.selector.clone(),
            maximum_signature_lifetime_seconds: 300,
        };
        let key = ed25519_dalek::SigningKey::from_bytes(&[46; 32]);
        Ok(match mode {
            OpenReceipt::Fresh => Selector::create_evaluated(journal, witness, config, key)?,
            OpenReceipt::Readback => Selector::recover_evaluated(journal, witness, config, key)?,
        })
    }

    fn bytes(&self) -> anyhow::Result<[Vec<u8>; 2]> {
        Ok([
            std::fs::read(self.0.path().join("journal"))?,
            std::fs::read(self.0.path().join("witness"))?,
        ])
    }
}

async fn published(
    f: &mut PublicationFixture,
) -> anyhow::Result<(
    support::Session,
    OriginalCellQ24TrainingCommandClientV1,
    OriginalCellEvaluationCommandClientV1,
    Peers,
)> {
    let (trainer, evaluator, peers) = f.clients()?;
    let prepared = crate::prepare_original_circuit_evaluated_retention_v1(
        f.context()?,
        trainer,
        evaluator,
        f.inputs()?,
    )
    .await?;
    let grant = f.host.original.version.sign(prepared.final_use_binding())?;
    let (task, trainer, evaluator) = prepared.publish_and_retain_original_evidence(grant).await?;
    // These are the same original sessions retained by the real publication.
    // No post-publication connection or fixture replacement is constructed.
    let c = f.start_c(task).await?;
    Ok((c, trainer, evaluator, peers))
}

fn sources<'a>(
    snapshot: &'a LearningIterationSnapshotV1,
    c: &'a support::Session,
    trainer: &'a OriginalCellQ24TrainingCommandClientV1,
    evaluator: &'a OriginalCellEvaluationCommandClientV1,
) -> OriginalCircuitEvaluatedSelectionReceiptSourcesV1<'a, FileAnchorWitnessStore> {
    OriginalCircuitEvaluatedSelectionReceiptSourcesV1 {
        snapshot,
        cell: &c.cell,
        trainer,
        evaluator,
    }
}

fn assert_legacy_observer_rejects_evaluated_selection(
    f: &PublicationFixture,
    selected: &crate::OriginalCircuitEvaluatedSelectionReceiptV1,
) -> anyhow::Result<()> {
    let config = crate::OriginalCircuitNextUseReceiptConfigV1 {
        selection: selected.snapshot().clone(),
        scope: f.host.config.scope.clone(),
        signer: f.host.original.credentials.observer.clone(),
        verifier: f.host.config.signing.verifier.clone(),
        training_evidence: f.training.attestation().clone(),
        selection_evidence: selected.attestation().clone(),
        maximum_signature_lifetime_seconds: 300,
    };
    // This actor and key were enrolled before A's original material was signed.
    // The exact signed S is valid; an unrelated custody refusal cannot pass.
    let key = ed25519_dalek::SigningKey::from_bytes(&[43; 32]);
    assert_eq!(
        config.signer.principal.principal_id,
        config.selection.owners.next_use_observer
    );
    assert_eq!(config.signer.verifying_key, key.verifying_key().to_bytes());
    config.verifier.require_signer_binding(
        codex_hepta_learning_ledger::LearningEvidenceRoleV1::Observer,
        &config.signer,
        now()?,
    )?;
    config.verifier.verify(
        codex_hepta_learning_ledger::LearningEvidenceRoleV1::Selector,
        selected.attestation(),
        &codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1(
            selected.receipt(),
        )?,
        now()?,
    )?;
    for mode in [OpenReceipt::Fresh, OpenReceipt::Readback] {
        let files = SelectorFiles::new()?;
        let (journal, witness) = files.files(f, &OpenReceipt::Fresh)?;
        let untouched = files.bytes()?;
        let result = match mode {
            OpenReceipt::Fresh => crate::OriginalCircuitNextUseReceiptOwnerV1::create(
                journal,
                witness,
                config.clone(),
                key.clone(),
            ),
            OpenReceipt::Readback => crate::OriginalCircuitNextUseReceiptOwnerV1::recover(
                journal,
                witness,
                config.clone(),
                key.clone(),
            ),
        };
        assert!(matches!(
            result,
            Err(crate::OriginalCircuitNextUseReceiptErrorV1::Owner(
                OwnerError::Binding("evaluated retention requires original T/B/S readbacks")
            ))
        ));
        assert_eq!(files.bytes()?, untouched);
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_selector_uses_actual_publication_and_recovers_original_five_cut()
-> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (mut c, trainer, evaluator, peers) = Box::pin(published(&mut f)).await?;
    let files = SelectorFiles::new()?;
    let mut selector = files.owner(&f, OpenReceipt::Fresh)?;
    let before = files.bytes()?;
    let publication = f.publication_bytes()?;
    let upstream = (
        f.host.original.predecessor_bytes()?,
        f.host.upstream_files()?,
        f.host.original_files()?,
    );
    let selected = selector
        .attest_original_evaluated_selection(sources(
            f.evaluation.snapshot(),
            &c,
            &trainer,
            &evaluator,
        ))
        .await?;
    assert_ne!(files.bytes()?, before);
    assert_eq!(
        &selected.snapshot().receipts[..4],
        &f.evaluation.snapshot().receipts
    );
    assert_eq!(selected.snapshot().receipts.len(), 5);
    assert!(selected.snapshot().training_no_update_v2().is_none());
    assert_legacy_observer_rejects_evaluated_selection(&f, &selected)?;
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(selected.snapshot().clone())?;
    assert_eq!(
        coordinator.next_stage(),
        Some(LearningIterationStageV1::NextUse)
    );
    assert_eq!(coordinator.next_task_bundle(), Some(&f.bundle));
    assert_eq!(
        c.cell
            .read_learning_selection(&LearningIterationCoordinatorV1::from_snapshot(
                f.evaluation.snapshot().clone()
            )?)?,
        selected.receipt().observation
    );
    assert_eq!(c.cell.snapshot(&f.source_c.scope)?.revision, 0);
    let completed = files.bytes()?;
    let read = selector
        .readback_evaluated_selection(sources(selected.snapshot(), &c, &trainer, &evaluator))
        .await?;
    assert_eq!(
        (read.snapshot(), read.receipt(), read.attestation()),
        (
            selected.snapshot(),
            selected.receipt(),
            selected.attestation()
        )
    );
    drop(selector);
    let mut recovered = files.owner(&f, OpenReceipt::Readback)?;
    // Calling the attest-shaped entry on a recovered owner remains read-only.
    let read = recovered
        .attest_original_evaluated_selection(sources(selected.snapshot(), &c, &trainer, &evaluator))
        .await?;
    assert_eq!(
        (read.snapshot(), read.receipt(), read.attestation()),
        (
            selected.snapshot(),
            selected.receipt(),
            selected.attestation()
        )
    );
    assert!(matches!(
        read.original_context().require_new_original_receipt(now()?),
        Err(crate::OriginalCircuitRetainedPublicationErrorV1::Binding(
            "recovered evaluated retention is read-only"
        ))
    ));
    assert_eq!(files.bytes()?, completed);
    assert_eq!(f.publication_bytes()?, publication);
    assert_eq!(
        (
            f.host.original.predecessor_bytes()?,
            f.host.upstream_files()?,
            f.host.original_files()?
        ),
        upstream
    );
    drop(recovered);
    drop(trainer);
    drop(evaluator);
    assert_eq!(peers.finish()?, [10, 10]);
    c.stop().await?;
    drop(c);
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_selector_cold_missing_cannot_claim_and_legacy_profile_stays_closed()
-> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let (mut c, trainer, evaluator, peers) = Box::pin(published(&mut f)).await?;
    let files = SelectorFiles::new()?;
    drop(files.owner(&f, OpenReceipt::Fresh)?);
    let untouched = files.bytes()?;
    let mut recovered = files.owner(&f, OpenReceipt::Readback)?;
    assert!(matches!(
        recovered
            .attest_original_evaluated_selection(sources(
                f.evaluation.snapshot(),
                &c,
                &trainer,
                &evaluator
            ))
            .await,
        Err(SelectionError::Owner(OwnerError::Store(
            ProductEvaluationExecutionStoreErrorV1::Missing
        )))
    ));
    assert_eq!(files.bytes()?, untouched);

    let legacy = SelectorFiles::new()?;
    let (journal, witness) = legacy.files(&f, &OpenReceipt::Fresh)?;
    assert!(matches!(
        Selector::create(
            journal,
            witness,
            OriginalCircuitSelectionReceiptConfigV1 {
                decision: f.evaluation.snapshot().clone(),
                scope: f.host.config.scope.clone(),
                signer: f.host.original.credentials.selector.clone(),
                verifier: f.host.config.signing.verifier.clone(),
                training_evidence: f.training.attestation().clone(),
                maximum_signature_lifetime_seconds: 300,
            },
            ed25519_dalek::SigningKey::from_bytes(&[46; 32])
        ),
        Err(SelectionError::Owner(OwnerError::Binding(
            "only original TrainingNoUpdate selection is supported"
        )))
    ));

    let cold = SelectorFiles::new()?;
    let (journal, witness) = cold.files(&f, &OpenReceipt::Fresh)?;
    assert!(matches!(
        Selector::create_evaluated(
            journal,
            witness,
            OriginalCircuitEvaluatedSelectionReceiptConfigV1 {
                context: f.readback_context()?,
                signer: f.host.original.credentials.selector.clone(),
                maximum_signature_lifetime_seconds: 300,
            },
            ed25519_dalek::SigningKey::from_bytes(&[46; 32])
        ),
        Err(SelectionError::Evaluated(
            crate::OriginalCircuitRetainedPublicationErrorV1::Binding(
                "recovered evaluated retention is read-only"
            )
        ))
    ));
    drop(recovered);
    drop(trainer);
    drop(evaluator);
    assert_eq!(peers.finish()?, [5, 5]);
    c.stop().await?;
    drop(c);
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_selector_refuses_either_original_owner_after_signed_completion()
-> anyhow::Result<()> {
    for owner in ["trainer", "evaluator"] {
        let mut f = Box::pin(PublicationFixture::ready()).await?;
        let (mut c, trainer, evaluator, peers) = Box::pin(published(&mut f)).await?;
        let files = SelectorFiles::new()?;
        let mut selector = files.owner(&f, OpenReceipt::Fresh)?;
        let selected = selector
            .attest_original_evaluated_selection(sources(
                f.evaluation.snapshot(),
                &c,
                &trainer,
                &evaluator,
            ))
            .await?;
        let completed = files.bytes()?;
        let publication = f.publication_bytes()?;
        match owner {
            "trainer" => f.host.original.withdraw_original_dataset()?,
            "evaluator" => f.host.retention_b.withdraw_target()?,
            _ => unreachable!(),
        }
        let read = selector
            .readback_evaluated_selection(sources(selected.snapshot(), &c, &trainer, &evaluator))
            .await;
        match owner {
            "trainer" => assert!(matches!(
                read,
                Err(SelectionError::Evaluated(
                    crate::OriginalCircuitRetainedPublicationErrorV1::Training(
                        crate::OriginalCellQ24TrainingCommandErrorV1::CommitUncertain
                    )
                ))
            )),
            "evaluator" => assert!(matches!(
                read,
                Err(SelectionError::Evaluated(
                    crate::OriginalCircuitRetainedPublicationErrorV1::Evaluation(
                        crate::OriginalCellEvaluationCommandErrorV1::CommitUncertain
                    )
                ))
            )),
            _ => unreachable!(),
        }
        assert_eq!(files.bytes()?, completed);
        assert_eq!(f.publication_bytes()?, publication);
        assert_eq!(c.cell.snapshot(&f.source_c.scope)?.revision, 0);
        drop(selector);
        drop(trainer);
        drop(evaluator);
        assert_eq!(
            peers.finish()?,
            if owner == "trainer" { [7, 6] } else { [7, 7] }
        );
        c.stop().await?;
        drop(c);
        f.finish().await?;
    }
    Ok(())
}

#[path = "circuit_evaluated_next_use_receipt_tests.rs"]
mod next_use_tests;
