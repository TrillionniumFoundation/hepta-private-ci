use codex_utils_absolute_path::AbsolutePathBuf;
use dirs::home_dir;
use std::path::PathBuf;
use std::sync::OnceLock;

static PROCESS_CODEX_HOME_OVERRIDE: OnceLock<AbsolutePathBuf> = OnceLock::new();

/// Returns the path to the Codex configuration directory, which can be
/// specified by the `CODEX_HOME` environment variable. If not set, defaults to
/// `~/.codex`.
///
/// - If `CODEX_HOME` is set, the value must exist and be a directory. The
///   value will be canonicalized and this function will Err otherwise.
/// - If `CODEX_HOME` is not set, this function does not verify that the
///   directory exists.
pub fn find_codex_home() -> std::io::Result<AbsolutePathBuf> {
    if let Some(codex_home) = PROCESS_CODEX_HOME_OVERRIDE.get() {
        return Ok(codex_home.clone());
    }
    let codex_home_env = std::env::var("CODEX_HOME")
        .ok()
        .filter(|val| !val.is_empty());
    find_codex_home_from_env(codex_home_env.as_deref())
}

/// Resolve the Hepta product home without changing the process environment.
///
/// `HEPTA_HOME` takes precedence over the legacy `CODEX_HOME` compatibility
/// fallback. If neither is set, Hepta uses `~/.hepta`.
pub fn find_hepta_home() -> std::io::Result<AbsolutePathBuf> {
    let hepta_home_env = non_empty_env("HEPTA_HOME")?;
    let legacy_codex_home_env = non_empty_env("CODEX_HOME")?;
    find_hepta_home_from_env(
        hepta_home_env.as_deref(),
        legacy_codex_home_env.as_deref(),
        home_dir().as_deref(),
    )
}

/// Install a process-scoped home override before any Codex runtime threads are
/// started. This lets product entry points share the Codex config loader
/// without mutating environment variables.
pub fn set_process_codex_home_override(codex_home: AbsolutePathBuf) -> std::io::Result<()> {
    if let Some(existing) = PROCESS_CODEX_HOME_OVERRIDE.get() {
        return if existing == &codex_home {
            Ok(())
        } else {
            Err(std::io::Error::new(
                std::io::ErrorKind::AlreadyExists,
                format!(
                    "process Codex home is already bound to {}, cannot rebind it to {}",
                    existing.as_path().display(),
                    codex_home.as_path().display()
                ),
            ))
        };
    }
    PROCESS_CODEX_HOME_OVERRIDE.set(codex_home).map_err(|_| {
        std::io::Error::new(
            std::io::ErrorKind::AlreadyExists,
            "process Codex home was initialized concurrently",
        )
    })
}

fn non_empty_env(name: &str) -> std::io::Result<Option<String>> {
    parse_env_value(name, std::env::var_os(name))
}

fn parse_env_value(
    name: &str,
    value: Option<std::ffi::OsString>,
) -> std::io::Result<Option<String>> {
    let Some(value) = value else {
        return Ok(None);
    };
    if value.is_empty() {
        return Ok(None);
    }
    value.into_string().map(Some).map_err(|_| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            format!("{name} contains non-UTF-8 data"),
        )
    })
}

fn find_hepta_home_from_env(
    hepta_home_env: Option<&str>,
    legacy_codex_home_env: Option<&str>,
    user_home: Option<&std::path::Path>,
) -> std::io::Result<AbsolutePathBuf> {
    if let Some(value) = hepta_home_env {
        return resolve_home_env("HEPTA_HOME", value);
    }
    if let Some(value) = legacy_codex_home_env {
        return resolve_home_env("CODEX_HOME", value);
    }
    let mut product_home = user_home.map(std::path::Path::to_path_buf).ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::NotFound,
            "Could not find home directory",
        )
    })?;
    product_home.push(".hepta");
    AbsolutePathBuf::from_absolute_path(product_home)
}

fn find_codex_home_from_env(codex_home_env: Option<&str>) -> std::io::Result<AbsolutePathBuf> {
    // Honor the `CODEX_HOME` environment variable when it is set to allow users
    // (and tests) to override the default location.
    match codex_home_env {
        Some(val) => resolve_home_env("CODEX_HOME", val),
        None => {
            let mut p = home_dir().ok_or_else(|| {
                std::io::Error::new(
                    std::io::ErrorKind::NotFound,
                    "Could not find home directory",
                )
            })?;
            p.push(".codex");
            AbsolutePathBuf::from_absolute_path(p)
        }
    }
}

fn resolve_home_env(env_name: &str, value: &str) -> std::io::Result<AbsolutePathBuf> {
    let path = PathBuf::from(value);
    let metadata = std::fs::metadata(&path).map_err(|err| match err.kind() {
        std::io::ErrorKind::NotFound => std::io::Error::new(
            std::io::ErrorKind::NotFound,
            format!("{env_name} points to {value:?}, but that path does not exist"),
        ),
        _ => std::io::Error::new(
            err.kind(),
            format!("failed to read {env_name} {value:?}: {err}"),
        ),
    })?;

    if !metadata.is_dir() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            format!("{env_name} points to {value:?}, but that path is not a directory"),
        ));
    }
    let canonical = path.canonicalize().map_err(|err| {
        std::io::Error::new(
            err.kind(),
            format!("failed to canonicalize {env_name} {value:?}: {err}"),
        )
    })?;
    AbsolutePathBuf::from_absolute_path(canonical)
}

