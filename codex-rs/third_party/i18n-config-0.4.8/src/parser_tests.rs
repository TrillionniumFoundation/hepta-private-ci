use super::*;
use pretty_assertions::assert_eq;

#[test]
fn maintained_parser_retains_fluent_and_gettext_configuration() {
    let config: I18nConfig = toml::from_str(
        r#"
fallback_language = "en-US"
subcrates = ["child"]

[fluent]
assets_dir = "translations"
domain = "example"

[gettext]
target_languages = ["zh-CN"]
output_dir = "locale"
"#,
    )
    .expect("parse the complete localization configuration");
    assert_eq!(config.fallback_language.to_string(), "en-US");
    assert_eq!(config.subcrates, vec![PathBuf::from("child")]);
    let fluent = config.fluent.expect("fluent configuration");
    assert_eq!(fluent.assets_dir, PathBuf::from("translations"));
    assert_eq!(fluent.domain.as_deref(), Some("example"));
    let gettext = config.gettext.expect("gettext configuration");
    assert_eq!(gettext.target_languages, vec!["zh-CN".to_string()]);
    assert_eq!(gettext.pot_dir(), PathBuf::from("locale/pot"));
    assert_eq!(gettext.po_dir(), PathBuf::from("locale/po"));
    assert_eq!(gettext.mo_dir(), PathBuf::from("locale/mo"));
    assert!(!gettext.extract_to_parent);
    assert!(!gettext.collate_extracted_subcrates);
    assert!(!gettext.use_fuzzy);
}

#[test]
fn crate_manifest_and_parent_localization_still_resolve() {
    let directory = tempfile::tempdir().expect("temporary crate directory");
    let child = directory.path().join("child");
    std::fs::create_dir(&child).expect("child crate");
    std::fs::write(
        directory.path().join("Cargo.toml"),
        "[package]\nname = \"parent\"\nversion = \"1.2.3\"\n",
    )
    .expect("parent manifest");
    std::fs::write(
        directory.path().join("i18n.toml"),
        "fallback_language = \"en-US\"\nsubcrates = [\"child\"]\n",
    )
    .expect("parent localization");
    std::fs::write(
        child.join("Cargo.toml"),
        "[package]\nname = \"child\"\nversion = \"2.3.4\"\n",
    )
    .expect("child manifest");
    let parent =
        Crate::from(directory.path(), /*parent*/ None, "i18n.toml").expect("parse parent crate");
    let child = Crate::from(child, Some(&parent), "i18n.toml").expect("parse child crate");
    assert_eq!(
        (&parent.name, &parent.version),
        (&"parent".to_string(), &"1.2.3".to_string())
    );
    assert_eq!(
        (&child.name, &child.version),
        (&"child".to_string(), &"2.3.4".to_string())
    );
    let (owner, config) = child
        .active_config()
        .expect("resolve owner")
        .expect("parent config");
    assert_eq!(owner.path, parent.path);
    assert_eq!(config.fallback_language.to_string(), "en-US");
    assert_eq!(child.find_parent().expect("find parent").name, "parent");
}

#[test]
fn invalid_toml_keeps_the_original_error_boundary_and_path() {
    let directory = tempfile::tempdir().expect("temporary configuration directory");
    let path = directory.path().join("i18n.toml");
    std::fs::write(&path, "fallback_language = [\n").expect("malformed fixture");
    match I18nConfig::from_file(&path) {
        Err(I18nConfigError::CannotDeserializeToml(observed_path, error)) => {
            assert_eq!(observed_path, path);
            assert!(!error.to_string().is_empty());
        }
        other => panic!("malformed TOML did not preserve the parse boundary: {other:?}"),
    }
}
