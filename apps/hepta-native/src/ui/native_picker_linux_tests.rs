use super::*;

#[test]
fn local_uri_decoding_preserves_the_exact_filename() {
    for (uri, path) in [
        ("file:///tmp/%20grant%20", "/tmp/ grant "),
        ("file://localhost/tmp/%E4%B8%AD%23%25", "/tmp/中#%"),
        ("file:/tmp/link/../grant", "/tmp/link/../grant"),
        ("file:///tmp/%2e%2e/grant", "/tmp/../grant"),
    ] {
        assert_eq!(decode_selected_uri(uri).unwrap(), PathBuf::from(path));
    }
}

#[test]
fn ambiguous_remote_malformed_and_oversized_uri_results_fail_closed() {
    for uri in [
        "file:///tmp/grant%0A",
        "file:///tmp/grant%0D%0A",
        "file:///tmp/grant%00",
        "file:///tmp/%FF",
        "file:///tmp/%",
        "file:///tmp/%GG",
        "file:relative",
        "file://remote/tmp/grant",
        "file://localhost.evil/tmp/grant",
        "file://user@localhost/tmp/grant",
        "https://localhost/tmp/grant",
        "file:///tmp/grant#fragment",
        "file:///tmp/grant?query",
    ] {
        assert!(decode_selected_uri(uri).is_err(), "accepted {uri}");
    }
    assert!(decode_selected_uri(&format!("file:///{}", "a".repeat(MAX_SELECTION_BYTES))).is_err());
}
