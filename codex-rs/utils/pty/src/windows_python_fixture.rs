//! Native CPython selection for the Windows console-input fixture.
//!
//! A POSIX Python can start on Windows yet use a different stdin contract.
//! Probe the runtime and execute its resolved path instead of trusting an alias.

#[cfg(windows)]
const PROBE: &str = "import os,sys; sys.stdout.reconfigure(encoding='utf-8'); print(sys.implementation.name); print(sys.platform); print(os.name); print(sys.executable)";

#[cfg(windows)]
pub(super) fn find_native_python() -> anyhow::Result<String> {
    find_native_python_with_probe(|candidate| {
        let output = std::process::Command::new(candidate)
            .args(["-I", "-S", "-c", PROBE])
            .output()
            .map_err(|error| error.to_string())?;
        if !output.status.success() {
            return Err(format!(
                "status {}; stderr {:?}",
                output.status,
                String::from_utf8_lossy(&output.stderr)
            ));
        }
        String::from_utf8(output.stdout).map_err(|error| error.to_string())
    })
}

fn find_native_python_with_probe(
    mut probe: impl FnMut(&str) -> Result<String, String>,
) -> anyhow::Result<String> {
    let mut failures = Vec::new();
    for candidate in ["python.exe", "python3.exe"] {
        let result = probe(candidate)
            .map_err(anyhow::Error::msg)
            .and_then(|output| parse_native_python(&output));
        match result {
            Ok(executable) => return Ok(executable),
            Err(error) => failures.push(format!("{candidate}: {error}")),
        }
    }
    anyhow::bail!(
        "ConPTY foreground input requires native CPython (sys.platform=win32, os.name=nt): {}",
        failures.join("; ")
    )
}

fn parse_native_python(output: &str) -> anyhow::Result<String> {
    let lines: Vec<_> = output.lines().collect();
    let ["cpython", "win32", "nt", executable] = lines.as_slice() else {
        anyhow::bail!("unexpected interpreter identity: {output:?}");
    };
    let bytes = executable.as_bytes();
    let drive_absolute = bytes.len() >= 3
        && bytes[0].is_ascii_alphabetic()
        && bytes[1] == b':'
        && matches!(bytes[2], b'\\' | b'/');
    let unc_absolute = executable
        .strip_prefix("\\\\")
        .is_some_and(|tail| tail.split('\\').filter(|part| !part.is_empty()).count() >= 2);
    anyhow::ensure!(
        !executable.contains('\0') && (drive_absolute || unc_absolute),
        "probe did not resolve an absolute Windows executable: {executable:?}"
    );
    Ok((*executable).to_owned())
}

#[cfg(test)]
#[path = "windows_python_fixture_tests.rs"]
mod tests;
