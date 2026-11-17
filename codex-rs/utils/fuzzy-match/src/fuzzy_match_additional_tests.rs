use super::fuzzy_match;

struct Case {
    name: &'static str,
    haystack: &'static str,
    needle: &'static str,
    expected: Option<(Vec<usize>, i32)>,
}

#[test]
fn public_literals_preserve_scalar_indices_and_scores() {
    let cases = [
        Case {
            name: "empty_both",
            haystack: "",
            needle: "",
            expected: Some((vec![], i32::MAX)),
        },
        Case {
            name: "empty_needle",
            haystack: "anything",
            needle: "",
            expected: Some((vec![], i32::MAX)),
        },
        Case {
            name: "empty_haystack",
            haystack: "",
            needle: "a",
            expected: None,
        },
        Case {
            name: "ascii_greedy",
            haystack: "hello",
            needle: "hl",
            expected: Some((vec![0, 2], -99)),
        },
        Case {
            name: "ascii_prefix",
            haystack: "FooBar",
            needle: "foO",
            expected: Some((vec![0, 1, 2], -100)),
        },
        Case {
            name: "ascii_spread",
            haystack: "a-b-c",
            needle: "abc",
            expected: Some((vec![0, 2, 4], -98)),
        },
        Case {
            name: "ascii_nonprefix",
            haystack: "my_file_name",
            needle: "file",
            expected: Some((vec![3, 4, 5, 6], 0)),
        },
        Case {
            name: "greedy_repeated",
            haystack: "abca",
            needle: "aa",
            expected: Some((vec![0, 3], -98)),
        },
        Case {
            name: "greedy_nonprefix",
            haystack: "baaab",
            needle: "ab",
            expected: Some((vec![1, 4], 2)),
        },
        Case {
            name: "space_is_literal",
            haystack: "a a",
            needle: "a ",
            expected: Some((vec![0, 1], -100)),
        },
        Case {
            name: "dotted_i_pair",
            haystack: "\u{130}",
            needle: "i\u{307}",
            expected: Some((vec![0], -100)),
        },
        Case {
            name: "dotted_i_single_i",
            haystack: "\u{130}",
            needle: "i",
            expected: Some((vec![0], -100)),
        },
        Case {
            name: "dotted_i_second_slot",
            haystack: "\u{130}",
            needle: "\u{307}",
            expected: Some((vec![0], -99)),
        },
        Case {
            name: "dotted_i_second_slot_nonprefix",
            haystack: "x\u{130}",
            needle: "\u{307}",
            expected: Some((vec![1], 1)),
        },
        Case {
            name: "dotted_i_repeated",
            haystack: "\u{130}\u{130}",
            needle: "i\u{307}i\u{307}",
            expected: Some((vec![0, 1], -100)),
        },
        Case {
            name: "dotted_i_first_origin_start",
            haystack: "\u{130}\u{130}",
            needle: "\u{307}i",
            expected: Some((vec![0, 1], -99)),
        },
        Case {
            name: "dotted_i_skipped_slot",
            haystack: "A\u{130}b",
            needle: "a\u{307}b",
            expected: Some((vec![0, 1, 2], -99)),
        },
        Case {
            name: "dotted_i_istanbul",
            haystack: "\u{130}stanbul",
            needle: "is",
            expected: Some((vec![0, 1], -99)),
        },
        Case {
            name: "sharp_s_no_ss",
            haystack: "stra\u{df}e",
            needle: "strasse",
            expected: None,
        },
        Case {
            name: "capital_sharp_s",
            haystack: "\u{1e9e}",
            needle: "\u{df}",
            expected: Some((vec![0], -100)),
        },
        Case {
            name: "needle_capital_sharp_s",
            haystack: "\u{df}",
            needle: "\u{1e9e}",
            expected: Some((vec![0], -100)),
        },
        Case {
            name: "capital_sharp_s_no_ss",
            haystack: "\u{1e9e}",
            needle: "ss",
            expected: None,
        },
        Case {
            name: "kelvin",
            haystack: "\u{212a}",
            needle: "k",
            expected: Some((vec![0], -100)),
        },
        Case {
            name: "kelvin_repeated",
            haystack: "\u{212a}K",
            needle: "kk",
            expected: Some((vec![0, 1], -100)),
        },
        Case {
            name: "angstrom",
            haystack: "\u{212b}",
            needle: "\u{e5}",
            expected: Some((vec![0], -100)),
        },
        Case {
            name: "ligature_no_full_casefold",
            haystack: "\u{fb03}",
            needle: "ffi",
            expected: None,
        },
        Case {
            name: "deseret_scalar",
            haystack: "\u{10400}",
            needle: "\u{10428}",
            expected: Some((vec![0], -100)),
        },
        Case {
            name: "deseret_nonprefix",
            haystack: "x\u{10400}",
            needle: "\u{10428}",
            expected: Some((vec![1], 0)),
        },
        Case {
            name: "emoji_character_index",
            haystack: "\u{1f600}A",
            needle: "a",
            expected: Some((vec![1], 0)),
        },
        Case {
            name: "no_canonical_normalization_a",
            haystack: "e\u{301}",
            needle: "\u{e9}",
            expected: None,
        },
        Case {
            name: "no_canonical_normalization_b",
            haystack: "\u{e9}",
            needle: "e\u{301}",
            expected: None,
        },
        Case {
            name: "accent_not_removed",
            haystack: "\u{e9}E",
            needle: "e",
            expected: Some((vec![1], 0)),
        },
        Case {
            name: "nul_scalar",
            haystack: "\0",
            needle: "\0",
            expected: Some((vec![0], -100)),
        },
        Case {
            name: "nul_nonprefix",
            haystack: "a\0b",
            needle: "\0",
            expected: Some((vec![1], 0)),
        },
        Case {
            name: "nul_needle_is_not_empty",
            haystack: "",
            needle: "\0",
            expected: None,
        },
        Case {
            name: "sigma_alone",
            haystack: "\u{3a3}",
            needle: "\u{3a3}",
            expected: Some((vec![0], -100)),
        },
        Case {
            name: "sigma_whole_string_difference",
            haystack: "\u{39f}\u{3a3}",
            needle: "\u{39f}\u{3a3}",
            expected: None,
        },
        Case {
            name: "sigma_lowercase_needle",
            haystack: "\u{39f}\u{3a3}",
            needle: "\u{3bf}\u{3c3}",
            expected: Some((vec![0, 1], -100)),
        },
        Case {
            name: "sigma_final_matches",
            haystack: "\u{3bf}\u{3c2}",
            needle: "\u{39f}\u{3a3}",
            expected: Some((vec![0, 1], -100)),
        },
        Case {
            name: "sigma_latin_context_difference",
            haystack: "A\u{3a3}",
            needle: "A\u{3a3}",
            expected: None,
        },
        Case {
            name: "sigma_latin_final_matches",
            haystack: "A\u{3c2}",
            needle: "A\u{3a3}",
            expected: Some((vec![0, 1], -100)),
        },
        Case {
            name: "sigma_following_cased",
            haystack: "A\u{3a3}A",
            needle: "A\u{3a3}A",
            expected: Some((vec![0, 1, 2], -100)),
        },
        Case {
            name: "sigma_ignorable_then_cased",
            haystack: "A\u{3a3}\u{301}A",
            needle: "A\u{3a3}\u{301}A",
            expected: Some((vec![0, 1, 2, 3], -100)),
        },
        Case {
            name: "sigma_ignorable_then_eof",
            haystack: "A\u{3c2}\u{301}",
            needle: "A\u{3a3}\u{301}",
            expected: Some((vec![0, 1, 2], -100)),
        },
        Case {
            name: "sigma_no_preceding_cased",
            haystack: "\u{3a3}\u{301}",
            needle: "\u{3a3}\u{301}",
            expected: Some((vec![0, 1], -100)),
        },
        Case {
            name: "sigma_punctuation_boundary",
            haystack: "A\u{3c2}!",
            needle: "A\u{3a3}!",
            expected: Some((vec![0, 1, 2], -100)),
        },
        Case {
            name: "sigma_newline_breaks_preceding",
            haystack: "A\n\u{3a3}",
            needle: "A\n\u{3a3}",
            expected: Some((vec![0, 1, 2], -100)),
        },
        Case {
            name: "sigma_cased_ignorable_is_not_preceding_context",
            haystack: "\u{345}\u{3a3}",
            needle: "\u{345}\u{3a3}",
            expected: Some((vec![0, 1], -100)),
        },
        Case {
            name: "sigma_cased_ignorable_before_eof",
            haystack: "A\u{3c2}\u{345}",
            needle: "A\u{3a3}\u{345}",
            expected: Some((vec![0, 1, 2], -100)),
        },
        Case {
            name: "sigma_cased_ignorable_before_cased",
            haystack: "A\u{3a3}\u{345}A",
            needle: "A\u{3a3}\u{345}A",
            expected: Some((vec![0, 1, 2, 3], -100)),
        },
    ];

    for case in cases {
        let actual = fuzzy_match(case.haystack, case.needle);
        assert_eq!(actual, case.expected, "{}", case.name);
    }
}
