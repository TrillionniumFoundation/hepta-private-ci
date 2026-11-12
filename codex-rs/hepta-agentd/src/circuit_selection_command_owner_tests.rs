//! Original Selector command behavior over actual Published A/C owners.
//! Enrollment, same-process channels and signed Training metadata are explicit
//! fixtures; these cases do not claim a native A/B/C deployment.

use super::*;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use crate::OriginalCircuitSelectionCommandClientV1;
use crate::OriginalCircuitSelectionCommandContextV1;
use crate::OriginalCircuitSelectionCommandErrorV1;
use crate::OriginalCircuitSelectionCommandOwnerV1;
use crate::learning_iteration_evidence_client::fixture_original_receipt_client_until_close;
use crate::learning_iteration_evidence_client::selection_command_test_support as command;

type RoleOwner = OriginalCircuitSelectionCommandOwnerV1<FileAnchorWitnessStore>;
type RoleThread = std::thread::JoinHandle<Result<u64, OriginalCircuitSelectionCommandErrorV1>>;
type TrainerThread = std::thread::JoinHandle<anyhow::Result<usize>>;

struct OriginalService {
    owner: Arc<RoleOwner>,
    published: ReadThread,
    trainer: TrainerThread,
}

impl OriginalService {
    fn start(f: &SelectionFixture, receipt_owner: SelectionOwner) -> anyhow::Result<Self> {
        let read_context = selection_context(&f.config);
        let published = original(&f.original, read_context.clone())?;
        let (live, channel) = transport::client(read_context)?;
        let published = transport::serve(published, channel);
        let (trainer, peer) = fixture_original_receipt_client_until_close(
            f.original.initial.clone(),
            f.original.training.clone(),
            f.config.verifier.clone(),
            f.config.training_evidence.clone(),
        )?;
        let owner = Arc::new(receipt_owner.into_command_owner(live, trainer)?);
        Ok(Self {
            owner,
            published,
            trainer: peer,
        })
    }

    fn finish(self, publication_withdrawn: bool) -> anyhow::Result<()> {
        drop(self.owner);
        let result = self
            .published
            .join()
            .map_err(|_| anyhow::anyhow!("original Published service thread"))?;
        if publication_withdrawn {
            anyhow::ensure!(result.is_err(), "actual withdrawn Published read refused");
        } else {
            result?;
        }
        let reads = self
            .trainer
            .join()
            .map_err(|_| anyhow::anyhow!("original Trainer service thread"))??;
        anyhow::ensure!(reads > 0, "actual original Trainer was read");
        Ok(())
    }
}

async fn command_context(
    f: &SelectionFixture,
) -> anyhow::Result<OriginalCircuitSelectionCommandContextV1> {
    let (dataset, original) = command::training_fixture_result(
        f.config.decision.clone(),
        f.config.scope.clone(),
        f.config.verifier.clone(),
        f.config.training_evidence.clone(),
    )
    .await?;
    Ok(
        OriginalCircuitSelectionCommandContextV1::from_original_training(
            dataset,
            f.config.scope.clone(),
            f.config.verifier.clone(),
            &original,
        )?,
    )
}

fn finish_command(
    client: OriginalCircuitSelectionCommandClientV1,
    server: RoleThread,
) -> anyhow::Result<u64> {
    drop(client);
    Ok(server
        .join()
        .map_err(|_| anyhow::anyhow!("original Selector command thread"))??)
}

