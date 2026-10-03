#[path = "support/stream_diagnostics.rs"]
mod stream_diagnostics;

use stream_diagnostics::MAX_STREAM_BYTES;
use stream_diagnostics::summarize_stream;

#[test]
fn short_streams_are_preserved_after_lossy_decoding() {
    for bytes in [b"".as_slice(), b"startup failed\n", b"bad \xff byte\n"] {
        assert_eq!(
            summarize_stream(bytes.iter().copied()),
            String::from_utf8_lossy(bytes)
        );
    }
}

#[test]
fn startup_error_survives_a_long_backtrace_without_losing_the_tail() {
    let bytes = format!(
        "startup cause\n{}\nfinal frame\n",
        "backtrace\n".repeat(1_000)
    );
    let result = summarize_stream(bytes.bytes());
    assert!(result.starts_with("startup cause\n"));
    assert!(result.ends_with("\nfinal frame\n"));
    assert!(result.contains("...[middle omitted]..."));
    assert!(result.len() <= MAX_STREAM_BYTES);
}

#[test]
fn exact_budget_preserves_output_and_one_extra_byte_is_marked() {
    let bytes = vec![b'x'; MAX_STREAM_BYTES];
    assert_eq!(summarize_stream(bytes.iter().copied()).as_bytes(), bytes);
    let longer = vec![b'x'; MAX_STREAM_BYTES + 1];
    let result = summarize_stream(longer.iter().copied());
    assert!(result.contains("...[middle omitted]..."));
    assert_eq!(result.len(), MAX_STREAM_BYTES);
}

#[test]
fn multibyte_boundaries_never_split_a_code_point() {
    let bytes = format!("cause 🦀\n{}\nend 🦀", "🦀".repeat(2_000));
    let result = summarize_stream(bytes.bytes());
    assert!(result.starts_with("cause 🦀\n"));
    assert!(result.ends_with("\nend 🦀"));
    assert!(!result.contains('\u{fffd}'));
    assert!(result.len() <= MAX_STREAM_BYTES);
}

#[test]
fn invalid_bytes_cannot_expand_the_decoded_budget() {
    for count in [MAX_STREAM_BYTES / 2, MAX_STREAM_BYTES, MAX_STREAM_BYTES * 3] {
        let mut bytes = b"first cause\n".to_vec();
        bytes.extend(std::iter::repeat_n(0xff, count));
        bytes.extend_from_slice(b"\nlast frame");
        let result = summarize_stream(bytes.iter().copied());
        assert!(result.starts_with("first cause\n"));
        assert!(result.ends_with("\nlast frame"));
        assert!(result.contains('\u{fffd}'));
        assert!(result.len() <= MAX_STREAM_BYTES);
    }
}

#[test]
fn large_streams_have_bounded_input_consumption() {
    let seen = std::cell::Cell::new(0);
    let bytes = std::iter::repeat_n(b'x', 1_000_000).inspect(|_| seen.set(seen.get() + 1));
    let result = summarize_stream(bytes);
    assert!(result.len() <= MAX_STREAM_BYTES);
    assert!(seen.get() <= 2 * (MAX_STREAM_BYTES + 1));
}
