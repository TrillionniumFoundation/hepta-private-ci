use super::*;
use pretty_assertions::assert_eq;
use std::error::Error;
use std::os::unix::net::UnixListener;

type TestResult = Result<(), Box<dyn Error>>;

#[test]
fn inherited_socketpair_preserves_exact_frame_bytes() -> TestResult {
    let (owner, mut application) = UnixStream::pair()?;
    let channel = AgentdNotesChannel::from_private_channel(owner)?;
    let peer = std::thread::spawn(move || -> io::Result<Vec<u8>> {
        let mut prefix = [0; 4];
        application.read_exact(&mut prefix)?;
        let mut request = vec![0; u32::from_be_bytes(prefix) as usize];
        application.read_exact(&mut request)?;
        application.write_all(&3_u32.to_be_bytes())?;
        application.write_all(b"ack")?;
        Ok(request)
    });
    assert_eq!(channel.exchange(b" exact\nbytes ")?, b"ack");
    assert_eq!(peer.join().expect("application thread")?, b" exact\nbytes ");
    Ok(())
}

#[test]
fn named_socket_is_not_a_bootstrap_channel() -> TestResult {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("not-private.sock");
    let listener = UnixListener::bind(&path)?;
    let client = UnixStream::connect(&path)?;
    let (server, _) = listener.accept()?;
    assert!(AgentdNotesChannel::from_private_channel(client).is_err());
    assert!(AgentdNotesChannel::from_private_channel(server).is_err());
    Ok(())
}

#[test]
fn lost_reply_permanently_disables_further_effect_entry() -> TestResult {
    let (owner, mut application) = UnixStream::pair()?;
    let channel = AgentdNotesChannel::from_private_channel(owner)?;
    let peer = std::thread::spawn(move || -> io::Result<Vec<u8>> {
        let mut request = [0; 10];
        application.read_exact(&mut request)?;
        Ok(request.to_vec())
    });
    assert!(channel.exchange(b"effect").is_err());
    assert!(channel.exchange(b"effect").is_err());
    assert_eq!(
        peer.join().expect("application thread")?,
        [0, 0, 0, 6, b'e', b'f', b'f', b'e', b'c', b't']
    );
    assert!(channel.disabled.load(Ordering::Acquire));
    Ok(())
}

#[test]
fn malformed_reply_prefix_closes_stream_without_accepting_a_later_reply() -> TestResult {
    let (owner, mut application) = UnixStream::pair()?;
    let channel = AgentdNotesChannel::from_private_channel(owner)?;
    let peer = std::thread::spawn(move || -> io::Result<()> {
        let mut request = [0; 5];
        application.read_exact(&mut request)?;
        application.write_all(&2049_u32.to_be_bytes())?;
        let mut byte = [0; 1];
        assert_eq!(application.read(&mut byte)?, 0);
        Ok(())
    });
    assert!(channel.exchange(b"x").is_err());
    assert!(channel.exchange(b"x").is_err());
    peer.join().expect("application thread")?;
    Ok(())
}

#[test]
fn invalid_bound_does_not_write_and_explicit_invalidation_is_permanent() -> TestResult {
    let (owner, mut application) = UnixStream::pair()?;
    let channel = AgentdNotesChannel::from_private_channel(owner)?;
    assert!(channel.exchange(&[]).is_err());
    assert!(
        channel
            .exchange(&vec![0; NOTES_REQUEST_MAX_BYTES + 1])
            .is_err()
    );
    channel.invalidate();
    assert!(channel.exchange(b"effect").is_err());
    let mut byte = [0; 1];
    assert_eq!(application.read(&mut byte)?, 0);
    Ok(())
}
