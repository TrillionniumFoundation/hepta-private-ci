use i18n_config::Crate;
use i18n_config::I18nConfig;
use i18n_config::I18nConfigError;
use pretty_assertions::assert_eq;
use std::error::Error;
use std::fs;
use std::path::PathBuf;

#[test]
fn reads_cargo_identity_and_fluent_configuration() -> Result<(), Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    fs::write(
        directory.path().join("Cargo.toml"),
        "[package]\nname = \"localized-app\"\nversion = \"1.2.3\"\n[dependencies]\n",
    )?;
    fs::write(
        directory.path().join("i18n.toml"),
        r#"fallback_language = "en-US"
subcrates = ["child"]
[fluent]
assets_dir = "locales/日本語"
domain = "application"
"#,
    )?;

    let parsed = Crate::from(directory.path(), /*parent*/ None, "i18n.toml")?;
    assert_eq!(
        (
            parsed.name.as_str(),
            parsed.version.as_str(),
            parsed.path.as_path(),
            parsed.config_file_path.as_path(),
            parsed.parent.is_none(),
        ),
        (
            "localized-app",
            "1.2.3",
            directory.path(),
            std::path::Path::new("i18n.toml"),
            true,
        )
    );
    let config = parsed.config_or_err()?;
    let fluent = config
        .fluent
        .as_ref()
        .ok_or("Fluent configuration missing")?;
    assert_eq!(
        (
            config.fallback_language.to_string(),
            config.subcrates.clone(),
            config.gettext.is_none(),
            fluent.assets_dir.clone(),
            fluent.domain.clone(),
        ),
        (
            "en-US".to_owned(),
            vec![PathBuf::from("child")],
            true,
            PathBuf::from("locales/日本語"),
            Some("application".to_owned()),
        )
    );
    Ok(())
}

#[test]
fn absent_localization_configuration_remains_optional() -> Result<(), Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    fs::write(
        directory.path().join("Cargo.toml"),
        "[package]\nname = \"plain-app\"\nversion = \"0.1.0\"\n",
    )?;

    let parsed = Crate::from(directory.path(), /*parent*/ None, "i18n.toml")?;
    assert!(parsed.i18n_config.is_none());
    assert!(parsed.active_config()?.is_none());
    assert!(matches!(
        parsed.config_or_err(),
        Err(I18nConfigError::NoI18nConfig(_))
    ));
    Ok(())
}

#[test]
fn malformed_cargo_manifest_preserves_the_error_path() -> Result<(), Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("Cargo.toml");
    fs::write(&path, "[package]\nname = [\n")?;

    match Crate::from(directory.path(), /*parent*/ None, "i18n.toml") {
        Err(I18nConfigError::CannotDeserializeToml(actual_path, error)) => {
            assert_eq!(actual_path, path);
            assert!(!error.to_string().is_empty());
        }
        other => panic!("expected a Cargo TOML parsing failure, got {:?}", other),
    }
    Ok(())
}

#[test]
fn invalid_localization_configuration_preserves_the_error_path() -> Result<(), Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("i18n.toml");
    for invalid in [
        "fallback_language = \"en-US\"\nfallback_language = \"de-DE\"\n",
        "[fluent]\nassets_dir = \"locales\"\n",
        "fallback_language = \"en-US\"\nsubcrates = 7\n",
    ] {
        fs::write(&path, invalid)?;
        match I18nConfig::from_file(&path) {
            Err(I18nConfigError::CannotDeserializeToml(actual_path, error)) => {
                assert_eq!(actual_path, path);
                assert!(!error.to_string().is_empty());
            }
            other => panic!("expected an i18n TOML parsing failure, got {:?}", other),
        }
    }
    Ok(())
}
