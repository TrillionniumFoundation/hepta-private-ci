mod zip_actual;
mod aws_actual;
#[cfg(test)]
mod i18n_tests {

#[test]
fn maintained_toml_parser_loads_actual_crate_and_locale_files() {
    let directory = tempfile::tempdir().unwrap();
    std::fs::write(directory.path().join("Cargo.toml"),
        "[package]\nname = 'i18n-check'\nversion = '1.2.3'\n").unwrap();
    std::fs::write(directory.path().join("i18n.toml"),
        "fallback_language = 'en-US'\nsubcrates = ['child']\n").unwrap();
    let value = i18n_config::Crate::from(directory.path(), None, "i18n.toml").unwrap();
    let locale = value.i18n_config.unwrap();
    assert_eq!((value.name, value.version, locale.fallback_language.to_string(), locale.subcrates),
        ("i18n-check".to_string(), "1.2.3".to_string(), "en-US".to_string(), vec![std::path::PathBuf::from("child")]));
}

#[test]
fn malformed_locale_retains_source_path_in_real_error_type() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("i18n.toml");
    std::fs::write(&path,
        "fallback_language = 'en-US'\nfallback_language = 'fr'\n").unwrap();
    match i18n_config::I18nConfig::from_file(&path) {
        Err(i18n_config::I18nConfigError::CannotDeserializeToml(actual, error)) => {
            assert_eq!(actual, path);
            assert!(error.to_string().contains("duplicate key"));
        }
        other => panic!("unexpected parser outcome: {other:?}"),
    }
}

}
