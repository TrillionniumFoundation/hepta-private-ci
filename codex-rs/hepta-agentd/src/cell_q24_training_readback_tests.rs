//! Actual deferred Trainer and four original Material services. Same-UID
//! admission and Outcome enrollment are explicit test custody, not deployment.
use super::super::super::readonly;
use super::*;
use crate::LearningIterationEvidenceClientV1;
use crate::LearningIterationRuntimeErrorV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::OriginalCellQ24TrainingReadbackConnectionV1;
use crate::learning_iteration_evidence_client::wire as evidence_wire;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::thread::JoinHandle;

pub(super) fn prebound(
    owner: Arc<Host>,
    config: OriginalCellQ24MaterialReceiptConfigV1,
    lifetime: Duration,
) -> anyhow::Result<(OriginalCellQ24TrainingReadbackConnectionV1, Server)> {
    let (connection, mut channel) = readonly::test_support::connection(config, lifetime)?;
    let server =
        std::thread::spawn(move || owner.serve_original_training_readback_channel(&mut channel));
    Ok((connection, server))
}

async fn train(
    fixture: &MaterialCommandFixture,
    owner: &Arc<Host>,
    dataset: &OriginalCellQ24MaterialCommandReceiptV1,
) -> anyhow::Result<OriginalCellQ24TrainingCommandReceiptV1> {
    let (client, server) = connected(
        Arc::clone(owner),
        context(fixture, dataset),
        Origin::Fresh,
        /*expected*/ None,
    )?;
    let completed = client
        .execute_training(Arc::new(AtomicBool::new(/*v*/ false)))
        .await?;
    assert!(matches!(
        completed.receipt().observation,
        LearningIterationObservationV1::TrainingNoUpdateV2(_)
    ));
    assert_eq!(finish(client, server)?, 1);
    Ok(completed)
}

