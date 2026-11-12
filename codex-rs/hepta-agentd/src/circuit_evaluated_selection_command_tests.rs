//! Actual same-A Candidate/B publication and evaluated S command owners.
//! Enrollment and same-process transports are explicit fixtures. These cases
//! establish command mechanisms, not ordinary or daemon/Root qualification.

use super::super::version_material;
use super::*;
use crate::OriginalCircuitEvaluatedLearningReadContextV1 as ReadContext;
use crate::OriginalCircuitEvaluatedSelectionCommandErrorV1 as CommandError;
use crate::OriginalCircuitEvaluatedSelectionCommandOwnerV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;
use crate::OriginalCircuitLearningReadErrorV1 as ReadError;
use crate::OriginalCircuitLearningReadOwnerV1;
use crate::circuit_feature_current::original_learning_read_fixture as reads;
use crate::learning_iteration_evidence_client::evaluated_selection_command_test_support as commands;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;
use std::sync::Arc;

type CommandOwner = OriginalCircuitEvaluatedSelectionCommandOwnerV1<FileAnchorWitnessStore>;
type ReadOwner = OriginalCircuitLearningReadOwnerV1<FileAnchorWitnessStore, FileAnchorWitnessStore>;

#[path = "circuit_evaluated_next_use_command_tests.rs"]
mod next_use_command_tests;

struct ActualCommand {
    f: PublicationFixture,
    c: support::Session,
    trainer: Arc<OriginalCellQ24TrainingCommandClientV1>,
    evaluator: Arc<OriginalCellEvaluationCommandClientV1>,
    peers: Peers,
    files: SelectorFiles,
    task_host: Arc<ReadOwner>,
    task_peer: std::thread::JoinHandle<Result<u64, ReadError>>,
    host: Arc<CommandOwner>,
}

impl ActualCommand {
    async fn ready(mode: OpenReceipt) -> anyhow::Result<Self> {
        let mut f = Box::pin(PublicationFixture::ready()).await?;
        let (c, trainer, evaluator, peers) = Box::pin(published(&mut f)).await?;
        let trainer = Arc::new(trainer);
        let evaluator = Arc::new(evaluator);
        let context = ReadContext::for_original_selection(f.context()?)?;
        let task_host = Arc::new(ReadOwner::from_original_evaluated_owners(
            c.cell.clone(),
            c.source.as_ref().clone(),
            c.runtime.identity.clone(),
            context.clone(),
        )?);
        let (live, task_channel) = reads::evaluated_client(context)?;
        let task_peer = reads::serve(Arc::clone(&task_host), task_channel);
        let files = SelectorFiles::new()?;
        let fresh = files.owner(&f, OpenReceipt::Fresh)?;
        let owner = match mode {
            OpenReceipt::Fresh => fresh,
            OpenReceipt::Readback => {
                drop(fresh);
                files.owner(&f, OpenReceipt::Readback)?
            }
        };
        let host = Arc::new(owner.into_evaluated_command_owner(
            live,
            Arc::clone(&trainer),
            Arc::clone(&evaluator),
        )?);
        Ok(Self {
            f,
            c,
            trainer,
            evaluator,
            peers,
            files,
            task_host,
            task_peer,
            host,
        })
    }

    async fn finish(self, counts: [u64; 2], task_reads: u64) -> anyhow::Result<()> {
        let Self {
            f,
            mut c,
            trainer,
            evaluator,
            peers,
            files,
            task_host,
            task_peer,
            host,
        } = self;
        drop(host);
        assert_eq!(
            task_peer.join().expect("same actual evaluated task peer")?,
            task_reads
        );
        drop(task_host);
        drop(trainer);
        drop(evaluator);
        assert_eq!(peers.finish()?, counts);
        drop(files);
        c.stop().await?;
        drop(c);
        f.finish().await
    }

    fn recover_original_owner(self) -> anyhow::Result<Self> {
        let Self {
            f,
            c,
            trainer,
            evaluator,
            peers,
            files,
            task_host,
            task_peer,
            host,
        } = self;
        let live = commands::release_original_task_peer(host)?;
        let owner = files.owner(&f, OpenReceipt::Readback)?;
        let host = Arc::new(owner.into_evaluated_command_owner(
            live,
            Arc::clone(&trainer),
            Arc::clone(&evaluator),
        )?);
        Ok(Self {
            f,
            c,
            trainer,
            evaluator,
            peers,
            files,
            task_host,
            task_peer,
            host,
        })
    }
}