#[tokio::test]
async fn q24_selector_command_binds_opaque_training_result_and_shared_dispatch()
-> anyhow::Result<()> {
    let mut f = SelectionFixture::ready().await?;
    let context = command_context(&f).await?;
    let service = OriginalService::start(&f, f.create()?)?;
    let (client, channel) = command::client(context.clone(), false, None)?;
    let server = command::serve(Arc::clone(&service.owner), channel);
    let before = f.bytes()?;
    assert!(matches!(
        client.readback().await,
        Err(OriginalCircuitSelectionCommandErrorV1::Missing)
    ));
    assert_eq!(f.bytes()?, before);
    let selected = client.execute_selection().await?;
    let original = LearningIterationCoordinatorV1::from_snapshot(f.config.decision.clone())?;
    assert_eq!(
        &selected.receipt().observation,
        &f.original.session.cell.read_learning_selection(&original)?,
    );
    assert_eq!(selected.training_attestation(), &f.config.training_evidence);
    assert_eq!(selected.snapshot().receipts.len(), 4);
    let bytes = f.bytes()?;
    assert!(matches!(
        client.execute_selection().await,
        Err(OriginalCircuitSelectionCommandErrorV1::ReadbackRequired)
    ));
    assert_eq!(client.readback().await?, selected);
    assert_eq!(f.bytes()?, bytes);

    // A second fresh connection cannot reset the same host's one dispatch bit.
    let (second, channel) = command::client(context, false, None)?;
    let second_server = command::serve(Arc::clone(&service.owner), channel);
    assert!(matches!(
        second.execute_selection().await,
        Err(OriginalCircuitSelectionCommandErrorV1::ReadbackRequired)
    ));
    assert_eq!(second.readback().await?, selected);
    assert_eq!(f.bytes()?, bytes);
    let selected_cut = LearningIterationCoordinatorV1::from_snapshot(selected.snapshot().clone())?;
    assert!(
        f.original
            .session
            .cell
            .read_learning_next_use(
                &selected_cut,
                f.original.session.source.as_ref(),
                &f.original.session.runtime.identity,
            )
            .is_err(),
        "Selection was obtained before ordinary C completion"
    );
    assert_eq!(finish_command(client, server)?, 3);
    assert_eq!(finish_command(second, second_server)?, 2);
    service.finish(false)?;
    f.original.session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_selector_command_lost_ack_recovers_original_signature_readonly() -> anyhow::Result<()>
{
    let mut f = SelectionFixture::ready().await?;
    let context = command_context(&f).await?;
    let service = OriginalService::start(&f, f.create()?)?;
    let (client, channel) = command::client(context.clone(), false, None)?;
    let server = command::lose_ack(Arc::clone(&service.owner), channel);
    assert!(matches!(
        client.execute_selection().await,
        Err(OriginalCircuitSelectionCommandErrorV1::CommitUncertain)
    ));
    assert!(matches!(
        client.readback().await,
        Err(OriginalCircuitSelectionCommandErrorV1::Unavailable)
    ));
    drop(client);
    let original = server
        .join()
        .map_err(|_| anyhow::anyhow!("lost ACK thread"))??;
    let bytes = f.bytes()?;
    service.finish(false)?;

    let recovered = OriginalService::start(&f, f.recover()?)?;
    // Even a fresh client's execute request cannot promote a recovered owner.
    let (fresh, channel) = command::client(context, false, None)?;
    let fresh_server = command::serve(Arc::clone(&recovered.owner), channel);
    assert!(matches!(
        fresh.execute_selection().await,
        Err(OriginalCircuitSelectionCommandErrorV1::ReadbackRequired)
    ));
    assert_eq!(fresh.readback().await?, original);
    let (cold, channel) = command::recover_client(
        f.config.decision.clone(),
        f.config.scope.clone(),
        f.config.verifier.clone(),
        f.config.training_evidence.clone(),
        Some((original.snapshot().clone(), original.attestation().clone())),
    )?;
    let cold_server = command::serve(Arc::clone(&recovered.owner), channel);
    assert!(matches!(
        cold.execute_selection().await,
        Err(OriginalCircuitSelectionCommandErrorV1::ReadbackRequired)
    ));
    assert_eq!(cold.readback().await?, original);
    assert_eq!(
        cold.receipt_attestation(original.receipt()).await?,
        *original.attestation()
    );
    assert_eq!(f.bytes()?, bytes);
    assert_eq!(finish_command(fresh, fresh_server)?, 2);
    assert_eq!(finish_command(cold, cold_server)?, 2);
    recovered.finish(false)?;
    f.original.session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_selector_command_recovered_missing_never_dispatches() -> anyhow::Result<()> {
    let mut f = SelectionFixture::ready().await?;
    let context = command_context(&f).await?;
    drop(f.create()?);
    let before = f.bytes()?;
    let service = OriginalService::start(&f, f.recover()?)?;
    let (client, channel) = command::client(context, false, None)?;
    let server = command::serve(Arc::clone(&service.owner), channel);
    assert!(matches!(
        client.execute_selection().await,
        Err(OriginalCircuitSelectionCommandErrorV1::ReadbackRequired)
    ));
    assert!(matches!(
        client.readback().await,
        Err(OriginalCircuitSelectionCommandErrorV1::Missing)
    ));
    assert_eq!(f.bytes()?, before);
    assert_eq!(finish_command(client, server)?, 2);
    service.finish(false)?;
    f.original.session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_selector_command_rejects_wrong_context_and_valid_renewal_before_dispatch()
-> anyhow::Result<()> {
    let mut f = SelectionFixture::ready().await?;
    let context = command_context(&f).await?;
    let service = OriginalService::start(&f, f.create()?)?;
    let before = f.bytes()?;
    command::reject_wrong_context(&service.owner)?;
    command::cancel_queued_execute(Arc::clone(&service.owner)).await?;
    assert_eq!(f.bytes()?, before);

    let mut renewed = f.config.training_evidence.clone();
    renewed.expires_at += 1;
    renewed.signature = SigningKey::from_bytes(&[101; 32])
        .sign(&renewed.signing_bytes())
        .to_bytes();
    f.config.verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &renewed,
        &learning_iteration_receipt_signing_bytes_v1(&f.original.training)?,
        now()?,
    )?;
    let (dataset, actual_decoder_result) = command::training_fixture_result(
        f.config.decision.clone(),
        f.config.scope.clone(),
        f.config.verifier.clone(),
        renewed,
    )
    .await?;
    let changed = OriginalCircuitSelectionCommandContextV1::from_original_training(
        dataset,
        f.config.scope.clone(),
        f.config.verifier.clone(),
        &actual_decoder_result,
    )?;
    let (wrong, channel) = command::client(changed, false, None)?;
    let wrong_server = command::serve(Arc::clone(&service.owner), channel);
    assert!(matches!(
        wrong.execute_selection().await,
        Err(OriginalCircuitSelectionCommandErrorV1::CommitUncertain)
    ));
    drop(wrong);
    assert!(
        wrong_server
            .join()
            .map_err(|_| anyhow::anyhow!("changed context thread"))?
            .is_err()
    );
    assert_eq!(f.bytes()?, before);
    // Rejection occurred before the shared once bit, so the original request
    // can still make its single legitimate dispatch.
    let (client, channel) = command::client(context, false, None)?;
    let server = command::serve(Arc::clone(&service.owner), channel);
    client.execute_selection().await?;
    assert_ne!(f.bytes()?, before);
    assert_eq!(finish_command(client, server)?, 1);
    service.finish(false)?;
    f.original.session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_selector_command_evidence_readback_detects_live_withdrawal() -> anyhow::Result<()> {
    let mut f = SelectionFixture::ready().await?;
    let context = command_context(&f).await?;
    let service = OriginalService::start(&f, f.create()?)?;
    let (client, channel) = command::client(context.clone(), false, None)?;
    let server = command::serve(Arc::clone(&service.owner), channel);
    let selected = client.execute_selection().await?;
    let bytes = f.bytes()?;
    let (evidence, channel) = command::evidence_client(&context)?;
    let evidence_server = command::serve_evidence(Arc::clone(&service.owner), channel);
    assert_eq!(
        evidence
            .readback(selected.snapshot(), selected.receipt())
            .await?,
        *selected.attestation(),
    );
    assert_eq!(f.bytes()?, bytes);
    f.original.version.withdraw()?;
    assert!(
        evidence
            .readback(selected.snapshot(), selected.receipt())
            .await
            .is_err()
    );
    assert_eq!(f.bytes()?, bytes);
    drop(evidence);
    assert!(
        evidence_server
            .join()
            .map_err(|_| anyhow::anyhow!("withdrawn evidence thread"))?
            .is_err()
    );
    assert!(matches!(
        client.readback().await,
        Err(OriginalCircuitSelectionCommandErrorV1::CommitUncertain)
    ));
    assert_eq!(f.bytes()?, bytes);
    assert_eq!(finish_command(client, server)?, 2);
    service.finish(true)?;
    f.original.session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_selector_command_keeps_original_expiry_and_external_custody() -> anyhow::Result<()> {
    let mut f = SelectionFixture::ready().await?;
    let context = command_context(&f).await?;
    let peer = command::identity()?;
    let (stream, unused) = UnixStream::pair()?;
    // SAFETY: observe the test UID, which the public bootstrap must refuse.
    let uid = unsafe { libc::geteuid() };
    assert!(
        OriginalCircuitSelectionCommandClientV1::from_original_stream(
            stream,
            crate::LearningIterationEvidencePeerV1 {
                pid: peer.pid,
                uid,
                boot_id: peer.boot_id.clone(),
                process_start_ticks: peer.process_start_ticks,
                actor_id: f.config.decision.owners.selector.clone(),
            },
            command::pidfd()?,
            context,
            Duration::from_secs(30),
            Duration::from_secs(300),
        )
        .is_err()
    );
    drop(unused);
    let (stream, unused) = UnixStream::pair()?;
    assert!(
        OriginalCircuitSelectionCommandClientV1::recover_from_original_stream(
            stream,
            crate::LearningIterationEvidencePeerV1 {
                pid: peer.pid,
                uid,
                boot_id: peer.boot_id,
                process_start_ticks: peer.process_start_ticks,
                actor_id: f.config.decision.owners.selector.clone(),
            },
            command::pidfd()?,
            f.config.decision.clone(),
            f.config.scope.clone(),
            f.config.verifier.clone(),
            f.config.training_evidence.clone(),
            None,
            Duration::from_secs(30),
            Duration::from_secs(300),
        )
        .is_err()
    );
    drop(unused);

    let expires_at = now()? + 10;
    f.config.training_evidence.expires_at = expires_at;
    f.config.training_evidence.signature = SigningKey::from_bytes(&[101; 32])
        .sign(&f.config.training_evidence.signing_bytes())
        .to_bytes();
    let context = command_context(&f).await?;
    let service = OriginalService::start(&f, f.create()?)?;
    let (client, channel) = command::client(context, false, None)?;
    let server = command::serve(Arc::clone(&service.owner), channel);
    assert!(matches!(
        client.readback().await,
        Err(OriginalCircuitSelectionCommandErrorV1::Missing)
    ));
    let before = f.bytes()?;
    // Original evidence remains valid throughout its expiry second. Wait
    // beyond that inclusive bound before testing refusal without an effect.
    let invalid_from = expires_at
        .checked_add(1)
        .ok_or_else(|| anyhow::anyhow!("original evidence expiry overflow"))?;
    tokio::time::sleep(
        Duration::from_secs(invalid_from.saturating_sub(now()?)) + Duration::from_millis(100),
    )
    .await;
    assert!(now()? > expires_at);
    assert!(matches!(
        client.execute_selection().await,
        Err(OriginalCircuitSelectionCommandErrorV1::Evidence(
            codex_hepta_learning_ledger::SignedEvidenceError::ValidityWindow
        ))
    ));
    assert!(matches!(
        client.readback().await,
        Err(OriginalCircuitSelectionCommandErrorV1::Unavailable)
    ));
    assert_eq!(f.bytes()?, before);
    assert_eq!(finish_command(client, server)?, 1);
    service.finish(false)?;
    f.original.session.stop().await?;
    Ok(())
}

#[path = "circuit_next_use_command_owner_tests.rs"]
mod next_use_command;
