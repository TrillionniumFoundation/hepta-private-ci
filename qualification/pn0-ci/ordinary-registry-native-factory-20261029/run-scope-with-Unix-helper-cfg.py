import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "work/hepta-windows-portable-tools-20261024"
OUT = Path(__file__).resolve().parent
PATHS = [
    "codex-rs/hepta-prompt-registry/src/durable.rs",
    "codex-rs/hepta-prompt-registry/src/durable_store_platform.rs",
    "codex-rs/hepta-prompt-registry/src/ordinary_windows_factory_tests.rs",
    "codex-rs/hepta-agentd/src/prompt_runtime.rs",
    "codex-rs/hepta-agentd/src/prompt_runtime_windows.rs",
    "codex-rs/windows-sandbox-rs/src/elevated/runner_client.rs",
    "codex-rs/hepta-agentd/src/control.rs",
    "codex-rs/uds/src/lib.rs",
    "codex-rs/uds/src/deadline_guard.rs",
    "codex-rs/uds/src/deadline_guard_tests.rs",
    "codex-rs/uds/src/lib_tests.rs",
    "codex-rs/uds/Cargo.toml",
    "codex-rs/Cargo.lock",
    "codex-rs/hepta-contracts/src/final_use.rs",
    "codex-rs/hepta-contracts/src/final_use_store.rs",
    "codex-rs/hepta-contracts/src/final_use_live_owner.rs",
    "codex-rs/hepta-contracts/src/final_use_windows_tests.rs",
]


def pins():
    return {path: hashlib.sha256((SOURCE / path).read_bytes()).hexdigest() for path in PATHS}


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


label = sys.argv[1]
argv = sys.argv[2:]
assert label.replace("-", "").isalnum() and argv
assert not (OUT / (label + "-started.json")).exists()
env = dict(os.environ)
env["PATH"] = str(ROOT / "work/coordination/nextest-0.9.103-component-verifier-tools-20261028-002/bin") + os.pathsep + env["PATH"]
env["CARGO_TARGET_DIR"] = str(ROOT / "work/targets/final-use-live-owner-contracts-20261028-006")
env["CARGO_BUILD_JOBS"] = "2"
env["PATH"] = str(ROOT / "work/coordination/runner-cross-compiler-tools-20261029-010/bin") + os.pathsep + str(ROOT / "work/coordination/runner-cross-compiler-tools-20261029-010/sysroot/usr/bin") + os.pathsep + env["PATH"]
before = pins()
start = time.monotonic()
utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
raw = OUT / (label + ".raw.log")
with raw.open("xb") as output:
    child = subprocess.Popen(argv, cwd=SOURCE / "codex-rs", env=env, stdout=output, stderr=subprocess.STDOUT)
    stat = Path(f"/proc/{child.pid}/stat").read_text()
    save(OUT / (label + "-started.json"), {
        "utc": utc, "argv": argv, "cwd": str(SOURCE / "codex-rs"),
        "pid": child.pid, "proc_stat_before_wait": stat,
        "source_before": before, "target_dir": env["CARGO_TARGET_DIR"], "jobs": 2,
        "scope": "New ordinary Registry source component validation only; Linux original package or GNU cfgtest compilation as argv specifies; no Agentd package/native Windows/PN1/model/SDK/supervisor or budget reset",
        "external_timeout_or_kill": False,
    })
    code = child.wait()
data = raw.read_bytes()
after = pins()
terminal = {
    "start_utc": utc, "end_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "argv": argv, "exit_code": code, "elapsed_seconds": time.monotonic() - start,
    "output_complete": True, "reaped": True, "raw_bytes": len(data),
    "raw_sha256": hashlib.sha256(data).hexdigest(),
    "source_before": before, "source_after": after, "source_unchanged": before == after,
    "Windows_native": "NOT_RUN", "Agentd_package_compile_and_tests": "NOT_RUN",
    "CI": "NOT_RUN", "COMMITTED": False, "PUBLISHED": False,
}
save(OUT / (label + "-terminal.json"), terminal)
print(json.dumps({key: terminal[key] for key in ("exit_code", "elapsed_seconds", "raw_bytes", "raw_sha256", "source_unchanged")}))
raise SystemExit(code)