fn exact_selection(
    left: &OriginalCircuitEvaluatedSelectionReceiptV1,
    right: &OriginalCircuitEvaluatedSelectionReceiptV1,
) {
    assert_eq!(
        (
            left.snapshot(),
            left.receipt(),
            left.attestation(),
            left.original_receipt_binding()
        ),
        (
            right.snapshot(),
            right.receipt(),
            right.attestation(),
            right.original_receipt_binding()
        )
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_selection_command_once_reads_originals_and_readonly_evidence()
-> anyhow::Result<()> {
    let actual = Box::pin(ActualCommand::ready(OpenReceipt::Fresh)).await?;
    let empty = actual.files.bytes()?;
    let publication = actual.f.publication_bytes()?;
    let upstream = (
        actual.f.host.original.predecessor_bytes()?,
        actual.f.host.upstream_files()?,
    );
    commands::reject_wrong_context(&actual.host)?;
    commands::refuse_evidence_without_pin(&actual.host)?;
    commands::cancel_queued_execute(Arc::clone(&actual.host)).await?;
    assert_eq!(actual.files.bytes()?, empty);
    let original_dataset = Box::pin(version_material::original_dataset(&actual.f)).await?;
    let (client, channel) = commands::stage_client(
        &original_dataset.config,
        &original_dataset.receipt,
        &actual.f.training,
        &actual.f.evaluation,
        false,
    )?;
    drop(original_dataset.readback);
    assert_eq!(
        original_dataset
            .peer
            .join()
            .expect("same actual Dataset command peer")?,
        1
    );
    let peer = commands::serve(Arc::clone(&actual.host), channel);
    assert!(matches!(
        client.readback().await,
        Err(CommandError::Missing)
    ));
    assert_eq!(actual.files.bytes()?, empty);
    let selected = client.execute_selection().await?;
    assert_ne!(actual.files.bytes()?, empty);
    assert_eq!(
        &selected.snapshot().receipts[..4],
        &actual.f.evaluation.snapshot().receipts
    );
    assert_eq!(selected.snapshot().receipts.len(), 5);
    assert!(selected.snapshot().training_no_update_v2().is_none());
    assert_eq!(
        LearningIterationCoordinatorV1::from_snapshot(selected.snapshot().clone())?
            .next_task_bundle(),
        Some(&actual.f.bundle)
    );
    selected
        .original_context()
        .require_new_original_receipt(now()?)?;
    assert_legacy_observer_rejects_evaluated_selection(&actual.f, &selected)?;
    let completed = actual.files.bytes()?;
    assert!(matches!(
        client.execute_selection().await,
        Err(CommandError::ReadbackRequired)
    ));
    exact_selection(&client.readback().await?, &selected);
    let (evidence, channel) = commands::evidence_client(&actual.host)?;
    let evidence_peer = commands::serve_evidence(Arc::clone(&actual.host), channel);
    assert_eq!(
        evidence
            .readback(selected.snapshot(), selected.receipt())
            .await?,
        *selected.attestation()
    );
    assert_eq!(actual.files.bytes()?, completed);
    assert_eq!(actual.f.publication_bytes()?, publication);
    assert_eq!(
        (
            actual.f.host.original.predecessor_bytes()?,
            actual.f.host.upstream_files()?
        ),
        upstream
    );
    assert_eq!(
        actual.c.cell.snapshot(&actual.f.source_c.scope)?.revision,
        0
    );
    drop(evidence);
    assert_eq!(
        evidence_peer
            .join()
            .expect("same readonly S evidence peer")?,
        1
    );
    drop(client);
    assert_eq!(peer.join().expect("same S command peer")?, 3);
    actual.finish([11, 11], 8).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_selection_command_lost_ack_recovers_only_exact_readback() -> anyhow::Result<()> {
    let actual = Box::pin(ActualCommand::ready(OpenReceipt::Fresh)).await?;
    let original_dataset = Box::pin(version_material::original_dataset(&actual.f)).await?;
    drop(original_dataset.readback);
    assert_eq!(
        original_dataset
            .peer
            .join()
            .expect("same original recovery Dataset")?,
        1
    );
    let publication = actual.f.publication_bytes()?;
    let empty = actual.files.bytes()?;
    let (client, channel) = commands::client(actual.f.context()?, false, None)?;
    let peer = commands::lose_ack(Arc::clone(&actual.host), channel);
    assert!(matches!(
        client.execute_selection().await,
        Err(CommandError::CommitUncertain)
    ));
    assert!(matches!(
        client.execute_selection().await,
        Err(CommandError::Unavailable)
    ));
    assert!(matches!(
        client.readback().await,
        Err(CommandError::Unavailable)
    ));
    drop(client);
    let original = peer.join().expect("actual S result before lost ACK")?;
    let completed = actual.files.bytes()?;
    assert_ne!(completed, empty);
    let actual = actual.recover_original_owner()?;
    commands::refuse_evidence_without_pin(&actual.host)?;
    // A fresh T/B context and client cannot promote a recovered host's S.
    // Only this client's own successful Execute ACK could retain Fresh.
    let (fresh_reader, channel) = commands::client(actual.f.context()?, false, None)?;
    let peer = commands::serve(Arc::clone(&actual.host), channel);
    assert!(matches!(
        fresh_reader.execute_selection().await,
        Err(CommandError::ReadbackRequired)
    ));
    let fresh_read = fresh_reader.readback().await?;
    exact_selection(&fresh_read, &original);
    assert!(matches!(
        fresh_read
            .original_context()
            .require_new_original_receipt(now()?),
        Err(crate::OriginalCircuitRetainedPublicationErrorV1::Binding(
            "recovered evaluated retention is read-only"
        ))
    ));
    drop(fresh_reader);
    assert_eq!(
        peer.join().expect("fresh reader of recovered original S")?,
        2
    );
    // A new original-host supplied cold fixture connection carries only readback.
    // The host's original task/T/B connections and their deadlines are unchanged.
    let (cold, channel) = commands::stage_client(
        &original_dataset.config,
        &original_dataset.receipt,
        &actual.f.training,
        &actual.f.evaluation,
        true,
    )?;
    let peer = commands::serve(Arc::clone(&actual.host), channel);
    assert!(matches!(
        cold.execute_selection().await,
        Err(CommandError::ReadbackRequired)
    ));
    let read = cold.readback().await?;
    exact_selection(&read, &original);
    assert!(matches!(
        read.original_context().require_new_original_receipt(now()?),
        Err(crate::OriginalCircuitRetainedPublicationErrorV1::Binding(
            "recovered evaluated retention is read-only"
        ))
    ));
    let next = SelectorFiles::new()?;
    let (journal, witness) = next.files(&actual.f, &OpenReceipt::Fresh)?;
    let untouched = next.bytes()?;
    let result = crate::OriginalCircuitNextUseReceiptOwnerV1::create_evaluated(
        journal,
        witness,
        crate::OriginalCircuitEvaluatedNextUseReceiptConfigV1 {
            selection: fresh_read,
            signer: actual.f.host.original.credentials.observer.clone(),
            maximum_signature_lifetime_seconds: 300,
        },
        ed25519_dalek::SigningKey::from_bytes(&[43; 32]),
    );
    assert!(matches!(
        result,
        Err(crate::OriginalCircuitNextUseReceiptErrorV1::Evaluated(
            crate::OriginalCircuitRetainedPublicationErrorV1::Binding(
                "recovered evaluated retention is read-only"
            )
        ))
    ));
    assert_eq!(next.bytes()?, untouched);
    assert_eq!(actual.files.bytes()?, completed);
    assert_eq!(actual.f.publication_bytes()?, publication);
    drop(cold);
    assert_eq!(peer.join().expect("cold original S command peer")?, 1);
    actual.finish([10, 10], 7).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_selection_command_recovered_missing_cannot_claim() -> anyhow::Result<()> {
    let actual = Box::pin(ActualCommand::ready(OpenReceipt::Readback)).await?;
    let empty = actual.files.bytes()?;
    let publication = actual.f.publication_bytes()?;
    commands::refuse_evidence_without_pin(&actual.host)?;
    // A fresh fixture client cannot change the actual recovered owner's brand.
    let (client, channel) = commands::client(actual.f.context()?, false, None)?;
    let peer = commands::serve(Arc::clone(&actual.host), channel);
    assert!(matches!(
        client.execute_selection().await,
        Err(CommandError::ReadbackRequired)
    ));
    assert!(matches!(
        client.readback().await,
        Err(CommandError::Missing)
    ));
    assert!(matches!(
        client.execute_selection().await,
        Err(CommandError::ReadbackRequired)
    ));
    commands::refuse_evidence_without_pin(&actual.host)?;
    assert_eq!(actual.files.bytes()?, empty);
    assert_eq!(actual.f.publication_bytes()?, publication);
    assert_eq!(
        actual.c.cell.snapshot(&actual.f.source_c.scope)?.revision,
        0
    );
    drop(client);
    assert_eq!(peer.join().expect("recovered original S command peer")?, 2);
    actual.finish([5, 5], 1).await
}

#[derive(Clone, Copy)]
enum Withdraw {
    Training,
    Evaluation,
}

async fn withdrawn_original(which: Withdraw) -> anyhow::Result<()> {
    let actual = Box::pin(ActualCommand::ready(OpenReceipt::Fresh)).await?;
    let (client, channel) = commands::client(actual.f.context()?, false, None)?;
    let peer = commands::serve(Arc::clone(&actual.host), channel);
    let selected = client.execute_selection().await?;
    let completed = actual.files.bytes()?;
    let publication = actual.f.publication_bytes()?;
    match which {
        Withdraw::Training => actual.f.host.original.withdraw_original_dataset()?,
        Withdraw::Evaluation => actual.f.host.retention_b.withdraw_target()?,
    }
    assert!(matches!(
        client.readback().await,
        Err(CommandError::CommitUncertain)
    ));
    assert!(matches!(
        client.readback().await,
        Err(CommandError::Unavailable)
    ));
    assert_eq!(selected.snapshot().receipts.len(), 5);
    assert_eq!(actual.files.bytes()?, completed);
    assert_eq!(actual.f.publication_bytes()?, publication);
    drop(client);
    assert_eq!(peer.join().expect("withdrawn original S command peer")?, 2);
    actual
        .finish(
            match which {
                Withdraw::Training => [7, 6],
                Withdraw::Evaluation => [7, 7],
            },
            3,
        )
        .await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_selection_command_never_reuses_s_after_training_withdrawal() -> anyhow::Result<()>
{
    Box::pin(withdrawn_original(Withdraw::Training)).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_selection_command_never_reuses_s_after_evaluation_withdrawal()
-> anyhow::Result<()> {
    Box::pin(withdrawn_original(Withdraw::Evaluation)).await
}
