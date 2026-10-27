//! Real registered-owner and SQLite composition; controlled test authority only.
//! A retained writer must keep the original Registry file locked as well as
//! its distinct durable-store fence. No effect is dispatched by this test.

use super::Fixture;
use super::assert_no_issuer_request;
use crate::AgentdConfig;
use crate::attach_production_operation_host;
use codex_hepta_memory::CognitiveStore;
use pretty_assertions::assert_eq;
use std::error::Error;
use std::fs::File;
use std::fs::OpenOptions;
use std::os::unix::fs::MetadataExt;
use std::sync::atomic::Ordering;

fn takes_same_lock(file: &File) -> Result<bool, Box<dyn Error>> {
    match file.try_lock() {
        Ok(()) => {
            file.unlock()?;
            Ok(true)
        }
        Err(std::fs::TryLockError::WouldBlock) => Ok(false),
        Err(std::fs::TryLockError::Error(error)) => Err(error.into()),
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn escaped_original_host_and_writer_retain_the_same_registered_owner_file()
-> Result<(), Box<dyn Error>> {
    let (mut config, fixture) = Fixture::new().await?;
    let identity = config.identity().clone();
    let lock_path = identity.layout.writer_lock();
    let original = std::fs::metadata(lock_path)?;
    let contender = OpenOptions::new().read(true).write(true).open(lock_path)?;
    assert!(!takes_same_lock(&contender)?);
    let (inputs, probes, issuer_peer) = fixture.inputs()?;
    attach_production_operation_host(&mut config, inputs).await?;
    let host = config
        .production_writer_host()
        .ok_or("original host absent")?;
    let writer = host.writer();
    writer.verify_current_authority().await?;
    drop(config);

    let host_lock_reacquired = takes_same_lock(&contender)?;
    let replacement = AgentdConfig::load(
        identity.fleet_root.clone(),
        identity.agent_id.clone(),
        identity.spawn_generation,
        identity.home_root.clone(),
        identity.run_root.clone(),
        identity.home_root.clone(),
        identity.workspace.clone(),
    );
    let replacement_loaded = replacement.is_ok();
    drop(replacement);
    // This separately retained SQLite/store fence must not be mistaken for
    // the registered process-owner lock tested above.
    let store_still_fenced = CognitiveStore::open(&identity.layout).await.is_err();
    writer.verify_current_authority().await?;
    drop(host);
    let writer_lock_reacquired = takes_same_lock(&contender)?;
    writer.verify_current_authority().await?;
    assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
    assert_no_issuer_request(issuer_peer)?;
    drop(writer);
    let final_lock_reacquired = takes_same_lock(&contender)?;
    let retained = contender.metadata()?;
    assert_eq!(
        (retained.dev(), retained.ino()),
        (original.dev(), original.ino())
    );
    eprintln!(
        "owner-custody host_lock_reacquired={host_lock_reacquired} replacement_loaded={replacement_loaded} writer_lock_reacquired={writer_lock_reacquired} store_still_fenced={store_still_fenced} final_lock_reacquired={final_lock_reacquired} dev={} ino={} effects=0",
        retained.dev(),
        retained.ino()
    );
    assert!(store_still_fenced);
    assert!(!host_lock_reacquired);
    assert!(!replacement_loaded);
    assert!(!writer_lock_reacquired);
    assert!(final_lock_reacquired);
    Ok(())
}
