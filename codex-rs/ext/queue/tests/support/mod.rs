use std::path::Path;
use std::process::Command;
use std::sync::OnceLock;

/// Require a real Python 3 interpreter, then quote both paths for the hook's
/// native shell. Missing fixture prerequisites must fail before queue admission.
pub fn python_hook_command(script: &Path) -> String {
    static PYTHON: OnceLock<String> = OnceLock::new();
    let python = PYTHON.get_or_init(|| {
        let candidates = if cfg!(windows) {
            ["python", "python3"]
        } else {
            ["python3", "python"]
        };
        let mut errors = Vec::new();
        for candidate in candidates {
            let output = Command::new(candidate)
                .args([
                    "-c",
                    "import sys; assert sys.version_info.major == 3; sys.stdout.buffer.write(sys.executable.encode('utf-8'))",
                ])
                .output();
            match output {
                Ok(output) if output.status.success() => {
                    let executable = String::from_utf8(output.stdout)
                        .expect("Python fixture executable must be UTF-8");
                    assert!(
                        Path::new(&executable).is_absolute(),
                        "Python fixture must resolve to an absolute executable"
                    );
                    return executable;
                }
                Ok(output) => errors.push(format!(
                    "{candidate}: {}: {}",
                    output.status,
                    String::from_utf8_lossy(&output.stderr)
                )),
                Err(error) => errors.push(format!("{candidate}: {error}")),
            }
        }
        panic!("queue hook fixtures require Python 3: {}", errors.join("; "));
    });
    let script = script.to_str().expect("hook fixture path must be UTF-8");
    #[cfg(windows)]
    {
        // cmd.exe handles these separately quoted arguments inside the hook
        // runner's outer /C quotation. Windows file names cannot contain '"'.
        format!(r#""{python}" "{script}""#)
    }
    #[cfg(not(windows))]
    {
        let python = python.replace('\'', "'\\''");
        let script = script.replace('\'', "'\\''");
        format!("'{python}' '{script}'")
    }
}
