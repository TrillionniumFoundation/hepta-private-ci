use codex_utils_cargo_bin::CargoBinError;
use codex_utils_cargo_bin::cargo_bin;
use pretty_assertions::assert_eq;
use std::process::Command;

const CASE: &str = "CODEX_CARGO_BIN_LOOKUP_RESULT_PROBE";
const NAME: &str = "codex-optional-lookup-probe";
const KEY: &str = "CARGO_BIN_EXE_codex-optional-lookup-probe";
const UNDERSCORE_KEY: &str = "CARGO_BIN_EXE_codex_optional_lookup_probe";

#[test]
fn lookup_reports_missing_metadata_and_preserves_explicit_paths() {
    if let Ok(case) = std::env::var(CASE) {
        match case.as_str() {
            "missing" => assert!(matches!(
                cargo_bin(NAME),
                Err(CargoBinError::NotFound { .. })
            )),
            "present" => {
                let expected = std::path::PathBuf::from(std::env::var_os(UNDERSCORE_KEY).unwrap());
                assert_eq!(cargo_bin(NAME).unwrap(), expected);
            }
            "invalid" => assert!(matches!(
                cargo_bin(NAME),
                Err(CargoBinError::ResolvedPathDoesNotExist { .. })
            )),
            _ => panic!("unknown lookup probe"),
        }
        return;
    }

    let present = tempfile::NamedTempFile::new().unwrap();
    let absent = tempfile::tempdir().unwrap();
    let missing_path = absent.path().join("missing-program");
    let current = std::env::current_exe().unwrap();
    for case in ["present", "missing", "invalid"] {
        let mut child = Command::new(&current);
        child
            .args([
                "--exact",
                "lookup_reports_missing_metadata_and_preserves_explicit_paths",
                "--nocapture",
            ])
            .env(CASE, case)
            .env_remove(KEY)
            .env_remove(UNDERSCORE_KEY)
            .env_remove("RUNFILES_MANIFEST_ONLY");
        match case {
            "present" => {
                child.env(UNDERSCORE_KEY, present.path());
            }
            "invalid" => {
                child.env(KEY, &missing_path);
            }
            "missing" => {}
            _ => unreachable!(),
        }
        let output = child.output().unwrap();
        assert!(
            output.status.success(),
            "{case} probe failed: {}{}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
    }
}
