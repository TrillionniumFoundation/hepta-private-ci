//! Actual native fits and Generator journals through the typed command
//! producer. Socket custody is an explicit same-UID fixture, not a deployed
//! external role host or an ordinary Root learning loop.

use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::*;
use crate::LearningIterationEvidencePeerV1;
use crate::OriginalCellQ24TrainingCommandClientV1;
use crate::OriginalCellQ24TrainingCommandContextV1;
use crate::OriginalCellQ24TrainingCommandErrorV1 as CommandError;
use crate::OriginalCellQ24TrainingCommandOwnerV1;
use crate::learning_iteration_evidence_client::command_test_support as transport;

type CommandOwner =
    OriginalCellQ24TrainingCommandOwnerV1<FileAnchorWitnessStore, FileAnchorWitnessStore>;

type SharedStage =
    Arc<SourceBoundCellQ24TrainingStageV1<FileAnchorWitnessStore, FileAnchorWitnessStore>>;

fn context(fixture: &Harness) -> OriginalCellQ24TrainingCommandContextV1 {
    OriginalCellQ24TrainingCommandContextV1 {
        dataset: fixture.config.dataset.clone(),
        scope: fixture.config.scope.clone(),
        verifier: fixture.config.verifier.clone(),
    }
}

async fn shared_owner(
    fixture: &Harness,
    create: bool,
) -> anyhow::Result<(Arc<CommandOwner>, SharedStage, Peers)> {
    let (capture, peers) = fixture.capture().await?;
    let training = if create {
        CellQ24TrainingOwnerV1::create_from_original_source(
            fixture.file("native-training", true)?,
            fixture.witness("native-witness", true)?,
            capture,
        )?
    } else {
        CellQ24TrainingOwnerV1::recover_from_original_source(
            fixture.file("native-training", false)?,
            fixture.witness("native-witness", false)?,
            capture,
        )?
    };
    let original =
        OriginalCellQ24TrainingStageV1::from_original_owners(training, fixture.receipts(create)?)
            .await?;
    let stage = Arc::new(SourceBoundCellQ24TrainingStageV1::from_original_stage(original).await?);
    let cancellation = Arc::new(AtomicBool::new(false));
    let owner = if create {
        OriginalCellQ24TrainingCommandOwnerV1::from_original_stage(
            Arc::clone(&stage),
            context(fixture),
            cancellation,
        )
        .await?
    } else {
        OriginalCellQ24TrainingCommandOwnerV1::recover_original_stage(
            Arc::clone(&stage),
            context(fixture),
            cancellation,
        )
        .await?
    };
    Ok((Arc::new(owner), stage, peers))
}

async fn owner(fixture: &Harness, create: bool) -> anyhow::Result<(Arc<CommandOwner>, Peers)> {
    let (owner, stage, peers) = shared_owner(fixture, create).await?;
    drop(stage);
    Ok((owner, peers))
}

#[tokio::test]
async fn original_training_command_executes_and_produces_actual_evidence_readback()
-> anyhow::Result<()> {
    let fixture = Harness::new().await?;
    let (owner, stage, peers) = shared_owner(&fixture, true).await?;
    let (client, channel) = transport::client(context(&fixture), false, None)?;
    let server = transport::serve(Arc::clone(&owner), channel);
    assert!(matches!(
        client.readback().await,
        Err(CommandError::Missing)
    ));
    let before = fixture.bytes()?;
    let completed = client
        .execute_training(Arc::new(AtomicBool::new(false)))
        .await?;
    assert!(matches!(
        completed.receipt().observation,
        LearningIterationObservationV1::TrainingNoUpdateV2(_)
    ));
    let after = fixture.bytes()?;
    // A second typed host handler retains the very same facade, with no
    // trainer/key getter or writer reopen. It reads the original completion.
    let shared =
        SourceBoundCellQ24TrainingStageV1::readback(stage.as_ref(), &fixture.config.dataset)
            .await?;
    assert_eq!(shared.receipt, *completed.receipt());
    assert_eq!(shared.attestation, *completed.attestation());
    assert_ne!(
        before, after,
        "actual native and Generator durable completion"
    );
    assert_eq!(client.readback().await?, completed);
    assert_eq!(
        client.receipt_attestation(completed.receipt()).await?,
        *completed.attestation()
    );
    assert!(matches!(
        client
            .execute_training(Arc::new(AtomicBool::new(false)))
            .await,
        Err(CommandError::ReadbackRequired)
    ));
    let (evidence, channel) = transport::evidence_client(&context(&fixture))?;
    let evidence_server = transport::serve_evidence(Arc::clone(&owner), channel);
    assert_eq!(
        evidence
            .readback(&fixture.config.dataset, completed.receipt())
            .await?,
        *completed.attestation()
    );
    drop(evidence);
    assert_eq!(
        evidence_server
            .join()
            .expect("original evidence producer")?,
        1
    );
    assert_eq!(
        fixture.bytes()?,
        after,
        "reads and duplicate execute never re-sign"
    );
    drop(client);
    assert_eq!(server.join().expect("original command producer")?, 4);
    drop(owner);
    drop(stage);
    finish(peers)?;
    Ok(())
}

