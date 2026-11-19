use super::deserialize_from;
use super::serialize_into;
use std::io;
use std::io::Write;

// Captured from the original bincode 1.3.3 representation of this vector.
const LEGACY_VECTOR: [u8; 40] = [
    4, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0, 0, 0, 0, 0,
    255, 255, 255, 255, 255, 255, 255, 255,
];

#[test]
fn legacy_fixed_width_vector_bytes_are_preserved() {
    let value = vec![1_u64, 2, 3, u64::MAX];
    let mut bytes = Vec::new();
    serialize_into(&mut bytes, &value).unwrap();
    assert_eq!(bytes, LEGACY_VECTOR);
    let decoded: Vec<u64> = deserialize_from(LEGACY_VECTOR.as_slice()).unwrap();
    assert_eq!(decoded, value);
}

#[test]
fn every_truncated_vector_boundary_is_rejected() {
    for end in 0..LEGACY_VECTOR.len() {
        let result = deserialize_from::<_, Vec<u64>>(&LEGACY_VECTOR[..end]);
        assert!(result.is_err(), "accepted truncated vector at byte {end}");
    }
}

#[test]
fn original_reader_trailing_byte_behavior_is_preserved() {
    let mut bytes = LEGACY_VECTOR.to_vec();
    bytes.extend_from_slice(b"following record");
    let mut cursor = io::Cursor::new(bytes);
    let decoded: Vec<u64> = deserialize_from(&mut cursor).unwrap();
    assert_eq!(decoded, vec![1_u64, 2, 3, u64::MAX]);
    assert_eq!(cursor.position(), LEGACY_VECTOR.len() as u64);
}

struct FailingWriter {
    remaining: usize,
    written: Vec<u8>,
}

impl Write for FailingWriter {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if self.remaining == 0 {
            return Err(io::Error::other("retained write failure"));
        }
        let count = self.remaining.min(bytes.len());
        self.written.extend_from_slice(&bytes[..count]);
        self.remaining -= count;
        Ok(count)
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

#[test]
fn buffered_write_failures_are_returned_before_drop() {
    for limit in [0, 1, 7, 8, 39] {
        let mut writer = FailingWriter {
            remaining: limit,
            written: Vec::new(),
        };
        let result = serialize_into(&mut writer, &vec![1_u64, 2, 3, u64::MAX]);
        assert!(result.is_err(), "lost write failure after {limit} bytes");
        assert_eq!(writer.written.as_slice(), &LEGACY_VECTOR[..limit]);
    }
}

#[test]
fn invalid_boolean_discriminants_are_rejected() {
    for value in [2_u8, 255] {
        let result = deserialize_from::<_, bool>(&[value][..]);
        assert!(result.is_err());
    }
}
