use super::fuzzy_match;

#[test]
fn haystack_larger_than_one_mebibyte_preserves_nonprefix_index() {
    let prefix_length = 1_048_576;
    let prefix = "a".repeat(prefix_length);
    let haystack = format!("{prefix}b");

    assert_eq!(fuzzy_match(&haystack, "b"), Some((vec![prefix_length], 0)));
}

#[test]
fn pending_final_sigma_survives_more_than_one_mebibyte_of_case_ignorables() {
    let mark_count = 524_289;
    let marks = "\u{301}".repeat(mark_count);
    let haystack = format!("A\u{3c2}{marks}");
    let needle = format!("A\u{3a3}{marks}");
    let scalar_count = mark_count + 2;
    let expected_indices = (0..scalar_count).collect();

    let actual = fuzzy_match(&haystack, &needle);
    assert_eq!(actual, Some((expected_indices, -100)));
}
