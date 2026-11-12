//! Actual ordinary A/C and original Selector/Observer command mechanisms.
//! Training metadata and process credentials are explicit fixtures. These tests
//! do not claim a native optimizer run or an installed cross-UID LEARN loop.

use super::*;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use crate::OriginalCircuitNextUseCommandClientV1;
use crate::OriginalCircuitNextUseCommandContextV1;
use crate::OriginalCircuitNextUseCommandErrorV1;
use crate::OriginalCircuitNextUseCommandOwnerV1;
use crate::OriginalCircuitSelectionCommandReceiptV1;
use crate::learning_iteration_evidence_client::next_use_command_test_support as next;

type ObserverHost = OriginalCircuitNextUseCommandOwnerV1<FileAnchorWitnessStore>;
type ObserverThread = std::thread::JoinHandle<Result<u64, OriginalCircuitNextUseCommandErrorV1>>;

struct CompletionFixture {
    f: SelectionFixture,
    selector: OriginalService,
    selection_context: OriginalCircuitSelectionCommandContextV1,
    selected: OriginalCircuitSelectionCommandReceiptV1,
}

impl CompletionFixture {
    async fn ready(selection_lifetime: Option<u64>) -> anyhow::Result<Self> {
        let mut f = SelectionFixture::ready().await?;
        if let Some(seconds) = selection_lifetime {
            f.config.maximum_signature_lifetime_seconds = seconds;
        }
        let selection_context = command_context(&f).await?;
        let selector = OriginalService::start(&f, f.create()?)?;
        let (client, channel) = command::client(selection_context.clone(), false, None)?;
        let thread = command::serve(Arc::clone(&selector.owner), channel);
        let selected = client.execute_selection().await?;
        assert_eq!(finish_command(client, thread)?, 1);
        // This is the actual original Selector command result, not the
        // fixture's pre-existing synthetic Selection signature.
        f.original.config.selection = selected.snapshot().clone();
        f.original.config.selection_evidence = selected.attestation().clone();
        f.original.selection = selected.receipt().clone();
        f.original.selection_signature = selected.attestation().clone();
        Ok(Self {
            f,
            selector,
            selection_context,
            selected,
        })
    }

    fn context(&self) -> anyhow::Result<OriginalCircuitNextUseCommandContextV1> {
        Ok(
            OriginalCircuitNextUseCommandContextV1::from_original_selection(
                self.f.original.config.scope.clone(),
                self.f.original.config.verifier.clone(),
                &self.selected,
            )?,
        )
    }

    async fn complete_c(&self) -> anyhow::Result<()> {
        let publication = execute(&self.f.original.session, 1).await?;
        let actual = read_receipt(
            &self.f.original.session,
            &self.f.original.definition,
            &publication,
        )?;
        assert_ne!(
            publication.input().scope.run_id,
            self.f.original.previous.input().scope.run_id,
        );
        assert_ne!(
            publication.input().observation,
            self.f.original.previous.input().observation,
        );
        assert_eq!(
            actual.bundle_digest,
            self.f.original.previous_decision.bundle_digest
        );
        Ok(())
    }

    async fn finish(mut self, withdrawn: bool) -> anyhow::Result<()> {
        self.selector.finish(withdrawn)?;
        self.f.original.session.stop().await?;
        Ok(())
    }
}

struct ObserverService {
    owner: Arc<ObserverHost>,
    published: ReadThread,
    trainer: TrainerThread,
    selector: RoleThread,
}

impl ObserverService {
    fn start(
        f: &CompletionFixture,
        owner: OriginalCircuitNextUseReceiptOwnerV1<FileAnchorWitnessStore>,
    ) -> anyhow::Result<Self> {
        let read_context = next_use_context(&f.f.original.config);
        let published = original(&f.f.original, read_context.clone())?;
        let (live, channel) = transport::client(read_context)?;
        let published = transport::serve(published, channel);
        let (trainer, trainer_thread) = fixture_original_receipt_client_until_close(
            f.f.original.initial.clone(),
            f.f.original.training.clone(),
            f.f.original.config.verifier.clone(),
            f.f.original.config.training_evidence.clone(),
        )?;
        // The predecessor is read from the actual original Selector owner.
        let (selector, channel) = command::evidence_client(&f.selection_context)?;
        let selector_thread = command::serve_evidence(Arc::clone(&f.selector.owner), channel);
        let owner = Arc::new(owner.into_command_owner(live, trainer, selector)?);
        Ok(Self {
            owner,
            published,
            trainer: trainer_thread,
            selector: selector_thread,
        })
    }

