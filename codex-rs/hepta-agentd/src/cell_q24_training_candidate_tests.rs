//! Actual Candidate material over the same four original Material services.
//! These are mechanism tests with explicit test keys and terminal labels.
//! They provide no independent B/retention panel or version/adoption grant.
use super::super::super::candidate_wire;
use super::super::super::connection;
use super::super::super::now as command_now;
use super::*;
use crate::OriginalCellQ24CandidateReadbackErrorV1 as CandidateError;
use crate::OriginalCellQ24TrainingCommandConnectionErrorV1 as ConnectionError;
use codex_hepta_types::AuthorityPosture;
use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;
use std::sync::atomic::Ordering;

#[path = "cell_q24_training_candidate_support_tests.rs"]
mod pages;
use pages::*;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_candidate_material_reconstructs_actual_pages_and_cold_original_signature()
-> anyhow::Result<()> {
    let mut fixture = MaterialCommandFixture::candidate_pages().await?;
    let (owner, peers) = support::owner(&fixture, Origin::Fresh)?;
    // Both descriptors are held before E/D or T exists. Neither binding below
    // can start a fresh transport lifetime after those original owners finish.
    let (candidate_connection, candidate_peer) = page_peer(
        Arc::clone(&owner),
        fixture.config.clone(),
        Origin::Fresh,
        /*expected*/ None,
        Fault::Original,
        /*gate*/ None,
        Duration::from_secs(300),
    )?;
    let (training_connection, training_server) = prebound(
        Arc::clone(&owner),
        fixture.config.clone(),
        Origin::Fresh,
        /*expected*/ None,
        Duration::from_secs(300),
    )?;
    let cut = complete_material(&fixture).await?;
    let trainer = training_connection.bind_original_dataset(cut.clone())?;
    let training = trainer
        .execute_training(Arc::new(AtomicBool::new(/*v*/ false)))
        .await?;
    let LearningIterationObservationV1::Training {
        candidate,
        artifact_bytes,
        ..
    } = &training.receipt().observation
    else {
        anyhow::bail!("actual original SGD must produce a Candidate");
    };
    assert_eq!(*artifact_bytes, 4_108);
    let originals = (fixture.training_bytes()?, fixture.bytes()?);
    let client = bind(
        candidate_connection,
        &fixture,
        cut.clone(),
        training.clone(),
    )?;
    let material = client.readback().await?;
    assert_eq!(material.bundle(), candidate.as_ref());
    assert_eq!(material.model().components(), &candidate.components);
    assert_eq!(
        Digest32::of_bytes(material.heads()),
        candidate.components.heads
    );
    assert_eq!(material.heads().len(), 4_108);
    assert_ne!(
        candidate.components.heads,
        fixture.training_baseline().components().heads
    );
    assert_eq!(material.receipt(), training.receipt());
    assert_eq!(material.attestation(), training.attestation());
    assert_eq!(material.authority(), AuthorityPosture::DENY_ALL);
    assert_eq!(candidate_peer.frames.load(Ordering::Acquire), 4);
    let original_heads = material.heads().to_vec();
    drop(material);
    // A new independent read starts another actual Begin and Finish on the
    // original nonce/lifetime. The previous Candidate is only a comparison pin.
    let repeated = client.readback().await?;
    assert_eq!(repeated.heads(), original_heads.as_slice());
    assert_eq!(repeated.receipt(), training.receipt());
    assert_eq!(repeated.attestation(), training.attestation());
    assert_eq!(candidate_peer.frames.load(Ordering::Acquire), 8);
    drop(repeated);
    drop(client);
    assert_eq!(candidate_peer.finish()?, 8);
    assert_eq!(finish(trainer, training_server)?, 1);
    assert_eq!((fixture.training_bytes()?, fixture.bytes()?), originals);
    drop(owner);
    let counts = finish_material(peers)?;
    assert_eq!(counts[0], 1);
    assert!(counts[1] > 0 && counts[2] > 0 && counts[3] > 0);

    // Recovery is performed explicitly by the original host using the same
    // files and witnesses. Candidate readback itself never bootstraps custody.
    fixture.reopen()?;
    let (recovered, peers) = support::owner(&fixture, Origin::Recovered)?;
    let (candidate_connection, candidate_peer) = page_peer(
        Arc::clone(&recovered),
        fixture.config.clone(),
        Origin::Recovered,
        Some(training.clone()),
        Fault::Original,
        /*gate*/ None,
        Duration::from_secs(300),
    )?;
    let (reader, server) = connected(
        Arc::clone(&recovered),
        context(&fixture, &cut),
        Origin::Recovered,
        Some(training.clone()),
    )?;
    assert_eq!(reader.readback().await?, training);
    assert_eq!(finish(reader, server)?, 1);
    let client = bind(candidate_connection, &fixture, cut, training.clone())?;
    let material = client.readback().await?;
    assert_eq!(material.heads(), original_heads.as_slice());
    assert_eq!(material.receipt(), training.receipt());
    assert_eq!(material.attestation(), training.attestation());
    assert_eq!(material.authority(), AuthorityPosture::DENY_ALL);
    drop(material);
    drop(client);
    assert_eq!(candidate_peer.finish()?, 4);
    assert_eq!((fixture.training_bytes()?, fixture.bytes()?), originals);
    drop(recovered);
    finish_material(peers)?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_candidate_material_readonly_preserves_no_update_missing_and_pending()
-> anyhow::Result<()> {
    let fixture = MaterialCommandFixture::new().await?;
    let (owner, peers) = support::owner(&fixture, Origin::Fresh)?;
    let cut = complete_material(&fixture).await?;
    let context = context(&fixture, &cut);
    let (trainer, server) = connected(
        Arc::clone(&owner),
        context.clone(),
        Origin::Fresh,
        /*expected*/ None,
    )?;
    let no_update = trainer
        .execute_training(Arc::new(AtomicBool::new(/*v*/ false)))
        .await?;
    assert!(matches!(
        no_update.receipt().observation,
        LearningIterationObservationV1::TrainingNoUpdateV2(_)
    ));
    assert_eq!(finish(trainer, server)?, 1);
    let originals = (fixture.training_bytes()?, fixture.bytes()?);
    let (connection, peer) = page_peer(
        Arc::clone(&owner),
        fixture.config.clone(),
        Origin::Fresh,
        /*expected*/ None,
        Fault::Original,
        /*gate*/ None,
        Duration::from_secs(300),
    )?;
    assert!(matches!(
        connection.bind_original_candidate_material(cut, no_update, fixture.training_baseline()),
        Err(ConnectionError::Candidate(CandidateError::NoCandidate))
    ));
    assert_eq!(peer.finish()?, 0);
    let (reply, disposition) = raw_page(Arc::clone(&owner), request(&context)?).await?;
    assert!(matches!(
        reply.result,
        candidate_wire::MaterialResult::NoCandidate
    ));
    assert!(disposition == candidate_wire::SessionDisposition::CloseReadback);
    assert_eq!((fixture.training_bytes()?, fixture.bytes()?), originals);
    drop(owner);
    finish_material(peers)?;

    let fixture = MaterialCommandFixture::new().await?;
    let (owner, peers) = support::owner(&fixture, Origin::Fresh)?;
    let originals = (fixture.training_bytes()?, fixture.bytes()?);
    let unresolved = unbound_request(&fixture, wire::Action::Readback);
    let unbound = candidate_wire::Request {
        schema: 1,
        operation: candidate_wire::OPERATION.into(),
        request_id: 1,
        binding: unresolved.binding,
        operation_id: unresolved.operation_id,
        dataset_head: unresolved.dataset_head,
        scope_binding: unresolved.scope_binding,
        actor_id: unresolved.actor_id,
        completion: Digest32::of_bytes(b"no future T has been asserted").to_string(),
        page: 0,
        transfer: 1,
        phase: candidate_wire::Phase::Begin,
    };
    let (reply, disposition) = raw_page(Arc::clone(&owner), unbound).await?;
    assert!(matches!(
        reply.result,
        candidate_wire::MaterialResult::ReadbackRequired
    ));
    assert!(disposition == candidate_wire::SessionDisposition::CloseReadback);
    assert!(matches!(
        &*owner.state.lock().expect("original state"),
        State::Awaiting(_)
    ));
    assert_eq!((fixture.training_bytes()?, fixture.bytes()?), originals);
    let old_execute = serde_json::to_vec(&unbound_request(&fixture, wire::Action::Execute))?;
    let rejected = {
        let owner = Arc::clone(&owner);
        tokio::task::spawn_blocking(move || {
            owner.candidate_material_response(
                &old_execute,
                /*request_id*/ 1,
                &mut candidate_wire::Session::new(),
            )
        })
        .await?
    };
    assert!(
        rejected.is_err(),
        "the old Execute purpose is not a Candidate action"
    );
    assert_eq!((fixture.training_bytes()?, fixture.bytes()?), originals);

    let cut = complete_material(&fixture).await?;
    let context = support::context(&fixture, &cut);
    // The explicit original test host initializes its actual writers outside
    // the Candidate purpose, using the production builder and actual D read.
    // No fit or receipt claim occurs; the Ready owner's Missing state is real.
    let started_at = command_now()?;
    let actual_cut =
        crate::OriginalCellQ24DatasetCommandReadbackV1::readback(&owner.dataset).await?;
    assert_eq!(actual_cut, cut);
    let read_request = wire::Request::new(
        &context,
        context.binding()?,
        /*request_id*/ 1,
        wire::Action::Readback,
        /*cancelled*/ false,
    );
    let bound = owner.actual_context(
        &actual_cut,
        &read_request,
        /*next_request_id*/ 1,
        started_at,
    )?;
    let custody = match std::mem::replace(
        &mut *owner.state.lock().expect("original custody"),
        State::Starting,
    ) {
        State::Awaiting(custody) => custody,
        _ => anyhow::bail!("unstarted original test custody"),
    };
    let ready = owner
        .build_original_owner(custody, bound, actual_cut, started_at)
        .await?;
    *owner.state.lock().expect("original Ready state") = State::Ready(ready);
    let missing_bytes = (fixture.training_bytes()?, fixture.bytes()?);
    let (reply, disposition) = raw_page(Arc::clone(&owner), request(&context)?).await?;
    assert!(matches!(
        reply.result,
        candidate_wire::MaterialResult::Missing
    ));
    assert!(disposition == candidate_wire::SessionDisposition::CloseReadback);
    assert_eq!((fixture.training_bytes()?, fixture.bytes()?), missing_bytes);
    drop(owner);
    finish_material(peers)?;

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
            Arc::new(AtomicBool::new(/*v*/ false)),
        )?,
    );
    let cut = complete_material(&fixture).await?;
    let context = support::context(&fixture, &cut);
    let (trainer, server) = connected(
        Arc::clone(&owner),
        context.clone(),
        Origin::Fresh,
        /*expected*/ None,
    )?;
    assert!(matches!(
        trainer
            .execute_training(Arc::new(AtomicBool::new(/*v*/ false)))
            .await,
        Err(CommandError::CommitUncertain)
    ));
    assert_eq!(finish(trainer, server)?, 1);
    let pending_bytes = (fixture.training_bytes()?, fixture.bytes()?);
    drop(owner);
    finish_material(peers)?;
    let (recovered, peers) = support::owner(&fixture, Origin::Recovered)?;
    let (reader, server) = connected(
        Arc::clone(&recovered),
        context.clone(),
        Origin::Recovered,
        /*expected*/ None,
    )?;
    assert!(matches!(
        reader.readback().await,
        Err(CommandError::Pending)
    ));
    assert_eq!(finish(reader, server)?, 1);
    let (reply, disposition) = raw_page(Arc::clone(&recovered), request(&context)?).await?;
    assert!(matches!(
        reply.result,
        candidate_wire::MaterialResult::Pending
    ));
    assert!(disposition == candidate_wire::SessionDisposition::CloseReadback);
    assert_eq!((fixture.training_bytes()?, fixture.bytes()?), pending_bytes);
    drop(recovered);
    finish_material(peers)?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_candidate_material_refuses_pages_renewal_window_withdrawal_and_cancel()
