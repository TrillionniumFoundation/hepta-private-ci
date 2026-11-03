use super::*;
use pretty_assertions::assert_eq;
use std::error::Error;
use std::fs;
use tempfile::tempdir;

#[test]
fn reads_age_fluent_profile() -> Result<(), Box<dyn Error>> {
    let directory = tempdir()?;
    let path = directory.path().join("i18n.toml");
    // The profile shipped in age 0.11.5, the transitive consumer of this crate.
    fs::write(
        &path,
        "fallback_language = \"en-US\"\n\n[fluent]\nassets_dir = \"i18n\"\n",
    )?;

    let config = I18nConfig::from_file(&path)?;
    let fluent = config.fluent.ok_or("missing fluent config")?;
    assert_eq!(
        (
            config.fallback_language.to_string(),
            config.subcrates,
            config.gettext.is_none(),
            fluent.assets_dir,
            fluent.domain
        ),
        (
            "en-US".to_owned(),
            Vec::<PathBuf>::new(),
            true,
            PathBuf::from("i18n"),
            None
        ),
    );
    Ok(())
}

#[test]
fn reads_cargo_manifest_and_its_localization_profile() -> Result<(), Box<dyn Error>> {
    let directory = tempdir()?;
    fs::write(directory.path().join("Cargo.toml"), "[package]\nname = \"localized-crate\"\nversion = \"1.2.3\"\nedition = \"2021\"\n[dependencies]\nserde = \"1\"\n")?;
    fs::write(directory.path().join("custom.toml"), "fallback_language = \"de-DE\"\n[fluent]\nassets_dir = \"locales\"\ndomain = \"custom-domain\"\n")?;

    let crt = Crate::from(directory.path(), /*parent*/ None, "custom.toml")?;
    let config = crt.config_or_err()?;
    let fluent = config.fluent.as_ref().ok_or("missing fluent config")?;
    assert_eq!(
        (
            &crt.name,
            &crt.version,
            &crt.path,
            &crt.config_file_path,
            crt.parent.is_none(),
            crt.module_name(),
            config.fallback_language.to_string(),
            &fluent.assets_dir,
            fluent.domain.as_deref()
        ),
        (
            &"localized-crate".to_owned(),
            &"1.2.3".to_owned(),
            &directory.path().to_path_buf(),
            &PathBuf::from("custom.toml"),
            true,
            "localized_crate".to_owned(),
            "de-DE".to_owned(),
            &PathBuf::from("locales"),
            Some("custom-domain")
        ),
    );
    Ok(())
}

#[test]
fn preserves_gettext_defaults_and_overridden_paths() -> Result<(), Box<dyn Error>> {
    let directory = tempdir()?;
    let path = directory.path().join("i18n.toml");
    let required = "fallback_language = \"en\"\nsubcrates = [\"child\"]\n[gettext]\ntarget_languages = [\"fr\", \"de\"]\noutput_dir = \"translations\"\n";
    fs::write(&path, required)?;
    let config = I18nConfig::from_file(&path)?;
    assert_eq!(config.subcrates, vec![PathBuf::from("child")]);
    let gettext = config.gettext.ok_or("missing gettext config")?;
    assert_eq!(
        (
            gettext.target_languages.as_slice(),
            gettext.pot_dir(),
            gettext.po_dir(),
            gettext.mo_dir(),
            gettext.extract_to_parent,
            gettext.collate_extracted_subcrates,
            gettext.use_fuzzy,
            gettext.add_location.to_str(),
            gettext.copyright_holder,
            gettext.msgid_bugs_address,
            gettext.xtr
        ),
        (
            ["fr".to_owned(), "de".to_owned()].as_slice(),
            PathBuf::from("translations/pot"),
            PathBuf::from("translations/po"),
            PathBuf::from("translations/mo"),
            false,
            false,
            false,
            "full",
            None,
            None,
            None
        ),
    );

    fs::write(&path, format!("{required}pot_dir = \"pot-custom\"\npo_dir = \"po-custom\"\nmo_dir = \"mo-custom\"\nextract_to_parent = true\ncollate_extracted_subcrates = true\nuse_fuzzy = true\nadd_location = \"never\"\ncopyright_holder = \"Owner\"\nmsgid_bugs_address = \"bugs@example.invalid\"\nxtr = false\n"))?;
    let gettext = I18nConfig::from_file(&path)?
        .gettext
        .ok_or("missing gettext config")?;
    assert_eq!(
        (
            gettext.pot_dir(),
            gettext.po_dir(),
            gettext.mo_dir(),
            gettext.extract_to_parent,
            gettext.collate_extracted_subcrates,
            gettext.use_fuzzy,
            gettext.add_location.to_str(),
            gettext.copyright_holder,
            gettext.msgid_bugs_address,
            gettext.xtr
        ),
        (
            PathBuf::from("pot-custom"),
            PathBuf::from("po-custom"),
            PathBuf::from("mo-custom"),
            true,
            true,
            true,
            "never",
            Some("Owner".to_owned()),
            Some("bugs@example.invalid".to_owned()),
            Some(false)
        ),
    );
    Ok(())
}

