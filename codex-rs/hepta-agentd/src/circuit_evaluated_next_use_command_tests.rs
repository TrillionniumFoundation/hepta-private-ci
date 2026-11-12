//! Same original A/publication, authenticated S command result and live
//! T/B/S/Source/Cell peers. These command/cold-read mechanisms are not ordinary
//! Candidate, daemon or Root qualification.

use super::*;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCircuitEvaluatedNextUseCommandErrorV1 as NextCommandError;
use crate::OriginalCircuitEvaluatedNextUseCommandOwnerV1;
use crate::OriginalCircuitEvaluatedNextUseReceiptConfigV1;
use crate::OriginalCircuitEvaluatedNextUseReceiptV1;
use crate::OriginalCircuitEvaluatedSelectionCommandClientV1;
use crate::OriginalCircuitNextUseReceiptOwnerV1;
use crate::OriginalCircuitRetainedPublicationErrorV1 as PublicationError;
use crate::learning_iteration_evidence_client::evaluated_next_use_command_test_support as next_commands;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;
use std::sync::Arc;

type NextCommandOwner = OriginalCircuitEvaluatedNextUseCommandOwnerV1<FileAnchorWitnessStore>;

struct ActualNextCommand {
    common: ActualCommand,
    material: OriginalCellQ24MaterialReceiptConfigV1,
    dataset: OriginalCellQ24MaterialCommandReceiptV1,
    selection: OriginalCircuitEvaluatedSelectionReceiptV1,
    selector_client: OriginalCircuitEvaluatedSelectionCommandClientV1,
    selector_peer: std::thread::JoinHandle<Result<u64, CommandError>>,
    selector_evidence_peer: std::thread::JoinHandle<Result<u64, CommandError>>,
    task_host: Arc<ReadOwner>,
    task_peer: std::thread::JoinHandle<Result<u64, ReadError>>,
    files: SelectorFiles,
    host: Arc<NextCommandOwner>,
}

fn next_owner(
    files: &SelectorFiles,
    f: &PublicationFixture,
    selection: &OriginalCircuitEvaluatedSelectionReceiptV1,
    mode: OpenReceipt,
) -> anyhow::Result<OriginalCircuitNextUseReceiptOwnerV1<FileAnchorWitnessStore>> {
    let (journal, witness) = files.files(f, &mode)?;
    let config = OriginalCircuitEvaluatedNextUseReceiptConfigV1 {
        // Recovery deliberately receives the fresh original S. Only the
        // recovered C owner's private brand can determine its new-work rights.
        selection: selection.clone(),
        signer: f.host.original.credentials.observer.clone(),
        maximum_signature_lifetime_seconds: 300,
    };
    let key = ed25519_dalek::SigningKey::from_bytes(&[43; 32]);
    Ok(match mode {
        OpenReceipt::Fresh => {
            OriginalCircuitNextUseReceiptOwnerV1::create_evaluated(journal, witness, config, key)?
        }
        OpenReceipt::Readback => {
            OriginalCircuitNextUseReceiptOwnerV1::recover_evaluated(journal, witness, config, key)?
        }
    })
}

