//! Actual Version/FinalUse mechanisms with an explicit UID-0 protocol fixture.
//! These do not assert native Training or a deployed independent-role loop.
use super::*;
use pretty_assertions::assert_eq;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires the original UID-0 issuer fixture"]
async fn retained_version_issuer_uses_actual_prepared_binding_and_installs_distinct_c()
-> anyhow::Result<()> {
    let mut fixture = RetainedIssuerFixtureV1::ready().await?;
    let (prepared, binding) = fixture.prepare().await?;
    let before = fixture.original.publication_bytes()?;
    let nonces = fixture.original.version.authority.capacity()?.used_nonces;
    let grant = fixture.original.version.sign(&binding)?;
    let peer = root_reply(
        fixture.root_peer.take().context("original Root peer")?,
        binding,
        RetainedIssuerReplyV1::Signed(grant),
    );
    OriginalCircuitRetainedVersionHostV1::run_original_issuer_fixture(fixture.host()).await?;
    peer.join()
        .map_err(|_| anyhow::anyhow!("original Root peer"))??;
    let actual =
        OriginalCircuitRetainedVersionHostV1::read_original_version_fixture(fixture.host()).await?;
    let publication = actual
        .publication()
        .context("actual installed C publication")?;
    assert_eq!(actual.intent_digest(), prepared.intent_digest());
    assert_eq!(
        publication.bundle_digest(),
        fixture.original.bundle.digest()?
    );
    assert_eq!(
        publication.run_id(),
        &fixture.original.source_c.scope.run_id
    );
    assert_eq!(
        publication.task_digest().as_array(),
        &fixture.original.config_c.task_digest
    );
    assert_eq!(publication.authority(), AuthorityPosture::DENY_ALL);
    assert_ne!(
        publication.run_id(),
        &fixture.original.source_a.scope.run_id
    );
    assert_ne!(
        fixture.original.source_c.observation,
        fixture.original.source_a.observation
    );
    assert_ne!(
        fixture.original.config_c.task_digest,
        fixture.original.config_a.task_digest
    );
    assert_ne!(fixture.original.publication_bytes()?, before);
    assert_eq!(
        fixture.original.version.authority.capacity()?.used_nonces,
        nonces + 1
    );
    require_no_second_issuer(fixture.host()).await;
    assert!(matches!(
        OriginalCircuitRetainedVersionHostV1::prepare_original_version_fixture(fixture.host())
            .await,
        Err(OriginalCircuitRetainedVersionErrorV1::ReadbackRequired)
    ));
    assert_eq!(
        fixture.original.version.authority.capacity()?.used_nonces,
        nonces + 1
    );
    // The real C factory is installed. A separate authorized RunStart and C
    // completion are deliberately not fabricated by this issuer mechanism.
    fixture.finish()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires the original UID-0 issuer fixture"]
async fn retained_version_issuer_denied_once_keeps_actual_prepared_operation_read_only()
-> anyhow::Result<()> {
    let mut fixture = RetainedIssuerFixtureV1::ready().await?;
    let (_, binding) = fixture.prepare().await?;
    let before = fixture.original.publication_bytes()?;
    let nonces = fixture.original.version.authority.capacity()?.used_nonces;
    let peer = root_reply(
        fixture.root_peer.take().context("original Root peer")?,
        binding.clone(),
        RetainedIssuerReplyV1::Denied,
    );
    OriginalCircuitRetainedVersionHostV1::run_original_issuer_fixture(fixture.host()).await?;
    peer.join()
        .map_err(|_| anyhow::anyhow!("original Root denial"))??;
    assert!(matches!(
        OriginalCircuitRetainedVersionHostV1::read_original_version_fixture(fixture.host()).await,
        Err(OriginalCircuitRetainedVersionErrorV1::FinalUseDenied)
    ));
    assert_eq!(
        OriginalCircuitRetainedVersionHostV1::read_original_final_use_binding(fixture.host())
            .await?,
        binding
    );
    require_no_second_issuer(fixture.host()).await;
    assert_eq!(fixture.original.publication_bytes()?, before);
    assert_eq!(
        fixture.original.version.authority.capacity()?.used_nonces,
        nonces
    );
    fixture.finish()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires the original UID-0 issuer fixture"]
async fn retained_version_issuer_lost_ack_never_reissues_original_intent() -> anyhow::Result<()> {
    let mut fixture = RetainedIssuerFixtureV1::ready().await?;
    let (_, binding) = fixture.prepare().await?;
    let before = fixture.original.publication_bytes()?;
    let nonces = fixture.original.version.authority.capacity()?.used_nonces;
    let peer = root_reply(
        fixture.root_peer.take().context("original Root peer")?,
        binding.clone(),
        RetainedIssuerReplyV1::LoseAck,
    );
    OriginalCircuitRetainedVersionHostV1::run_original_issuer_fixture(fixture.host()).await?;
    peer.join()
        .map_err(|_| anyhow::anyhow!("original Root lost acknowledgement"))??;
    assert!(matches!(
        OriginalCircuitRetainedVersionHostV1::read_original_version_fixture(fixture.host()).await,
        Err(OriginalCircuitRetainedVersionErrorV1::CommitUncertain)
    ));
    assert_eq!(
        OriginalCircuitRetainedVersionHostV1::read_original_final_use_binding(fixture.host())
            .await?,
        binding
    );
    require_no_second_issuer(fixture.host()).await;
    assert_eq!(fixture.original.publication_bytes()?, before);
    assert_eq!(
        fixture.original.version.authority.capacity()?.used_nonces,
        nonces
    );
    fixture.finish()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires the original UID-0 issuer fixture"]
async fn retained_version_issuer_wrong_grant_cannot_replace_prepared_purpose() -> anyhow::Result<()>
{
    let mut fixture = RetainedIssuerFixtureV1::ready().await?;
    let (_, binding) = fixture.prepare().await?;
    let before = fixture.original.publication_bytes()?;
    let nonces = fixture.original.version.authority.capacity()?.used_nonces;
    let mut wrong = binding.clone();
    wrong.destination_id = "runtime.learning.resident-admission.v3".into();
    let grant = fixture.original.version.sign(&wrong)?;
    let peer = root_reply(
        fixture.root_peer.take().context("original Root peer")?,
        binding.clone(),
        RetainedIssuerReplyV1::Signed(grant),
    );
    OriginalCircuitRetainedVersionHostV1::run_original_issuer_fixture(fixture.host()).await?;
    peer.join()
        .map_err(|_| anyhow::anyhow!("wrong-purpose Root fixture"))??;
    assert!(matches!(
        OriginalCircuitRetainedVersionHostV1::read_original_version_fixture(fixture.host()).await,
        Err(OriginalCircuitRetainedVersionErrorV1::CommitUncertain)
    ));
    assert_eq!(
        OriginalCircuitRetainedVersionHostV1::read_original_final_use_binding(fixture.host())
            .await?,
        binding
    );
    require_no_second_issuer(fixture.host()).await;
    assert_eq!(fixture.original.publication_bytes()?, before);
    assert_eq!(
        fixture.original.version.authority.capacity()?.used_nonces,
        nonces
    );
    fixture.finish()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires the original UID-0 issuer fixture"]
async fn retained_version_issuer_withdrawal_before_root_request_sends_no_frame()
-> anyhow::Result<()> {
    let mut fixture = RetainedIssuerFixtureV1::ready().await?;
    fixture.prepare().await?;
    let before = fixture.original.publication_bytes()?;
    let nonces = fixture.original.version.authority.capacity()?.used_nonces;
    fixture.original.version.withdraw()?;
    OriginalCircuitRetainedVersionHostV1::run_original_issuer_fixture(fixture.host()).await?;
    no_root_frame(fixture.root_peer.take().context("original Root peer")?)?;
    assert!(
        OriginalCircuitRetainedVersionHostV1::read_original_version_fixture(fixture.host())
            .await
            .is_err()
    );
    require_no_second_issuer(fixture.host()).await;
    assert_eq!(fixture.original.publication_bytes()?, before);
    assert_eq!(
        fixture.original.version.authority.capacity()?.used_nonces,
        nonces
    );
    fixture.finish()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires the original UID-0 issuer fixture"]
async fn retained_version_issuer_queued_cancellation_sends_no_frame_and_never_reopens_once()
-> anyhow::Result<()> {
    let mut fixture = RetainedIssuerFixtureV1::ready().await?;
    let (prepared, binding) = fixture.prepare().await?;
    let before = fixture.original.publication_bytes()?;
    let nonces = fixture.original.version.authority.capacity()?.used_nonces;
    let host = fixture.host();
    std::thread::spawn(move || -> anyhow::Result<()> {
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(1)
            .max_blocking_threads(1)
            .enable_all()
            .build()?;
        runtime.block_on(async move {
            let (occupied_tx, occupied_rx) = tokio::sync::oneshot::channel();
            let (release_tx, release_rx) = std::sync::mpsc::channel();
            let blocker = tokio::task::spawn_blocking(move || {
                let _ = occupied_tx.send(());
                release_rx.recv()
            });
            occupied_rx.await?;
            let mut request =
                Box::pin(OriginalCircuitRetainedVersionHostV1::run_original_issuer_fixture(host));
            std::future::poll_fn(|cx| match std::future::Future::poll(request.as_mut(), cx) {
                std::task::Poll::Pending => std::task::Poll::Ready(()),
                std::task::Poll::Ready(_) => {
                    panic!("issuer request must queue behind the original blocker")
                }
            })
            .await;
            drop(request);
            release_tx.send(())?;
            blocker.await??;
            tokio::task::spawn_blocking(|| {}).await?;
            Ok(())
        })
    })
    .join()
    .map_err(|_| anyhow::anyhow!("queued original issuer runtime"))??;
    no_root_frame(fixture.root_peer.take().context("original Root peer")?)?;
    require_no_second_issuer(fixture.host()).await;
    assert_eq!(
        OriginalCircuitRetainedVersionHostV1::read_original_final_use_binding(fixture.host())
            .await?,
        binding
    );
    assert_eq!(
        OriginalCircuitRetainedVersionHostV1::read_original_version_fixture(fixture.host()).await?,
        prepared
    );
    assert_eq!(fixture.original.publication_bytes()?, before);
    assert_eq!(
        fixture.original.version.authority.capacity()?.used_nonces,
        nonces
    );
    fixture.finish()
}
