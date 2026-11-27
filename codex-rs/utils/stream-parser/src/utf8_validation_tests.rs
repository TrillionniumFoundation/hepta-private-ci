use super::validate_utf8;

#[test]
fn validation_borrows_complete_unicode_and_empty_input() {
    for text in ["", "ASCII\0", "é汉🦀", "\u{d7ff}\u{e000}\u{10ffff}"] {
        let actual = validate_utf8(text.as_bytes()).expect("complete UTF-8");
        assert_eq!(actual, text);
        assert_eq!(actual.as_ptr(), text.as_ptr());
    }
}

#[test]
fn validation_preserves_invalid_and_incomplete_error_details() {
    for bytes in [
        b"a\xff".as_slice(),
        b"ok\xe2(\xa1",
        b"ok\xe2\x82x",
        b"ok\xf0\x90\x80x",
        b"\xed\xa0\x80",
        b"\xf4\x90\x80\x80",
        b"ok\xc3",
        b"ok\xe2\x82",
        b"ok\xf0\x90\x80",
    ] {
        let expected = std::str::from_utf8(bytes).expect_err("invalid fixture");
        let actual = validate_utf8(bytes).expect_err("invalid UTF-8");
        assert_eq!(
            (actual.valid_up_to(), actual.error_len(), actual.to_string()),
            (
                expected.valid_up_to(),
                expected.error_len(),
                expected.to_string()
            )
        );
    }
}
