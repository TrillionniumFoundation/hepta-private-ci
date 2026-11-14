use crate::take_bytes_at_char_boundary;

#[test]
fn native_prefix_uses_the_public_string_api() {
    let text = "aé汉😀z";
    let boundaries = [0, 1, 1, 3, 3, 3, 6, 6, 6, 6, 10, 11, 11];
    for (budget, expected) in boundaries.into_iter().enumerate() {
        let actual = take_bytes_at_char_boundary(text, budget);
        assert_eq!(actual, &text[..expected]);
        assert_eq!(actual.as_ptr(), text.as_ptr());
    }
}

#[test]
fn native_prefix_accepts_zero_and_unbounded_budgets() {
    for text in ["", "ascii", "é汉😀", "\0\u{10ffff}"] {
        assert_eq!(take_bytes_at_char_boundary(text, 0), "");
        assert_eq!(take_bytes_at_char_boundary(text, usize::MAX), text);
    }
}

#[test]
fn native_prefix_has_no_one_mib_input_limit() {
    let prefix = "x".repeat(1_048_575);
    let text = format!("{prefix}😀tail");
    for budget in 1_048_575..1_048_579 {
        assert_eq!(take_bytes_at_char_boundary(&text, budget), prefix);
    }
    assert_eq!(
        take_bytes_at_char_boundary(&text, 1_048_579),
        &text[..1_048_579]
    );
    assert_eq!(take_bytes_at_char_boundary(&text, usize::MAX), text);
}
