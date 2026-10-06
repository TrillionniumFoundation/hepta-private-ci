use super::*;
use pretty_assertions::assert_eq;
use std::io::Write;

#[test]
fn snapshot_uses_an_independent_cursor_and_matches_trimmed_marker() {
    let mut file = NamedTempFile::new().unwrap();
    write!(file, "{EXPECTED_MARKER}\r\n").unwrap();
    let snapshot = Snapshot::read(&file);
    assert_eq!(snapshot.marker_match, Some(true));
    assert_eq!(snapshot.captured_bytes, Some(EXPECTED_MARKER.len() + 2));
    // A snapshot read must not move the writer's file pointer.
    file.write_all(b"tail").unwrap();
    let next = Snapshot::read(&file);
    assert_eq!(next.marker_match, Some(false));
    assert_eq!(next.file_len, Some((EXPECTED_MARKER.len() + 6) as u64));
    assert!(!snapshot.report().contains(EXPECTED_MARKER));
}

#[test]
fn snapshot_is_bounded_and_does_not_claim_complete_output() {
    let mut file = NamedTempFile::new().unwrap();
    file.write_all(EXPECTED_MARKER.as_bytes()).unwrap();
    let padding = vec![b' '; OUTPUT_CAP as usize - EXPECTED_MARKER.len()];
    file.write_all(&padding).unwrap();
    file.write_all(b"unobserved-tail").unwrap();
    let snapshot = Snapshot::read(&file);
    assert_eq!(snapshot.captured_bytes, Some(OUTPUT_CAP as usize));
    assert!(snapshot.file_len.unwrap() > OUTPUT_CAP);
    // True only for the bounded snapshot, although the file has extra content.
    assert_eq!(snapshot.marker_match, Some(true));
    assert!(!snapshot.report().contains("unobserved-tail"));
}

#[test]
fn partial_read_is_unavailable_instead_of_false_or_zero() {
    struct FailingReader(bool);
    impl Read for FailingReader {
        fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
            if self.0 {
                return Err(io::Error::other("synthetic reader failure"));
            }
            self.0 = true;
            let secret = b"secret-prefix";
            buffer[..secret.len()].copy_from_slice(secret);
            Ok(secret.len())
        }
    }
    let mut snapshot = Snapshot::default();
    snapshot.error = snapshot.read_bytes(FailingReader(false)).err();
    assert_eq!(snapshot.captured_bytes, Some(b"secret-prefix".len()));
    assert_eq!(snapshot.marker_match, None);
    assert!(!snapshot.read_complete);
    assert!(snapshot.error.is_some());
    assert!(!snapshot.report().contains("secret-prefix"));
}

#[test]
fn encoded_command_roundtrips_exact_utf16le_without_bom_or_added_script() {
    for command in [
        "& 'C:\\Python\\python.exe' 'C:\\fixture\\queue hook''s spaces.py'",
        "& 'C:\\工具\\python.exe' 'C:\\fixture\\🦀.py'",
        "",
    ] {
        let encoded = encode_command(command);
        let bytes = base64::engine::general_purpose::STANDARD
            .decode(encoded)
            .unwrap();
        let expected = command
            .encode_utf16()
            .flat_map(u16::to_le_bytes)
            .collect::<Vec<_>>();
        assert_eq!(bytes, expected);
        let units = bytes
            .chunks_exact(2)
            .map(|pair| u16::from_le_bytes([pair[0], pair[1]]))
            .collect::<Vec<_>>();
        assert_eq!(String::from_utf16(&units).unwrap(), command);
    }
}
