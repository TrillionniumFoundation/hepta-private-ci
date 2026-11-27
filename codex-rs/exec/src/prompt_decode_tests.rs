use super::PromptDecodeError;
use super::decode_prompt_bytes;

#[test]
fn utf8_prompts_preserve_unicode_and_strip_only_one_leading_bom() {
    for (input, expected) in [
        (b"".as_slice(), ""),
        ("é汉🦀\n".as_bytes(), "é汉🦀\n"),
        ("\u{feff}é汉🦀\n".as_bytes(), "é汉🦀\n"),
        ("\u{feff}\u{feff}prompt".as_bytes(), "\u{feff}prompt"),
        ("prompt\u{feff}".as_bytes(), "prompt\u{feff}"),
    ] {
        assert_eq!(decode_prompt_bytes(input), Ok(expected.to_string()));
    }
}

#[test]
fn invalid_and_incomplete_utf8_report_offsets_after_bom_removal() {
    for (input, valid_up_to) in [
        (b"\xff".as_slice(), 0),
        (b"ok\xe2(\xa1", 2),
        (b"ok\xe2\x82x", 2),
        (b"ok\xf0\x90\x80x", 2),
        (b"\xef\xbb\xbfprompt\xed\xa0\x80", 6),
        (b"\xef\xbb\xbfprompt\xf4\x90\x80\x80", 6),
        (b"\xc3", 0),
        (b"ok\xe2\x82", 2),
        (b"\xef\xbb\xbfprompt\xf0\x90\x80", 6),
    ] {
        assert_eq!(
            decode_prompt_bytes(input),
            Err(PromptDecodeError::InvalidUtf8 { valid_up_to })
        );
    }
}

#[test]
fn utf16_boms_still_decode_both_byte_orders_and_surrogate_pairs() {
    assert_eq!(
        decode_prompt_bytes(b"\xff\xfe\xe9\x00\x3e\xd8\x80\xdd\n\0"),
        Ok("é🦀\n".to_string())
    );
    assert_eq!(
        decode_prompt_bytes(b"\xfe\xff\x00\xe9\xd8\x3e\xdd\x80\0\n"),
        Ok("é🦀\n".to_string())
    );
    for (input, encoding) in [
        (b"\xff\xfea".as_slice(), "UTF-16LE"),
        (b"\xff\xfe\0\xd8", "UTF-16LE"),
        (b"\xfe\xffa", "UTF-16BE"),
        (b"\xfe\xff\xdc\0", "UTF-16BE"),
    ] {
        assert_eq!(
            decode_prompt_bytes(input),
            Err(PromptDecodeError::InvalidUtf16 { encoding })
        );
    }
}

#[test]
fn utf32_boms_are_rejected_before_utf16_detection() {
    for (input, encoding) in [
        (b"\xff\xfe\0\0a\0\0\0".as_slice(), "UTF-32LE"),
        (b"\0\0\xfe\xff\0\0\0a", "UTF-32BE"),
    ] {
        assert_eq!(
            decode_prompt_bytes(input),
            Err(PromptDecodeError::UnsupportedBom { encoding })
        );
    }
}

#[test]
fn unicode_prompt_above_one_mib_has_no_native_frame_limit() {
    let text = "é汉🦀\n".repeat(110_000);
    assert!(text.len() > 1024 * 1024);
    assert_eq!(decode_prompt_bytes(text.as_bytes()), Ok(text));
}

#[test]
fn decode_prompt_bytes_strips_utf8_bom() {
    let input = [0xEF, 0xBB, 0xBF, b'h', b'i', b'\n'];

    let out = decode_prompt_bytes(&input).expect("decode utf-8 with BOM");

    assert_eq!(out, "hi\n");
}

#[test]
fn decode_prompt_bytes_decodes_utf16le_bom() {
    // UTF-16LE BOM + "hi\n"
    let input = [0xFF, 0xFE, b'h', 0x00, b'i', 0x00, b'\n', 0x00];

    let out = decode_prompt_bytes(&input).expect("decode utf-16le with BOM");

    assert_eq!(out, "hi\n");
}

#[test]
fn decode_prompt_bytes_decodes_utf16be_bom() {
    // UTF-16BE BOM + "hi\n"
    let input = [0xFE, 0xFF, 0x00, b'h', 0x00, b'i', 0x00, b'\n'];

    let out = decode_prompt_bytes(&input).expect("decode utf-16be with BOM");

    assert_eq!(out, "hi\n");
}

#[test]
fn decode_prompt_bytes_rejects_utf32le_bom() {
    // UTF-32LE BOM + "hi\n"
    let input = [
        0xFF, 0xFE, 0x00, 0x00, b'h', 0x00, 0x00, 0x00, b'i', 0x00, 0x00, 0x00, b'\n', 0x00, 0x00,
        0x00,
    ];

    let err = decode_prompt_bytes(&input).expect_err("utf-32le should be rejected");

    assert_eq!(
        err,
        PromptDecodeError::UnsupportedBom {
            encoding: "UTF-32LE"
        }
    );
}

#[test]
fn decode_prompt_bytes_rejects_utf32be_bom() {
    // UTF-32BE BOM + "hi\n"
    let input = [
        0x00, 0x00, 0xFE, 0xFF, 0x00, 0x00, 0x00, b'h', 0x00, 0x00, 0x00, b'i', 0x00, 0x00, 0x00,
        b'\n',
    ];

    let err = decode_prompt_bytes(&input).expect_err("utf-32be should be rejected");

    assert_eq!(
        err,
        PromptDecodeError::UnsupportedBom {
            encoding: "UTF-32BE"
        }
    );
}

#[test]
fn decode_prompt_bytes_rejects_invalid_utf8() {
    // Invalid UTF-8 sequence: 0xC3 0x28
    let input = [0xC3, 0x28];

    let err = decode_prompt_bytes(&input).expect_err("invalid utf-8 should fail");

    assert_eq!(err, PromptDecodeError::InvalidUtf8 { valid_up_to: 0 });
}
