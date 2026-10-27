//! Controlled original registered File, actual Root worker and blocking CAS.
//! Read-only fenced clones must not become a second operational owner.
use super::*;
use pretty_assertions::assert_eq;
use std::fs::File;
use std::fs::OpenOptions;
use std::os::unix::fs::MetadataExt;

fn takes_lock(file: &File) -> Result<bool, Box<dyn Error>> {
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
async fn original_blocking_cas_keeps_file_after_session_and_worker_retire()
-> Result<(), Box<dyn Error>> {
    let directory = tempfile::Builder::new()
        .permissions(std::fs::Permissions::from_mode(0o700))
        .tempdir()?;
    let (trust, _) = fixture();
    let config = original_config(&directory.path().canonicalize()?, &trust)?;
    let original = config.identity().layout.writer_lock();
    let contender = OpenOptions::new().read(true).write(true).open(original)?;
    let identity = contender.metadata()?;
    let (session, head, peer, key) = connected().await;
    let (device, _, _device_directory) = owner(&session, key);
    let (notes, frontier, _notes_directory) = owner(&session, key);
    session
        .activate_final_use_owners(vec![device.clone(), notes.clone()])
        .await?;
    config.retain_root_session(&session)?;
    let retained = Arc::downgrade(&session.writer_file);
    let worker = session.worker.abort_handle();
    let authority = session.authority();
    let clock = session.clock();
    let verifier = session.verifier();
    drop(config);
    assert!(!takes_lock(&contender)?);
    frontier.wait.store(true, Ordering::Release);
    head.store(2, Ordering::Release);
    tokio::time::timeout(Duration::from_secs(2), async {
        while !frontier.entered.load(Ordering::Acquire) {
            tokio::time::sleep(Duration::from_millis(2)).await;
        }
    })
    .await?;
    drop(session);
    assert!(clock.now_unix_ms().is_err());
    assert!(verifier.verify(&authority, &authority.agent_id).is_err());
    tokio::time::timeout(Duration::from_secs(1), async {
        while !worker.is_finished() {
            tokio::task::yield_now().await;
        }
    })
    .await?;
    // The actual blocking CAS remains in its original frontier store even
    // though the cancelled async observation worker is already finished.
    assert!(frontier.wait.load(Ordering::Acquire));
    assert!(retained.upgrade().is_some());
    assert!(!takes_lock(&contender)?);
    frontier.wait.store(false, Ordering::Release);
    tokio::time::timeout(Duration::from_secs(1), async {
        while retained.upgrade().is_some() {
            tokio::task::yield_now().await;
        }
    })
    .await?;
    assert!(takes_lock(&contender)?);
    assert!(clock.now_unix_ms().is_err());
    assert!(verifier.verify(&authority, &authority.agent_id).is_err());
    assert_eq!(
        (contender.metadata()?.dev(), contender.metadata()?.ino()),
        (identity.dev(), identity.ino())
    );
    tokio::task::spawn_blocking(move || peer.join())
        .await?
        .map_err(|_| "original observation peer panicked")?;
    eprintln!(
        "root-session-blocking-custody worker_finished=true blocking_retired=true fenced_readonly_retained=true same_inode=true final_lock_reacquired=true effects=0"
    );
    Ok(())
}
