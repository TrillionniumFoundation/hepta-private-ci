//! Actual Unix socket-pair kernel bytes, no separate process or UI effects.
use super::*;
use crate::{ActionArgumentsV1, CapabilityGrantV1};
use codex_hepta_types::Digest32;
#[cfg(unix)]
use std::io::Write;
#[cfg(unix)]
use std::net::Shutdown;
#[cfg(unix)]
use std::os::unix::net::UnixStream;
#[cfg(unix)]
use std::time::Duration;

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}
fn verifier() -> ActionVerifierV1 {
    ActionVerifierV1 {
        generation: 12,
        grant: CapabilityGrantV1 {
            digest: digest(b"external-untrusted-grant"),
            allowed: 1 | 2 | 4 | 8 | 16,
        },
    }
}
fn click(sequence: u64) -> ActionFrameV1 {
    ActionFrameV1 {
        generation: 12,
        sequence,
        capability_digest: verifier().grant.digest,
        arguments: ActionArgumentsV1::Click {
            target_digest: digest(b"element"),
            x: 3,
            y: 4,
        },
    }
}

#[test]
fn denies_empty_or_unbounded_sessions() {
    let io = std::io::Cursor::new(Vec::<u8>::new());
    assert!(matches!(
        FrameDuplexV1::new(io, verifier(), 4097),
        Err(FrameWireErrorV1::InvalidBound)
    ));
    let mut bad = verifier();
    bad.generation = 0;
    assert!(matches!(
        FrameDuplexV1::new(std::io::Cursor::new(Vec::<u8>::new()), bad, 2),
        Err(FrameWireErrorV1::InvalidBound)
    ));
}

#[cfg(unix)]
#[test]
fn real_kernel_socket_pair_roundtrips_exactly_32_frames() {
    let (first, second) = UnixStream::pair().expect("pair");
    first
        .set_read_timeout(Some(Duration::from_secs(3)))
        .expect("timeout");
    second
        .set_read_timeout(Some(Duration::from_secs(3)))
        .expect("timeout");
    let thread = std::thread::spawn(move || {
        let mut worker = FrameDuplexV1::new(second, verifier(), 32).expect("worker");
        for _ in 0..32 {
            let action = worker.receive().expect("verified inbound");
            worker.send(action.frame()).expect("data-only echo");
        }
        assert!(!worker.is_poisoned());
    });
    let mut client = FrameDuplexV1::new(first, verifier(), 32).expect("client");
    for sequence in 1..=32 {
        let action = click(sequence);
        client.send(&action).expect("send");
        assert_eq!(client.receive().expect("echo").frame(), &action);
    }
    thread.join().expect("worker thread");
    assert!(!client.is_poisoned());
    assert_eq!(
        client.send(&click(33)),
        Err(FrameWireErrorV1::LimitExceeded)
    );
}

#[cfg(unix)]
#[test]
fn wrong_sequence_and_capability_do_not_write_bytes() {
    let (first, second) = UnixStream::pair().expect("pair");
    let mut producer = FrameDuplexV1::new(first, verifier(), 2).expect("producer");
    let mut consumer = FrameDuplexV1::new(second, verifier(), 2).expect("consumer");
    assert_eq!(
        producer.send(&click(2)),
        Err(FrameWireErrorV1::SequenceMismatch)
    );
    let mut foreign = click(1);
    foreign.capability_digest = digest(b"foreign");
    assert_eq!(
        producer.send(&foreign),
        Err(FrameWireErrorV1::Action(ActionErrorV1::CapabilityDenied))
    );
    producer.send(&click(1)).expect("valid send");
    assert_eq!(
        consumer.receive().expect("valid inbound").frame(),
        &click(1)
    );
}

#[cfg(unix)]
#[test]
fn corrupt_padding_denied_then_session_poisoned() {
    let (mut raw, second) = UnixStream::pair().expect("pair");
    let mut consumer = FrameDuplexV1::new(second, verifier(), 2).expect("consumer");
    let mut bad = click(1).encode().expect("encode");
    bad[255] = 1;
    raw.write_all(&bad)
        .expect("write deliberately corrupted input");
    assert_eq!(
        consumer.receive().map(|_| ()),
        Err(FrameWireErrorV1::Action(ActionErrorV1::NonCanonicalPadding))
    );
    assert!(consumer.is_poisoned());
    assert_eq!(
        consumer.receive().map(|_| ()),
        Err(FrameWireErrorV1::Poisoned)
    );
}

#[cfg(unix)]
#[test]
fn truncated_frame_denied_then_session_poisoned() {
    let (mut raw, second) = UnixStream::pair().expect("pair");
    let mut consumer = FrameDuplexV1::new(second, verifier(), 2).expect("consumer");
    raw.write_all(&[0_u8; 25]).expect("partial write");
    raw.shutdown(Shutdown::Write).expect("end truncated stream");
    assert_eq!(
        consumer.receive().map(|_| ()),
        Err(FrameWireErrorV1::Io(std::io::ErrorKind::UnexpectedEof))
    );
    assert!(consumer.is_poisoned());
    assert_eq!(
        consumer.receive().map(|_| ()),
        Err(FrameWireErrorV1::Poisoned)
    );
}

#[cfg(unix)]
#[test]
fn skipped_inbound_sequence_denied_then_session_poisoned() {
    let (mut raw, second) = UnixStream::pair().expect("pair");
    let mut consumer = FrameDuplexV1::new(second, verifier(), 2).expect("consumer");
    raw.write_all(&click(2).encode().expect("encode"))
        .expect("write");
    assert_eq!(
        consumer.receive().map(|_| ()),
        Err(FrameWireErrorV1::SequenceMismatch)
    );
    assert!(consumer.is_poisoned());
}