#[cfg(test)]
mod tests {
    use super::find_codex_home_from_env;
    use super::find_hepta_home_from_env;
    #[cfg(unix)]
    use super::parse_env_value;
    use codex_utils_absolute_path::AbsolutePathBuf;
    use dirs::home_dir;
    use pretty_assertions::assert_eq;
    use std::fs;
    use std::io::ErrorKind;
    use tempfile::TempDir;

    #[test]
    fn find_codex_home_env_missing_path_is_fatal() {
        let temp_home = TempDir::new().expect("temp home");
        let missing = temp_home.path().join("missing-codex-home");
        let missing_str = missing
            .to_str()
            .expect("missing codex home path should be valid utf-8");

        let err = find_codex_home_from_env(Some(missing_str)).expect_err("missing CODEX_HOME");
        assert_eq!(err.kind(), ErrorKind::NotFound);
        assert!(
            err.to_string().contains("CODEX_HOME"),
            "unexpected error: {err}"
        );
    }

    #[test]
    fn find_codex_home_env_file_path_is_fatal() {
        let temp_home = TempDir::new().expect("temp home");
        let file_path = temp_home.path().join("codex-home.txt");
        fs::write(&file_path, "not a directory").expect("write temp file");
        let file_str = file_path
            .to_str()
            .expect("file codex home path should be valid utf-8");

        let err = find_codex_home_from_env(Some(file_str)).expect_err("file CODEX_HOME");
        assert_eq!(err.kind(), ErrorKind::InvalidInput);
        assert!(
            err.to_string().contains("not a directory"),
            "unexpected error: {err}"
        );
    }

    #[test]
    fn find_codex_home_env_valid_directory_canonicalizes() {
        let temp_home = TempDir::new().expect("temp home");
        let temp_str = temp_home
            .path()
            .to_str()
            .expect("temp codex home path should be valid utf-8");

        let resolved = find_codex_home_from_env(Some(temp_str)).expect("valid CODEX_HOME");
        let expected = temp_home
            .path()
            .canonicalize()
            .expect("canonicalize temp home");
        let expected = AbsolutePathBuf::from_absolute_path(expected).expect("absolute home");
        assert_eq!(resolved, expected);
    }

    #[test]
    fn find_codex_home_without_env_uses_default_home_dir() {
        let resolved =
            find_codex_home_from_env(/*codex_home_env*/ None).expect("default CODEX_HOME");
        let mut expected = home_dir().expect("home dir");
        expected.push(".codex");
        let expected = AbsolutePathBuf::from_absolute_path(expected).expect("absolute home");
        assert_eq!(resolved, expected);
    }

    #[test]
    fn hepta_home_precedence_is_hepta_then_legacy_codex() {
        let hepta_home = TempDir::new().expect("temp Hepta home");
        let codex_home = TempDir::new().expect("temp Codex home");
        let user_home = TempDir::new().expect("temp user home");
        let resolved = find_hepta_home_from_env(
            hepta_home.path().to_str(),
            codex_home.path().to_str(),
            Some(user_home.path()),
        )
        .expect("resolve Hepta home");
        assert_eq!(
            resolved.as_path(),
            hepta_home.path().canonicalize().expect("canonicalize")
        );
    }

    #[test]
    fn hepta_home_uses_legacy_codex_home_as_compatibility_fallback() {
        let codex_home = TempDir::new().expect("temp Codex home");
        let user_home = TempDir::new().expect("temp user home");
        let resolved =
            find_hepta_home_from_env(None, codex_home.path().to_str(), Some(user_home.path()))
                .expect("resolve legacy home");
        assert_eq!(
            resolved.as_path(),
            codex_home.path().canonicalize().expect("canonicalize")
        );
    }

    #[test]
    fn hepta_home_defaults_to_dot_hepta_without_creating_it() {
        let user_home = TempDir::new().expect("temp user home");
        let resolved = find_hepta_home_from_env(None, None, Some(user_home.path()))
            .expect("resolve default Hepta home");
        let expected = user_home.path().join(".hepta");
        assert_eq!(resolved.as_path(), expected);
        assert!(!expected.exists());
    }

    #[test]
    fn invalid_explicit_hepta_home_is_fatal() {
        let user_home = TempDir::new().expect("temp user home");
        let missing = user_home.path().join("missing");
        let error = find_hepta_home_from_env(missing.to_str(), None, Some(user_home.path()))
            .expect_err("invalid HEPTA_HOME must fail");
        assert_eq!(error.kind(), ErrorKind::NotFound);
        assert!(error.to_string().contains("HEPTA_HOME"));
    }

    #[cfg(unix)]
    #[test]
    fn non_utf8_hepta_home_is_not_silently_treated_as_unset() {
        use std::os::unix::ffi::OsStringExt;

        let error = parse_env_value("HEPTA_HOME", Some(std::ffi::OsString::from_vec(vec![0xff])))
            .expect_err("non-UTF-8 product home must fail");
        assert_eq!(error.kind(), ErrorKind::InvalidData);
        assert!(error.to_string().contains("HEPTA_HOME"));
    }
}
