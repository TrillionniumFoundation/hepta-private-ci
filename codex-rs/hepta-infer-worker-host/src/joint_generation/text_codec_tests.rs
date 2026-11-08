use super::valid_next;

#[test]
fn utf8_mask_rejects_overlong_surrogate_and_out_of_unicode_encodings() {
    for (prefix, byte) in [
        (&[][..], 0xc0),
        (&[][..], 0xff),
        (&[0xe0][..], 0x80),
        (&[0xed][..], 0xa0),
        (&[0xf0][..], 0x80),
        (&[0xf4][..], 0x90),
    ] {
        assert!(!valid_next(prefix, byte));
    }
    for text in ["a", "é", "中", "🙂", "\u{10ffff}"] {
        let mut prefix = Vec::new();
        for byte in text.bytes() {
            assert!(valid_next(&prefix, byte));
            prefix.push(byte);
        }
        assert_eq!(std::str::from_utf8(&prefix), Ok(text));
    }
}
