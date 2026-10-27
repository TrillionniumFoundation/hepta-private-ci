use super::Crate;
use super::I18nConfig;
use super::I18nConfigError;
use pretty_assertions::assert_eq;
use std::path::PathBuf;
use tempfile::tempdir;

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