#[test]
fn preserves_parent_config_selection() -> Result<(), Box<dyn Error>> {
    let directory = tempdir()?;
    let child_path = directory.path().join("child");
    fs::create_dir(&child_path)?;
    fs::write(
        directory.path().join("Cargo.toml"),
        "[package]\nname = \"parent\"\nversion = \"1.0.0\"\n",
    )?;
    fs::write(directory.path().join("i18n.toml"), "fallback_language = \"en-US\"\nsubcrates = [\"child\"]\n[gettext]\ntarget_languages = [\"fr\"]\noutput_dir = \"translations\"\ncollate_extracted_subcrates = true\n")?;
    fs::write(
        child_path.join("Cargo.toml"),
        "[package]\nname = \"child\"\nversion = \"2.0.0\"\n",
    )?;
    fs::write(child_path.join("i18n.toml"), "fallback_language = \"de\"\n[gettext]\ntarget_languages = [\"de\"]\noutput_dir = \"local\"\nextract_to_parent = true\n")?;
    let parent = Crate::from(directory.path(), /*parent*/ None, "i18n.toml")?;
    let child = Crate::from(child_path, Some(&parent), "i18n.toml")?;
    let (active_crate, active_config) = child.active_config()?.ok_or("missing active config")?;
    assert_eq!(
        (
            &active_crate.name,
            active_config.fallback_language.to_string(),
            child.collated_subcrate()
        ),
        (&"parent".to_owned(), "en-US".to_owned(), true),
    );
    Ok(())
}

#[test]
fn rejects_invalid_profiles_with_the_original_file_path() -> Result<(), Box<dyn Error>> {
    let directory = tempdir()?;
    let path = directory.path().join("invalid.toml");
    for source in [
        "fallback_language = [",
        "fallback_language = \"en\"\nfallback_language = \"de\"\n",
        "[fluent]\nassets_dir = \"i18n\"\n",
        "fallback_language = 42\n",
    ] {
        fs::write(&path, source)?;
        match I18nConfig::from_file(&path) {
            Err(I18nConfigError::CannotDeserializeToml(actual_path, error)) => {
                assert_eq!(actual_path, path);
                assert!(!error.to_string().is_empty());
            }
            result => panic!("expected path-carrying parse error, got {:?}", result),
        }
    }
    Ok(())
}

#[test]
fn rejects_invalid_cargo_manifests_with_the_manifest_path() -> Result<(), Box<dyn Error>> {
    let directory = tempdir()?;
    let path = directory.path().join("Cargo.toml");
    for source in ["[package", "[package]\nname = \"missing-version\"\n"] {
        fs::write(&path, source)?;
        match Crate::from(directory.path(), /*parent*/ None, "i18n.toml") {
            Err(I18nConfigError::CannotDeserializeToml(actual_path, error)) => {
                assert_eq!(actual_path, path);
                assert!(!error.to_string().is_empty());
            }
            result => panic!("expected path-carrying parse error, got {:?}", result),
        }
    }
    Ok(())
}
