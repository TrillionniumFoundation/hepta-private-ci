use super::*;

#[test]
fn selected_paths_preserve_whitespace_in_the_filename() {
    let root = std::env::temp_dir();
    for name in [" input.json", "input.json ", " input.json "] {
        let selected = root.join(name);
        assert_eq!(absolute_path(selected.to_str().unwrap()).unwrap(), selected);
    }
}

#[test]
fn path_input_rejects_relative_names_nul_and_unbounded_text() {
    for invalid in ["", "relative.json", " /a.json", "/a\0.json"] {
        assert!(absolute_path(invalid).is_err());
    }
    let excessive = std::env::temp_dir().join("a".repeat(MAX_NATIVE_PATH_BYTES + 1));
    assert!(absolute_path(excessive.to_str().unwrap()).is_err());
}
