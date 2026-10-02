use std::io;
use std::os::unix::net::UnixListener;
use std::path::Path;
use std::thread;
use std::time::Duration;
use std::time::Instant;

use pretty_assertions::assert_eq;

use super::super::socket_fixture_io::FixtureIo;
use super::super::socket_fixture_io::FrameEnd;
use super::super::socket_fixture_io::context;
use super::exchange_frame;

type TestResult = Result<(), Box<dyn std::error::Error>>;

fn fixture() -> io::Result<tempfile::TempDir> {
    // Darwin's sun_path also needs the trailing NUL. Do not inherit a long TMPDIR.
    tempfile::Builder::new()
        .prefix("hsup-io-")
        .tempdir_in("/tmp")
}

fn server(
    path: &Path,
    response: impl FnOnce(&mut FixtureIo) -> io::Result<()> + Send + 'static,
) -> io::Result<thread::JoinHandle<io::Result<Vec<u8>>>> {
    let listener =
        UnixListener::bind(path).map_err(|error| context("bind control listener", error))?;
    listener
        .set_nonblocking(/*nonblocking*/ true)
        .map_err(|error| context("set control listener nonblocking", error))?;
    Ok(thread::spawn(move || {
        let deadline = Instant::now() + Duration::from_secs(2);
        let stream = loop {
            if Instant::now() >= deadline {
                return Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "socket fixture accept control peer: absolute deadline expired",
                ));
            }
            match listener.accept() {
                Ok((stream, _)) => break stream,
                Err(error)
                    if matches!(
                        error.kind(),
                        io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
                    ) =>
                {
                    thread::sleep(Duration::from_millis(5));
                }
                Err(error) => return Err(context("accept control peer", error)),
            }
        };
        let mut stream = FixtureIo::new(stream, Duration::from_secs(1))?;
        let request = stream.read_frame(FrameEnd::Eof)?;
        response(&mut stream)?;
        Ok(request)
    }))
}

#[test]
fn same_peer_complete_frame_preserves_first_newline_and_request() -> TestResult {
    let temp = fixture()?;
    let path = temp.path().join("control.sock");
    let worker = server(&path, |stream| stream.write_frame(b"reply\nignored\n"))?;
    let reply = exchange_frame(
        &path,
        std::process::id(),
        b"request\n",
        /*maximum*/ 6,
        Duration::from_millis(200),
    );
    let request = worker.join().expect("server does not panic")?;
    assert_eq!(reply?, b"reply\n");
    assert_eq!(request, b"request\n");
    Ok(())
}

#[test]
fn successful_partial_reads_cannot_renew_the_whole_exchange_deadline() -> TestResult {
    let temp = fixture()?;
    let path = temp.path().join("drip.sock");
    let worker = server(&path, |stream| {
        for _ in 0..8 {
            if let Err(error) = stream.write_frame(b"x") {
                return if matches!(
                    error.kind(),
                    io::ErrorKind::BrokenPipe | io::ErrorKind::ConnectionReset
                ) {
                    Ok(())
                } else {
                    Err(error)
                };
            }
            thread::sleep(Duration::from_millis(50));
        }
        match stream.write_frame(b"\n") {
            Ok(()) => Ok(()),
            Err(error)
                if matches!(
                    error.kind(),
                    io::ErrorKind::BrokenPipe | io::ErrorKind::ConnectionReset
                ) =>
            {
                Ok(())
            }
            Err(error) => Err(error),
        }
    })?;
    let started = Instant::now();
    let result = exchange_frame(
        &path,
        std::process::id(),
        b"request\n",
        /*maximum*/ 64,
        Duration::from_millis(200),
    );
    let elapsed = started.elapsed();
    worker.join().expect("drip server does not panic")?;
    assert_eq!(
        result.expect_err("drip must time out").kind(),
        io::ErrorKind::TimedOut
    );
    // Allow runner scheduling delay; the late complete frame must still reject.
    assert!(
        elapsed < Duration::from_secs(2),
        "exchange took {elapsed:?}"
    );
    Ok(())
}

#[test]
fn mismatched_peer_is_rejected_before_any_request_byte() -> TestResult {
    let temp = fixture()?;
    let path = temp.path().join("peer.sock");
    let worker = server(&path, |_stream| Ok(()))?;
    let expected_pid = std::process::id().checked_add(1).expect("PID can advance");
    let result = exchange_frame(
        &path,
        expected_pid,
        b"private request\n",
        /*maximum*/ 64,
        Duration::from_millis(200),
    );
    let request = worker.join().expect("peer server does not panic")?;
    assert_eq!(
        result.expect_err("wrong peer rejected").kind(),
        io::ErrorKind::PermissionDenied
    );
    assert_eq!(request, Vec::<u8>::new());
    Ok(())
}

#[test]
fn reply_byte_bound_and_incomplete_eof_preserve_caller_validation() -> TestResult {
    for (wire, maximum, expected) in [
        (b"123456789\n".as_slice(), 4, b"12345".as_slice()),
        (b"incomplete".as_slice(), 64, b"incomplete".as_slice()),
        (b"".as_slice(), 64, b"".as_slice()),
    ] {
        let temp = fixture()?;
        let path = temp.path().join("bounded.sock");
        let worker = server(&path, move |stream| stream.write_frame(wire))?;
        let reply = exchange_frame(
            &path,
            std::process::id(),
            b"request\n",
            maximum,
            Duration::from_millis(200),
        );
        worker.join().expect("bounded server does not panic")?;
        assert_eq!(reply?, expected);
    }
    Ok(())
}