fn join_readback(client: LearningIterationEvidenceClientV1, server: Server) -> anyhow::Result<u64> {
    drop(client);
    Ok(server
        .join()
        .expect("original Trainer read-only endpoint")?)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_training_readback_unready_and_wrong_purpose_never_initialize()
-> anyhow::Result<()> {
    let fixture = MaterialCommandFixture::new().await?;
    let (owner, peers) = support::owner(&fixture, Origin::Fresh)?;
    let original = fixture.training_bytes()?;
    let dataset = complete_material(&fixture).await?;
    let context = context(&fixture, &dataset);
    let mut request = readonly::request(&context, readonly::binding(&context)?, 1);
    let bytes = serde_json::to_vec(&request)?;
    let response: wire::Response =
        serde_json::from_slice(&owner.original_training_readback_response(&bytes, 1)?)?;
    assert!(matches!(
        response.result,
        wire::CommandResult::ReadbackRequired
    ));
    assert!(
        owner.command_response(&bytes, 1).is_err(),
        "new purpose is not old bootstrap"
    );
    request.operation = wire::OPERATION.into();
    assert!(
        owner
            .original_training_readback_response(&serde_json::to_vec(&request)?, 1,)
            .is_err()
    );
    request.operation = readonly::OPERATION.into();
    request.action = wire::Action::Execute;
    assert!(
        owner
            .original_training_readback_response(&serde_json::to_vec(&request)?, 1,)
            .is_err(),
        "read-only endpoint must reject Execute before Ready"
    );
    assert!(matches!(
        &*owner.state.lock().expect("state"),
        State::Awaiting(_)
    ));
    assert_eq!(fixture.training_bytes()?, original);
    let (initial, initial_server) = prebound(
        Arc::clone(&owner), fixture.config.clone(), Duration::from_secs(300),
    )?;
    assert!(matches!(
        initial.read_original_training(dataset.clone()).await,
        Err(CommandError::ReadbackRequired)
    ));
    assert_eq!(
        initial_server.join().expect("unready original first read")?,
        1
    );
    assert!(matches!(&*owner.state.lock().expect("state"), State::Awaiting(_)));
    assert_eq!(fixture.training_bytes()?, original);
    drop(owner);
    assert_eq!(finish_material(peers)?, [0; 4]);

    // Explicit recovered custody still stays Awaiting on this purpose. It
    // neither opens native history nor upgrades readback to original recovery.
    let (recovered, peers) = support::owner(&fixture, Origin::Recovered)?;
    request.action = wire::Action::Readback;
    let response: wire::Response = serde_json::from_slice(
        &recovered.original_training_readback_response(&serde_json::to_vec(&request)?, 1)?,
    )?;
    assert!(matches!(
        response.result,
        wire::CommandResult::ReadbackRequired
    ));
    assert!(matches!(
        &*recovered.state.lock().expect("state"),
        State::Awaiting(_)
    ));
    assert_eq!(fixture.training_bytes()?, original);
    drop(recovered);
    assert_eq!(finish_material(peers)?, [0; 4]);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_training_readback_preserves_cold_signature_and_initial_deadline()
-> anyhow::Result<()> {
    let fixture = MaterialCommandFixture::new().await?;
    let (owner, peers) = support::owner(&fixture, Origin::Fresh)?;
    let (connection, readonly_server) = prebound(
        Arc::clone(&owner),
        fixture.config.clone(),
        Duration::from_secs(300),
    )?;
    let dataset = complete_material(&fixture).await?;
    let training = train(&fixture, &owner, &dataset).await?;
    let retained = fixture.training_bytes()?;
    let material = fixture.bytes()?;
    let (actual, evidence) = connection.read_original_training(dataset.clone()).await?;
    assert_eq!(actual, training);
    assert_eq!(
        evidence
            .readback(dataset.snapshot(), training.receipt())
            .await?,
        *training.attestation()
    );
    assert_eq!(join_readback(evidence, readonly_server)?, 2);
    assert_eq!(fixture.training_bytes()?, retained);
    assert_eq!(fixture.bytes()?, material);

    // A stream bound to the old command endpoint is rejected by its original
    // operation check. The new client must not silently retry that purpose.
    let (wrong, mut channel) =
        readonly::test_support::connection(fixture.config.clone(), Duration::from_secs(300))?;
    let wrong_server = {
        let owner = Arc::clone(&owner);
        std::thread::spawn(move || owner.serve_command_channel(&mut channel))
    };
    let wrong = wrong.bind_original_training(dataset.clone(), training.clone())?;
    assert!(
        wrong
            .readback(dataset.snapshot(), training.receipt())
            .await
            .is_err()
    );
    assert!(
        wrong
            .readback(dataset.snapshot(), training.receipt())
            .await
            .is_err()
    );
    drop(wrong);
    assert!(
        wrong_server
            .join()
            .expect("wrong-purpose original endpoint")
            .is_err()
    );
    assert_eq!(fixture.training_bytes()?, retained);

    let (expired, mut channel) =
        readonly::test_support::connection(fixture.config.clone(), Duration::from_millis(30))?;
    let expired_server = std::thread::spawn(move || -> anyhow::Result<()> {
        let mut received = false;
        let _closed = channel.exchange(|_| {
            received = true;
            Err(HostIssuerTransportError::Unavailable)
        });
        anyhow::ensure!(
            !received,
            "late binding must not send on an expired initial stream"
        );
        Ok(())
    });
    tokio::time::sleep(Duration::from_millis(60)).await;
    assert!(
        expired
            .bind_original_training(dataset.clone(), training.clone())
            .is_err()
    );
    expired_server
        .join()
        .expect("original absolute readback end")?;
    assert_eq!(fixture.training_bytes()?, retained);
    drop(owner);
    let fresh_counts = finish_material(peers)?;
    eprintln!("HEPTA_ORIGINAL_TRAINING_READBACK_FRESH_MATERIAL_COUNTS {fresh_counts:?}");

    let (recovered, peers) = support::owner(&fixture, Origin::Recovered)?;
    let (cold, cold_server) = prebound(
        Arc::clone(&recovered),
        fixture.config.clone(),
        Duration::from_secs(300),
    )?;
    let cold = cold.bind_original_training(dataset.clone(), training.clone())?;
    assert!(
        cold.readback(dataset.snapshot(), training.receipt())
            .await
            .is_err()
    );
    assert_eq!(join_readback(cold, cold_server)?, 1);
    assert!(matches!(
        &*recovered.state.lock().expect("state"),
        State::Awaiting(_)
    ));
    assert_eq!(fixture.training_bytes()?, retained);

    // Recovery is a separate, explicit original-host operation. Only after it
    // has retained Ready may a newly delivered read-only connection observe T.
    let (reader, reader_server) = connected(
        Arc::clone(&recovered),
        context(&fixture, &dataset),
        Origin::Recovered,
        Some(training.clone()),
    )?;
    assert_eq!(reader.readback().await?, training);
    assert!(matches!(
        reader
            .execute_training(Arc::new(AtomicBool::new(/*v*/ false)))
            .await,
        Err(CommandError::ReadbackRequired)
    ));
    assert_eq!(finish(reader, reader_server)?, 1);
    let (cold, cold_server) = prebound(
        Arc::clone(&recovered),
        fixture.config.clone(),
        Duration::from_secs(300),
    )?;
    let cold = cold.bind_original_training(dataset.clone(), training.clone())?;
    assert_eq!(
        cold.readback(dataset.snapshot(), training.receipt())
            .await?,
        *training.attestation()
    );
    assert_eq!(join_readback(cold, cold_server)?, 1);
    assert_eq!(fixture.training_bytes()?, retained);
    assert_eq!(fixture.bytes()?, material);
    drop(recovered);
    let cold_counts = finish_material(peers)?;
    eprintln!("HEPTA_ORIGINAL_TRAINING_READBACK_COLD_MATERIAL_COUNTS {cold_counts:?}");
    assert_eq!(cold_counts[0], 1);
    Ok(())
}

#[derive(Clone, Copy)]
enum Fault {
    Renewed,
    Missing,
    Pending,
}

fn fault_peer(
    owner: Arc<Host>,
    fixture: &MaterialCommandFixture,
    expected: &OriginalCellQ24TrainingCommandReceiptV1,
    fault: Fault,
) -> anyhow::Result<(
    OriginalCellQ24TrainingReadbackConnectionV1,
    JoinHandle<anyhow::Result<u64>>,
)> {
    let (connection, mut channel) =
        readonly::test_support::connection(fixture.config.clone(), Duration::from_secs(300))?;
    let verifier = fixture.config.verifier.clone();
    let expected = expected.clone();
    let server = std::thread::spawn(move || -> anyhow::Result<u64> {
        for request_id in 1..=128 {
            if !channel.exchange(|bytes| {
                let bytes = owner
                    .original_training_readback_response(bytes, request_id)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                let mut response: wire::Response = serde_json::from_slice(&bytes)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                let wire::CommandResult::Completed { snapshot, evidence } = response.result else {
                    return Err(HostIssuerTransportError::InvalidRequest);
                };
                response.result = match fault {
                    Fault::Missing => wire::CommandResult::Missing,
                    Fault::Pending => wire::CommandResult::Pending,
                    Fault::Renewed => {
                        let mut changed = evidence
                            .decode()
                            .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                        if changed != *expected.attestation() {
                            return Err(HostIssuerTransportError::InvalidRequest);
                        }
                        changed.expires_at += 1;
                        changed.signature = SigningKey::from_bytes(&[1; 32])
                            .sign(&changed.signing_bytes())
                            .to_bytes();
                        let payload =
                            learning_iteration_receipt_signing_bytes_v1(expected.receipt())
                                .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                        verifier
                            .verify(
                                LearningEvidenceRoleV1::Generator,
                                &changed,
                                &payload,
                                super::super::super::now()
                                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?,
                            )
                            .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                        wire::CommandResult::Completed {
                            snapshot,
                            evidence: evidence_wire::Evidence::from_original(&changed),
                        }
                    }
                };
                serde_json::to_vec(&response).map_err(|_| HostIssuerTransportError::InvalidRequest)
            })? {
                return Ok(request_id - 1);
            }
        }
        anyhow::bail!("bounded original readback frame budget")
    });
    Ok((connection, server))
}

fn cancel_queued_readback(
    owner: Arc<Host>,
    config: OriginalCellQ24MaterialReceiptConfigV1,
    dataset: OriginalCellQ24MaterialCommandReceiptV1,
    training: OriginalCellQ24TrainingCommandReceiptV1,
) -> anyhow::Result<()> {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .max_blocking_threads(1)
        .enable_all()
        .build()?;
    runtime.block_on(async move {
        let (connection, server) = prebound(owner, config, Duration::from_secs(300))?;
        let client = connection.bind_original_training(dataset.clone(), training.clone())?;
        let (occupied_tx, occupied_rx) = tokio::sync::oneshot::channel();
        let (release_tx, release_rx) = std::sync::mpsc::channel();
        let blocker = tokio::task::spawn_blocking(move || {
            let _ = occupied_tx.send(());
            release_rx.recv()
        });
        occupied_rx.await?;
        let mut future = Box::pin(client.readback(dataset.snapshot(), training.receipt()));
        std::future::poll_fn(|cx| match std::future::Future::poll(future.as_mut(), cx) {
            std::task::Poll::Pending => std::task::Poll::Ready(()),
            std::task::Poll::Ready(_) => panic!("readback must queue behind the blocker"),
        })
        .await;
        drop(future);
        assert!(
            client
                .readback(dataset.snapshot(), training.receipt())
                .await
                .is_err()
        );
        release_tx.send(())?;
        blocker.await??;
        // A queued read may finish as a read, but cannot restore the abandoned
        // caller's channel or cause an Execute/bootstrap request afterward.
        assert_eq!(join_readback(client, server)?, 1);
        Ok(())
    })
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_training_readback_changed_evidence_and_withdrawal_consume_channel()
-> anyhow::Result<()> {
    let mut fixture = MaterialCommandFixture::new().await?;
    let (owner, peers) = support::owner(&fixture, Origin::Fresh)?;
    let dataset = complete_material(&fixture).await?;
    let training = train(&fixture, &owner, &dataset).await?;
    let retained = fixture.training_bytes()?;
    let material = fixture.bytes()?;
    for fault in [Fault::Renewed, Fault::Missing, Fault::Pending] {
        let (connection, server) = fault_peer(Arc::clone(&owner), &fixture, &training, fault)?;
        let client = connection.bind_original_training(dataset.clone(), training.clone())?;
        assert!(
            client
                .readback(dataset.snapshot(), training.receipt())
                .await
                .is_err()
        );
        assert!(matches!(
            client
                .readback(dataset.snapshot(), training.receipt())
                .await,
            Err(LearningIterationRuntimeErrorV1::OwnerUnavailable(
                "original learning evidence owner"
            ))
        ));
        drop(client);
        assert_eq!(server.join().expect("changed original reply")?, 1);
        assert_eq!(fixture.training_bytes()?, retained);
        assert_eq!(fixture.bytes()?, material);
    }
    tokio::task::spawn_blocking({
        let owner = Arc::clone(&owner);
        let config = fixture.config.clone();
        let dataset = dataset.clone();
        let training = training.clone();
        move || cancel_queued_readback(owner, config, dataset, training)
    })
    .await??;
    assert_eq!(fixture.training_bytes()?, retained);
    assert_eq!(fixture.bytes()?, material);
    let (connection, server) = prebound(
        Arc::clone(&owner),
        fixture.config.clone(),
        Duration::from_secs(300),
    )?;
    let client = connection.bind_original_training(dataset.clone(), training.clone())?;
    assert_eq!(
        client
            .readback(dataset.snapshot(), training.receipt())
            .await?,
        *training.attestation()
    );
    fixture.withdraw()?;
    assert!(
        client
            .readback(dataset.snapshot(), training.receipt())
            .await
            .is_err()
    );
    assert!(
        client
            .readback(dataset.snapshot(), training.receipt())
            .await
            .is_err()
    );
    drop(client);
    assert_eq!(server.join().expect("withdrawn real original Source")?, 2);
    assert_eq!(fixture.training_bytes()?, retained);
    assert_eq!(fixture.bytes()?, material);
    drop(owner);
    // Withdrawal closes the actual Source/evidence peers. Preserve their
    // original error results; no replacement or replay is attempted.
    for peer in peers {
        let _withdrawn_original_result = peer.join().expect("original withdrawn Material peer");
    }
    Ok(())
}