impl ActualNextCommand {
    async fn ready(mode: OpenReceipt) -> anyhow::Result<Self> {
        let common = Box::pin(ActualCommand::ready(OpenReceipt::Fresh)).await?;
        let original_dataset = Box::pin(version_material::original_dataset(&common.f)).await?;
        let material = original_dataset.config;
        let dataset = original_dataset.receipt;
        drop(original_dataset.readback);
        assert_eq!(
            original_dataset
                .peer
                .join()
                .expect("same actual D command peer")?,
            1
        );
        let (selector_client, channel) = commands::stage_client(
            &material,
            &dataset,
            &common.f.training,
            &common.f.evaluation,
            false,
        )?;
        let selector_peer = commands::serve(Arc::clone(&common.host), channel);
        let executed_s = selector_client.execute_selection().await?;
        // This same client retains Fresh only after its own authenticated
        // Execute ACK. A cold Readback never supplies fresh C authority.
        let selection = selector_client.readback().await?;
        exact_selection(&selection, &executed_s);
        selection
            .original_context()
            .require_new_original_receipt(now()?)?;
        let actual_publication = execute(&common.c, 1).await?;
        let actual = read_receipt(&common.c, &common.f.definition, &actual_publication)?;
        assert_eq!(actual.bundle_digest, common.f.bundle.digest()?);
        assert_ne!(
            actual.bundle_digest,
            common.f.host.original.candidate.digest()?
        );
        assert_eq!(
            actual.representation.prediction_q24,
            vec![Q / 4, Q, 0, 0, 0]
        );
        let (selector, channel) = commands::evidence_client(&common.host)?;
        let selector_evidence_peer = commands::serve_evidence(Arc::clone(&common.host), channel);
        let context = ReadContext::for_original_next_use(selection.clone())?;
        let task_host = Arc::new(ReadOwner::from_original_evaluated_owners(
            common.c.cell.clone(),
            common.c.source.as_ref().clone(),
            common.c.runtime.identity.clone(),
            context.clone(),
        )?);
        let (live, channel) = reads::evaluated_client(context)?;
        let task_peer = reads::serve(Arc::clone(&task_host), channel);
        let files = SelectorFiles::new()?;
        let fresh = next_owner(&files, &common.f, &selection, OpenReceipt::Fresh)?;
        let owner = match mode {
            OpenReceipt::Fresh => fresh,
            OpenReceipt::Readback => {
                drop(fresh);
                next_owner(&files, &common.f, &selection, OpenReceipt::Readback)?
            }
        };
        let host = Arc::new(owner.into_evaluated_command_owner(
            live,
            Arc::clone(&common.trainer),
            Arc::clone(&common.evaluator),
            selector,
        )?);
        Ok(Self {
            common,
            material,
            dataset,
            selection,
            selector_client,
            selector_peer,
            selector_evidence_peer,
            task_host,
            task_peer,
            files,
            host,
        })
    }

    fn recover_original_owner(self) -> anyhow::Result<Self> {
        let Self {
            common,
            material,
            dataset,
            selection,
            selector_client,
            selector_peer,
            selector_evidence_peer,
            task_host,
            task_peer,
            files,
            host,
        } = self;
        let (live, selector) = next_commands::release_original_read_peers(host)?;
        let owner = next_owner(&files, &common.f, &selection, OpenReceipt::Readback)?;
        let host = Arc::new(owner.into_evaluated_command_owner(
            live,
            Arc::clone(&common.trainer),
            Arc::clone(&common.evaluator),
            selector,
        )?);
        Ok(Self {
            common,
            material,
            dataset,
            selection,
            selector_client,
            selector_peer,
            selector_evidence_peer,
            task_host,
            task_peer,
            files,
            host,
        })
    }

    async fn finish(
        self,
        counts: [u64; 2],
        selection_reads: u64,
        next_reads: u64,
        selector_evidence_reads: u64,
    ) -> anyhow::Result<()> {
        let Self {
            common,
            material: _,
            dataset: _,
            selection: _,
            selector_client,
            selector_peer,
            selector_evidence_peer,
            task_host,
            task_peer,
            files,
            host,
        } = self;
        drop(host);
        assert_eq!(
            task_peer
                .join()
                .expect("same actual five-cut C task peer")?,
            next_reads
        );
        drop(task_host);
        assert_eq!(
            selector_evidence_peer
                .join()
                .expect("same actual readonly S evidence peer")?,
            selector_evidence_reads
        );
        drop(selector_client);
        assert_eq!(
            selector_peer
                .join()
                .expect("same original S command peer")?,
            2
        );
        drop(files);
        common.finish(counts, selection_reads).await
    }
}

