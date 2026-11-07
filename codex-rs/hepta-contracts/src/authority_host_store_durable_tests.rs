use super::*;
use pretty_assertions::assert_eq;
use std::sync::Mutex;
use std::sync::mpsc;

#[test]
fn a_visible_rename_cannot_be_read_as_current_before_publication_finishes() {
    #[derive(Debug)]
    enum PublicationEvent {
        VisibleRename,
        Completed(Result<(), AuthorityTrustError>),
    }

    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let store = Arc::new(
        HostAuthorityFrontierStore::initialize(root.clone(), OWNER.into(), 1_u64).unwrap(),
    );
    let (events, observed) = mpsc::channel();
    let entered = events.clone();
    let (resume, released) = mpsc::channel();
    let released = Mutex::new(released);
    *root.before_directory_sync.lock().unwrap() = Some(Arc::new(move || {
        entered
            .send(PublicationEvent::VisibleRename)
            .map_err(std::io::Error::other)?;
        released
            .lock()
            .unwrap()
            .recv_timeout(Duration::from_secs(10))
            .map_err(std::io::Error::other)
    }));
    let writing = store.clone();
    let publisher = std::thread::spawn(move || {
        let result = writing.compare_and_set(OWNER, &1, &2);
        let _ = events.send(PublicationEvent::Completed(result));
        result
    });
    let entered = match observed.recv_timeout(Duration::from_secs(10)) {
        Ok(PublicationEvent::VisibleRename) => Ok(()),
        Ok(PublicationEvent::Completed(result)) => {
            Err(format!("publisher completed before the rename barrier: {result:?}"))
        }
        Err(error) => Err(format!("rename barrier was not observed: {error:?}")),
    };
    if let Err(error) = entered {
        *root.before_directory_sync.lock().unwrap() = None;
        drop(resume);
        let finished = publisher.is_finished();
        let joined = finished.then(|| publisher.join());
        panic!("{error}; publisher_finished={finished}; joined={joined:?}");
    }
    // The real data-file fsync and rename have finished; directory durability
    // is deliberately not acknowledged yet. Only the unsafe private read sees
    // the new value. Public reads/open must contend on the publication lock.
    assert_eq!(store.read(), Ok(2));
    let public = store.load(OWNER);
    let reopened = HostAuthorityFrontierStore::<u64>::open(root.clone(), OWNER.into());
    *root.before_directory_sync.lock().unwrap() = None;
    resume.send(()).unwrap();
    assert_eq!(publisher.join().unwrap(), Ok(()));
    assert_eq!(public, Err(AuthorityTrustError::Conflict));
    assert!(matches!(reopened, Err(AuthorityTrustError::Conflict)));
    assert_eq!(store.load(OWNER), Ok(2));
}

#[test]
fn uncertain_directory_sync_is_never_an_ack_but_can_be_independently_reconciled() {
    let directory = tempfile::tempdir().unwrap();
    let root = test_directory(directory.path());
    let store = HostAuthorityFrontierStore::initialize(root.clone(), OWNER.into(), 1_u64).unwrap();
    *root.before_directory_sync.lock().unwrap() = Some(Arc::new(|| {
        Err(std::io::Error::other("controlled durability failure"))
    }));
    assert_eq!(
        store.compare_and_set(OWNER, &1, &2),
        Err(AuthorityTrustError::Unavailable)
    );
    assert_eq!(
        store.read(),
        Ok(2),
        "rename was visible despite the failed acknowledgement"
    );
    assert_eq!(store.load(OWNER), Err(AuthorityTrustError::Unavailable));
    assert!(matches!(
        HostAuthorityFrontierStore::<u64>::open(root.clone(), OWNER.into()),
        Err(AuthorityTrustError::Unavailable)
    ));
    // An independent serialized read must actually sync file+directory before
    // acknowledging the retained value. It does not restore the predecessor or
    // authorize a writer generation/replay; that belongs to the original owner.
    *root.before_directory_sync.lock().unwrap() = None;
    assert_eq!(store.load(OWNER), Ok(2));
    assert_eq!(
        store.compare_and_set(OWNER, &1, &3),
        Err(AuthorityTrustError::Conflict)
    );
}
