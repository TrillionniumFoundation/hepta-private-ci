//! Actual streaming and owner-window controls; these bytes are not model weights.
use super::*;
use pretty_assertions::assert_eq;
use std::io;
use std::io::Write;
use std::os::unix::net::UnixStream;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;
use tokio_util::sync::CancellationToken;

#[test]
fn live_startup_stream_retains_exact_chunks_and_the_original_deadline() {
    let startup = SmolLmStartupExecutionV1::new(CancellationToken::new());
    let execution = startup.execution();
    let deadline = execution.deadline();
    let payload = vec![19; 1024 * 1024 + 13];
    let actual =
        wire::measure(Cursor::new(&payload), payload.len() as u64, Some(execution)).unwrap();
    assert_eq!(
        actual,
        (
            payload.len() as u64,
            Digest32::of_bytes(&payload),
            vec![
                (1024 * 1024, Digest32::of_bytes(&payload[..1024 * 1024])),
                (13, Digest32::of_bytes(&payload[1024 * 1024..])),
            ]
        )
    );
    assert_eq!(execution.deadline(), deadline);
    execution.check().unwrap();
}

struct CountingReader<'a> {
    calls: &'a mut usize,
    cancellation: Option<CancellationToken>,
    result: io::Result<usize>,
}

impl Read for CountingReader<'_> {
    fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        *self.calls += 1;
        if let Some(token) = &self.cancellation {
            token.cancel();
        }
        bytes[0] = 7;
        std::mem::replace(&mut self.result, Ok(0))
    }
}

#[test]
fn expired_or_cancelled_scan_performs_no_payload_read() {
    for cancelled in [false, true] {
        let token = CancellationToken::new();
        let deadline = if cancelled {
            token.cancel();
            Instant::now() + Duration::from_secs(120)
        } else {
            Instant::now()
        };
        let execution = NeuralCognitiveExecutionV1::with_deadline(deadline, token);
        let mut calls = 0;
        let error = wire::measure(
            CountingReader {
                calls: &mut calls,
                cancellation: None,
                result: Ok(1),
            },
            1024,
            Some(&execution),
        )
        .unwrap_err();
        assert!(error.contains(if cancelled { "cancelled" } else { "deadline" }));
        assert_eq!(calls, 0);
    }
}

#[test]
fn cancellation_during_read_cannot_turn_short_read_eof_or_eintr_into_success() {
    for result in [
        Ok(1),
        Ok(0),
        Err(io::Error::from(io::ErrorKind::Interrupted)),
    ] {
        let token = CancellationToken::new();
        let startup = SmolLmStartupExecutionV1::new(token.clone());
        let mut calls = 0;
        let error = wire::measure(
            CountingReader {
                calls: &mut calls,
                cancellation: Some(token),
                result,
            },
            1024,
            Some(startup.execution()),
        )
        .unwrap_err();
        assert!(error.contains("cancelled"));
        assert_eq!(calls, 1);
    }
}

struct OwnedBlockingReader {
    stream: UnixStream,
    entered: Option<std::sync::mpsc::Sender<()>>,
    dropped: Arc<AtomicBool>,
}

impl Read for OwnedBlockingReader {
    fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        if let Some(entered) = self.entered.take() {
            entered.send(()).unwrap();
        }
        self.stream.read(bytes)
    }
}

impl Drop for OwnedBlockingReader {
    fn drop(&mut self) {
        self.dropped.store(true, Ordering::SeqCst);
    }
}

#[test]
fn late_os_read_retains_its_owner_until_return_then_rejects_without_resetting_time() {
    for cancelled in [false, true] {
        let (stream, mut writer) = UnixStream::pair().unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(5)))
            .unwrap();
        let token = CancellationToken::new();
        let deadline = Instant::now() + Duration::from_secs(2);
        let execution = NeuralCognitiveExecutionV1::with_deadline(deadline, token.clone());
        let dropped = Arc::new(AtomicBool::new(false));
        let (entered_tx, entered_rx) = std::sync::mpsc::channel();
        let (done_tx, done_rx) = std::sync::mpsc::channel();
        let input = OwnedBlockingReader {
            stream,
            entered: Some(entered_tx),
            dropped: dropped.clone(),
        };
        let task = std::thread::spawn(move || {
            let result = wire::measure(input, 1024, Some(&execution));
            done_tx.send(result).unwrap();
        });
        entered_rx.recv_timeout(Duration::from_secs(2)).unwrap();
        if cancelled {
            token.cancel();
        } else {
            std::thread::sleep(deadline.saturating_duration_since(Instant::now()));
        }
        // Cancellation/expiry is not evidence that the still-blocked OS read
        // terminated. Its file owner cannot be discarded by an outer timeout.
        assert!(!dropped.load(Ordering::SeqCst));
        assert!(done_rx.try_recv().is_err());
        writer.write_all(b"late bytes").unwrap();
        writer.shutdown(std::net::Shutdown::Write).unwrap();
        let error = done_rx
            .recv_timeout(Duration::from_secs(2))
            .unwrap()
            .unwrap_err();
        assert!(error.contains(if cancelled { "cancelled" } else { "deadline" }));
        task.join().unwrap();
        assert!(dropped.load(Ordering::SeqCst));
    }
}
