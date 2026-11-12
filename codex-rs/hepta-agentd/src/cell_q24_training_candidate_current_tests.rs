//! Real SourceBound CURRENT reads after an initial complete Candidate transfer.
//! These retain explicit fixture custody and never qualify ordinary adoption.
use super::super::super::super::candidate_current as protocol;
use super::*;
use pretty_assertions::assert_eq;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_candidate_current_reads_maximum_seventeen_pages_then_one_frame()
-> anyhow::Result<()> {
    let fixture = MaterialCommandFixture::candidate_maximum_pages().await?;
    let (owner, peers) = support::owner(&fixture, Origin::Fresh)?;
    let dataset = complete_material(&fixture).await?;
    let (trainer, server) = connected(
        Arc::clone(&owner),
        context(&fixture, &dataset),
        Origin::Fresh,
        /*expected*/ None,
    )?;
    let training = trainer
        .execute_training(Arc::new(AtomicBool::new(/*v*/ false)))
        .await?;
    assert_eq!(finish(trainer, server)?, 1);
    let (connection, peer) = page_peer(
        Arc::clone(&owner),
        fixture.config.clone(),
        Origin::Fresh,
        /*expected*/ None,
        Fault::Original,
        /*gate*/ None,
        Duration::from_secs(300),
    )?;
    let before = (fixture.training_bytes()?, fixture.bytes()?);
    let client = bind(connection, &fixture, dataset.clone(), training.clone())?;
    let first = client.readback().await?;
    assert_eq!(first.heads().len(), 32_780);
    assert_eq!(peer.frames.load(Ordering::Acquire), 17);
    for expected_frames in 18..=20 {
        let current = client.readback().await?;
        assert_eq!(
            (
                current.heads(),
                current.bundle(),
                current.receipt(),
                current.attestation(),
                current.authority()
            ),
            (
                first.heads(),
                first.bundle(),
                first.receipt(),
                first.attestation(),
                AuthorityPosture::DENY_ALL
            ),
        );
        assert_eq!(peer.frames.load(Ordering::Acquire), expected_frames);
    }
    let context = context(&fixture, &dataset);
    let completion = candidate_wire::completion_digest(training.receipt(), training.attestation())?;
    assert!(
        protocol::Request::new(
            &context,
            context.binding()?,
            completion,
            /*request_id*/ 129,
            first.heads()
        )
        .is_err()
    );
    drop(client);
    assert_eq!(peer.finish()?, 20);
    assert_eq!((fixture.training_bytes()?, fixture.bytes()?), before);
    drop(owner);
    finish_material(peers)?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_candidate_current_requires_complete_same_session_and_context()
-> anyhow::Result<()> {
    let run = completed_candidate().await?;
    let (connection, peer) = page_peer(
        Arc::clone(&run.owner),
        run.fixture.config.clone(),
        Origin::Fresh,
        /*expected*/ None,
        Fault::Original,
        /*gate*/ None,
        Duration::from_secs(300),
    )?;
    let client = bind(
        connection,
        &run.fixture,
        run.dataset.clone(),
        run.training.clone(),
    )?;
    let material = client.readback().await?;
    let context = context(&run.fixture, &run.dataset);
    let request = protocol::Request::new(
        &context,
        context.binding()?,
        candidate_wire::completion_digest(material.receipt(), material.attestation())?,
        /*request_id*/ 1,
        material.heads(),
    )?;
    let before = (run.fixture.training_bytes()?, run.fixture.bytes()?);
    let owner = Arc::clone(&run.owner);
    let encoded = serde_json::to_vec(&request)?;
    assert!(
        tokio::task::spawn_blocking(move || {
            owner.candidate_material_response(
                &encoded,
                /*request_id*/ 1,
                &mut candidate_wire::Session::new(),
            )
        })
        .await?
        .is_err()
    );
    let mut wrong_profile = request.clone();
    wrong_profile.binding = Digest32::of_bytes(b"different original frozen profile").to_string();
    assert!(
        wrong_profile
            .require_context(&context, context.binding()?, /*request_id*/ 1)
            .is_err()
    );
    let mut replay = request.clone();
    replay.request_id = 2;
    assert!(
        replay
            .require_context(&context, context.binding()?, /*request_id*/ 1)
            .is_err()
    );
    let mut page_in_current = serde_json::to_value(&request)?;
    page_in_current["page"] = serde_json::json!(0);
    assert!(serde_json::from_value::<protocol::ReadRequest>(page_in_current).is_err());
    drop(client);
    assert_eq!(peer.finish()?, 3);
    assert_eq!(
        (run.fixture.training_bytes()?, run.fixture.bytes()?),
        before
    );
    run.close()?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_candidate_current_refuses_replayed_nonce_and_other_purpose() -> anyhow::Result<()>
{
    for fault in [Fault::WrongCurrentNonce, Fault::WrongCurrentPurpose] {
        rejects_current_reply(fault).await?;
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_candidate_current_refuses_changed_signature_pin_and_head_proof()
-> anyhow::Result<()> {
    for fault in [Fault::WrongCurrentCompletion, Fault::WrongCurrentHeads] {
        rejects_current_reply(fault).await?;
    }
    Ok(())
}

async fn rejects_current_reply(fault: Fault) -> anyhow::Result<()> {
    let run = completed_candidate().await?;
    let (connection, peer) = page_peer(
        Arc::clone(&run.owner),
        run.fixture.config.clone(),
        Origin::Fresh,
        /*expected*/ None,
        fault,
        /*gate*/ None,
        Duration::from_secs(300),
    )?;
    let before = (run.fixture.training_bytes()?, run.fixture.bytes()?);
    let client = bind(
        connection,
        &run.fixture,
        run.dataset.clone(),
        run.training.clone(),
    )?;
    let first = client.readback().await?;
    assert_eq!(first.attestation(), run.training.attestation());
    assert!(matches!(
        client.readback().await,
        Err(CandidateError::Binding(_))
    ));
    assert!(matches!(
        client.readback().await,
        Err(CandidateError::Unavailable)
    ));
    assert_eq!(peer.frames.load(Ordering::Acquire), 4);
    drop(client);
    assert_eq!(peer.finish()?, 4);
    assert_eq!(
        (run.fixture.training_bytes()?, run.fixture.bytes()?),
        before
    );
    run.close()?;
    Ok(())
}

#[derive(Clone, Copy)]
enum OriginalCurrentFault {
    NativeArtifact,
    GeneratorReceipt,
    SourceWithdrawal,
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_candidate_current_rechecks_actual_native_artifact_after_cache()
-> anyhow::Result<()> {
    rejects_original_current(OriginalCurrentFault::NativeArtifact).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_candidate_current_rechecks_actual_generator_journal_after_cache()
-> anyhow::Result<()> {
    rejects_original_current(OriginalCurrentFault::GeneratorReceipt).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_candidate_current_rechecks_actual_source_after_cache() -> anyhow::Result<()> {
    rejects_original_current(OriginalCurrentFault::SourceWithdrawal).await
}

async fn rejects_original_current(fault: OriginalCurrentFault) -> anyhow::Result<()> {
    let mut run = completed_candidate().await?;
    let (connection, peer) = page_peer(
        Arc::clone(&run.owner),
        run.fixture.config.clone(),
        Origin::Fresh,
        /*expected*/ None,
        Fault::Original,
        /*gate*/ None,
        Duration::from_secs(300),
    )?;
    let client = bind(
        connection,
        &run.fixture,
        run.dataset.clone(),
        run.training.clone(),
    )?;
    let first = client.readback().await?;
    assert_eq!(first.attestation(), run.training.attestation());
    match fault {
        OriginalCurrentFault::NativeArtifact => run.fixture.corrupt_training_artifact()?,
        OriginalCurrentFault::GeneratorReceipt => run.fixture.corrupt_training_receipt()?,
        OriginalCurrentFault::SourceWithdrawal => run.fixture.withdraw()?,
    }
    let after_fault = (run.fixture.training_bytes()?, run.fixture.bytes()?);
    assert!(matches!(
        client.readback().await,
        Err(CandidateError::Command(CommandError::CommitUncertain))
    ));
    assert!(matches!(
        client.readback().await,
        Err(CandidateError::Unavailable)
    ));
    assert_eq!(peer.frames.load(Ordering::Acquire), 4);
    drop(client);
    assert_eq!(peer.finish()?, 4);
    assert_eq!(
        (run.fixture.training_bytes()?, run.fixture.bytes()?),
        after_fault
    );
    if matches!(fault, OriginalCurrentFault::SourceWithdrawal) {
        drop(run.owner);
        let failures = run
            .peers
            .into_iter()
            .map(|peer| peer.join().expect("original Source CURRENT peer").is_err())
            .filter(|failed| *failed)
            .count();
        assert!(failures > 0);
    } else {
        run.close()?;
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_candidate_current_cancellation_never_restores_cached_current()
-> anyhow::Result<()> {
    let run = completed_candidate().await?;
    let reached = Arc::new(tokio::sync::Notify::new());
    let (release, released) = std::sync::mpsc::channel();
    let (connection, peer) = page_peer(
        Arc::clone(&run.owner),
        run.fixture.config.clone(),
        Origin::Fresh,
        /*expected*/ None,
        Fault::HoldCurrent,
        Some(ResponseGate {
            reached: Arc::clone(&reached),
            release: released,
        }),
        Duration::from_secs(300),
    )?;
    let before = (run.fixture.training_bytes()?, run.fixture.bytes()?);
    let client = Arc::new(bind(
        connection,
        &run.fixture,
        run.dataset.clone(),
        run.training.clone(),
    )?);
    client.readback().await?;
    let pending = tokio::spawn({
        let client = Arc::clone(&client);
        async move { client.readback().await }
    });
    tokio::time::timeout(Duration::from_secs(30), reached.notified()).await?;
    pending.abort();
    match pending.await {
        Err(error) => assert!(error.is_cancelled()),
        Ok(_) => anyhow::bail!("Candidate Current wait was not cancelled"),
    }
    assert!(matches!(
        client.readback().await,
        Err(CandidateError::Unavailable)
    ));
    release.send(())?;
    drop(client);
    assert_eq!(peer.finish()?, 4);
    assert_eq!(
        (run.fixture.training_bytes()?, run.fixture.bytes()?),
        before
    );
    run.close()?;
    Ok(())
}
