use std::fs;
use std::path::PathBuf;

use anyhow::Result;
use i18n_config::Crate;
use i18n_config::I18nConfig;
use i18n_config::I18nConfigError;
use pretty_assertions::assert_eq;

#[test]
fn localization_config_preserves_unicode_strings_and_optional_sections() -> Result<()> {
    let directory = tempfile::tempdir()?;
    fs::write(
        directory.path().join("Cargo.toml"),
        "[package]\nname = 'localized-package'\nversion = '1.2.3'\n",
    )?;
    fs::write(
        directory.path().join("i18n.toml"),
        r#"
fallback_language = "en-US"
subcrates = ["子程序", "path with spaces"]

[fluent]
assets_dir = 'locales\literal'
domain = """A localized
domain"""
"#,
    )?;

    let package = Crate::from(directory.path(), /*parent*/ None, "i18n.toml")?;
    let config = package.config_or_err()?;
    let fluent = config.fluent.as_ref().expect("Fluent configuration");
    assert_eq!(
        (
            package.name.as_str(),
            package.version.as_str(),
            package.module_name(),
            config.fallback_language.to_string(),
            config.subcrates.clone(),
            fluent.assets_dir.clone(),
            fluent.domain.as_deref(),
            config.gettext.is_none(),
        ),
        (
            "localized-package",
            "1.2.3",
            "localized_package".to_string(),
            "en-US".to_string(),
            vec![PathBuf::from("子程序"), PathBuf::from("path with spaces")],
            PathBuf::from(r"locales\literal"),
            Some("A localized\ndomain"),
            true,
        )
    );
    Ok(())
}

#[test]
fn localization_parent_config_keeps_gettext_defaults_and_inheritance() -> Result<()> {
    let parent_directory = tempfile::tempdir()?;
    let child_directory = tempfile::tempdir()?;
    for (directory, name) in [
        (parent_directory.path(), "localization-parent"),
        (child_directory.path(), "localization-child"),
    ] {
        fs::write(
            directory.join("Cargo.toml"),
            format!("[package]\nname = '{name}'\nversion = '0.1.0'\n"),
        )?;
    }
    fs::write(
        parent_directory.path().join("i18n.toml"),
        "fallback_language = 'en-US'\n[gettext]\ntarget_languages = ['fr', 'zh-CN']\noutput_dir = 'translations'\ncollate_extracted_subcrates = true\n",
    )?;
    fs::write(
        child_directory.path().join("i18n.toml"),
        "fallback_language = 'en-US'\n[gettext]\ntarget_languages = []\noutput_dir = 'child-translations'\nextract_to_parent = true\n",
    )?;

    let parent = Crate::from(parent_directory.path(), /*parent*/ None, "i18n.toml")?;
    let child = Crate::from(child_directory.path(), Some(&parent), "i18n.toml")?;
    let (active_package, active_config) = child.active_config()?.expect("inherited configuration");
    let gettext = active_config
        .gettext
        .as_ref()
        .expect("Gettext configuration");
    assert_eq!(
        (
            active_package.name.as_str(),
            gettext.target_languages.clone(),
            gettext.pot_dir(),
            gettext.po_dir(),
            gettext.mo_dir(),
            gettext.add_location.to_str(),
            gettext.use_fuzzy,
            child.collated_subcrate(),
        ),
        (
            "localization-parent",
            vec!["fr".to_string(), "zh-CN".to_string()],
            PathBuf::from("translations/pot"),
            PathBuf::from("translations/po"),
            PathBuf::from("translations/mo"),
            "full",
            false,
            true,
        )
    );
    Ok(())
}

#[test]
fn localization_parser_rejects_invalid_documents_with_the_original_path() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("i18n.toml");
    for input in [
        "fallback_language = [",
        "fallback_language = 'en-US'\nfallback_language = 'fr'\n",
        "fallback_language = 'en-US'\nsubcrates = 42\n",
        "subcrates = []\n",
    ] {
        fs::write(&path, input)?;
        let error = I18nConfig::from_file(&path).expect_err("invalid localization config");
        match error {
            I18nConfigError::CannotDeserializeToml(actual_path, source) => {
                assert_eq!(actual_path, path);
                assert!(!source.to_string().is_empty());
            }
            error => panic!("unexpected localization error: {error}"),
        }
    }

    fs::write(
        directory.path().join("Cargo.toml"),
        "[package]\nname = 'without-localization'\nversion = '0.1.0'\n",
    )?;
    fs::remove_file(&path)?;
    let package = Crate::from(directory.path(), /*parent*/ None, "i18n.toml")?;
    assert_eq!(
        (package.name.as_str(), package.i18n_config.is_none()),
        ("without-localization", true)
    );
    Ok(())
}
