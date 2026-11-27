use super::*;
use pretty_assertions::assert_eq;
use tempfile::tempdir;

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

#[test]
fn reads_crate_and_fluent_configuration_from_files() {
    let directory = tempdir().expect("create crate directory");
    std::fs::write(
        directory.path().join("Cargo.toml"),
        "[package]\nname = 'localized-app'\nversion = '0.4.0'\n",
    )
    .expect("write Cargo manifest");
    std::fs::write(
        directory.path().join("i18n.toml"),
        "fallback_language = 'en-US'\nsubcrates = ['child']\n[fluent]\nassets_dir = 'i18n/语言'\ndomain = 'messages'\n",
    )
    .expect("write Fluent configuration");

    let krate = Crate::from(directory.path(), /*parent*/ None, "i18n.toml")
        .expect("load crate and localization");
    let config = krate.config_or_err().expect("read active configuration");
    let fluent = config.fluent.as_ref().expect("read Fluent configuration");

    assert_eq!(
        (
            krate.name.as_str(),
            krate.version.as_str(),
            krate.module_name(),
            config.fallback_language.to_string(),
            config.subcrates.clone(),
            fluent.assets_dir.clone(),
            fluent.domain.clone(),
        ),
        (
            "localized-app",
            "0.4.0",
            "localized_app".to_string(),
            "en-US".to_string(),
            vec![PathBuf::from("child")],
            PathBuf::from("i18n/语言"),
            Some("messages".to_string()),
        )
    );
}

#[test]
fn reads_gettext_options_and_default_output_paths() {
    let directory = tempdir().expect("create configuration directory");
    let path = directory.path().join("i18n.toml");
    std::fs::write(
        &path,
        "fallback_language = 'en'\n[gettext]\ntarget_languages = ['fr', 'zh-CN']\noutput_dir = 'locale'\nadd_location = 'file'\nuse_fuzzy = true\n",
    )
    .expect("write gettext configuration");

    let config = I18nConfig::from_file(&path).expect("read gettext configuration");
    let gettext = config.gettext.expect("read gettext settings");

    assert_eq!(
        (
            gettext.target_languages.clone(),
            gettext.pot_dir(),
            gettext.po_dir(),
            gettext.mo_dir(),
            gettext.add_location.to_str(),
            gettext.use_fuzzy,
            gettext.extract_to_parent,
        ),
        (
            vec!["fr".to_string(), "zh-CN".to_string()],
            PathBuf::from("locale/pot"),
            PathBuf::from("locale/po"),
            PathBuf::from("locale/mo"),
            "file",
            true,
            false,
        )
    );
}

#[test]
fn malformed_configuration_preserves_source_path_in_error() {
    let directory = tempdir().expect("create configuration directory");
    let path = directory.path().join("i18n.toml");
    for contents in [
        "fallback_language = [unterminated",
        "fallback_language = 'en'\nfallback_language = 'fr'\n",
    ] {
        std::fs::write(&path, contents).expect("write invalid configuration");

        let error = I18nConfig::from_file(&path).expect_err("reject invalid TOML");

        match error {
            I18nConfigError::CannotDeserializeToml(actual, source) => {
                assert_eq!(actual, path);
                assert!(!source.to_string().is_empty());
            }
            other => panic!("unexpected parse error: {other}"),
        }
    }
}
