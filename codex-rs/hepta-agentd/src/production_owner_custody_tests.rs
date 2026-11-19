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

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "actual UID0 original Root preparation, private TMPDIR and original writer required"]
async fn root_preparation_does_not_unlock_a_retained_uninstalled_original_writer()
-> Result<(), Box<dyn Error>> {
    // SAFETY: geteuid reads only this process's actual kernel credential.
    assert_eq!(unsafe { libc::geteuid() }, 0);
    let parent = std::env::var_os("HEPTA_CHECKPOINT_TEST_ROOT")
        .ok_or("explicit private Root test parent required")?;
    let parent = std::path::PathBuf::from(parent).canonicalize()?;
    assert_eq!(std::env::temp_dir().canonicalize()?, parent);
    let (config, fixture) = Fixture::new().await?;
    let identity = config.identity().clone();
    assert!(identity.fleet_root.starts_with(&parent));
    let original = std::fs::metadata(identity.layout.writer_lock())?;
    let contender = OpenOptions::new()
        .read(true)
        .write(true)
        .open(identity.layout.writer_lock())?;
    let (inputs, probes, issuer_peer) = fixture.inputs()?;
    // This is the existing public original host API, before Config install.
    // Its controlled test authority is not a genuine production Root grant.
    let host = crate::AgentdProductionWriterHost::open_with_recovery(
        &config,
        inputs.current_cut,
        inputs.authority,
        inputs.verifier,
        inputs.lease_id,
        inputs.lease_generation,
    )
    .await?;
    assert!(config.production_writer_host().is_none());
    let writer = host.writer();
    writer.verify_current_authority().await?;
    assert!(!takes_same_lock(&contender)?);
    let prepared =
        config.prepare_root_handoff(/*expected_uid*/ 60001, /*expected_gid*/ 60001);
    let preparation_returned = prepared.is_ok();
    let rejected_retained = matches!(&prepared, Err(crate::AgentdError::GenerationFenced(message))
        if message == "original Root configuration handoff: live production handles retain the original writer file");
    let lock_reacquired = takes_same_lock(&contender)?;
    writer.verify_current_authority().await?;
    drop(prepared);
    drop(host);
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
        "root-prepare-custody actual_uid=0 preparation_returned={preparation_returned} rejected_retained={rejected_retained} lock_reacquired={lock_reacquired} final_lock_reacquired={final_lock_reacquired} dev={} ino={} effects=0",
        retained.dev(),
        retained.ino()
    );
    assert!(!preparation_returned);
    assert!(rejected_retained);
    assert!(!lock_reacquired);
    assert!(final_lock_reacquired);
    Ok(())
}
