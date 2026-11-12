//! The same real D/T/B drives Version preparation, one original Root issuer
//! request, and the existing C factory. UID-0 signing remains an explicit test.
use super::*;
use crate::AgentdUnixFinalUseGrantProvider;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use std::io::Read;
use std::io::Write;
use std::os::unix::net::UnixStream;

#[path = "circuit_evaluated_version_shared_command_tests.rs"]
mod shared_commands;

fn root_reply(
    mut stream: UnixStream,
    expected: FinalUseBinding,
    signed: SignedFinalUseGrant,
) -> std::thread::JoinHandle<anyhow::Result<()>> {
    std::thread::spawn(move || {
        stream.set_read_timeout(Some(Duration::from_secs(30)))?;
        let mut length = [0; 4];
        stream.read_exact(&mut length)?;
        let length = u32::from_be_bytes(length) as usize;
        anyhow::ensure!(
            (1..=4096).contains(&length),
            "bounded original Root request"
        );
        let mut bytes = vec![0; length];
        stream.read_exact(&mut bytes)?;
        let request: serde_json::Value = serde_json::from_slice(&bytes)?;
        assert_eq!(
            request,
            serde_json::json!({
                "schema_version": 1, "operation": "runtime.agentd.production_operation", "binding": expected,
            })
        );
        let response = serde_json::to_vec(&serde_json::json!({
            "schema_version": 1,
            "revocations": { "authority_epoch": 1, "revision": 1, "revoked_grant_ids": [] },
            "grant": signed, "denial_reason": null,
        }))?;
        stream.write_all(&(u32::try_from(response.len())?).to_be_bytes())?;
        stream.write_all(&response)?;
        let mut extra = [0; 1];
        assert_eq!(
            stream.read(&mut extra)?,
            0,
            "the consumed issuer cannot send another request"
        );
        Ok(())
    })
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires the original UID-0 issuer fixture"]
async fn evaluated_version_issuer_consumes_actual_d_t_b_and_installs_original_c_once()
-> anyhow::Result<()> {
    // SAFETY: this ignored case must be selected by the existing UID-0 runner.
    anyhow::ensure!(
        unsafe { libc::geteuid() } == 0,
        "original UID-0 issuer fixture"
    );
    let mut f = Box::pin(PublicationFixture::ready_with_live_artifacts()).await?;
    let OriginalDataset {
        config,
        receipt: dataset,
        readback,
        peer,
    } = Box::pin(original_dataset(&f)).await?;
    // Three real, independently bound command sessions plus Version's original
    // fourth session exercise the actual global permit. This case proves the
    // shared S/C mechanism under that cap; the separate mixed-purpose case
    // checks Root command / Candidate pages / B evidence / Version command.
    let mut occupied = Vec::new();
    let mut occupied_peers = Vec::new();
    for _ in 0..3 {
        let (connection, served) = commands::original_version_training_readback_connection(
            config.clone(),
            Arc::clone(&f.trainer),
        )?;
        let client = connection.bind_original_dataset(dataset.clone())?;
        assert_eq!(client.readback().await?, f.training);
        occupied.push(client);
        occupied_peers.push(served);
    }
    let (trainer, evaluator, peers) = initial_version_connections(&f, &config)?;
    commands::original_version_fifth_connection_refuses(Arc::clone(&f.trainer)).await?;
    let (stream, root) = UnixStream::pair()?;
    let issuer = AgentdUnixFinalUseGrantProvider::from_root_stream(
        stream,
        std::process::id(),
        commands::pidfd()?,
        Duration::from_secs(30),
        Duration::from_secs(300),
    )?;
    let admission = f.c.take().expect("one actual C admission");
    let request = admission.request.clone();
    let (task, runtime) = support::retained_version_task_inputs(
        admission,
        f.definition.clone(),
        f.source_c.clone(),
        Arc::clone(&f.host.original.baseline),
        f.bundle.clone(),
        f.original_source.as_ref().clone(),
        f.identity_a.clone(),
    )?;
    let checkpoint = f.host.original.version.retained_artifact_checkpoint()?;
    let inputs = f.inputs()?;
    let host = Arc::new(VersionHost::from_original_evaluated_owners(
        config.clone(),
        readback,
        trainer,
        evaluator,
        inputs,
        task,
        checkpoint,
        issuer,
        Duration::from_secs(300),
    )?);
    let prepared = VersionHost::prepare_original_version_fixture(Arc::clone(&host)).await?;
    assert!(prepared.publication().is_none());
    let binding = VersionHost::read_original_final_use_binding(Arc::clone(&host)).await?;
    assert_eq!(
        binding.destination_id,
        "agentd.cell-generation.next-task-same-model"
    );
    let before = f.publication_bytes()?;
    let upstream = (
        f.host.original.predecessor_bytes()?,
        f.host.upstream_files()?,
        f.host.original_files()?,
    );
    let nonces = f.host.original.version.authority.capacity()?.used_nonces;
    let root_peer = root_reply(
        root,
        binding.clone(),
        f.host.original.version.sign(&binding)?,
    );
    VersionHost::run_original_issuer_fixture(Arc::clone(&host)).await?;
    root_peer
        .join()
        .expect("actual original Root issuer frame")?;
    let actual = VersionHost::read_original_version_fixture(Arc::clone(&host)).await?;
    assert_eq!(actual.intent_digest(), prepared.intent_digest());
    let publication = actual.publication().expect("actual original C factory");
    assert_eq!(publication.bundle_digest(), f.bundle.digest()?);
    assert_ne!(
        publication.bundle_digest(),
        f.host.original.candidate.digest()?
    );
    assert_eq!(publication.run_id(), &f.source_c.scope.run_id);
    assert_ne!(publication.run_id(), &f.source_a.scope.run_id);
    assert_eq!(
        publication.task_digest().as_array(),
        &f.config_c.task_digest
    );
    assert_eq!(
        publication.authority(),
        codex_hepta_types::AuthorityPosture::DENY_ALL
    );
    assert_ne!(f.publication_bytes()?, before);
    assert_eq!(
        f.host.original.version.authority.capacity()?.used_nonces,
        nonces + 1
    );
    assert_eq!(
        (
            f.host.original.predecessor_bytes()?,
            f.host.upstream_files()?,
            f.host.original_files()?
        ),
        upstream
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
        f.host.original.version.authority.capacity()?.used_nonces,
        nonces + 1
    );
    let (installed, cell, source, task) =
        VersionHost::take_original_installed_c_fixture(Arc::clone(&host)).await?;
    assert!(matches!(
        VersionHost::take_original_installed_c_fixture(Arc::clone(&host)).await,
        Err(VersionError::ReadbackRequired)
    ));
    let mut c = Box::pin(support::start_installed_retained_version(
        runtime, request, installed, cell, source, task, &f.bundle,
    ))
    .await?;
    Box::pin(shared_commands::run_shared_s_c(
        &f,
        Arc::clone(&host),
        &config,
        &dataset,
        &c,
    ))
    .await?;
    commands::original_version_fifth_connection_refuses(Arc::clone(&f.trainer)).await?;
    // These are still the original three sessions: no rebind or replacement
    // was needed while Version, S and C used the same fourth command client.
    for client in &occupied {
        assert_eq!(client.readback().await?, f.training);
    }
    drop(occupied);
    for served in occupied_peers {
        assert_eq!(
            served
                .join()
                .expect("original occupied Trainer command session")?,
            2
        );
    }
    drop(host);
    let counts = peers.finish()?;
    assert_eq!(counts[0], counts[1]);
    assert!(
        (6..128).contains(&counts[0]),
        "actual original T/B read budget"
    );
    assert!(peer.join().expect("same original Dataset Version peer")? > 1);
    c.stop().await?;
    drop(c);
    // AuthBus signing and same-process peers remain explicit test fixtures;
    // this real factory/command mechanism does not count as ordinary custody.
    f.finish().await
}
