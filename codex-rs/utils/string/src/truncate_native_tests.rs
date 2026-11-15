use super::approx_bytes_for_tokens;
use super::approx_tokens_from_byte_count;
use super::truncate_middle_chars;
use super::truncate_middle_with_token_budget;
use pretty_assertions::assert_eq;

#[test]
fn marker_budget_preserves_original_utf8_and_odd_split_behavior() {
    assert_eq!(
        truncate_middle_chars("abcdefg", 3),
        "a…4 chars truncated…fg"
    );
    assert_eq!(truncate_middle_chars("😀😀😀", 3), "…3 chars truncated…");
    assert_eq!(
        truncate_middle_with_token_budget("é汉😀", 1),
        ("é…2 tokens truncated…".into(), Some(3))
    );
    assert_eq!(truncate_middle_chars("a\u{301}b", 0), "…3 chars truncated…");
}

#[test]
fn marker_collision_keeps_the_original_no_truncation_report() {
    for (text, budget) in [("…6 tokens truncated…", 0), ("ab…6 tokens truncated…cd", 1)] {
        assert_eq!(
            truncate_middle_with_token_budget(text, budget),
            (text.to_owned(), None)
        );
    }
}

#[test]
fn zero_empty_and_unbounded_budgets_preserve_output_ownership() {
    for text in ["", "ascii", "\0é汉😀"] {
        assert_eq!(truncate_middle_chars(text, usize::MAX), text);
        assert_eq!(
            truncate_middle_with_token_budget(text, usize::MAX),
            (text.to_owned(), None)
        );
    }
    assert_eq!(truncate_middle_chars("", 0), "");
    assert_eq!(
        truncate_middle_with_token_budget("", 0),
        (String::new(), None)
    );
    let output = {
        let text = String::from("owned after source drop");
        truncate_middle_chars(&text, usize::MAX)
    };
    assert_eq!(output, "owned after source drop");
}

#[test]
fn saturation_precedes_token_division() {
    assert_eq!(approx_bytes_for_tokens(usize::MAX), usize::MAX);
    assert_eq!(approx_bytes_for_tokens(usize::MAX / 4 + 1), usize::MAX);
    for value in usize::MAX - 3..=usize::MAX {
        assert_eq!(approx_tokens_from_byte_count(value), u64::MAX / 4);
    }
}
