use super::normalize_markdown_hash_location_suffix;
use pretty_assertions::assert_eq;

#[test]
fn markdown_location_preserves_empty_and_nonnumeric_points() {
    for (input, expected) in [
        ("#L", ":"),
        ("#LC", "::"),
        ("#L-L", ":-"),
        ("#L-LC", ":-:"),
        ("#L文字C😀-LéC\0", ":文字:😀-é:\0"),
        (
            "#L000C18446744073709551616-L0",
            ":000:18446744073709551616-0",
        ),
        ("#L9C8C7-L6C5C4-L3", ":9:8C7-6:5C4-L3"),
        ("#L1-L-2", ":1--2"),
    ] {
        assert_eq!(
            normalize_markdown_hash_location_suffix(input).as_deref(),
            Some(expected)
        );
    }
}

#[test]
fn markdown_location_rejects_missing_required_markers() {
    for input in [
        "",
        "#",
        "L1",
        "##L1",
        "#l1",
        "#C1",
        "#L-",
        "#L1-2",
        "#L1C2-😀",
    ] {
        assert_eq!(normalize_markdown_hash_location_suffix(input), None);
    }
}

#[test]
fn markdown_location_handles_markers_and_unicode_across_frames() {
    for padding in 4091..=4098 {
        let line = "0".repeat(padding);
        for (tail, normalized) in [
            ("C2-L3C4", ":2-3:4"),
            ("-L3C4", "-3:4"),
            ("😀C2-L汉Cé", "😀:2-汉:é"),
        ] {
            assert_eq!(
                normalize_markdown_hash_location_suffix(&format!("#L{line}{tail}")),
                Some(format!(":{line}{normalized}"))
            );
        }
        assert_eq!(
            normalize_markdown_hash_location_suffix(&format!("#L{line}-X")),
            None
        );
    }
}

#[test]
fn markdown_location_has_no_total_frame_limit() {
    let line = "9".repeat(2_097_155);
    assert_eq!(
        normalize_markdown_hash_location_suffix(&format!("#L{line}C😀-L0C汉")),
        Some(format!(":{line}:😀-0:汉"))
    );
    assert_eq!(
        normalize_markdown_hash_location_suffix(&format!("#L{line}-")),
        None
    );
}
