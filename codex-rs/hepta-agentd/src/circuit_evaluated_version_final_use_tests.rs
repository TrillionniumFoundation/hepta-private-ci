//! Actual UID-0 FinalUse issuer mechanism. Original T/B and publication are
//! real fixture owners; Root credentials and same-process transport are test
//! inputs. This ignored suite is not part of a default non-root PASS.

use super::*;
use anyhow::Context as _;
use crate::AgentdUnixFinalUseGrantProvider;
use crate::NeuronGenerationCurrentOwnerV1;
use crate::NeuronGenerationUpdateReadbackV1;
use crate::OriginalCircuitRetainedVersionErrorV1 as VersionError;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::io::Write;
use std::os::unix::net::UnixStream;
use std::sync::Mutex;

fn original_root_reply(
    mut stream: UnixStream,
    binding: FinalUseBinding,
    grant: SignedFinalUseGrant,
) -> std::thread::JoinHandle<anyhow::Result<()>> {
    std::thread::spawn(move || {
        stream.set_read_timeout(Some(Duration::from_secs(30)))?;
        let mut length = [0; 4];
        stream.read_exact(&mut length)?;
        let length = u32::from_be_bytes(length) as usize;
        anyhow::ensure!((1..=4096).contains(&length), "original Root request bound");
        let mut bytes = vec![0; length];
        stream.read_exact(&mut bytes)?;
        let request: serde_json::Value = serde_json::from_slice(&bytes)?;
        assert_eq!(request, serde_json::json!({
            "schema_version": 1,
            "operation": "runtime.agentd.production_operation",
            "binding": binding,
        }));
        let response = serde_json::to_vec(&serde_json::json!({
            "schema_version": 1,
            "revocations": { "authority_epoch": 1, "revision": 1, "revoked_grant_ids": [] },
            "grant": grant,
            "denial_reason": null,
        }))?;
        stream.write_all(&(response.len() as u32).to_be_bytes())?;
        stream.write_all(&response)?;
        let mut extra = [0; 1];
        assert_eq!(stream.read(&mut extra)?, 0, "one original issuer request");
        Ok(())
    })
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires the original UID-0 issuer fixture"]
async fn evaluated_version_late_b_loss_keeps_published_material_but_cannot_serve_s_or_start_c()
-> anyhow::Result<()> {
    // SAFETY: this is the existing explicitly selected UID-0 issuer suite.
    anyhow::ensure!(unsafe { libc::geteuid() } == 0, "actual UID-0 issuer fixture required");
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let inputs = f.inputs()?;
    let control = Arc::clone(&inputs.current);
    let operation = crate::learning_retained_task_operation_id_v1(
        &LearningIterationCoordinatorV1::from_snapshot(f.evaluation.snapshot().clone())?,
    )?;
    let arm = Arc::new(Mutex::new(None::<Digest32>));
    let (reached_tx, reached_rx) = tokio::sync::oneshot::channel();
    let (release_tx, release_rx) = std::sync::mpsc::channel();
    let watched = Arc::clone(&control);
    let armed = Arc::clone(&arm);
    let watched_operation = operation.clone();
    let mut reached_tx = Some(reached_tx);
    let mut published_e_reads = 0_u64;
    let (evaluator, evaluator_peer) = f.host.host.as_ref().context("same original E host")?
        .fixture_original_readback_connection_before_response(move || {
            let expected = *armed.lock().map_err(|_| anyhow::anyhow!("fixture intent arm"))?;
            let Some(intent) = expected else { return Ok(()); };
            let prepared = NeuronGenerationCurrentOwnerV1::recover_operation(
                &watched, watched_operation.as_str(), intent,
            )?;
            if matches!(NeuronGenerationCurrentOwnerV1::read_operation(&watched, &prepared)?,
                NeuronGenerationUpdateReadbackV1::Published(_))
            {
                published_e_reads += 1;
                // The first post-publication E read belongs to the consumed
                // publication. Its second read is Version's final read after
                // actual C install and reader construction. No response is
                // replaced; pause before calling the real E dispatch.
                if published_e_reads == 2 {
                    reached_tx.take().context("one original late E boundary")?
                        .send(()).map_err(|_| anyhow::anyhow!("fixture observer dropped"))?;
                    release_rx.recv_timeout(Duration::from_secs(30))?;
                }
            }
            Ok(())
        })?;
    let (held, peers) = Box::pin(held_predecessors_with_evaluator(&f, evaluator, evaluator_peer)).await?;
    let (task, c_runtime) = support::retained_version_task_inputs(
        f.c.take().context("one actual separate C admission")?,
        f.definition.clone(), f.source_c.clone(), Arc::clone(&f.host.original.baseline),
        f.bundle.clone(), f.original_source.as_ref().clone(), f.identity_a.clone(),
    )?;
    let (root_stream, root_peer) = UnixStream::pair()?;
    let issuer = AgentdUnixFinalUseGrantProvider::from_root_stream(
        root_stream, std::process::id(), commands::pidfd()?,
        Duration::from_secs(30), Duration::from_secs(300),
    )?;
    let host = Arc::new(Version::from_original_evaluated_owners(
        f.host.original.command_config.clone(), held.dataset, held.trainer, held.evaluator,
        inputs, task, f.host.original.version.retained_artifact_checkpoint()?, issuer,
        Duration::from_secs(300),
    )?);
    let prepared = Version::prepare_original_version_fixture(Arc::clone(&host)).await?;
    assert!(prepared.publication().is_none());
    let intent = prepared.intent_digest();
    *arm.lock().map_err(|_| anyhow::anyhow!("fixture intent arm"))? = Some(intent);
    let binding = Version::read_original_final_use_binding(Arc::clone(&host)).await?;
    let nonces = f.host.original.version.authority.capacity()?.used_nonces;
    let grant = f.host.original.version.sign(&binding)?;
    let root = original_root_reply(root_peer, binding, grant);
    let worker = tokio::spawn(Version::run_original_issuer_fixture(Arc::clone(&host)));
    tokio::time::timeout(Duration::from_secs(30), reached_rx).await??;
    let original_operation = NeuronGenerationCurrentOwnerV1::recover_operation(
        &control, operation.as_str(), intent,
    )?;
    assert!(matches!(NeuronGenerationCurrentOwnerV1::read_operation(&control, &original_operation)?,
        NeuronGenerationUpdateReadbackV1::Published(_)));
    f.host.retention_b.withdraw_target()?;
    release_tx.send(())?;
    worker.await??;
    root.join().expect("actual original Root frame")?;
    assert!(host.fixture_original_final_use_uncertain());
    assert!(host.fixture_original_selection_reader_installed()?,
        "the actual reader was installed before the final failed E read");
    let published_bytes = f.publication_bytes()?;
    let c_journal = c_runtime.identity.home_root.join("q24-cell.journal");
    let installed_c = std::fs::read(&c_journal)?;
    assert_eq!(f.host.original.version.authority.capacity()?.used_nonces, nonces + 1);
    assert!(matches!(Version::fixture_read_bound_original_version(Arc::clone(&host)).await,
        Err(VersionError::CommitUncertain)));
    let context = crate::OriginalCircuitEvaluatedLearningReadContextV1::for_original_selection(f.readback_context()?)?;
    let (reader, channel) = crate::circuit_feature_current::original_learning_read_fixture::evaluated_client(context)?;
    let server = tokio::spawn(Version::fixture_serve_original_selection_channel(Arc::clone(&host), channel));
    assert!(reader.read_current().await.is_err());
    server.abort();
    assert!(server.await.expect_err("unready serving lane cancelled").is_cancelled());
    drop(reader);
    assert!(Version::run_original_c(Arc::clone(&host), codex_arg0::Arg0DispatchPaths::default()).await.is_err());
    assert!(Version::prepare_original_version_fixture(Arc::clone(&host)).await.is_err());
    assert!(matches!(Version::run_original_issuer_fixture(Arc::clone(&host)).await,
        Err(VersionError::ReadbackRequired)));
    assert_eq!(f.publication_bytes()?, published_bytes);
    assert_eq!(std::fs::read(c_journal)?, installed_c);
    assert_eq!(f.host.original.version.authority.capacity()?.used_nonces, nonces + 1);
    drop(host);
    let reads = peers.finish()?;
    assert!(reads.iter().all(|count| *count > 0));
    drop(c_runtime);
    f.finish().await
}
