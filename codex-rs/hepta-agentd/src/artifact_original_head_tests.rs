//! These actual-file mechanisms do not run ordinary A/B/C or restart daemons.
//! The private socket policy exception is explicit in the fixture support.

use std::fs;
use std::sync::atomic::AtomicBool;

use codex_hepta_learning_artifacts::decode_artifact_head_bytes_v1;
use pretty_assertions::assert_eq;

use super::super::Error;

#[path = "artifact_original_head_support_tests.rs"]
mod support;
use support::Fixture;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_artifact_head_signs_once_and_cold_reads_saved_signature() -> anyhow::Result<()> {
    let mut fixture = Fixture::new()?;
    let (owner, source) = fixture.create().await?;
    let running = AtomicBool::new(false);
    let bytes = owner.sign_original(&running)?;
    let signed = decode_artifact_head_bytes_v1(&bytes)?;
    let stored = fixture.head_bytes()?;
    assert!(matches!(owner.sign_original(&running), Err(Error::ReadbackRequired)));
    assert_eq!(fixture.head_bytes()?, stored);
    let prepared = fixture.prepared.take().ok_or_else(|| anyhow::anyhow!("original continuation"))?;
    fixture.writer.lock().map_err(|_| anyhow::anyhow!("writer lock"))?
        .finish_original_registry(prepared, signed.clone())?;
    assert_eq!(owner.read_original(&running)?, bytes);
    drop(owner);
    anyhow::ensure!(source.join().map_err(|_| anyhow::anyhow!("source thread"))?? >= 5);
    let (recovered, source) = fixture.recover().await?;
    assert_eq!(recovered.read_original(&running)?, bytes);
    assert_eq!(decode_artifact_head_bytes_v1(&bytes)?, signed);
    assert!(matches!(recovered.sign_original(&running), Err(Error::ReadbackRequired)));
    assert_eq!(fixture.head_bytes()?, stored);
    drop(recovered);
    source.join().map_err(|_| anyhow::anyhow!("source thread"))??;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_artifact_head_lost_reply_reads_original_without_recreating_writer() -> anyhow::Result<()> {
    let mut fixture = Fixture::new()?;
    let (owner, source) = fixture.create().await?;
    let running = AtomicBool::new(false);
    // The original effect completed, but the caller abandons both the reply
    // and its sole writer continuation. Only saved original evidence remains.
    drop(owner.sign_original(&running)?);
    drop(fixture.prepared.take());
    let stored = fixture.head_bytes()?;
    drop(owner);
    source.join().map_err(|_| anyhow::anyhow!("source thread"))??;
    let (recovered, source) = fixture.recover().await?;
    let first = recovered.read_original(&running)?;
    let second = recovered.read_original(&running)?;
    assert_eq!(first, second);
    assert_eq!(fixture.head_bytes()?, stored);
    assert!(matches!(recovered.sign_original(&running), Err(Error::ReadbackRequired)));
    let mut writer = fixture.writer.lock().map_err(|_| anyhow::anyhow!("writer lock"))?;
    let before = writer.read_original_registry_durable(&fixture.config.publication)?;
    assert_eq!(before.checkpoint().phase, codex_hepta_learning_artifacts::ArtifactPublicationPhaseV1::RegistryDurable);
    assert!(writer.prepare_original_registry(fixture.config.publication.clone(), b"payload").is_err());
    assert_eq!(writer.read_original_registry_durable(&fixture.config.publication)?.checkpoint(), before.checkpoint());
    drop(writer);
    drop(recovered);
    source.join().map_err(|_| anyhow::anyhow!("source thread"))??;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_artifact_head_restored_source_cannot_revive_consumed_connection() -> anyhow::Result<()> {
    let mut fixture = Fixture::new()?;
    let (owner, source) = fixture.create().await?;
    let running = AtomicBool::new(false);
    owner.sign_original(&running)?;
    let stored = fixture.head_bytes()?;
    let registry = fs::read_dir(fixture.root.join("artifact/registries"))?
        .next().ok_or_else(|| anyhow::anyhow!("original registry"))??.path();
    let original = fs::read(&registry)?;
    let mut damaged = original.clone();
    damaged[0] ^= 1;
    fs::write(&registry, damaged)?;
    assert!(owner.read_original(&running).is_err());
    fs::write(&registry, &original)?;
    assert!(owner.read_original(&running).is_err());
    assert!(matches!(owner.sign_original(&running), Err(Error::ReadbackRequired)));
    assert_eq!(fixture.head_bytes()?, stored);
    assert_eq!(fs::read(&registry)?, original);
    drop(owner);
    assert!(source.join().map_err(|_| anyhow::anyhow!("source thread"))?.is_err());
    Ok(())
}
