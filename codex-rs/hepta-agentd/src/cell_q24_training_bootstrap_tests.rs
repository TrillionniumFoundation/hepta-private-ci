//! Actual deferred original Training over the same Material command owner,
//! Source service and both original evidence producers. Credential enrollment,
//! same-UID framing and cohorts are explicit fixtures; this does not claim
//! deployed independent role hosts or a daemon/Root cold restart.
use std::sync::atomic::AtomicBool;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::WitnessStoreError;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::super::wire;
use super::*;
use crate::OriginalCellQ24MaterialCommandErrorV1 as MaterialError;
use crate::OriginalCellQ24MaterialEvidenceRoleV1 as Role;
use crate::OriginalCellQ24MaterialSourceErrorV1 as SourceError;
use crate::OriginalCellQ24TrainingCommandErrorV1 as CommandError;
use crate::cell_q24_material_receipt_owner::MaterialCommandFixture;
use crate::learning_iteration_evidence_client::command_test_support as transport;
use crate::learning_iteration_evidence_client::material::bootstrap_ports as material;

#[path = "cell_q24_training_bootstrap_support_tests.rs"]
pub(super) mod support;
use support::*;

fn unbound_request(f: &MaterialCommandFixture, action: wire::Action) -> wire::Request {
    wire::Request {
        schema: 1,
        operation: wire::OPERATION.into(),
        request_id: 1,
        binding: Digest32::of_bytes(b"unresolved-original-training-context").to_string(),
        operation_id: f.config.initial.request.operation_id.to_string(),
        dataset_head: Digest32::of_bytes(b"not-an-asserted-Dataset-head").to_string(),
        scope_binding: f.config.scope.binding().to_string(),
        actor_id: f.config.initial.owners.trainer.to_string(),
        action,
        cancelled: false,
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn deferred_training_uses_actual_material_cut_and_original_source_without_precreation()
-> anyhow::Result<()> {
    let fixture = MaterialCommandFixture::new().await?;
    let original_material = fixture.bytes()?;
    let (owner, peers) = support::owner(&fixture, Origin::Fresh)?;
    let (connection, server) = prebound(
        Arc::clone(&owner),
        fixture.config.clone(),
        Origin::Fresh,
        None,
        Duration::from_secs(300),
    )?;
    let (readback_connection, readback_server) = original_readback::prebound(
        Arc::clone(&owner),
        fixture.config.clone(),
        Duration::from_secs(300),
    )?;
    let before = fixture.training_bytes()?;
    assert!(before[0].is_empty() && before[2].is_empty());
    assert_eq!(fixture.bytes()?, original_material);
    // Both original stages really execute after the Trainer host was bound.
    let cut = complete_material(&fixture).await?;
    assert_eq!(fixture.training_bytes()?, before);
    let context = context(&fixture, &cut);
    let client = connection.bind_original_dataset(cut.clone())?;
    assert!(matches!(
        client.readback().await,
        Err(CommandError::ReadbackRequired)
    ));
    assert_eq!(fixture.training_bytes()?, before);
    let started = Instant::now();
    let completed = client
        .execute_training(Arc::new(AtomicBool::new(false)))
        .await;
    eprintln!(
        "HEPTA_DEFERRED_TRAINING_EXECUTE elapsed_us={} result={:?}",
        started.elapsed().as_micros(),
        completed.as_ref().map(|_| ()).map_err(ToString::to_string)
    );
    let completed = completed?;
    assert!(matches!(
        completed.receipt().observation,
        LearningIterationObservationV1::TrainingNoUpdateV2(_)
    ));
    let after = fixture.training_bytes()?;
    assert_ne!(before, after);
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

    // The deep original Source stays live, while this distinct read-only
    // command purpose keeps its initially admitted 30-s/300-s bounds.
    // Existing local-owner legacy evidence mechanisms still cover 500 ms.
    let evidence = readback_connection.bind_original_training(cut, completed.clone())?;
    let started = Instant::now();
    let observed = evidence
        .readback(&context.dataset, completed.receipt())
        .await;
    let client_elapsed = started.elapsed().as_micros();
    drop(evidence);
    let server_result = readback_server
        .join()
        .expect("actual Training read-only producer");
    eprintln!(
        "HEPTA_DEFERRED_TRAINING_READONLY client_us={client_elapsed} total_us={} client={:?} server={:?}",
        started.elapsed().as_micros(),
        observed.as_ref().map(|_| ()).map_err(ToString::to_string),
        server_result
            .as_ref()
            .map(|n| *n)
            .map_err(ToString::to_string)
    );
    assert_eq!(observed?, *completed.attestation());
    assert_eq!(server_result?, 1);
    assert_eq!(fixture.training_bytes()?, after);
    assert_eq!(finish(client, server)?, 4);
    drop(owner);
    let counts = finish_material(peers)?;
    eprintln!(
        "HEPTA_DEFERRED_TRAINING_MATERIAL_COUNTS dataset={} source={} experience={} dataset_evidence={}",
        counts[0], counts[1], counts[2], counts[3]
    );
    assert_eq!(
        counts[0], 1,
        "the host reads the actual Dataset command once"
    );
    assert!(counts[1] > 0 && counts[2] > 0 && counts[3] > 0);
    assert_eq!(
        counts[2], counts[3],
        "both original evidence owners are read equally"
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn deferred_training_lost_ack_recovers_same_job_and_original_signature() -> anyhow::Result<()>
{
    let fixture = MaterialCommandFixture::new().await?;
    let (owner, peers) = support::owner(&fixture, Origin::Fresh)?;
    let cut = complete_material(&fixture).await?;
    let context = context(&fixture, &cut);
    let (client, lost) = lose_ack(Arc::clone(&owner), context.clone())?;
    assert!(matches!(
        client
            .execute_training(Arc::new(AtomicBool::new(false)))
            .await,
        Err(CommandError::CommitUncertain)
    ));
    drop(client);
    lost.join().expect("only original ACK lost")?;
    let after = fixture.training_bytes()?;
    let (reader, server) = connected(Arc::clone(&owner), context.clone(), Origin::Recovered, None)?;
    let original = reader.readback().await?;
    assert_eq!(fixture.training_bytes()?, after);
    assert_eq!(finish(reader, server)?, 1);
    drop(owner);
    finish_material(peers)?;

    // A caller mislabelling these existing files Fresh cannot make Awaiting
    // assert that native work is Missing, even for an unrelated D correlation.
    let (custody, dataset, peers) = inputs(&fixture, Origin::Recovered)?;
    let fresh = Arc::new(Host::from_original_custody(
        custody,
        fixture.training_configuration(),
        dataset,
        Arc::new(AtomicBool::new(false)),
    )?);
    let response = raw_response(
        Arc::clone(&fresh),
        unbound_request(&fixture, wire::Action::Readback),
    )
    .await??;
    assert!(matches!(
        response.result,
        wire::CommandResult::ReadbackRequired
    ));
    assert_eq!(fixture.training_bytes()?, after);
    assert!(matches!(
        &*fresh.state.lock().expect("state"),
        State::Awaiting(_)
    ));
    drop(fresh);
    assert_eq!(finish_material(peers)?, [0; 4]);

    let (recovered, peers) = support::owner(&fixture, Origin::Recovered)?;
    let (reader, server) = connected(
        Arc::clone(&recovered),
        context,
        Origin::Recovered,
        Some(original.clone()),
    )?;
    assert_eq!(reader.readback().await?, original);
    assert!(matches!(
        reader
            .execute_training(Arc::new(AtomicBool::new(false)))
            .await,
        Err(CommandError::ReadbackRequired)
    ));
    assert_eq!(fixture.training_bytes()?, after);
    assert_eq!(finish(reader, server)?, 1);
    drop(recovered);
    assert_eq!(finish_material(peers)?[0], 1);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn deferred_training_missing_dataset_or_partial_owners_never_bootstrap_replacements()
-> anyhow::Result<()> {
    let fixture = MaterialCommandFixture::new().await?;
    let (owner, peers) = support::owner(&fixture, Origin::Fresh)?;
    let before = fixture.training_bytes()?;
    for action in [wire::Action::Readback, wire::Action::Execute] {
        let response =
            raw_response(Arc::clone(&owner), unbound_request(&fixture, action)).await??;
        match action {
            wire::Action::Readback => assert!(matches!(
                response.result,
                wire::CommandResult::ReadbackRequired
            )),
            wire::Action::Execute => {
                assert!(matches!(response.result, wire::CommandResult::Unavailable))
            }
        }
        assert!(matches!(
            &*owner.state.lock().expect("state"),
            State::Awaiting(_)
        ));
        assert_eq!(fixture.training_bytes()?, before);
    }
    drop(owner);
    assert_eq!(finish_material(peers)?, [1, 0, 0, 0]);

    let fixture = MaterialCommandFixture::new().await?;
    let (mut custody, dataset, peers) = inputs(&fixture, Origin::Fresh)?;
    custody.receipt_file = fixture.readonly_training_receipt()?;
    let owner = Arc::new(Host::from_original_custody(
        custody,
        fixture.training_configuration(),
        dataset,
        Arc::new(AtomicBool::new(false)),
    )?);
    let before = fixture.training_bytes()?;
    let cut = complete_material(&fixture).await?;
    let context = context(&fixture, &cut);
    let (client, server) = connected(Arc::clone(&owner), context.clone(), Origin::Fresh, None)?;
    assert!(matches!(
        client
            .execute_training(Arc::new(AtomicBool::new(false)))
            .await,
        Err(CommandError::CommitUncertain)
    ));
    drop(client);
    assert!(server.join().expect("partial bootstrap producer").is_err());
    let partial = fixture.training_bytes()?;
    assert_ne!(partial[0], before[0]);
    assert_eq!(&partial[2..], &before[2..]);
    assert!(matches!(
        &*owner.state.lock().expect("state"),
        State::Fenced
    ));
    drop(owner);
    finish_material(peers)?;
    let (recovered, peers) = support::owner(&fixture, Origin::Recovered)?;
    let (reader, server) = connected(Arc::clone(&recovered), context, Origin::Recovered, None)?;
    assert!(matches!(
        reader.readback().await,
        Err(CommandError::CommitUncertain)
    ));
    drop(reader);
    assert!(server.join().expect("partial cold bootstrap").is_err());
    assert_eq!(
        fixture.training_bytes()?,
        partial,
        "recovery does not finish a missing original owner"
    );
    drop(recovered);
    finish_material(peers)?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn deferred_training_wrong_context_does_not_consume_original_custody() -> anyhow::Result<()> {
    let fixture = MaterialCommandFixture::new().await?;
    let (owner, peers) = support::owner(&fixture, Origin::Fresh)?;
    let before = fixture.training_bytes()?;
    let cut = complete_material(&fixture).await?;
    let valid = context(&fixture, &cut);
    let mut changed = LearningIterationCoordinatorV1::new(
        valid.dataset.request.clone(),
        valid.dataset.owners.clone(),
    )?;
    for mut receipt in valid.dataset.receipts.clone() {
        if matches!(
            receipt.observation,
            LearningIterationObservationV1::Dataset { .. }
        ) {
            receipt.evidence_digest = Digest32::of_bytes(b"unsigned-rebound-Dataset-negative");
        }
        let at = receipt.observed_unix_seconds;
        changed.record(receipt, at)?;
    }
    let mut wrong = valid.clone();
    wrong.dataset = changed.snapshot().clone();
    let (client, server) = connected(Arc::clone(&owner), wrong, Origin::Fresh, None)?;
    assert!(matches!(
        client
            .execute_training(Arc::new(AtomicBool::new(false)))
            .await,
        Err(CommandError::CommitUncertain)
    ));
    drop(client);
    assert!(server.join().expect("wrong Dataset context").is_err());
    assert_eq!(fixture.training_bytes()?, before);
    assert!(matches!(
        &*owner.state.lock().expect("state"),
        State::Awaiting(_)
    ));
    let (client, server) = connected(Arc::clone(&owner), valid, Origin::Fresh, None)?;
    let original = client
        .execute_training(Arc::new(AtomicBool::new(false)))
        .await?;
    assert!(matches!(
        original.receipt().observation,
        LearningIterationObservationV1::TrainingNoUpdateV2(_)
    ));
    assert_ne!(fixture.training_bytes()?, before);
    assert_eq!(finish(client, server)?, 1);
    drop(owner);
    assert_eq!(finish_material(peers)?[0], 2);
    Ok(())
}

struct LostNativeClaimAck(FileAnchorWitnessStore);
impl AnchorWitnessStore for LostNativeClaimAck {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.0.current()
    }
    fn compare_and_swap(
        &mut self,
        before: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.0.compare_and_swap(before, next)?;
        if next.sequence == 2 {
            return Err(WitnessStoreError::Indeterminate);
        }
        Ok(())
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn deferred_training_failed_source_or_pending_claim_never_rearms() -> anyhow::Result<()> {
    let mut fixture = MaterialCommandFixture::new().await?;
    let (owner, peers) = support::owner(&fixture, Origin::Fresh)?;
    let cut = complete_material(&fixture).await?;
    let before = fixture.training_bytes()?;
    let captured = Arc::new(tokio::sync::Notify::new());
    let release = Arc::new(tokio::sync::Notify::new());
    *owner.writer_gate.lock().expect("gate") = Some(WriterGate {
        captured: Arc::clone(&captured),
        release: Arc::clone(&release),
    });
    let (client, server) = connected(
        Arc::clone(&owner),
        context(&fixture, &cut),
        Origin::Fresh,
        None,
    )?;
    let client = Arc::new(client);
    let task = tokio::spawn({
        let client = Arc::clone(&client);
        async move {
            client
                .execute_training(Arc::new(AtomicBool::new(false)))
                .await
        }
    });
    tokio::time::timeout(Duration::from_secs(30), captured.notified()).await?;
    // The actual Source capture has finished; writer work has not begun.
    fixture.withdraw()?;
    release.notify_one();
    assert!(matches!(task.await?, Err(CommandError::CommitUncertain)));
    drop(client);
    assert!(server.join().expect("withdrawn queued source").is_err());
    assert!(matches!(
        &*owner.state.lock().expect("state"),
        State::Fenced
    ));
    assert_eq!(
        fixture.training_bytes()?,
        before,
        "no writer initializes after capture withdrawal"
    );
    drop(owner);
    // The actual rejected source/evidence peer closes its original channel.
    for peer in peers {
        let _original_result = peer.join().expect("original withdrawal peer");
    }

    let fixture = MaterialCommandFixture::new().await?;
    let (custody, dataset, peers) = inputs(&fixture, Origin::Fresh)?;
    let OriginalCellQ24TrainingBootstrapCustodyV1 {
        native_file,
        native_witness,
        receipt_file,
        receipt_witness,
        generator_key,
        baseline,
        material_source,
        experience,
        dataset: data_evidence,
    } = custody;
    let owner = Arc::new(
        OriginalCellQ24TrainingBootstrapOwnerV1::from_original_custody(
            OriginalCellQ24TrainingBootstrapCustodyV1 {
                native_file,
                native_witness: LostNativeClaimAck(native_witness),
                receipt_file,
                receipt_witness,
                generator_key,
                baseline,
                material_source,
                experience,
                dataset: data_evidence,
            },
            fixture.training_configuration(),
            dataset,
            Arc::new(AtomicBool::new(false)),
        )?,
    );
    let cut = complete_material(&fixture).await?;
    let context = context(&fixture, &cut);
    let (client, server) = connected(Arc::clone(&owner), context.clone(), Origin::Fresh, None)?;
    assert!(matches!(
        client
            .execute_training(Arc::new(AtomicBool::new(false)))
            .await,
        Err(CommandError::CommitUncertain)
    ));
    drop(client);
    assert_eq!(
        server.join().expect("lost native claim acknowledgement")?,
        1
    );
    let pending = fixture.training_bytes()?;
    drop(owner);
    finish_material(peers)?;
    let (recovered, peers) = support::owner(&fixture, Origin::Recovered)?;
    let (reader, server) = connected(Arc::clone(&recovered), context, Origin::Recovered, None)?;
    assert!(matches!(
        reader.readback().await,
        Err(CommandError::Pending)
    ));
    assert!(matches!(
        reader
            .execute_training(Arc::new(AtomicBool::new(false)))
            .await,
        Err(CommandError::ReadbackRequired)
    ));
    assert_eq!(fixture.training_bytes()?, pending);
    assert_eq!(finish(reader, server)?, 1);
    drop(recovered);
    finish_material(peers)?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn deferred_training_attenuation_and_prebound_transport_preserve_original_custody()
-> anyhow::Result<()> {
    let fixture = MaterialCommandFixture::new().await?;
    let before = fixture.bytes()?;
    let (experience, peer) = material::commands(&fixture, Role::Experience)?;
    assert!(matches!(
        experience.into_original_dataset_readback(&fixture.config),
        Err(MaterialError::Binding(
            "same original Dataset command context"
        ))
    ));
    assert_eq!(material::finish(peer)?, 0);
    let (dataset, peer) = material::commands(&fixture, Role::Dataset)?;
    let mut changed = fixture.config.clone();
    changed.maximum_signature_lifetime_seconds -= 1;
    assert!(matches!(
        dataset.into_original_dataset_readback(&changed),
        Err(MaterialError::Binding(
            "same original Dataset command context"
        ))
    ));
    assert_eq!(material::finish(peer)?, 0);
    assert_eq!(fixture.bytes()?, before);

    let cut = complete_material(&fixture).await?;
    let (dataset, peer) = material::commands(&fixture, Role::Dataset)?;
    let readonly = dataset.into_original_dataset_readback(&fixture.config)?;
    assert_eq!(readonly.readback().await?, cut);
    drop(readonly);
    assert_eq!(material::finish(peer)?, 1);

    let original_peer = transport::identity()?;
    let (stream, _server) = std::os::unix::net::UnixStream::pair()?;
    assert!(matches!(
        OriginalCellQ24MaterialSourceConnectionV1::from_original_stream(
            stream,
            crate::LearningIterationEvidencePeerV1 {
                pid: original_peer.pid,
                // SAFETY: explicit test rejection of its own process custody.
                uid: unsafe { libc::geteuid() },
                boot_id: original_peer.boot_id,
                process_start_ticks: original_peer.process_start_ticks,
                actor_id: fixture.config.initial.owners.dataset.clone(),
            },
            transport::pidfd()?,
            fixture.config.initial.clone(),
            fixture.config.scope.clone(),
            fixture.training_baseline(),
            Duration::from_millis(500),
            Duration::from_secs(300),
        ),
        Err(SourceError::Binding(
            "original Material connection and empty Root cut"
        ))
    ));
    let retained_material = fixture.bytes()?;
    let (connection, peer) = material::source_connection(&fixture, Duration::from_millis(40))?;
    tokio::time::sleep(Duration::from_millis(80)).await;
    let remote = OriginalCellQ24MaterialSourceConnectionV1::bind_original_dataset(
        connection,
        source_config(&fixture, &cut),
    )?;
    assert!(matches!(
        remote.read_current().await,
        Err(SourceError::Unavailable)
    ));
    drop(remote);
    assert!(
        material::finish(peer).is_err(),
        "finalization never restarts the expired transport"
    );
    assert_eq!(fixture.bytes()?, retained_material);
    Ok(())
}

#[path = "cell_q24_training_command_connection_tests.rs"]
mod command_connection;

#[path = "cell_q24_training_candidate_tests.rs"]
mod candidate_material;

#[path = "cell_q24_training_readback_tests.rs"]
mod original_readback;
