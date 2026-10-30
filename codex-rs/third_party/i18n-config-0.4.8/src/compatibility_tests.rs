use super::{Crate, I18nConfig, I18nConfigError};
use std::path::PathBuf;

#[test]
fn public_crate_loader_preserves_package_and_language_config() {
    let directory = tempfile::tempdir().unwrap();
    std::fs::write(
        directory.path().join("Cargo.toml"),
        "[package]\nname = \"sample-app\"\nversion = \"0.1.0\"\n",
    )
    .unwrap();
    std::fs::write(
        directory.path().join("i18n.toml"),
        r#"fallback_language = "en-US"
subcrates = ["tools"]
[fluent]
assets_dir = "i18n/assets"
domain = "messages"
[gettext]
target_languages = ["fr", "zh-CN"]
output_dir = "locale"
"#,
    )
    .unwrap();
    let loaded = Crate::from(directory.path(), /*parent*/ None, "i18n.toml").unwrap();
    assert_eq!(
        (&*loaded.name, &*loaded.version, loaded.module_name()),
        ("sample-app", "0.1.0", "sample_app".to_string()),
    );
    let config = loaded.config_or_err().unwrap();
    assert_eq!(config.fallback_language.to_string(), "en-US");
    assert_eq!(config.subcrates, [PathBuf::from("tools")]);
    let fluent = config.fluent.as_ref().unwrap();
    assert_eq!(
        (&fluent.assets_dir, fluent.domain.as_deref()),
        (&PathBuf::from("i18n/assets"), Some("messages")),
    );
    let gettext = loaded.gettext_config_or_err().unwrap();
    assert_eq!(gettext.target_languages, ["fr", "zh-CN"]);
    assert_eq!(gettext.pot_dir(), PathBuf::from("locale/pot"));
    assert_eq!(gettext.po_dir(), PathBuf::from("locale/po"));
    assert_eq!(gettext.mo_dir(), PathBuf::from("locale/mo"));
    assert!(!gettext.extract_to_parent);
    assert!(!gettext.collate_extracted_subcrates);
    assert!(!gettext.use_fuzzy);
    assert_eq!(gettext.add_location.to_str(), "full");
}

#[test]
fn public_config_loader_preserves_defaults_and_unicode() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("i18n.toml");
    std::fs::write(
        &path,
        "fallback_language = \"zh-CN\"\n[fluent]\nassets_dir = \"多语言/资源\"\n",
    )
    .unwrap();
    let config = I18nConfig::from_file(&path).unwrap();
    assert_eq!(config.fallback_language.to_string(), "zh-CN");
    assert!(config.subcrates.is_empty());
    assert!(config.gettext.is_none());
    let fluent = config.fluent.unwrap();
    assert_eq!(
        (fluent.assets_dir, fluent.domain),
        (PathBuf::from("多语言/资源"), None),
    );
}

#[test]
fn public_parse_errors_keep_path_and_diagnostic() {
    let directory = tempfile::tempdir().unwrap();
    let config = directory.path().join("i18n.toml");
    for invalid in ["fallback_language = [", "fallback_language = 42"] {
        std::fs::write(&config, invalid).unwrap();
        match I18nConfig::from_file(&config).unwrap_err() {
            I18nConfigError::CannotDeserializeToml(path, error) => {
                assert_eq!(path, config);
                assert!(!error.to_string().is_empty());
            }
            other => panic!("expected a path-bound TOML error, got {other}", other = other),
        }
    }
    let manifest = directory.path().join("Cargo.toml");
    std::fs::write(&manifest, "[package]\nname = [").unwrap();
    match Crate::from(directory.path(), /*parent*/ None, "i18n.toml").unwrap_err() {
        I18nConfigError::CannotDeserializeToml(path, error) => {
            assert_eq!(path, manifest);
            assert!(!error.to_string().is_empty());
        }
        other => panic!("expected a path-bound Cargo TOML error, got {other}", other = other),
    }
}
