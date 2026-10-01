use std::error::Error;
use std::io::Cursor;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::WireEnvelopeV2;

use super::*;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

fn frame() -> TestResult<DecodedEnvelope> {
    Ok(DecodedEnvelope::V2(WireEnvelopeV2::new(
        StableId::new("schema.bounded-read.v1")?,
        StableId::new("producer.bounded-read")?,
        Generation::new(1)?,
        b"bounded frame body".to_vec(),
    )?))
}

fn exhausted(result: Result<DecodedEnvelope, ReadFrameError>) -> TestResult<ReadFrameBudgetExceeded> {
    match result {
        Err(ReadFrameError::Io(error)) => error
            .get_ref()
            .and_then(|cause| cause.downcast_ref::<ReadFrameBudgetExceeded>())
            .copied()
            .ok_or_else(|| "expected structured budget exhaustion".into()),
        _ => Err("expected I/O budget exhaustion".into()),
    }
}

struct Interrupting {
    calls: usize,
}

impl Read for Interrupting {
    fn read(&mut self, _: &mut [u8]) -> io::Result<usize> {
        self.calls += 1;
        Err(io::ErrorKind::Interrupted.into())
    }
}

#[test]
fn normal_public_reader_bounds_continuous_interrupted() -> TestResult {
    let mut reader = Interrupting { calls: 0 };
    let failure = exhausted(read_frame(&mut reader))?;
    assert_eq!(reader.calls, 32);
    assert_eq!(failure.bytes_read, 0);
    assert_eq!(failure.read_calls, 32);
    assert_eq!(failure.interrupted_reads, 32);
    Ok(())
}

#[test]
fn call_budget_also_charges_interrupted_attempts() -> TestResult {
    let mut reader = Interrupting { calls: 0 };
    let mut budget = ReadFrameBudget::new(3, 10);
    let failure = exhausted(read_frame_with_budget(&mut reader, &mut budget))?;
    assert_eq!(reader.calls, 3);
    assert_eq!(failure.read_calls, 3);
    assert_eq!(failure.interrupted_reads, 3);
    assert_eq!(budget.remaining_calls(), 0);
    assert_eq!(budget.remaining_interrupts(), 7);
    Ok(())
}

#[test]
fn zero_budget_does_not_touch_reader() -> TestResult {
    for (calls, interruptions) in [(0, 8), (8, 0), (0, 0)] {
        let mut reader = Interrupting { calls: 0 };
        let mut budget = ReadFrameBudget::new(calls, interruptions);
        let failure = exhausted(read_frame_with_budget(&mut reader, &mut budget))?;
        assert_eq!(reader.calls, 0);
        assert_eq!(failure.bytes_read, 0);
        assert_eq!(failure.read_calls, 0);
    }
    Ok(())
}

struct TinyReader {
    bytes: Cursor<Vec<u8>>,
    calls: usize,
    interrupt_first: bool,
}

impl Read for TinyReader {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        self.calls += 1;
        if self.interrupt_first {
            self.interrupt_first = false;
            return Err(io::ErrorKind::Interrupted.into());
        }
        let size = output.len().min(1);
        self.bytes.read(&mut output[..size])
    }
}

#[test]
fn one_byte_delivery_and_transient_interruption_use_same_parser() -> TestResult {
    let expected = frame()?;
    let bytes = expected.encode();
    let size = bytes.len();
    let mut reader = TinyReader {
        bytes: Cursor::new(bytes),
        calls: 0,
        interrupt_first: true,
    };
    let mut budget = ReadFrameBudget::new(size + 1, 2);
    assert_eq!(read_frame_with_budget(&mut reader, &mut budget)?, expected);
    assert_eq!(reader.calls, size + 1);
    assert_eq!(budget.remaining_calls(), 0);
    assert_eq!(budget.remaining_interrupts(), 1);
    Ok(())
}

#[test]
fn partial_consumption_is_reported_not_refunded() -> TestResult {
    let bytes = frame()?.encode();
    let size = bytes.len();
    let mut reader = TinyReader {
        bytes: Cursor::new(bytes),
        calls: 0,
        interrupt_first: false,
    };
    let mut budget = ReadFrameBudget::new(size - 1, 8);
    let failure = exhausted(read_frame_with_budget(&mut reader, &mut budget))?;
    assert_eq!(failure.bytes_read, size - 1);
    assert_eq!(failure.read_calls, size - 1);
    assert_eq!(reader.bytes.position(), (size - 1) as u64);
    assert_eq!(budget.remaining_calls(), 0);
    Ok(())
}

#[test]
fn allowance_can_be_shared_across_complete_frames() -> TestResult {
    let expected = frame()?;
    let bytes = expected.encode();
    let size = bytes.len();
    let mut input = bytes.clone();
    input.extend_from_slice(&bytes);
    let mut reader = Cursor::new(input);
    let mut budget = ReadFrameBudget::new(2, 8);
    assert_eq!(read_frame_with_budget(&mut reader, &mut budget)?, expected);
    assert_eq!(budget.remaining_calls(), 0);
    let failure = exhausted(read_frame_with_budget(&mut reader, &mut budget))?;
    assert_eq!(failure.bytes_read, 0);
    assert_eq!(failure.read_calls, 0);
    assert_eq!(reader.position(), size as u64);
    Ok(())
}

#[test]
fn eof_remains_eof_instead_of_budget_exhaustion() -> TestResult {
    let bytes = frame()?.encode();
    for cut in [0, 1, bytes.len() - 1] {
        let mut reader = Cursor::new(&bytes[..cut]);
        match read_frame(&mut reader) {
            Err(ReadFrameError::Io(error)) => {
                assert_eq!(error.kind(), io::ErrorKind::UnexpectedEof);
            }
            _ => return Err("expected canonical unexpected EOF".into()),
        }
    }
    Ok(())
}

#[test]
fn would_block_is_not_retried() {
    struct WouldBlock(usize);
    impl Read for WouldBlock {
        fn read(&mut self, _: &mut [u8]) -> io::Result<usize> {
            self.0 += 1;
            Err(io::ErrorKind::WouldBlock.into())
        }
    }
    let mut reader = WouldBlock(0);
    assert!(matches!(
        read_frame(&mut reader),
        Err(ReadFrameError::Io(error)) if error.kind() == io::ErrorKind::WouldBlock
    ));
    assert_eq!(reader.0, 1);
}

#[test]
fn violating_read_contract_is_rejected_without_overcounting() {
    struct InvalidReader;
    impl Read for InvalidReader {
        fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
            Ok(output.len() + 1)
        }
    }
    assert!(matches!(
        read_frame(&mut InvalidReader),
        Err(ReadFrameError::Io(error)) if error.kind() == io::ErrorKind::InvalidData
    ));
}
