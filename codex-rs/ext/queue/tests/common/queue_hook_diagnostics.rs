//! Test-owned observations for the original queue Python hook commands.

use std::fs;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;

use serde_json::Value;
use serde_json::json;

const PYTHON_IDENTITY: &str = r#"import hashlib as _hepta_hashlib
import json as _hepta_json
import os as _hepta_os
from pathlib import Path as _HeptaPath
import sys as _hepta_sys

_hepta_identity = {
    "schema": "queue-hook-interpreter-v1",
    "executable": _hepta_sys.executable,
    "version": _hepta_sys.version,
    "argv": _hepta_sys.argv,
    "pid": _hepta_os.getpid(),
    "script_sha256": _hepta_hashlib.sha256(_HeptaPath(__file__).read_bytes()).hexdigest(),
}
try:
    _hepta_digest = _hepta_hashlib.sha256()
    with open(_hepta_sys.executable, "rb") as _hepta_binary:
        for _hepta_chunk in iter(lambda: _hepta_binary.read(65536), b""):
            _hepta_digest.update(_hepta_chunk)
    _hepta_identity["executable_sha256"] = _hepta_digest.hexdigest()
except OSError as _hepta_error:
    _hepta_identity["executable_hash_error"] = str(_hepta_error)
_HeptaPath(_hepta_os.environ["HEPTA_QUEUE_HOOK_RUN"]).joinpath("interpreter.json").write_text(
    _hepta_json.dumps(_hepta_identity, sort_keys=True) + "\n", encoding="utf-8"
)

"#;

const UNIX_LAUNCHER: &str = r#"#!/bin/sh
HEPTA_QUEUE_HOOK_RUN=$(mktemp -d @ROOT@/run-XXXXXX) || exit 125
export HEPTA_QUEUE_HOOK_RUN
printf 'started\n' > "$HEPTA_QUEUE_HOOK_RUN/started.txt" || exit 125
command -v python3 > "$HEPTA_QUEUE_HOOK_RUN/resolver.stdout" 2> "$HEPTA_QUEUE_HOOK_RUN/resolver.stderr"
printf '%s\n' "$?" > "$HEPTA_QUEUE_HOOK_RUN/resolver-exit-code.txt" || exit 125
@COMMAND@ > "$HEPTA_QUEUE_HOOK_RUN/stdout.bin" 2> "$HEPTA_QUEUE_HOOK_RUN/stderr.bin"
HEPTA_QUEUE_HOOK_EXIT=$?
printf '%s\n' "$HEPTA_QUEUE_HOOK_EXIT" > "$HEPTA_QUEUE_HOOK_RUN/exit-code.txt" || exit 125
cat "$HEPTA_QUEUE_HOOK_RUN/stdout.bin" || exit 125
cat "$HEPTA_QUEUE_HOOK_RUN/stderr.bin" >&2 || exit 125
exit "$HEPTA_QUEUE_HOOK_EXIT"
"#;

const WINDOWS_LAUNCHER: &str = r#"@echo off
setlocal DisableDelayedExpansion
set "HEPTA_QUEUE_HOOK_RUN=@ROOT@\run-%RANDOM%-%RANDOM%"
mkdir "%HEPTA_QUEUE_HOOK_RUN%"
if errorlevel 1 exit /b 125
> "%HEPTA_QUEUE_HOOK_RUN%\started.txt" echo started
where python3 > "%HEPTA_QUEUE_HOOK_RUN%\resolver.stdout" 2> "%HEPTA_QUEUE_HOOK_RUN%\resolver.stderr"
> "%HEPTA_QUEUE_HOOK_RUN%\resolver-exit-code.txt" echo %ERRORLEVEL%
@COMMAND@ > "%HEPTA_QUEUE_HOOK_RUN%\stdout.bin" 2> "%HEPTA_QUEUE_HOOK_RUN%\stderr.bin"
set "HEPTA_QUEUE_HOOK_EXIT=%ERRORLEVEL%"
> "%HEPTA_QUEUE_HOOK_RUN%\exit-code.txt" echo %HEPTA_QUEUE_HOOK_EXIT%
type "%HEPTA_QUEUE_HOOK_RUN%\stdout.bin"
type "%HEPTA_QUEUE_HOOK_RUN%\stderr.bin" 1>&2
exit /b %HEPTA_QUEUE_HOOK_EXIT%
"#;

fn shell_quote(path: &Path) -> String {
    format!("'{}'", path.display().to_string().replace('\'', "'\"'\"'"))
}