#[tokio::test]
async fn original_training_command_recovers_same_job_and_full_signature_read_only()
-> anyhow::Result<()> {
    let fixture = Harness::new().await?;
    let (original, peers) = owner(&fixture, true).await?;
    let (client, channel) = transport::client(context(&fixture), false, None)?;
    let server = transport::serve(Arc::clone(&original), channel);
    let completed = client
        .execute_training(Arc::new(AtomicBool::new(false)))
        .await?;
    drop(client);
    server.join().expect("original command producer")?;
    drop(original);
    finish(peers)?;
    let before = fixture.bytes()?;
    let (recovered, peers) = owner(&fixture, false).await?;
    // Even a fresh execution-capable fixture client cannot make the recovered
    // original host execute again. Its admission is independently read-only.
    let (client, channel) = transport::client(context(&fixture), false, Some(completed.clone()))?;
    let server = transport::serve(Arc::clone(&recovered), channel);
    assert!(matches!(
        client
            .execute_training(Arc::new(AtomicBool::new(false)))
            .await,
        Err(CommandError::ReadbackRequired)
    ));
    assert_eq!(client.readback().await?, completed);
    drop(client);
    assert_eq!(server.join().expect("recovered original producer")?, 2);
    drop(recovered);
    finish(peers)?;
    assert_eq!(fixture.bytes()?, before);
    Ok(())
}

#[tokio::test]
async fn original_training_command_lost_ack_reads_existing_completion_without_reexecution()
-> anyhow::Result<()> {
    let fixture = Harness::new().await?;
    let (owner, peers) = owner(&fixture, true).await?;
    let (client, channel) = transport::client(context(&fixture), false, None)?;
    let server = transport::lose_ack(Arc::clone(&owner), channel);
    assert!(matches!(
        client
            .execute_training(Arc::new(AtomicBool::new(false)))
            .await,
        Err(CommandError::CommitUncertain)
    ));
    server.join().expect("lost original ACK")?;
    assert!(matches!(
        client.readback().await,
        Err(CommandError::Unavailable)
    ));
    drop(client);
    let before = fixture.bytes()?;
    let (client, channel) = transport::client(context(&fixture), true, None)?;
    let server = transport::serve(Arc::clone(&owner), channel);
    let completed = client.readback().await?;
    assert!(matches!(
        completed.receipt().observation,
        LearningIterationObservationV1::TrainingNoUpdateV2(_)
    ));
    assert_eq!(client.readback().await?, completed);
    assert!(matches!(
        client
            .execute_training(Arc::new(AtomicBool::new(false)))
            .await,
        Err(CommandError::ReadbackRequired)
    ));
    drop(client);
    assert_eq!(server.join().expect("original same-job readback")?, 2);
    drop(owner);
    finish(peers)?;
    assert_eq!(
        fixture.bytes()?,
        before,
        "no second native or signature claim"
    );
    Ok(())
}

