use codex_utils_cargo_bin::CargoBinError;
use codex_utils_cargo_bin::cargo_bin;
use std::env;
use std::error::Error;
use std::fs;
use std::io;
use std::path::PathBuf;
use std::process::Command;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

const SCENARIO_ENV: &str = "CODEX_CARGO_BIN_LOOKUP_SCENARIO";
const BINARY_NAME: &str = "codex-cargo-bin-fixture";
const PRIMARY_ENV: &str = "CARGO_BIN_EXE_codex-cargo-bin-fixture";
const UNDERSCORE_ENV: &str = "CARGO_BIN_EXE_codex_cargo_bin_fixture";
const ABSENT_BINARY_NAME: &str = "codex-cargo-bin-absent-fixture";

#[test]
fn cargo_bin_preserves_optional_bazel_lookup() -> Result<(), Box<dyn Error>> {
    if let Some(scenario) = env::var_os(SCENARIO_ENV) {
        let scenario = scenario
            .into_string()
            .map_err(|_| io::Error::other("lookup scenario is not Unicode"))?;
        let name = if scenario == "bazel-absent" {
            ABSENT_BINARY_NAME
        } else {
            BINARY_NAME
        };
        let result = cargo_bin(name);
        match scenario.as_str() {
            "bazel-absent" | "bazel-undeclared-sibling" => {
                let expected_keys = if name == ABSENT_BINARY_NAME {
                    vec![
                        "CARGO_BIN_EXE_codex-cargo-bin-absent-fixture".to_owned(),
                        "CARGO_BIN_EXE_codex_cargo_bin_absent_fixture".to_owned(),
                    ]
                } else {
                    vec![PRIMARY_ENV.to_owned(), UNDERSCORE_ENV.to_owned()]
                };
                assert!(
                    matches!(
                        &result,
                        Err(CargoBinError::NotFound { name: actual_name, env_keys, .. })
                            if actual_name == name && env_keys == &expected_keys
                    ),
                    "missing manifest-only binary must return NotFound: {result:?}"
                );
            }
            "declared-primary" | "declared-underscore" | "cargo-legacy" => {
                let path = result?;
                let expected = if scenario == "cargo-legacy" {
                    env::current_dir()?.join(format!("{BINARY_NAME}{}", env::consts::EXE_SUFFIX))
                } else {
                    env::current_dir()?.join("fixture.bin")
                };
                assert!(
                    path.is_absolute(),
                    "lookup returned a relative path: {path:?}"
                );
                assert!(
                    fs::canonicalize(&path)? == fs::canonicalize(&expected)?,
                    "lookup resolved {path:?} instead of {expected:?}"
                );
            }
            "invalid-primary" => {
                let expected_path =
                    env::var_os(PRIMARY_ENV).map(PathBuf::from).ok_or_else(|| {
                        io::Error::other("invalid primary fixture was not configured")
                    })?;
                assert!(
                    matches!(
                        &result,
                        Err(CargoBinError::ResolvedPathDoesNotExist { key, path })
                            if key == PRIMARY_ENV && path == &expected_path
                    ),
                    "invalid primary must remain an error despite a valid underscore entry: {result:?}"
                );
            }
            other => {
                return Err(io::Error::other(format!("unknown lookup scenario: {other}")).into());
            }
        }
        return Ok(());
    }

    // The crate disables library tests. This integration test re-enters the
    // same real test executable so each lookup owns its process environment.
    let timestamp = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let directory = env::temp_dir().join(format!(
        "codex-cargo-bin-lookup-{}-{timestamp}",
        std::process::id()
    ));
    fs::create_dir(&directory)?;
    let result = (|| -> Result<(), Box<dyn Error>> {
        let directory = fs::canonicalize(&directory)?;
        fs::write(directory.join("fixture.bin"), b"lookup fixture\n")?;
        fs::write(
            directory.join(format!("{BINARY_NAME}{}", env::consts::EXE_SUFFIX)),
            b"legacy lookup fixture\n",
        )?;
        let manifest = directory.join("MANIFEST");
        fs::write(&manifest, "_main/cargo-bin-fixture fixture.bin\n")?;
        fs::create_dir(directory.join("deps"))?;
        let child_exe = directory
            .join("deps")
            .join(format!("lookup-probe{}", env::consts::EXE_SUFFIX));
        fs::copy(env::current_exe()?, &child_exe)?;

        // The pinned runfiles macro needs Bazel's compile-time repository
        // identity. Cargo uses absolute env paths; Bazel exercises the actual
        // manifest-relative resolution. Every scenario runs in either backend.
        let manifest_resolution = option_env!("REPOSITORY_NAME").is_some();
        let valid_value = if manifest_resolution {
            PathBuf::from("_main/cargo-bin-fixture")
        } else {
            directory.join("fixture.bin")
        };
        let invalid_value = if manifest_resolution {
            PathBuf::from("_main/missing-fixture")
        } else {
            directory.join("missing-fixture")
        };

        for scenario in [
            "bazel-absent",
            "bazel-undeclared-sibling",
            "declared-primary",
            "declared-underscore",
            "invalid-primary",
            "cargo-legacy",
        ] {
            let mut command = Command::new(&child_exe);
            command
                .args([
                    "--exact",
                    "cargo_bin_preserves_optional_bazel_lookup",
                    "--nocapture",
                    "--test-threads=1",
                ])
                .current_dir(&directory);
            for (key, _) in env::vars_os() {
                let Some(name) = key.to_str() else {
                    continue;
                };
                if name.starts_with("CARGO_BIN_EXE_")
                    || (name.starts_with("CARGO_TARGET_") && name.ends_with("_RUNNER"))
                    || matches!(
                        name,
                        "RUNFILES_MANIFEST_ONLY"
                            | "RUNFILES_MANIFEST_FILE"
                            | "RUNFILES_DIR"
                            | "TEST_SRCDIR"
                    )
                {
                    command.env_remove(key);
                }
            }
            command.env(SCENARIO_ENV, scenario);
            match scenario {
                "bazel-absent" | "bazel-undeclared-sibling" => {
                    // Missing binary env must be decided before loading a
                    // manifest or probing an undeclared Cargo sibling.
                    command
                        .env("RUNFILES_MANIFEST_ONLY", "1")
                        .env("RUNFILES_MANIFEST_FILE", directory.join("absent-manifest"));
                }
                "declared-primary" | "declared-underscore" | "invalid-primary" => {
                    if manifest_resolution {
                        command
                            .env("RUNFILES_MANIFEST_ONLY", "1")
                            .env("RUNFILES_MANIFEST_FILE", &manifest);
                    }
                    match scenario {
                        "declared-primary" => {
                            command.env(PRIMARY_ENV, &valid_value);
                        }
                        "declared-underscore" => {
                            command.env(UNDERSCORE_ENV, &valid_value);
                        }
                        "invalid-primary" => {
                            command
                                .env(PRIMARY_ENV, &invalid_value)
                                .env(UNDERSCORE_ENV, &valid_value);
                        }
                        _ => {
                            return Err(
                                io::Error::other("unexpected declared lookup scenario").into()
                            );
                        }
                    }
                }
                "cargo-legacy" => {}
                _ => return Err(io::Error::other("unexpected lookup scenario").into()),
            }
            let output = command.output()?;
            if !output.status.success() {
                return Err(io::Error::other(format!(
                    "lookup scenario {scenario} failed with {}:\nstdout:\n{}\nstderr:\n{}",
                    output.status,
                    String::from_utf8_lossy(&output.stdout),
                    String::from_utf8_lossy(&output.stderr)
                ))
                .into());
            }
            println!(
                "lookup scenario {scenario} passed; declared_manifest_resolution={manifest_resolution}"
            );
        }
        Ok(())
    })();
    let cleanup = fs::remove_dir_all(&directory);
    result?;
    cleanup?;
    Ok(())
}
