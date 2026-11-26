use super::ValidationError;
use super::codex_hia_utf8_stream;
use super::decode;
use super::validate;
use pretty_assertions::assert_eq;

fn classification(bytes: &[u8]) {
    let expected = std::str::from_utf8(bytes)
        .map(str::as_bytes)
        .map_err(|error| (error.valid_up_to(), error.error_len()));
    let actual = validate(bytes)
        .map(str::as_bytes)
        .map_err(|error| (error.valid_up_to(), error.error_len()));
    assert_eq!(actual, expected, "input: {bytes:02x?}");
}

#[test]
fn all_one_and_two_byte_inputs_match_rust() {
    classification(&[]);
    for first in 0..=u8::MAX {
        classification(&[first]);
        for second in 0..=u8::MAX {
            classification(&[first, second]);
        }
    }
}

#[test]
fn multibyte_boundaries_prefixes_and_errors_match_rust() {
    let boundary = [0, 0x7f, 0x80, 0x8f, 0x90, 0x9f, 0xa0, 0xbf, 0xc0, 0xff];
    for first in 0xe0..=0xf4 {
        for second in boundary {
            for third in boundary {
                classification(&[first, second, third]);
                classification(&[b'a', 0xc3, 0xa9, first, second, third]);
                for fourth in boundary {
                    classification(&[first, second, third, fourth]);
                    classification(&[b'a', first, second, third, fourth, b'z']);
                }
            }
        }
    }
}

#[test]
fn borrowed_input_above_seed_capacity_has_no_new_limit() {
    let mut bytes = "aé中🦀".repeat(/*n*/ 131_073).into_bytes();
    assert!(bytes.len() > 1_048_576);
    classification(&bytes);
    bytes.extend_from_slice(&[0xf0, 0x9f, 0xa6]);
    classification(&bytes);
    bytes.push(0xff);
    classification(&bytes);
}

#[test]
fn malformed_native_results_are_rejected_before_string_construction() {
    let cases = [
        ([0, 0, 4, 0], 4),
        ([1, 3, 4, 0], 4),
        ([1, 0, 3, 0], 4),
        ([1, 0, 4, 1], 4),
        ([1, 1, 4, 1], 4),
        ([1, 1, 0, 0], 4),
        ([1, 1, 0, 4], 4),
        ([1, 2, 0, 0], 4),
        ([1, 2, 4, 0], 4),
        ([1, 2, 1, 1], 4),
        ([1, 1, u64::MAX, 1], 4),
    ];
    for (words, length) in cases {
        assert!(decode(encoded(words), length).is_err(), "{words:?}");
    }
    assert_eq!(decode(encoded([1, 0, 4, 0]), /*source_len*/ 4), Ok(None));
    assert_eq!(
        decode(encoded([1, 1, 1, 2]), /*source_len*/ 4),
        Ok(Some(ValidationError {
            valid_up_to: 1,
            error_len: Some(2),
        }))
    );
    assert_eq!(
        decode(encoded([1, 2, 1, 0]), /*source_len*/ 4),
        Ok(Some(ValidationError {
            valid_up_to: 1,
            error_len: None,
        }))
    );
}

fn encoded(words: [u64; 4]) -> [u8; 32] {
    let mut output = [0; 32];
    for (field, word) in output.chunks_exact_mut(8).zip(words) {
        field.copy_from_slice(&word.to_le_bytes());
    }
    output
}

#[test]
fn raw_abi_preserves_source_workspace_and_output_guards() {
    for fill in [0, 0xa5] {
        let source = [b'a', 0xe2, 0x82];
        for capacity in [0, 1, 8, 31, 32, 40] {
            let mut output = [fill; 56];
            let mut workspace = [0x5a; 19];
            // SAFETY: offset eight leaves 48 live output bytes, covering every
            // advertised capacity; source and workspace are disjoint arrays.
            let returned = unsafe {
                codex_hia_utf8_stream(
                    source.as_ptr(),
                    source.len() as u64,
                    output.as_mut_ptr().add(/*count*/ 8),
                    capacity,
                    workspace.as_mut_ptr(),
                    workspace.len() as u64,
                )
            };
            let mut expected = [fill; 56];
            if capacity < 32 {
                assert_eq!(returned, 0xffff_fffe);
            } else {
                assert_eq!(returned, 32);
                expected[8..40].copy_from_slice(&encoded([1, 2, 1, 0]));
            }
            assert_eq!(output, expected);
            assert_eq!(source, [b'a', 0xe2, 0x82]);
            assert_eq!(workspace, [0x5a; 19]);
        }
    }
}