    fn finish(self, published_failed: bool, selector_failed: bool) -> anyhow::Result<usize> {
        drop(self.owner);
        let published = self
            .published
            .join()
            .map_err(|_| anyhow::anyhow!("original C Published read thread"))?;
        assert_eq!(published.is_err(), published_failed);
        let selector = self
            .selector
            .join()
            .map_err(|_| anyhow::anyhow!("original Selector readback thread"))?;
        assert_eq!(selector.is_err(), selector_failed);
        let reads = self
            .trainer
            .join()
            .map_err(|_| anyhow::anyhow!("original Trainer fixture thread"))??;
        Ok(reads)
    }
}

fn finish_observer(
    client: OriginalCircuitNextUseCommandClientV1,
    server: ObserverThread,
) -> anyhow::Result<u64> {
    drop(client);
    Ok(server
        .join()
        .map_err(|_| anyhow::anyhow!("original Observer command thread"))??)
}

#[tokio::test]
async fn q24_next_use_command_attests_actual_different_c_and_shares_dispatch() -> anyhow::Result<()>
{
    let f = CompletionFixture::ready(None).await?;
    f.complete_c().await?;
    let context = f.context()?;
    let service = ObserverService::start(&f, f.f.original.create_owner()?)?;
    let (client, channel) = next::client(context.clone(), false, None)?;
    let server = next::serve(Arc::clone(&service.owner), channel);
    let before = f.f.original.bytes()?;
    let task_before = owner_bytes(&f.f.original.session)?;
    assert!(matches!(
        client.readback().await,
        Err(OriginalCircuitNextUseCommandErrorV1::Missing)
    ));
    assert_eq!(f.f.original.bytes()?, before);
    let completed = client.attest_completed_task().await?;
    let selected = LearningIterationCoordinatorV1::from_snapshot(f.selected.snapshot().clone())?;
    assert_eq!(
        &completed.receipt().observation,
        &f.f.original.session.cell.read_learning_next_use(
            &selected,
            f.f.original.session.source.as_ref(),
            &f.f.original.session.runtime.identity,
        )?,
    );
    assert_eq!(completed.selection_attestation(), f.selected.attestation());
    assert_eq!(
        completed.training_attestation(),
        f.selected.training_attestation()
    );
    assert_eq!(completed.snapshot().receipts.len(), 5);
    let bytes = f.f.original.bytes()?;
    assert!(matches!(
        client.attest_completed_task().await,
        Err(OriginalCircuitNextUseCommandErrorV1::ReadbackRequired),
    ));
    assert_eq!(client.readback().await?, completed);
    let (second, channel) = next::client(context, false, None)?;
    let second_server = next::serve(Arc::clone(&service.owner), channel);
    assert!(matches!(
        second.attest_completed_task().await,
        Err(OriginalCircuitNextUseCommandErrorV1::ReadbackRequired),
    ));
    assert_eq!(second.readback().await?, completed);
    assert_eq!(f.f.original.bytes()?, bytes);
    assert_eq!(owner_bytes(&f.f.original.session)?, task_before);
    assert_eq!(finish_observer(client, server)?, 3);
    assert_eq!(finish_observer(second, second_server)?, 2);
    assert!(service.finish(false, false)? > 0);
    f.finish(false).await?;
    Ok(())
}

