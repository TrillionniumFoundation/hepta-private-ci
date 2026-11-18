use super::find_uuids;
use pretty_assertions::assert_eq;

const UUID: &str = "00112233-4455-6677-8899-aAbBcCdDeEfF";

#[test]
fn uuid_matches_keep_original_case_and_non_overlapping_order() {
    assert_eq!(
        find_uuids(&format!("a{UUID}{UUID}f")),
        vec![UUID.to_string(), UUID.to_string()]
    );
}

#[test]
fn uuid_matches_cross_borrowed_window_boundaries() {
    for padding in 4058..=4100 {
        for prefix in ["é", "汉", "😀"] {
            assert_eq!(
                find_uuids(&format!("{}{prefix}{UUID}{UUID}", "x".repeat(padding))),
                vec![UUID.to_string(), UUID.to_string()]
            );
        }
    }
}

#[test]
fn uuid_matches_have_no_one_mib_source_limit() {
    let source = format!("{UUID}{}{UUID}", "f".repeat(1_048_579));
    assert_eq!(
        find_uuids(&source),
        vec![UUID.to_string(), UUID.to_string()]
    );
}
