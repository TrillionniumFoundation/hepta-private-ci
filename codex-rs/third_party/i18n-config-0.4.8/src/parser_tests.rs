use super::Crate;
use super::I18nConfig;
use super::I18nConfigError;
use std::path::PathBuf;
use tempfile::tempdir;

#[test]
fn parses_fluent_configuration_and_defaults() {
    let directory = tempdir().expect("temporary directory");
    let path = directory.path().join("i18n.toml");
    std::fs::write(
        &path,
        "fallback_language = \"en-US\"\n[fluent]\nassets_dir = \"i18n\"\n",
    )
    .expect("configuration");

    let config = I18nConfig::from_file(&path).expect("parse fluent configuration");

    assert_eq!(config.fallback_language.to_string(), "en-US");
    assert_eq!(config.subcrates, Vec::<PathBuf>::new());
    assert_eq!(
        config.fluent.expect("fluent").assets_dir,
        PathBuf::from("i18n")
    );
    assert!(config.gettext.is_none());
}

#[test]
fn parses_cargo_package_and_associated_configuration() {
    let directory = tempdir().expect("temporary directory");
    std::fs::write(
        directory.path().join("Cargo.toml"),
        "[package]\nname = \"localized-tool\"\nversion = \"1.2.3\"\n",
    )
    .expect("package metadata");
    std::fs::write(
        directory.path().join("i18n.toml"),
        "fallback_language = \"en\"\nsubcrates = [\"child\"]\n[fluent]\nassets_dir = \"i18n\"\n",
    )
    .expect("configuration");

    let package = Crate::from(directory.path(), /*parent*/ None, "i18n.toml")
        .expect("parse package and configuration");

    assert_eq!(
        (package.name.as_str(), package.version.as_str()),
        ("localized-tool", "1.2.3")
    );
    assert_eq!(
        package.i18n_config.expect("configuration").subcrates,
        vec![PathBuf::from("child")]
    );
}

#[test]
fn rejects_malformed_syntax_duplicate_keys_and_invalid_locale() {
    let directory = tempdir().expect("temporary directory");
    let path = directory.path().join("i18n.toml");
    for invalid in [
        "fallback_language = [\n",
        "fallback_language = \"en\"\nfallback_language = \"fr\"\n",
        "fallback_language = \"not_a_language\"\n",
    ] {
        std::fs::write(&path, invalid).expect("invalid configuration");

        let error = I18nConfig::from_file(&path).expect_err("configuration must fail");

        assert!(
            matches!(error, I18nConfigError::CannotDeserializeToml(error_path, _) if error_path == path)
        );
    }
}