#[tokio::test]
async fn q24_next_use_command_lost_ack_recovers_exact_original_signature_readonly()
-> anyhow::Result<()> {
    let f = CompletionFixture::ready(None).await?;
    f.complete_c().await?;
    let context = f.context()?;
    let service = ObserverService::start(&f, f.f.original.create_owner()?)?;
    let (client, channel) = next::client(context.clone(), false, None)?;
    let server = next::lose_ack(Arc::clone(&service.owner), channel);
    assert!(matches!(
        client.attest_completed_task().await,
        Err(OriginalCircuitNextUseCommandErrorV1::CommitUncertain)
    ));
    assert!(matches!(
        client.readback().await,
        Err(OriginalCircuitNextUseCommandErrorV1::Unavailable)
    ));
    drop(client);
    let original = server
        .join()
        .map_err(|_| anyhow::anyhow!("lost original C ACK"))??;
    let bytes = f.f.original.bytes()?;
    assert!(service.finish(false, false)? > 0);

    let recovered = ObserverService::start(&f, f.f.original.recover_owner()?)?;
    let (fresh, channel) = next::client(context, false, None)?;
    let fresh_server = next::serve(Arc::clone(&recovered.owner), channel);
    assert!(matches!(
        fresh.attest_completed_task().await,
        Err(OriginalCircuitNextUseCommandErrorV1::ReadbackRequired)
    ));
    assert_eq!(fresh.readback().await?, original);
    let (cold, channel) = next::recover_client(
        f.selected.snapshot().clone(),
        f.f.original.config.scope.clone(),
        f.f.original.config.verifier.clone(),
        f.selected.training_attestation().clone(),
        f.selected.attestation().clone(),
        Some((original.snapshot().clone(), original.attestation().clone())),
    )?;
    let cold_server = next::serve(Arc::clone(&recovered.owner), channel);
    assert!(matches!(
        cold.attest_completed_task().await,
        Err(OriginalCircuitNextUseCommandErrorV1::ReadbackRequired)
    ));
    assert_eq!(cold.readback().await?, original);
    assert_eq!(
        cold.receipt_attestation(original.receipt()).await?,
        *original.attestation()
    );
    assert_eq!(f.f.original.bytes()?, bytes);
    assert_eq!(finish_observer(fresh, fresh_server)?, 2);
    assert_eq!(finish_observer(cold, cold_server)?, 2);
    assert!(recovered.finish(false, false)? > 0);
    f.finish(false).await?;
    Ok(())
}

#[tokio::test]
async fn q24_next_use_command_early_dispatch_never_runs_c_or_resets_admission() -> anyhow::Result<()>
{
    let f = CompletionFixture::ready(None).await?;
    let context = f.context()?;
    let service = ObserverService::start(&f, f.f.original.create_owner()?)?;
    let (client, channel) = next::client(context.clone(), false, None)?;
    let server = next::serve(Arc::clone(&service.owner), channel);
    let before = f.f.original.bytes()?;
    let task_before = owner_bytes(&f.f.original.session)?;
    assert!(matches!(
        client.attest_completed_task().await,
        Err(OriginalCircuitNextUseCommandErrorV1::CommitUncertain)
    ));
    assert!(matches!(
        client.readback().await,
        Err(OriginalCircuitNextUseCommandErrorV1::Unavailable)
    ));
    assert_eq!(f.f.original.bytes()?, before);
    assert_eq!(owner_bytes(&f.f.original.session)?, task_before);
    assert_eq!(finish_observer(client, server)?, 1);
    // The original C publication rejects before either predecessor is read.
    assert_eq!(service.finish(true, false)?, 0);

    // The ordinary task machinery, outside the Observer, now really runs C.
    // Restoring the original owner cannot convert the failed dispatch into
    // permission to issue a new attestation.
    f.complete_c().await?;
    let recovered = ObserverService::start(&f, f.f.original.recover_owner()?)?;
    let (client, channel) = next::client(context, false, None)?;
    let server = next::serve(Arc::clone(&recovered.owner), channel);
    assert!(matches!(
        client.attest_completed_task().await,
        Err(OriginalCircuitNextUseCommandErrorV1::ReadbackRequired)
    ));
    assert!(matches!(
        client.readback().await,
        Err(OriginalCircuitNextUseCommandErrorV1::Missing)
    ));
    assert_eq!(f.f.original.bytes()?, before);
    assert_eq!(finish_observer(client, server)?, 2);
    assert!(recovered.finish(false, false)? > 0);
    f.finish(false).await?;
    Ok(())
}

