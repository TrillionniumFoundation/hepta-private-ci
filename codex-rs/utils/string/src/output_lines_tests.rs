use super::count_lines;
use pretty_assertions::assert_eq;

#[test]
fn line_count_preserves_rust_line_semantics() {
    for (text, expected) in [
        ("", 0),
        ("\n", 1),
        ("\r", 1),
        ("\r\n", 1),
        ("a\n", 1),
        ("a\n\n", 2),
        ("a\nb", 2),
        ("a\r\nb\rc", 2),
        ("\0\u{0085}\u{2028}\u{2029}", 1),
        ("é\n💡\r\n終", 3),
    ] {
        assert_eq!(count_lines(text), expected, "input: {text:?}");
    }
}

#[test]
fn line_count_matches_original_rust_across_transport_boundaries() {
    for prefix in [0, 4094, 4095, 4096, 4097, 8191, 8192, 8193] {
        for suffix in ["", "\r", "\n", "\r\n", "\n\n", "é\nx", "💡\r\n終"] {
            let mut text = "x".repeat(prefix);
            text.push_str(suffix);
            assert_eq!(
                count_lines(&text),
                text.lines().count(),
                "prefix: {prefix}, suffix: {suffix:?}"
            );
        }
    }
}

#[test]
fn line_count_preserves_inputs_larger_than_the_foreign_frame_limit() {
    let mut text = "zero\r\né💡\nlast".repeat(/*n*/ 131_073);
    assert_eq!(count_lines(&text), text.lines().count());
    text.push('\n');
    assert_eq!(count_lines(&text), text.lines().count());
    text.push('\r');
    assert_eq!(count_lines(&text), text.lines().count());
}
