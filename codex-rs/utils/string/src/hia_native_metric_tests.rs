use crate::sanitize_metric_tag_value;
use pretty_assertions::assert_eq;

#[test]
fn native_metric_preserves_tag_semantics() {
    let cases = [
        ("", "unspecified"),
        ("___", "unspecified"),
        ("./-_", "unspecified"),
        (" é汉😀 ", "unspecified"),
        ("__a.b-c/d_E09__", "a.b-c/d_E09"),
        ("bad value!", "bad_value"),
        ("aé汉😀z", "a___z"),
        ("__a\0b__", "a_b"),
        ("é/a\u{301}/汉", "/a_/"),
    ];
    let actual: Vec<_> = cases
        .iter()
        .map(|(input, _)| sanitize_metric_tag_value(input))
        .collect();
    let expected: Vec<_> = cases.iter().map(|(_, expected)| *expected).collect();
    assert_eq!(actual, expected);
}

#[test]
fn native_metric_checks_the_entire_tag_before_truncation() {
    let punctuation = "/.".repeat(128);
    assert_eq!(sanitize_metric_tag_value(&punctuation), "unspecified");
    assert_eq!(
        sanitize_metric_tag_value(&format!("{punctuation}___Z___")),
        punctuation
    );
    assert_eq!(sanitize_metric_tag_value(&"x".repeat(257)), "x".repeat(256));
    let trailing = format!("a{}", "_".repeat(2_097_155));
    assert_eq!(sanitize_metric_tag_value(&trailing), "a");
}

#[test]
fn native_metric_maps_characters_once_across_chunk_boundaries() {
    for split in 1..=3 {
        let leading = "_".repeat(1_048_575 - split);
        let text = format!("{leading}A😀B__");
        assert_eq!(sanitize_metric_tag_value(&text), "A_B");
    }
    let leading = "汉".repeat(1_000_001);
    assert_eq!(
        sanitize_metric_tag_value(&format!("{leading}aé汉😀z{leading}")),
        "a___z"
    );
}

#[test]
fn native_metric_callers_keep_independent_streaming_state() {
    std::thread::scope(|scope| {
        for worker in 0..8 {
            scope.spawn(move || {
                for iteration in 0..64 {
                    let input = format!("__tag/{worker}é{iteration}😀__");
                    let expected = format!("tag/{worker}_{iteration}");
                    assert_eq!(sanitize_metric_tag_value(&input), expected);
                }
            });
        }
    });
}