#[tokio::test]
async fn q24_next_use_command_pins_both_original_signatures_before_dispatch() -> anyhow::Result<()>
{
    let f = CompletionFixture::ready(None).await?;
    f.complete_c().await?;
    let context = f.context()?;
    let service = ObserverService::start(&f, f.f.original.create_owner()?)?;
    let before = f.f.original.bytes()?;
    next::reject_wrong_context(&service.owner)?;
    next::cancel_queued_execute(Arc::clone(&service.owner)).await?;
    assert_eq!(f.f.original.bytes()?, before);
    for role in [
        LearningEvidenceRoleV1::Generator,
        LearningEvidenceRoleV1::Selector,
    ] {
        let mut training = f.selected.training_attestation().clone();
        let mut selection = f.selected.attestation().clone();
        let (signature, key, receipt) = if role == LearningEvidenceRoleV1::Generator {
            (
                &mut training,
                SigningKey::from_bytes(&[101; 32]),
                &f.f.original.training,
            )
        } else {
            (
                &mut selection,
                SigningKey::from_bytes(&[102; 32]),
                f.selected.receipt(),
            )
        };
        signature.expires_at += 1;
        signature.signature = key.sign(&signature.signing_bytes()).to_bytes();
        f.f.original.config.verifier.verify(
            role,
            signature,
            &learning_iteration_receipt_signing_bytes_v1(receipt)?,
            now()?,
        )?;
        let (wrong, channel) = next::recover_client(
            f.selected.snapshot().clone(),
            f.f.original.config.scope.clone(),
            f.f.original.config.verifier.clone(),
            training,
            selection,
            None,
        )?;
        let wrong_server = next::serve(Arc::clone(&service.owner), channel);
        assert!(matches!(
            wrong.readback().await,
            Err(OriginalCircuitNextUseCommandErrorV1::CommitUncertain)
        ));
        drop(wrong);
        assert!(
            wrong_server
                .join()
                .map_err(|_| anyhow::anyhow!("renewed predecessor"))?
                .is_err()
        );
        assert_eq!(f.f.original.bytes()?, before);
    }
    let (client, channel) = next::client(context, false, None)?;
    let server = next::serve(Arc::clone(&service.owner), channel);
    client.attest_completed_task().await?;
    assert_ne!(f.f.original.bytes()?, before);
    assert_eq!(finish_observer(client, server)?, 1);
    assert!(service.finish(false, false)? > 0);
    f.finish(false).await?;
    Ok(())
}

#[tokio::test]
async fn q24_next_use_command_readback_refuses_actual_publication_withdrawal() -> anyhow::Result<()>
{
    let mut f = CompletionFixture::ready(None).await?;
    f.complete_c().await?;
    let context = f.context()?;
    let service = ObserverService::start(&f, f.f.original.create_owner()?)?;
    let (client, channel) = next::client(context.clone(), false, None)?;
    let server = next::serve(Arc::clone(&service.owner), channel);
    let completed = client.attest_completed_task().await?;
    let bytes = f.f.original.bytes()?;
    let task_bytes = owner_bytes(&f.f.original.session)?;

    // The legacy evidence lane remains bounded to 500 ms. Complete the real
    // owner read, then hold only its ACK until this original client times out.
    // No signature, snapshot or CURRENT response is synthesized by this gate.
    let (evidence, channel) = next::evidence_client(&context)?;
    let (release, evidence_server) =
        next::serve_evidence_late_response(Arc::clone(&service.owner), channel);
    let started = std::time::Instant::now();
    let legacy = evidence
        .readback(completed.snapshot(), completed.receipt())
        .await;
    eprintln!(
        "LEARN_C_LEGACY_BOUND elapsed_us={} result={:?}",
        started.elapsed().as_micros(),
        legacy.as_ref().map(|_| ()),
    );
    assert!(matches!(
        legacy,
        Err(crate::LearningIterationRuntimeErrorV1::OwnerUnavailable(
            "original learning evidence owner"
        ))
    ));
    release.send(())?;
    // The server still awaits original Tokio I/O. Joining on the sole runtime
    // thread would stop its reactor after the client's timeout.
    let (original_responses, evidence_terminal) =
        tokio::task::spawn_blocking(move || evidence_server.join())
            .await?
            .map_err(|_| anyhow::anyhow!("original bounded Observer evidence peer"))?;
    assert_eq!(original_responses, 1);
    eprintln!("LEARN_C_LEGACY_BOUND peer_terminal={evidence_terminal:?}");
    assert!(matches!(
        evidence_terminal,
        Err(OriginalCircuitNextUseCommandErrorV1::Transport(
            codex_hepta_contracts::HostIssuerTransportError::DeadlineElapsed
                | codex_hepta_contracts::HostIssuerTransportError::Closed
                | codex_hepta_contracts::HostIssuerTransportError::Unavailable
        ))
    ));
    assert_eq!(f.f.original.bytes()?, bytes);
    assert_eq!(owner_bytes(&f.f.original.session)?, task_bytes);

    // Root's actual stage adapter uses this already-held command capability.
    // A fresh full read proves that a late legacy reply is not used as CURRENT.
    let started = std::time::Instant::now();
    let current = client.readback().await;
    eprintln!(
        "LEARN_C_COMMAND_CURRENT elapsed_us={} result={:?}",
        started.elapsed().as_micros(),
        current.as_ref().map(|_| ()),
    );
    let current = current?;
    assert_eq!(current, completed);
    assert_eq!(current.attestation(), completed.attestation());
    assert_eq!(f.f.original.bytes()?, bytes);
    assert_eq!(owner_bytes(&f.f.original.session)?, task_bytes);

    f.f.original.version.withdraw()?;
    assert!(matches!(
        evidence
            .readback(completed.snapshot(), completed.receipt())
            .await,
        Err(crate::LearningIterationRuntimeErrorV1::OwnerUnavailable(
            "original learning evidence owner"
        ))
    ));
    drop(evidence);
    assert!(matches!(
        client.readback().await,
        Err(OriginalCircuitNextUseCommandErrorV1::CommitUncertain)
    ));
    assert_eq!(f.f.original.bytes()?, bytes);
    assert_eq!(owner_bytes(&f.f.original.session)?, task_bytes);
    let commands = tokio::task::spawn_blocking(move || finish_observer(client, server)).await??;
    // Execute, independent full CURRENT, then the actual withdrawal rejection.
    assert_eq!(commands, 3);
    // The actual C publication rejects before another predecessor read.
    // The Selector channel is left unmodified, never replaced or retried.
    assert!(tokio::task::spawn_blocking(move || service.finish(true, false)).await?? > 0);
    f.finish(false).await?;
    Ok(())
}

