use super::*;
use pretty_assertions::assert_eq;

#[test]
fn first_match_handles_prefix_fallback_and_overlapping_occurrences() {
    assert_eq!(find_subslice(b"abababacababaca", b"ababaca"), Some(2));
    assert_eq!(find_subslice(b"ababcabcabababd", b"ababd"), Some(10));
    assert_eq!(find_subslice(b"aaaaabaaaaab", b"aaaab"), Some(1));
}

#[test]
fn advancing_the_cursor_selects_the_next_non_overlapping_occurrence() {
    let serialized = b"ababa|aba";
    let needle = b"aba";
    let first = find_subslice(serialized, needle)
        .unwrap_or_else(|| panic!("first source occurrence missing"));
    let cursor = first + needle.len();
    let next = find_subslice(&serialized[cursor..], needle)
        .unwrap_or_else(|| panic!("second source occurrence missing"));
    assert_eq!((first, cursor + next), (0, 6));
}

#[test]
fn empty_or_absent_needles_preserve_missing_semantics() {
    assert_eq!(find_subslice(b"", b""), None);
    assert_eq!(find_subslice(b"payload", b""), None);
    assert_eq!(find_subslice(b"", b"payload"), None);
    assert_eq!(find_subslice(b"short", b"longer-needle"), None);
    assert_eq!(find_subslice(b"aaaaaaaa", b"aaaab"), None);
}