fn exact_next_use(
    left: &OriginalCircuitEvaluatedNextUseReceiptV1,
    right: &OriginalCircuitEvaluatedNextUseReceiptV1,
) {
    assert_eq!(
        (
            left.snapshot(),
            left.receipt(),
            left.attestation(),
            left.original_selection().original_receipt_binding()
        ),
        (
            right.snapshot(),
            right.receipt(),
            right.attestation(),
            right.original_selection().original_receipt_binding()
        )
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_next_use_command_once_reads_originals_and_readonly_evidence()
-> anyhow::Result<()> {
    let actual = Box::pin(ActualNextCommand::ready(OpenReceipt::Fresh)).await?;
    let empty = actual.files.bytes()?;
    let original_s = actual.common.files.bytes()?;
    let publication = actual.common.f.publication_bytes()?;
    let upstream = (
        actual.common.f.host.original.predecessor_bytes()?,
        actual.common.f.host.upstream_files()?,
        actual.common.f.host.original_files()?,
    );
    next_commands::reject_wrong_context(&actual.host)?;
    next_commands::refuse_evidence_without_pin(&actual.host)?;
    next_commands::cancel_queued_execute(Arc::clone(&actual.host)).await?;
    assert_eq!(actual.files.bytes()?, empty);
    let (client, channel) =
        next_commands::stage_client(&actual.material, &actual.dataset, &actual.selection, false)?;
    let peer = next_commands::serve(Arc::clone(&actual.host), channel);
    let completed = client.attest_completed_task().await?;
    assert_eq!(completed.snapshot().receipts.len(), 6);
    assert_eq!(
        &completed.snapshot().receipts[..5],
        &actual.selection.snapshot().receipts
    );
    assert!(completed.snapshot().training_no_update_v2().is_none());
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(completed.snapshot().clone())?;
    assert_eq!(coordinator.next_stage(), None);
    assert_eq!(
        coordinator.next_task_bundle(),
        Some(&actual.common.f.bundle)
    );
    assert!(matches!(
        completed.receipt().observation,
        LearningIterationObservationV1::RetainedModelNextUse { retained_bundle, .. }
        if retained_bundle == actual.common.f.bundle.digest()?
    ));
    completed
        .original_selection()
        .original_context()
        .require_new_original_receipt(now()?)?;
    let committed = actual.files.bytes()?;
    assert_ne!(committed, empty);
    assert!(matches!(
        client.attest_completed_task().await,
        Err(NextCommandError::ReadbackRequired)
    ));
    let read = client.readback().await?;
    exact_next_use(&read, &completed);
    read.original_selection()
        .original_context()
        .require_new_original_receipt(now()?)?;
    let (evidence, channel) = next_commands::evidence_client(&actual.host)?;
    let evidence_peer = next_commands::serve_evidence(Arc::clone(&actual.host), channel);
    assert_eq!(
        evidence
            .readback(completed.snapshot(), completed.receipt())
            .await?,
        *completed.attestation()
    );
    assert_eq!(actual.files.bytes()?, committed);
    assert_eq!(actual.common.files.bytes()?, original_s);
    assert_eq!(actual.common.f.publication_bytes()?, publication);
    assert_eq!(
        (
            actual.common.f.host.original.predecessor_bytes()?,
            actual.common.f.host.upstream_files()?,
            actual.common.f.host.original_files()?,
        ),
        upstream
    );
    assert_eq!(
        actual
            .common
            .c
            .cell
            .snapshot(&actual.common.f.source_c.scope)?
            .revision,
        1
    );
    drop(evidence);
    assert_eq!(
        evidence_peer
            .join()
            .expect("actual readonly C evidence peer")?,
        1
    );
    drop(client);
    assert_eq!(peer.join().expect("same original C command peer")?, 2);
    actual.finish([26, 26], 17, 7, 6).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_next_use_command_lost_ack_recovers_only_exact_readback() -> anyhow::Result<()> {
    let actual = Box::pin(ActualNextCommand::ready(OpenReceipt::Fresh)).await?;
    let empty = actual.files.bytes()?;
    let original_s = actual.common.files.bytes()?;
    let publication = actual.common.f.publication_bytes()?;
    let (client, channel) =
        next_commands::stage_client(&actual.material, &actual.dataset, &actual.selection, false)?;
    let peer = next_commands::lose_ack(Arc::clone(&actual.host), channel);
    assert!(matches!(
        client.attest_completed_task().await,
        Err(NextCommandError::CommitUncertain)
    ));
    assert!(matches!(
        client.attest_completed_task().await,
        Err(NextCommandError::Unavailable)
    ));
    assert!(matches!(
        client.readback().await,
        Err(NextCommandError::Unavailable)
    ));
    drop(client);
    let original = peer.join().expect("actual C before lost ACK")?;
    let committed = actual.files.bytes()?;
    assert_ne!(committed, empty);
    let actual = actual.recover_original_owner()?;
    next_commands::refuse_evidence_without_pin(&actual.host)?;
    // Supplying a fresh original S cannot turn a recovered C host into a
    // signing owner or promote this new client's first Readback into Fresh.
    let (fresh_reader, channel) = next_commands::client(actual.selection.clone(), false, None)?;
    let peer = next_commands::serve(Arc::clone(&actual.host), channel);
    assert!(matches!(
        fresh_reader.attest_completed_task().await,
        Err(NextCommandError::ReadbackRequired)
    ));
    let read = fresh_reader.readback().await?;
    exact_next_use(&read, &original);
    assert!(matches!(
        read.original_selection()
            .original_context()
            .require_new_original_receipt(now()?),
        Err(PublicationError::Binding(
            "recovered evaluated retention is read-only"
        ))
    ));
    drop(fresh_reader);
    assert_eq!(peer.join().expect("fresh client of recovered C host")?, 2);
    // New original-host supplied fixture command framing grants only readback.
    // Original T/B/S/task channels and their deadlines have not been replaced.
    let (cold, channel) =
        next_commands::stage_client(&actual.material, &actual.dataset, &actual.selection, true)?;
    let peer = next_commands::serve(Arc::clone(&actual.host), channel);
    assert!(matches!(
        cold.attest_completed_task().await,
        Err(NextCommandError::ReadbackRequired)
    ));
    let read = cold.readback().await?;
    exact_next_use(&read, &original);
    assert!(matches!(
        read.original_selection()
            .original_context()
            .require_new_original_receipt(now()?),
        Err(PublicationError::Binding(
            "recovered evaluated retention is read-only"
        ))
    ));
    assert_eq!(actual.files.bytes()?, committed);
    assert_eq!(actual.common.files.bytes()?, original_s);
    assert_eq!(actual.common.f.publication_bytes()?, publication);
    assert_eq!(
        actual
            .common
            .c
            .cell
            .snapshot(&actual.common.f.source_c.scope)?
            .revision,
        1
    );
    drop(cold);
    assert_eq!(peer.join().expect("cold original C command peer")?, 1);
    actual.finish([26, 26], 17, 7, 6).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_next_use_command_recovered_missing_cannot_claim() -> anyhow::Result<()> {
    let actual = Box::pin(ActualNextCommand::ready(OpenReceipt::Readback)).await?;
    let empty = actual.files.bytes()?;
    let original_s = actual.common.files.bytes()?;
    let publication = actual.common.f.publication_bytes()?;
    next_commands::refuse_evidence_without_pin(&actual.host)?;
    let (client, channel) =
        next_commands::stage_client(&actual.material, &actual.dataset, &actual.selection, true)?;
    let peer = next_commands::serve(Arc::clone(&actual.host), channel);
    assert!(matches!(
        client.attest_completed_task().await,
        Err(NextCommandError::ReadbackRequired)
    ));
    assert!(matches!(
        client.readback().await,
        Err(NextCommandError::Missing)
    ));
    assert!(matches!(
        client.attest_completed_task().await,
        Err(NextCommandError::ReadbackRequired)
    ));
    next_commands::refuse_evidence_without_pin(&actual.host)?;
    assert_eq!(actual.files.bytes()?, empty);
    assert_eq!(actual.common.files.bytes()?, original_s);
    assert_eq!(actual.common.f.publication_bytes()?, publication);
    assert_eq!(
        actual
            .common
            .c
            .cell
            .snapshot(&actual.common.f.source_c.scope)?
            .revision,
        1
    );
    drop(client);
    assert_eq!(peer.join().expect("recovered original C command peer")?, 1);
    actual.finish([11, 11], 7, 1, 1).await
}
