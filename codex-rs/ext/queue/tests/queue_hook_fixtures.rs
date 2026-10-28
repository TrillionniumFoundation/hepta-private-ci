use std::path::Path;

fn python_hook_command(script_path: &Path) -> String {
    if cfg!(windows) {
        format!("python \"{}\"", script_path.display())
    } else {
        let quoted = script_path.display().to_string().replace('\'', "'\"'\"'");
        format!("python3 '{quoted}'")
    }
}

pub(super) fn write_rejecting_prompt_hook(home: &Path) {
    let script_path = home.join("queue prompt hook.py");
    let log_path = home.join("queue_prompt_hook.log");
    let script = format!(
        r#"import json
from pathlib import Path
import sys

payload = json.load(sys.stdin)
with Path(r"{log_path}").open("a", encoding="utf-8") as log:
    log.write(payload["prompt"] + "\n")
if payload["prompt"] == "blocked":
    print(json.dumps({{"decision": "block", "reason": "blocked by queue hook"}}))
"#,
        log_path = log_path.display(),
    );
    std::fs::write(&script_path, script)
        .unwrap_or_else(|error| panic!("write queue hook script: {error}"));
    let hooks = serde_json::json!({
        "hooks": {
            "UserPromptSubmit": [{
                "hooks": [{
                    "type": "command",
                    "command": python_hook_command(&script_path),
                }]
            }]
        }
    });
    std::fs::write(home.join("hooks.json"), hooks.to_string())
        .unwrap_or_else(|error| panic!("write queue hooks: {error}"));
}

pub(super) fn write_blocking_prompt_hook(home: &Path) {
    let script_path = home.join("queue blocking prompt hook.py");
    let entered_path = home.join("queue_blocking_prompt_hook.entered");
    let release_path = home.join("queue_blocking_prompt_hook.release");
    let script = format!(
        r#"import json
from pathlib import Path
import sys
import time

payload = json.load(sys.stdin)
if payload["prompt"] in ["delay exact persistence", "delay exact rejection"]:
    Path(r"{entered_path}").write_text("entered", encoding="utf-8")
    deadline = time.monotonic() + 20
    while not Path(r"{release_path}").exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("timed out waiting to release queue persistence hook")
        time.sleep(0.01)
    if payload["prompt"] == "delay exact rejection":
        print(json.dumps({{"decision": "block", "reason": "delayed queue rejection"}}))
"#,
        entered_path = entered_path.display(),
        release_path = release_path.display(),
    );
    std::fs::write(&script_path, script)
        .unwrap_or_else(|error| panic!("write blocking queue hook script: {error}"));
    let hooks = serde_json::json!({
        "hooks": {
            "UserPromptSubmit": [{
                "hooks": [{
                    "type": "command",
                    "command": python_hook_command(&script_path),
                }]
            }]
        }
    });
    std::fs::write(home.join("hooks.json"), hooks.to_string())
        .unwrap_or_else(|error| panic!("write blocking queue hooks: {error}"));
}