-> anyhow::Result<()> {
    let started = std::time::Instant::now();
    // Fixed test phases locate a timeout without changing its budget or coverage.
    let report = |phase: &str, fault: Option<Fault>| {
        eprintln!(
            "HEPTA_CANDIDATE_MATERIAL_PHASE phase={phase} fault={fault:?} elapsed_ms={}",
            started.elapsed().as_millis()
        );
    };
    // These faults change only replies after successful original owner reads.
    // Share the completed T and its four live Source connections; each case
    // still gets its own channel, Session and irreversibly consumed client.
    report("fault-fixture-start", None);
    let run = completed_candidate().await?;
    report("fault-fixture-ready", None);
    let original = (run.fixture.training_bytes()?, run.fixture.bytes()?);
    for fault in [
        Fault::WrongPage,
        Fault::WrongCompletion,
        Fault::WrongOffset,
        Fault::WrongTotal,
        Fault::CorruptHeads,
        Fault::CloseAfterFirst,
        Fault::WrongFinishDigest,
        Fault::DropFinishAck,
    ] {
        report("fault-case-start", Some(fault));
        let (connection, peer) = page_peer(
            Arc::clone(&run.owner),
            run.fixture.config.clone(),
            Origin::Fresh,
            /*expected*/ None,
            fault,
            /*gate*/ None,
            Duration::from_secs(300),
        )?;
        let client = bind(
            connection,
            &run.fixture,
            run.dataset.clone(),
            run.training.clone(),
        )?;
        report("fault-readback-start", Some(fault));
        let error = match client.readback().await {
            Ok(_) => anyhow::bail!("invalid original page unexpectedly accepted: {fault:?}"),
            Err(error) => error,
        };
        report("fault-readback-finished", Some(fault));
        // Count successful replies from the actual original handler before
        // any fault mutation. An earlier failed owner cannot satisfy a later
        // negative case by returning Missing, Pending or Uncertain instead.
        assert_eq!(peer.original_begins.load(Ordering::Acquire), 1);
        assert_eq!(
            peer.original_finishes.load(Ordering::Acquire),
            if matches!(fault, Fault::WrongFinishDigest | Fault::DropFinishAck) {
                1
            } else {
                0
            }
        );
        match fault {
            Fault::WrongPage | Fault::WrongCompletion => assert!(matches!(
                error,
                CandidateError::Binding("exact Candidate purpose, page and full completion pin")
            )),
            Fault::WrongOffset | Fault::WrongTotal => assert!(matches!(
                error,
                CandidateError::Binding("signed Candidate length and consecutive page")
            )),
            Fault::CorruptHeads => assert!(matches!(
                error,
                CandidateError::Binding("complete signed original Candidate body")
            )),
            Fault::CloseAfterFirst | Fault::DropFinishAck => assert!(matches!(
                error,
                CandidateError::Command(CommandError::Transport(_))
            )),
            Fault::WrongFinishDigest => assert!(matches!(
                error, CandidateError::Command(CommandError::CommitUncertain)
            )),
            Fault::Original => unreachable!(),
        }
        assert!(matches!(
            client.readback().await,
            Err(CandidateError::Unavailable)
        ));
        drop(client);
        report("fault-peer-join-start", Some(fault));
        if matches!(fault, Fault::DropFinishAck) {
            assert_eq!(peer.frames.load(Ordering::Acquire), 4);
            assert!(peer.finish().is_err(), "actual Finish was read before its ACK was lost");
        } else {
            assert_eq!(
                peer.finish()?,
                match fault {
                    Fault::CorruptHeads => 3,
                    Fault::WrongFinishDigest => 4,
                    _ => 1,
                }
            );
        }
        report("fault-peer-joined", Some(fault));
        assert_eq!(
            (run.fixture.training_bytes()?, run.fixture.bytes()?),
            original
        );
        report("fault-case-finished", Some(fault));
    }
    run.close()?;
    report("fault-fixture-closed", None);

    report("renewal-fixture-start", None);
    let run = completed_candidate().await?;
    report("renewal-fixture-ready", None);
    let context = support::context(&run.fixture, &run.dataset);
    let original = (run.fixture.training_bytes()?, run.fixture.bytes()?);
    let after_original_expiry = run
        .training
        .attestation()
        .expires_at
        .checked_add(/*rhs*/ 1)
        .expect("fixture expiry permits a one-second renewal");
    let mut renewed = run.training.attestation().clone();
    renewed.expires_at = after_original_expiry;
    // Negative control only: a valid signature from the explicit fixture key,
    // over the same real receipt, must not replace the original saved window.
    renewed.signature = ed25519_dalek::SigningKey::from_bytes(&[1; 32])
        .sign(&renewed.signing_bytes())
        .to_bytes();
    let renewed = wire::authenticate_receipt(
        &context,
        run.training.receipt().clone(),
        renewed,
        command_now()?,
    )?;
    assert_ne!(renewed.attestation(), run.training.attestation());
    assert!(matches!(
        wire::authenticate_receipt(
            &context,
            run.training.receipt().clone(),
            run.training.attestation().clone(),
            after_original_expiry,
        ),
        Err(CommandError::Evidence(
            codex_hepta_learning_ledger::SignedEvidenceError::ValidityWindow
        ))
    ));
    assert_eq!(
        wire::authenticate_receipt(
            &context,
            renewed.receipt().clone(),
            renewed.attestation().clone(),
            after_original_expiry,
        )?,
        renewed
    );
    let (connection, peer) = page_peer(
        Arc::clone(&run.owner),
        run.fixture.config.clone(),
        Origin::Recovered,
        Some(run.training.clone()),
        Fault::Original,
        /*gate*/ None,
        Duration::from_secs(300),
    )?;
    assert!(matches!(
        connection.bind_original_candidate_material(
            run.dataset.clone(),
            renewed.clone(),
            run.fixture.training_baseline(),
        ),
        Err(ConnectionError::Candidate(CandidateError::Binding(
            "same original Candidate predecessor and baseline"
        )))
    ));
    assert_eq!(peer.finish()?, 0);
    let (connection, peer) = page_peer(
        Arc::clone(&run.owner),
        run.fixture.config.clone(),
        Origin::Fresh,
        /*expected*/ None,
        Fault::Original,
        /*gate*/ None,
        Duration::from_secs(300),
    )?;
    let client = bind(connection, &run.fixture, run.dataset.clone(), renewed)?;
    report("renewed-readback-start", None);
    assert!(matches!(
        client.readback().await,
        Err(CandidateError::Command(CommandError::Transport(_)))
    ));
    report("renewed-readback-finished", None);
    assert!(matches!(
        client.readback().await,
        Err(CandidateError::Unavailable)
    ));
    drop(client);
    report("renewed-peer-join-start", None);
    assert!(
        peer.finish().is_err(),
        "the actual original owner refuses a different full signature"
    );
    report("renewed-peer-joined", None);

    let (connection, peer) = page_peer(
        Arc::clone(&run.owner),
        run.fixture.config.clone(),
        Origin::Fresh,
        /*expected*/ None,
        Fault::Original,
        /*gate*/ None,
        Duration::from_millis(40),
    )?;
    tokio::time::sleep(Duration::from_millis(80)).await;
    assert!(
        connection
            .bind_original_candidate_material(
                run.dataset.clone(),
                run.training.clone(),
                run.fixture.training_baseline(),
            )
            .is_err()
    );
    assert_eq!(peer.frames.load(Ordering::Acquire), 0);
    if let Ok(count) = peer.finish() {
        assert_eq!(count, 0);
    }
    report("expired-window-peer-joined", None);
    let mut request = request(&context)?;
    request.page = candidate_wire::MAX_PAGES as u8;
    assert!(raw_page(Arc::clone(&run.owner), request).await.is_err());
    assert_eq!(
        (run.fixture.training_bytes()?, run.fixture.bytes()?),
        original
    );
    run.close()?;
    report("renewal-fixture-closed", None);

    report("withdrawal-fixture-start", None);
    let mut run = completed_candidate().await?;
    report("withdrawal-fixture-ready", None);
    let original = (run.fixture.training_bytes()?, run.fixture.bytes()?);
    let reached = Arc::new(tokio::sync::Notify::new());
    let (release, released) = std::sync::mpsc::channel();
    let (connection, peer) = page_peer(
        Arc::clone(&run.owner),
        run.fixture.config.clone(),
        Origin::Fresh,
        /*expected*/ None,
        Fault::Original,
        Some(ResponseGate {
            reached: Arc::clone(&reached),
            release: released,
        }),
        Duration::from_secs(300),
    )?;
    let client = Arc::new(bind(
        connection,
        &run.fixture,
        run.dataset.clone(),
        run.training.clone(),
    )?);
    let pending = tokio::spawn({
        let client = Arc::clone(&client);
        async move { client.readback().await }
    });
    report("withdrawal-first-page-wait", None);
    tokio::time::timeout(Duration::from_secs(30), reached.notified()).await?;
    report("withdrawal-first-page-reached", None);
    run.fixture.withdraw()?;
    release.send(())?;
    report("withdrawal-readback-wait", None);
    assert!(matches!(
        pending.await?,
        Err(CandidateError::Command(CommandError::CommitUncertain))
    ));
    report("withdrawal-readback-finished", None);
    assert!(matches!(
        client.readback().await,
        Err(CandidateError::Unavailable)
    ));
    drop(client);
    report("withdrawal-peer-join-start", None);
    assert_eq!(peer.finish()?, 4);
    report("withdrawal-peer-joined", None);
    assert_eq!(
        (run.fixture.training_bytes()?, run.fixture.bytes()?),
        original
    );
    drop(run.owner);
    report("withdrawal-source-peers-join-start", None);
    let mut source_failure = false;
    for peer in run.peers {
        source_failure |= peer
            .join()
            .expect("original withdrawn Material peer")
            .is_err();
    }
    assert!(
        source_failure,
        "a real original source/evidence read must reject withdrawal"
    );
    report("withdrawal-source-peers-joined", None);

    report("cancel-fixture-start", None);
    let run = completed_candidate().await?;
    report("cancel-fixture-ready", None);
    let original = (run.fixture.training_bytes()?, run.fixture.bytes()?);
    let reached = Arc::new(tokio::sync::Notify::new());
    let (release, released) = std::sync::mpsc::channel();
    let (connection, peer) = page_peer(
        Arc::clone(&run.owner),
        run.fixture.config.clone(),
        Origin::Fresh,
        /*expected*/ None,
        Fault::Original,
        Some(ResponseGate {
            reached: Arc::clone(&reached),
            release: released,
        }),
        Duration::from_secs(300),
    )?;
    let client = Arc::new(bind(
        connection,
        &run.fixture,
        run.dataset.clone(),
        run.training.clone(),
    )?);
    let pending = tokio::spawn({
        let client = Arc::clone(&client);
        async move { client.readback().await }
    });
    report("cancel-first-page-wait", None);
    tokio::time::timeout(Duration::from_secs(30), reached.notified()).await?;
    report("cancel-first-page-reached", None);
    pending.abort();
    match pending.await {
        Err(error) => assert!(error.is_cancelled()),
        Ok(_) => anyhow::bail!("Candidate await was not cancelled"),
    }
    report("cancel-waiter-aborted", None);
    assert!(matches!(
        client.readback().await,
        Err(CandidateError::Unavailable)
    ));
    release.send(())?;
    drop(client);
    // The already-running Begin may return, but cancellation prevents every
    // later Page/Finish and the partial original channel is never restored.
    report("cancel-peer-join-start", None);
    assert_eq!(peer.finish()?, 1);
    report("cancel-peer-joined", None);
    assert_eq!(
        (run.fixture.training_bytes()?, run.fixture.bytes()?),
        original
    );
    run.close()?;
    report("cancel-fixture-closed", None);
    Ok(())
}

#[path = "cell_q24_candidate_stage_tests.rs"]
mod ordinary_stages;
