//! Real local socket controls only; these do not mint a Root/human owner.

use super::*;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::panic::AssertUnwindSafe;
use std::panic::catch_unwind;

#[test]
fn normal_return_and_unwind_stop_and_shutdown_before_scope_join() {
    for unwind in [false, true] {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("paired-lane.sock");
        let listener = UnixListener::bind(&path).unwrap();
        let _client = UnixStream::connect(&path).unwrap();
        let (mut server, _) = listener.accept().unwrap();
        server
            .set_read_timeout(Some(Duration::from_secs(1)))
            .unwrap();
        let stopping = AtomicBool::new(false);
        let active = Mutex::new(Some(server.try_clone().unwrap()));
        let (result_sender, result_receiver) = std::sync::mpsc::channel();
        let outcome = catch_unwind(AssertUnwindSafe(|| {
            std::thread::scope(|scope| {
                scope.spawn(|| {
                    let result = server.read(&mut [0]);
                    result_sender.send(result).unwrap();
                });
                let stop = StopPairedLane {
                    stopping: &stopping,
                    active: &active,
                };
                if unwind {
                    panic!("synthetic original serve unwind control");
                }
                drop(stop);
            });
        }));
        assert_eq!(outcome.is_err(), unwind);
        assert!(stopping.load(Ordering::Acquire));
        assert_eq!(result_receiver.recv().unwrap().unwrap(), 0);
    }
}

#[test]
fn kernel_peer_credentials_distinguish_same_uid_wrong_pid_and_wrong_gid() {
    let directory = tempfile::tempdir().unwrap();
    let listener = UnixListener::bind(directory.path().join("peer.sock")).unwrap();
    let _client = UnixStream::connect(directory.path().join("peer.sock")).unwrap();
    let (server, _) = listener.accept().unwrap();
    // SAFETY: observe this test process without changing credentials.
    let (uid, gid) = unsafe { (libc::getuid(), libc::getgid()) };
    let peer = HostIssuerPeer {
        uid,
        pid: std::process::id(),
    };
    assert!(is_original_peer(&server, peer, gid).unwrap());
    let different_pid = HostIssuerPeer {
        pid: peer.pid + 1,
        ..peer
    };
    assert!(!is_original_peer(&server, different_pid, gid).unwrap());
    assert!(!is_original_peer(&server, peer, gid ^ 1).unwrap());
}
