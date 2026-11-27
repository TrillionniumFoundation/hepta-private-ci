use super::exchange;
use super::supported::open_socket;
use crate::AuthorityTrustError;
use crate::authority_trust_unix::MAX_RESPONSE_BYTES;
use crate::authority_trust_unix::UnixPqTrustEndpointConfig;
use crate::authority_trust_unix::tests::key;
use std::fs;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;
use std::thread;
use std::time::Duration;
use std::time::Instant;

type TestResult<T> = Result<T, Box<dyn std::error::Error + Send + Sync>>;

fn endpoint() -> TestResult<(tempfile::TempDir, UnixListener, UnixPqTrustEndpointConfig)> {
    let root = tempfile::tempdir()?;
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700))?;
    let socket_path = root.path().join("transport.sock");
    let listener = UnixListener::bind(&socket_path)?;
    fs::set_permissions(&socket_path, fs::Permissions::from_mode(0o600))?;
    listener.set_nonblocking(true)?;
    let (_, pin) = key(/*seed*/ 94)?;
    let config = UnixPqTrustEndpointConfig {
        socket_path,
        peer_uid: rustix::process::geteuid().as_raw(),
        service_id: "transport".into(),
        key_generation: 1,
        public_key_id: pin.public_key_id,
        public_key_spki: pin.public_key_spki,
        timeout_ms: 2000,
    };
    Ok((root, listener, config))
}

fn receive(listener: &UnixListener) -> TestResult<std::os::unix::net::UnixStream> {
    let deadline = Instant::now() + Duration::from_secs(2);
    let mut stream = loop {
        match listener.accept() {
            Ok((stream, _)) => break stream,
            Err(error)
                if error.kind() == std::io::ErrorKind::WouldBlock && Instant::now() < deadline =>
            {
                thread::sleep(Duration::from_millis(1));
            }
            Err(error) => return Err(error.into()),
        }
    };
    stream.set_nonblocking(false)?;
    stream.set_read_timeout(Some(Duration::from_secs(2)))?;
    stream.set_write_timeout(Some(Duration::from_secs(2)))?;
    let mut length = [0; 4];
    stream.read_exact(&mut length)?;
    assert_eq!(u32::from_be_bytes(length), 7);
    let mut request = [0; 7];
    stream.read_exact(&mut request)?;
    assert_eq!(&request, b"request");
    Ok(stream)
}

#[test]
fn actual_socket_is_nonblocking_and_close_on_exec_before_connect() -> TestResult<()> {
    let fd = open_socket()?;
    assert!(rustix::io::fcntl_getfd(&fd)?.contains(rustix::io::FdFlags::CLOEXEC));
    assert!(rustix::fs::fcntl_getfl(&fd)?.contains(rustix::fs::OFlags::NONBLOCK));
    Ok(())
}

#[test]
fn actual_fragmented_response_does_not_reset_absolute_deadline() -> TestResult<()> {
    let (_root, listener, config) = endpoint()?;
    let server = thread::spawn(move || -> TestResult<()> {
        let mut stream = receive(&listener)?;
        let length = 8_u32.to_be_bytes();
        stream.write_all(&length[..2])?;
        thread::sleep(Duration::from_millis(1100));
        stream.write_all(&length[2..])?;
        thread::sleep(Duration::from_millis(1100));
        // The peer may already have closed after the original absolute deadline.
        // A transport that resets the deadline for the body would accept this.
        let _ = stream.write_all(b"response");
        Ok(())
    });
    let result = exchange(
        &config,
        b"request",
        Instant::now() + Duration::from_millis(config.timeout_ms),
    );
    server.join().expect("transport service thread panicked")?;
    assert_eq!(result, Err(AuthorityTrustError::Unavailable));
    Ok(())
}

#[test]
fn actual_oversized_response_is_rejected_from_length_without_reading_body() -> TestResult<()> {
    let (_root, listener, config) = endpoint()?;
    let server = thread::spawn(move || -> TestResult<()> {
        let mut stream = receive(&listener)?;
        stream.write_all(&((MAX_RESPONSE_BYTES + 1) as u32).to_be_bytes())?;
        Ok(())
    });
    let result = exchange(
        &config,
        b"request",
        Instant::now() + Duration::from_millis(config.timeout_ms),
    );
    server.join().expect("transport service thread panicked")?;
    assert_eq!(result, Err(AuthorityTrustError::Invalid));
    Ok(())
}