pub fn write_hook(home: &Path, script_path: &Path, script: &str) -> String {
    let parent = std::env::var_os("HEPTA_QUEUE_HOOK_DIAGNOSTICS_DIR")
        .or_else(|| std::env::var_os("TEST_UNDECLARED_OUTPUTS_DIR"))
        .map(PathBuf::from)
        .unwrap_or_else(std::env::temp_dir);
    fs::create_dir_all(&parent).expect("create hook diagnostic artifact parent");
    let root = tempfile::Builder::new()
        .prefix("queue-hook-")
        .tempdir_in(parent)
        .expect("create unique hook diagnostic directory")
        .keep();
    // Preserve the original command literally, including its path quoting.
    // This observation must not silently replace python3 or repair its invocation.
    let original_command = format!("python3 {}", script_path.display());
    fs::write(script_path, format!("{PYTHON_IDENTITY}{script}"))
        .expect("write original hook with interpreter identity preamble");
    let launcher = home.join(if cfg!(windows) {
        "queue_hook_diagnostic.cmd"
    } else {
        "queue_hook_diagnostic.sh"
    });
    let wrapper = if cfg!(windows) {
        WINDOWS_LAUNCHER.replace("@ROOT@", &root.display().to_string().replace('%', "%%"))
    } else {
        UNIX_LAUNCHER.replace("@ROOT@", &shell_quote(&root))
    }
    .replace("@COMMAND@", &original_command);
    fs::write(&launcher, wrapper).expect("write hook diagnostic launcher");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;

        fs::set_permissions(&launcher, fs::Permissions::from_mode(/*mode*/ 0o700))
            .expect("make test diagnostic launcher executable");
    }
    let command = if cfg!(windows) {
        format!("\"{}\"", launcher.display())
    } else {
        shell_quote(&launcher)
    };
    let descriptor = json!({
        "schema": "queue-hook-diagnostics-v1",
        "root": root,
        "original_command": original_command,
        "observed_command": command,
        "script": script_path,
        "missing_exit_means": "running_or_interrupted_unknown",
    });
    fs::write(root.join("descriptor.json"), descriptor.to_string())
        .expect("retain hook diagnostic command identity");
    fs::write(home.join("queue_hook_diagnostics.json"), descriptor.to_string())
        .expect("retain hook diagnostic artifact location");
    eprintln!("QUEUE_HOOK_DIAGNOSTIC_LOCATION {descriptor}");
    command
}

pub struct HookDiagnostics {
    root: PathBuf,
}

impl HookDiagnostics {
    pub fn attach(home: &Path) -> Self {
        let descriptor: Value = serde_json::from_slice(
            &fs::read(home.join("queue_hook_diagnostics.json"))
                .expect("read hook diagnostic artifact location"),
        )
        .expect("decode hook diagnostic artifact location");
        let root = descriptor["root"]
            .as_str()
            .expect("diagnostic directory must be a path");
        Self {
            root: PathBuf::from(root),
        }
    }
}

impl Drop for HookDiagnostics {
    fn drop(&mut self) {
        // Do not change or consume the test's result or protocol event stream.
        // Complete files stay in the artifact directory even if this bounded
        // console snapshot observes an in-flight or interrupted invocation.
        let snapshot = diagnostic_snapshot(&self.root);
        eprintln!(
            "QUEUE_HOOK_DIAGNOSTIC_SNAPSHOT {}",
            json!({"root": self.root.display().to_string(), "observation": snapshot}),
        );
    }
}

fn diagnostic_snapshot(root: &Path) -> Value {
    let entries = match fs::read_dir(root) {
        Ok(entries) => entries,
        Err(error) => return json!({"diagnostic_read_error": error.to_string()}),
    };
    let mut invocations = Vec::new();
    let mut omitted = 0;
    let mut remaining_console_bytes = 16 * 1024;
    for entry in entries {
        let entry = match entry {
            Ok(entry) => entry,
            Err(error) => return json!({"diagnostic_read_error": error.to_string()}),
        };
        if !entry.file_name().to_string_lossy().starts_with("run-") {
            continue;
        }
        if invocations.len() == 64 {
            omitted += 1;
            continue;
        }
        let run = entry.path();
        let mut files = serde_json::Map::new();
        for name in [
            "started.txt",
            "resolver.stdout",
            "resolver.stderr",
            "resolver-exit-code.txt",
            "interpreter.json",
            "stdout.bin",
            "stderr.bin",
            "exit-code.txt",
        ] {
            let observed = (|| -> std::io::Result<Value> {
                let file = fs::File::open(run.join(name))?;
                let size = file.metadata()?.len();
                let mut bytes = Vec::new();
                let limit = remaining_console_bytes.min(4096);
                file.take(u64::try_from(limit).expect("bounded console limit"))
                    .read_to_end(&mut bytes)?;
                remaining_console_bytes -= bytes.len();
                let truncated = size > u64::try_from(bytes.len()).expect("bounded console bytes");
                Ok(json!({"bytes": bytes, "observed_size": size, "console_truncated": truncated}))
            })();
            files.insert(
                name.to_string(),
                match observed {
                    Ok(value) => value,
                    Err(error) => json!({"read_error": error.to_string()}),
                },
            );
        }
        let exit_code = files
            .get("exit-code.txt")
            .filter(|value| value["console_truncated"].as_bool() == Some(false))
            .and_then(|value| serde_json::from_value::<Vec<u8>>(value["bytes"].clone()).ok())
            .and_then(|bytes| String::from_utf8(bytes).ok())
            .and_then(|value| value.trim().parse::<i32>().ok());
        let outcome = if exit_code.is_some() {
            "exit_recorded"
        } else {
            "running_or_interrupted_unknown"
        };
        invocations.push(json!({
            "invocation": entry.file_name().to_string_lossy(),
            "exit_code": exit_code,
            "outcome": outcome,
            "files": files,
        }));
    }
    json!({
        "invocations": invocations,
        "console_omitted_invocations": omitted,
        "console_bytes_remaining": remaining_console_bytes,
    })
}
