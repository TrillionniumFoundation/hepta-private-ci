//! Cold Version retains the actual four-cut and held C owners. A Fresh input
//! context cannot restore execution or produce another FinalUse request.
use super::*;
use crate::OriginalCircuitEvaluatedVersionRecoveryV1;
use crate::circuit_feature_current::original_learning_read_fixture as reads;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_version_cold_readback_keeps_four_cut_and_original_c_readiness()
-> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready_with_live_artifacts()).await?;
    let OriginalDataset {
        config,
        receipt,
        readback,
        peer,
    } = Box::pin(original_dataset(&f)).await?;
    // These original owner channels exist before publication. Recovery moves
    // them once; it cannot open replacement owner or command custody later.
    let (training_connection, evaluation_connection, peers) =
        initial_version_connections(&f, &config)?;
    let (mut c, files, selected) = Box::pin(published_and_selected(&mut f)).await?;
    let crate::circuit_feature_current::Publication::Update { original, .. } =
        &c.retirement.0.publication
    else {
        anyhow::bail!("actual retained Control publication");
    };
    let intent = original.intent_digest();
    let version = &f.host.original.version;
    let artifact_selection = version.retained_publication_selection()?;
    let host = Arc::new(VersionHost::recover_from_original_evaluated_owners(
        config.clone(),
        readback,
        training_connection,
        evaluation_connection,
        OriginalCircuitEvaluatedVersionRecoveryV1 {
            dataset: receipt.clone(),
            // Deliberately Fresh: the recovery constructor must attenuate it.
            evaluation: f.context()?,
            intent_digest: intent,
            cell: c.cell.clone(),
            source: Arc::clone(&c.source),
            identity: c.runtime.identity.clone(),
            current: version.reopen_current()?,
            artifacts: version.authorities()?.artifacts,
            artifact_checkpoint: version.retained_artifact_checkpoint()?,
            artifact_selection: artifact_selection.signed,
            artifact_verifier: artifact_selection.verifier,
        },
        Duration::from_secs(300),
    )?);
    let before = (
        f.publication_bytes()?,
        files.bytes()?,
        f.host.original.predecessor_bytes()?,
    );
    use crate::OriginalCircuitEvaluatedVersionProgressV1 as Progress;
    let (progress, progress_peer) = VersionHost::original_evaluated_version_fixture_client(
        Arc::clone(&host),
        &config,
        &receipt,
        &f.training,
        &f.evaluation,
    )?;
    let observed = progress.readback().await?;
    for _ in 0..4 {
        assert_eq!(
            progress.publication_progress().await?,
            Progress::ReadbackAvailable
        );
    }
    assert_eq!(
        VersionHost::verify_original_progress_protocol_fixture(Arc::clone(&host)).await?,
        Progress::ReadbackAvailable
    );
    assert_eq!(observed.intent_digest(), intent);
    let publication = observed.publication().expect("same actual held C");
    assert_eq!(publication.bundle_digest(), f.bundle.digest()?);
    assert_eq!(publication.run_id(), &f.source_c.scope.run_id);
    assert_eq!(
        publication.authority(),
        codex_hepta_types::AuthorityPosture::DENY_ALL
    );
    assert!(matches!(
        VersionHost::prepare_original_version_fixture(Arc::clone(&host)).await,
        Err(VersionError::ReadbackRequired)
    ));
    assert!(matches!(
        VersionHost::run_original_issuer_fixture(Arc::clone(&host)).await,
        Err(VersionError::ReadbackRequired)
    ));
    assert_eq!(
        (
            f.publication_bytes()?,
            files.bytes()?,
            f.host.original.predecessor_bytes()?
        ),
        before
    );

    // Genuine Fresh receipt custody is still not a capability to restart S/C
    // under a recovered Version. Both refusals happen before any task/evidence
    // request, journal append or exchange of the retained T/B clients.
    let context = ReadContext::for_original_selection(f.context()?)?;
    let reader = Arc::new(ReadOwner::from_original_evaluated_owners(
        c.cell.clone(),
        c.source.as_ref().clone(),
        c.runtime.identity.clone(),
        context.clone(),
    )?);
    let (live, channel) = reads::evaluated_client(context)?;
    let source_peer = reads::serve(Arc::clone(&reader), channel);
    let fresh_s = SelectorFiles::new()?;
    let fresh_owner = fresh_s.owner(&f, OpenReceipt::Fresh)?;
    let fresh_bytes = fresh_s.bytes()?;
    assert!(matches!(
        VersionHost::bind_original_evaluated_selection_owner(Arc::clone(&host), fresh_owner, live,)
            .await,
        Err(VersionError::ReadbackRequired)
    ));
    assert_eq!(fresh_s.bytes()?, fresh_bytes);
    assert_eq!(
        source_peer
            .join()
            .expect("cold Version refuses fresh S before remote read")?,
        0
    );
    drop(reader);

    // The supplied S read capability owns the original completed S journal;
    // it has no Execute route and is not a fabricated evidence response.
    let (trainer, evaluator, source_peers) = f.clients()?;
    let trainer = Arc::new(trainer);
    let evaluator = Arc::new(evaluator);
    let original_s = Arc::new(
        files
            .owner(&f, OpenReceipt::Readback)?
            .into_evaluated_readback_owner(
                selected.clone(),
                c.cell.clone(),
                Arc::clone(&trainer),
                Arc::clone(&evaluator),
            )?,
    );
    let (s_reader, s_peer) = original_s.fixture_original_client(None)?;
    let context = ReadContext::for_original_next_use(selected.clone())?;
    let reader = Arc::new(ReadOwner::from_original_evaluated_owners(
        c.cell.clone(),
        c.source.as_ref().clone(),
        c.runtime.identity.clone(),
        context.clone(),
    )?);
    let (live, channel) = reads::evaluated_client(context)?;
    let source_peer = reads::serve(Arc::clone(&reader), channel);
    let fresh_c = SelectorFiles::new()?;
    let (journal, witness) = fresh_c.files(&f, &OpenReceipt::Fresh)?;
    let owner = crate::OriginalCircuitNextUseReceiptOwnerV1::create_evaluated(
        journal,
        witness,
        crate::OriginalCircuitEvaluatedNextUseReceiptConfigV1 {
            selection: selected.clone(),
            signer: f.host.original.credentials.observer.clone(),
            maximum_signature_lifetime_seconds: 300,
        },
        ed25519_dalek::SigningKey::from_bytes(&[43; 32]),
    )?;
    let fresh_bytes = fresh_c.bytes()?;
    assert!(matches!(
        VersionHost::bind_original_evaluated_next_use_owner(
            Arc::clone(&host),
            owner,
            live,
            s_reader,
        )
        .await,
        Err(VersionError::ReadbackRequired)
    ));
    assert_eq!(fresh_c.bytes()?, fresh_bytes);
    assert_eq!(
        source_peer
            .join()
            .expect("cold Version refuses fresh C before remote read")?,
        0
    );
    assert_eq!(
        s_peer
            .join()
            .expect("cold Version refuses before original S read")?,
        0
    );
    drop(reader);
    drop(original_s);
    drop(trainer);
    drop(evaluator);
    assert_eq!(source_peers.finish()?, [0, 0]);
    assert_eq!(
        (
            f.publication_bytes()?,
            files.bytes()?,
            f.host.original.predecessor_bytes()?
        ),
        before
    );

    let (client, channel) = readiness::version_client(&config, &receipt, &selected)?;
    let (ready, waiting) = tokio::sync::oneshot::channel();
    let server = tokio::spawn(VersionHost::fixture_synchronized_evaluated_readiness(
        Arc::clone(&host),
        channel,
        selected.clone(),
        ready,
    ));
    // Actual D/T/B plus final Source/Cell/CURRENT finish before the consumer
    // sends. The original server and client deadlines were already bound.
    waiting.await?;
    assert_eq!(client.read_current().await?, None);
    let completed = execute(&c, 1).await?;
    assert_eq!(
        read_receipt(&c, &f.definition, &completed)?.bundle_digest,
        f.bundle.digest()?
    );
    let read = client
        .read_current()
        .await?
        .expect("actual C through same Version producer");
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(selected.snapshot().clone())?;
    assert_eq!(
        read.observation(),
        &c.cell
            .read_learning_next_use(&coordinator, c.source.as_ref(), &c.runtime.identity,)?
    );
    let completed_bytes = (c_bytes(&c)?, files.bytes()?);
    f.host.original.version.withdraw()?;
    // The worker still finished its publication. This hint deliberately says
    // nothing about CURRENT; the mandatory actual read must detect withdrawal.
    assert_eq!(
        progress.publication_progress().await?,
        Progress::ReadbackAvailable
    );
    assert!(progress.readback().await.is_err());
    assert!(matches!(
        progress
            .prepare_original_version(Arc::new(std::sync::atomic::AtomicBool::new(false)))
            .await,
        Err(VersionError::ReadbackRequired)
    ));
    assert!(client.read_current().await.is_err());
    assert!(matches!(
        client.read_current().await,
        Err(ReadError::Unavailable)
    ));
    assert_eq!((c_bytes(&c)?, files.bytes()?), completed_bytes);
    drop(client);
    assert!(server.await?.is_err());
    drop(progress);
    assert_eq!(
        progress_peer
            .join()
            .expect("same original cold Version progress channel")?,
        7
    );
    drop(host);
    let counts = peers.finish()?;
    assert_eq!(counts[0], counts[1]);
    assert!(
        (6..128).contains(&counts[0]),
        "actual repeated T/B reads remain bounded"
    );
    assert!(peer.join().expect("same original Dataset recovery peer")? > 1);
    c.stop().await?;
    drop(c);
    f.finish().await
}
