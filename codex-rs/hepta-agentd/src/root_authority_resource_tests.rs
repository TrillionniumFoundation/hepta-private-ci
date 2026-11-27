//! Same original consumers must release their actual journal locks after
//! session/worker retirement, even though their clocks point back to LiveRoot.
use super::*;
use pretty_assertions::assert_eq;
use std::collections::BTreeMap;
use std::fs::OpenOptions;
use std::os::unix::fs::MetadataExt;
use std::path::Path;

fn contents(path: &Path) -> Result<BTreeMap<String, Vec<u8>>, std::io::Error> {
    let mut result = BTreeMap::new();
    for entry in std::fs::read_dir(path)? {
        let entry = entry?;
        if entry.file_type()?.is_file() {
            result.insert(
                entry.file_name().to_string_lossy().into_owned(),
                std::fs::read(entry.path())?,
            );
        }
    }
    Ok(result)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn retired_original_session_releases_both_journals_and_live_root_after_worker_exit()
-> Result<(), Box<dyn std::error::Error>> {
    let (session, _, peer, key) = connected().await;
    let weak = Arc::downgrade(&session.live);
    let worker = session.worker.abort_handle();
    let (device, _, device_directory) = owner(&session, key);
    let (notes, _, notes_directory) = owner(&session, key);
    session
        .activate_final_use_owners(vec![device.clone(), notes.clone()])
        .await?;
    let authority = session.authority();
    let clock = session.clock();
    let verifier = session.verifier();
    verifier.verify(&authority, &authority.agent_id)?;
    let device_lock = OpenOptions::new()
        .read(true)
        .write(true)
        .open(device_directory.path().join("authority.lock"))?;
    let notes_lock = OpenOptions::new()
        .read(true)
        .write(true)
        .open(notes_directory.path().join("authority.lock"))?;
    let device_identity = device_lock.metadata()?;
    let notes_identity = notes_lock.metadata()?;
    let device_before = contents(device_directory.path())?;
    let notes_before = contents(notes_directory.path())?;
    assert!(device_lock.try_lock().is_err());
    assert!(notes_lock.try_lock().is_err());
    assert!(!worker.is_finished());
    drop(session);
    assert!(clock.now_unix_ms().is_err());
    assert!(verifier.verify(&authority, &authority.agent_id).is_err());
    // Drop EVERY external original owner/clock/verifier before waiting for
    // the original task to finish. AbortHandle only observes task completion;
    // it holds no replacement Root, authority, consumer, clock or journal.
    drop(device);
    drop(notes);
    drop(clock);
    drop(verifier);
    tokio::time::timeout(Duration::from_secs(1), async {
        while !worker.is_finished() {
            tokio::task::yield_now().await;
        }
    })
    .await?;
    tokio::task::spawn_blocking(move || peer.join())
        .await?
        .map_err(|_| "original observation peer panicked")?;
    assert!(worker.is_finished());
    let live_retained = weak.upgrade().is_some();
    let device_released = device_lock.try_lock().is_ok();
    let notes_released = notes_lock.try_lock().is_ok();
    let bytes_unchanged = device_before == contents(device_directory.path())?
        && notes_before == contents(notes_directory.path())?;
    eprintln!(
        "original_root_resource_observation worker_finished={} live_retained={} device_lock_reacquired={} notes_lock_reacquired={} bytes_unchanged={}",
        worker.is_finished(),
        live_retained,
        device_released,
        notes_released,
        bytes_unchanged,
    );
    assert_eq!(
        (
            live_retained,
            device_released,
            notes_released,
            bytes_unchanged
        ),
        (false, true, true, true)
    );
    assert_eq!(
        (device_lock.metadata()?.dev(), device_lock.metadata()?.ino()),
        (device_identity.dev(), device_identity.ino())
    );
    assert_eq!(
        (notes_lock.metadata()?.dev(), notes_lock.metadata()?.ino()),
        (notes_identity.dev(), notes_identity.ino())
    );
    device_lock.unlock()?;
    notes_lock.unlock()?;
    Ok(())
}