#[tokio::test]
async fn q24_next_use_command_preserves_original_expiry_and_external_custody() -> anyhow::Result<()>
{
    let f = CompletionFixture::ready(Some(10)).await?;
    f.complete_c().await?;
    let context = f.context()?;
    let peer = next::identity()?;
    let (stream, unused) = UnixStream::pair()?;
    // SAFETY: observe only this test process, which production must reject.
    let uid = unsafe { libc::geteuid() };
    assert!(
        OriginalCircuitNextUseCommandClientV1::from_original_stream(
            stream,
            crate::LearningIterationEvidencePeerV1 {
                pid: peer.pid,
                uid,
                boot_id: peer.boot_id.clone(),
                process_start_ticks: peer.process_start_ticks,
                actor_id: f
                    .f
                    .original
                    .config
                    .selection
                    .owners
                    .next_use_observer
                    .clone(),
            },
            next::pidfd()?,
            context.clone(),
            Duration::from_secs(30),
            Duration::from_secs(300),
        )
        .is_err()
    );
    drop(unused);
    let (stream, unused) = UnixStream::pair()?;
    assert!(
        OriginalCircuitNextUseCommandClientV1::recover_from_original_stream(
            stream,
            crate::LearningIterationEvidencePeerV1 {
                pid: peer.pid,
                uid,
                boot_id: peer.boot_id,
                process_start_ticks: peer.process_start_ticks,
                actor_id: f
                    .f
                    .original
                    .config
                    .selection
                    .owners
                    .next_use_observer
                    .clone(),
            },
            next::pidfd()?,
            f.selected.snapshot().clone(),
            f.f.original.config.scope.clone(),
            f.f.original.config.verifier.clone(),
            f.selected.training_attestation().clone(),
            f.selected.attestation().clone(),
            None,
            Duration::from_secs(30),
            Duration::from_secs(300),
        )
        .is_err()
    );
    drop(unused);
    let service = ObserverService::start(&f, f.f.original.create_owner()?)?;
    let (client, channel) = next::client(context, false, None)?;
    let server = next::serve(Arc::clone(&service.owner), channel);
    assert!(matches!(
        client.readback().await,
        Err(OriginalCircuitNextUseCommandErrorV1::Missing)
    ));
    let bytes = f.f.original.bytes()?;
    let expires = f.selected.attestation().expires_at;
    // Original evidence remains valid throughout its expiry second. Wait
    // beyond that inclusive bound before testing refusal without an effect.
    let invalid_from = expires
        .checked_add(1)
        .ok_or_else(|| anyhow::anyhow!("original evidence expiry overflow"))?;
    tokio::time::sleep(
        Duration::from_secs(invalid_from.saturating_sub(now()?)) + Duration::from_millis(100),
    )
    .await;
    assert!(now()? > expires);
    assert!(matches!(
        client.attest_completed_task().await,
        Err(OriginalCircuitNextUseCommandErrorV1::Evidence(
            codex_hepta_learning_ledger::SignedEvidenceError::ValidityWindow
        ))
    ));
    assert!(matches!(
        client.readback().await,
        Err(OriginalCircuitNextUseCommandErrorV1::Unavailable)
    ));
    assert_eq!(f.f.original.bytes()?, bytes);
    assert_eq!(finish_observer(client, server)?, 1);
    assert!(service.finish(false, false)? > 0);
    f.finish(false).await?;
    Ok(())
}

#[path = "circuit_completion_readiness_owner_tests.rs"]
mod readiness;
