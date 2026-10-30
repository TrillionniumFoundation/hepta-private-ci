use codex_utils_cargo_bin::cargo_bin;
use codex_utils_cargo_bin::find_resource;
use codex_utils_cargo_bin::runfiles_available;
use pretty_assertions::assert_eq;
use std::fs;
use std::process::Command;

const CASE_ENV: &str = "CODEX_WINDOWS_SANDBOX_TEST_BUNDLE_CASE";
const STARTED_FILE: &str = "test-started.txt";

/// Re-execute one real test beside copies of both production helper binaries.
///
/// The parent owns the bundle until the exact child test has exited. Copies are
/// independent files because setup may adjust helper ACLs. Neither the parent
/// environment nor the production helper resolver is changed.
pub(super) fn run_in_helper_bundle(test_name: &str) -> bool {
    if let Some(expected_case) = std::env::var_os(CASE_ENV) {
        assert_eq!(expected_case.as_os_str(), std::ffi::OsStr::new(test_name));
        let executable = std::env::current_exe()
            .unwrap_or_else(|error| panic!("locate bundled test executable: {error}"));
        let directory = executable
            .parent()
            .unwrap_or_else(|| panic!("bundled test executable has no parent: {executable:?}"));
        for name in ["codex-windows-sandbox-setup.exe", "codex-command-runner.exe"] {
            assert!(directory.join(name).is_file(), "missing bundled helper {name}");
        }
        fs::write(directory.join(STARTED_FILE), test_name)
            .unwrap_or_else(|error| panic!("record exact bundled test admission: {error}"));
        return false;
    }

    let bundle = tempfile::tempdir()
        .unwrap_or_else(|error| panic!("create owned Windows sandbox helper bundle: {error}"));
    let source = std::env::current_exe()
        .unwrap_or_else(|error| panic!("locate original test executable: {error}"));
    let child = bundle.path().join("windows-sandbox-unit-test.exe");
    fs::copy(&source, &child)
        .unwrap_or_else(|error| panic!("copy test executable {source:?} to {child:?}: {error}"));
    for name in ["codex-windows-sandbox-setup", "codex-command-runner"] {
        let file_name = format!("{name}.exe");
        let source = if runfiles_available() {
            // Both labels are declared in this crate's test_data_extra. Unit
            // tests do not receive integration tests' CARGO_BIN_EXE variables.
            find_resource!(&file_name)
                .unwrap_or_else(|error| panic!("resolve declared helper runfile {name}: {error}"))
        } else {
            cargo_bin(name)
                .unwrap_or_else(|error| panic!("resolve built Cargo helper {name}: {error}"))
        };
        let destination = bundle.path().join(file_name);
        fs::copy(&source, &destination).unwrap_or_else(|error| {
            panic!("copy helper {source:?} to independent file {destination:?}: {error}")
        });
    }

    let output = Command::new(&child)
        .args(["--exact", test_name, "--nocapture", "--color", "never", "--test-threads=1"])
        .env(CASE_ENV, test_name)
        .output()
        .unwrap_or_else(|error| panic!("execute bundled test {test_name}: {error}"));
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    eprintln!("bundled test {test_name}\nstdout:\n{stdout}\nstderr:\n{stderr}");
    assert!(
        output.status.success(),
        "bundled test {test_name} failed with {}\nstdout:\n{stdout}\nstderr:\n{stderr}",
        output.status,
    );
    let started = fs::read_to_string(bundle.path().join(STARTED_FILE))
        .unwrap_or_else(|error| panic!("read exact bundled test admission: {error}"));
    assert_eq!(started, test_name);
    assert_eq!(
        stdout.lines().filter(|line| line.starts_with("test result: ok. 1 passed; 0 failed; 0 ignored;")).count(),
        1,
        "the exact bundled test must execute once without a skip; stdout={stdout:?}",
    );
    // output() has waited for the actual child. Keep the independently copied
    // helpers alive through that wait and through validation of its test result.
    true
}