#[tokio::test]
async fn original_training_command_withdrawal_after_claim_preserves_pending_without_signature()
-> anyhow::Result<()> {
    let fixture = Harness::new().await?;
    let (capture, peers) = fixture.capture().await?;
    let training = CellQ24TrainingOwnerV1::create_from_original_source(
        fixture.file("native-training", true)?,
        WithdrawAfterClaim {
            witness: fixture.witness("native-witness", true)?,
            source: Arc::clone(&fixture.source),
            run: fixture.config.dataset.request.source_run_id.clone(),
        },
        capture,
    )?;
    let original =
        OriginalCellQ24TrainingStageV1::from_original_owners(training, fixture.receipts(true)?)
            .await?;
    let stage = Arc::new(SourceBoundCellQ24TrainingStageV1::from_original_stage(original).await?);
    let owner = Arc::new(
        OriginalCellQ24TrainingCommandOwnerV1::from_original_stage(
            stage,
            context(&fixture),
            Arc::new(AtomicBool::new(false)),
        )
        .await?,
    );
    let (recovery_capture, recovery_peers) = fixture.capture().await?;
    let before = fixture.bytes()?;
    let (client, channel) = transport::client(context(&fixture), false, None)?;
    let server = transport::serve(Arc::clone(&owner), channel);
    assert!(matches!(
        client
            .execute_training(Arc::new(AtomicBool::new(false)))
            .await,
        Err(CommandError::CommitUncertain)
    ));
    drop(client);
    assert_eq!(server.join().expect("withdrawn original command")?, 1);
    drop(owner);
    finish(peers)?;
    let after = fixture.bytes()?;
    assert_ne!(before[0], after[0]);
    assert_ne!(before[1], after[1]);
    assert_eq!(before[2..], after[2..], "Generator never claimed or signed");
    let mut recovered = CellQ24TrainingOwnerV1::recover_from_original_source(
        fixture.file("native-training", false)?,
        fixture.witness("native-witness", false)?,
        recovery_capture,
    )?;
    assert!(matches!(
        recovered.readback(),
        Err(CellQ24TrainingOwnerErrorV1::Pending)
    ));
    drop(recovered);
    finish(recovery_peers)?;
    assert_eq!(fixture.bytes()?, after);
    Ok(())
}

#[tokio::test]
async fn original_training_command_wrong_context_cannot_claim_or_consume_admission()
-> anyhow::Result<()> {
    let fixture = Harness::new().await?;
    let (owner, peers) = owner(&fixture, true).await?;
    let before = fixture.bytes()?;
    transport::reject_wrong_actor(Arc::clone(&owner))
        .join()
        .expect("wrong original actor")?;
    assert_eq!(fixture.bytes()?, before);
    let (client, channel) = transport::client(context(&fixture), false, None)?;
    let server = transport::serve(Arc::clone(&owner), channel);
    let completed = client
        .execute_training(Arc::new(AtomicBool::new(false)))
        .await?;
    assert!(matches!(
        completed.receipt().observation,
        LearningIterationObservationV1::TrainingNoUpdateV2(_)
    ));
    drop(client);
    assert_eq!(
        server
            .join()
            .expect("original producer after refused context")?,
        1
    );
    drop(owner);
    finish(peers)?;
    Ok(())
}

#[tokio::test]
async fn original_training_command_public_bootstrap_refuses_same_process_custody()
-> anyhow::Result<()> {
    let fixture = Harness::new().await?;
    let identity = transport::identity()?;
    let (stream, _server) = std::os::unix::net::UnixStream::pair()?;
    let result = OriginalCellQ24TrainingCommandClientV1::from_original_stream(
        stream,
        LearningIterationEvidencePeerV1 {
            pid: identity.pid,
            // SAFETY: read only this explicit fixture process's UID.
            uid: unsafe { libc::geteuid() },
            boot_id: identity.boot_id,
            process_start_ticks: identity.process_start_ticks,
            actor_id: fixture.config.dataset.owners.trainer.clone(),
        },
        transport::pidfd()?,
        context(&fixture),
        std::time::Duration::from_secs(30),
        std::time::Duration::from_secs(300),
    );
    assert!(matches!(
        result,
        Err(CommandError::Transport(
            codex_hepta_contracts::HostIssuerTransportError::PeerDenied
        ))
    ));
    assert!(!fixture.root.join("native-training").exists());
    assert!(!fixture.root.join("training-receipt").exists());
    Ok(())
}
