//! Real TLS fixture I/O under the original absolute server deadlines.
use std::io;
use std::io::Read;
use std::io::Write;
use std::net::TcpListener;
use std::net::TcpStream;
use std::sync::Arc;
use std::sync::mpsc;
use std::thread;
use std::time::Duration;
use std::time::Instant;

struct DeadlineStream<'a> {
    stream: &'a mut TcpStream,
    deadline: Instant,
}

impl DeadlineStream<'_> {
    fn remaining(&self) -> io::Result<Duration> {
        self.deadline
            .checked_duration_since(Instant::now())
            .filter(|duration| !duration.is_zero())
            .ok_or_else(|| io::Error::new(io::ErrorKind::TimedOut, "original TLS fixture deadline"))
    }
}

impl Read for DeadlineStream<'_> {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        self.stream.set_read_timeout(Some(self.remaining()?))?;
        self.stream.read(output)
    }
}

impl Write for DeadlineStream<'_> {
    fn write(&mut self, input: &[u8]) -> io::Result<usize> {
        self.stream.set_write_timeout(Some(self.remaining()?))?;
        self.stream.write(input)
    }
    fn flush(&mut self) -> io::Result<()> {
        self.stream.flush()
    }
}

pub(super) fn read_complete_client_hello(
    stream: &mut TcpStream,
    deadline: Instant,
) -> io::Result<usize> {
    let mut stream = DeadlineStream { stream, deadline };
    let mut header = [0; 5];
    stream.read_exact(&mut header)?;
    let mut acceptor = rustls::server::Acceptor::default();
    acceptor.read_tls(&mut io::Cursor::new(header))?;
    let mut total = header.len();
    loop {
        match acceptor.accept() {
            Ok(Some(_)) => {
                eprintln!(
                    "TLS_FIXTURE_CLIENT_HELLO complete_bytes={total} first_header={header:02x?}"
                );
                return Ok(total);
            }
            Ok(None) => {}
            Err((error, _)) => return Err(io::Error::other(error)),
        }
        if total >= 65_536 {
            return Err(io::Error::other("ClientHello exceeds fixture bound"));
        }
        let read = acceptor.read_tls(&mut Read::take(&mut stream, (65_536 - total) as u64))?;
        if read == 0 {
            return Err(io::Error::new(
                io::ErrorKind::UnexpectedEof,
                "incomplete ClientHello",
            ));
        }
        total += read;
    }
}

pub(super) fn spawn_certificate_rejection_server()
-> io::Result<(String, mpsc::Receiver<io::Result<usize>>, mpsc::Sender<()>)> {
    codex_utils_rustls_provider::ensure_rustls_crypto_provider();
    let certified =
        rcgen::generate_simple_self_signed(vec!["127.0.0.1".into()]).map_err(io::Error::other)?;
    let config = Arc::new(
        rustls::ServerConfig::builder()
            .with_no_client_auth()
            .with_single_cert(
                vec![certified.cert.der().clone()],
                rustls_pki_types::PrivateKeyDer::from(certified.signing_key),
            )
            .map_err(io::Error::other)?,
    );
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    let address = listener.local_addr()?;
    listener.set_nonblocking(/*nonblocking*/ true)?;
    let (attempts_tx, attempts_rx) = mpsc::channel();
    let (stop_tx, stop_rx) = mpsc::channel();
    thread::spawn(move || {
        let result = (|| {
            let deadline = Instant::now() + Duration::from_secs(/*secs*/ 5);
            let mut attempts = 0;
            while attempts < 2 && Instant::now() < deadline {
                if stop_rx.try_recv().is_ok() {
                    break;
                }
                match listener.accept() {
                    Ok((mut socket, _)) => {
                        socket.set_nonblocking(/*nonblocking*/ false)?;
                        let mut connection = rustls::ServerConnection::new(Arc::clone(&config))
                            .map_err(io::Error::other)?;
                        let mut stream = DeadlineStream {
                            stream: &mut socket,
                            deadline: deadline
                                .min(Instant::now() + Duration::from_secs(/*secs*/ 2)),
                        };
                        if connection.complete_io(&mut stream).is_ok() {
                            return Err(io::Error::other(
                                "untrusted certificate unexpectedly accepted",
                            ));
                        }
                        attempts += 1;
                    }
                    Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(/*millis*/ 10))
                    }
                    Err(error) => return Err(error),
                }
            }
            Ok(attempts)
        })();
        let _ = attempts_tx.send(result);
    });
    Ok((format!("https://{address}/mcp"), attempts_rx, stop_tx))
}
