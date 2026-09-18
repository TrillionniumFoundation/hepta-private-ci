use super::Digest32;
use std::io;
use std::io::Read;

#[test]
fn bounded_stream_digest_matches_bytes_at_buffer_boundaries() {
    for length in [0, 1, 32767, 32768, 32769, 131072] {
        let bytes = vec![37; length];
        assert_eq!(
            Digest32::of_reader(bytes.as_slice(), length as u64).unwrap(),
            Digest32::of_bytes(&bytes)
        );
    }
}

struct CountingReader {
    reads: usize,
    bytes: usize,
}

impl Read for CountingReader {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        self.reads += 1;
        if self.reads == 1 {
            return Err(io::ErrorKind::Interrupted.into());
        }
        output.fill(1);
        self.bytes += output.len();
        Ok(output.len())
    }
}

#[test]
fn unbounded_reader_stops_after_one_overflow_byte() {
    for limit in [0, 1, 32768, 70000] {
        let mut reader = CountingReader { reads: 0, bytes: 0 };
        let error = Digest32::of_reader(&mut reader, limit).unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::InvalidData);
        assert_eq!(reader.bytes as u64, limit + 1);
    }
}

struct BrokenReader;

impl Read for BrokenReader {
    fn read(&mut self, _output: &mut [u8]) -> io::Result<usize> {
        Err(io::ErrorKind::PermissionDenied.into())
    }
}

#[test]
fn stream_error_never_returns_a_partial_digest() {
    assert_eq!(
        Digest32::of_reader(BrokenReader, 4096).unwrap_err().kind(),
        io::ErrorKind::PermissionDenied
    );
}
