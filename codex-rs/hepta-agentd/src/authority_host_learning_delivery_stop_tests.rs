//! Cancellation owns only the additional stream; no authority fixture is used.
use super::*;
use pretty_assertions::assert_eq;
use std::io::Read;

#[test]
fn ending_original_scope_closes_the_retained_learning_stream() -> io::Result<()> {
    let stopped = AtomicBool::new(false);
    let (stream, mut peer) = UnixStream::pair()?;
    peer.set_read_timeout(Some(Duration::from_secs(1)))?;
    let active = Mutex::new(Some(stream));
    let stop = StopLearning {
        stopped: &stopped,
        active: &active,
    };
    drop(stop);
    assert!(stopped.load(Ordering::Acquire));
    // The duplicate socket held for cleanup remains owned, but shutdown must
    // unblock the peer even before that duplicate's eventual descriptor drop.
    assert!(active.lock().unwrap().is_some());
    assert_eq!(peer.read(&mut [0_u8; 1])?, 0);
    Ok(())
}
