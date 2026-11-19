from pathlib import Path
import os
import subprocess
import json
import time
import hashlib
import sys

base = Path("/home/qq/hepta-shared-framework-f8e4-20261109")
task = Path("/home/qq/hepta-framework-followup-a60a-20261110")
source = task / "source"
record = task / "maintenance-r4-complete"
record.mkdir(exist_ok=True)
env = os.environ.copy()
env.update(
    PATH=str(base / "tools/bin") + ":/home/qq/.cargo/bin:" + env.get("PATH", ""),
    RUSTUP_TOOLCHAIN="1.96.0",
    CARGO_TARGET_DIR=str(base / "target"),
    CARGO_BUILD_JOBS="2",
    CARGO_INCREMENTAL="0",
    CARGO_PROFILE_DEV_DEBUG="0",
    CARGO_PROFILE_TEST_DEBUG="0",
    TMPDIR="/home/qq/t-a60a4",
    PYTHONDONTWRITEBYTECODE="1",
)
result = {
    "source": "fb1397873bef0eea81efe0c8aac48c56385ffe55",
    "commands": [],
    "complete": False,
}


def save():
    (record / "progress.json").write_text(json.dumps(result, indent=2) + "\n")


def run(name, args, cwd=None):
    t = time.time()
    with (record / (name + ".log")).open("wb") as log:
        p = subprocess.run(
            args, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=600
        )
    r = {
        "name": name,
        "argv": args,
        "exit_code": p.returncode,
        "wall_seconds": time.time() - t,
    }
    result["commands"].append(r)
    save()
    print(json.dumps(r), flush=True)
    if p.returncode:
        sys.exit(p.returncode)


assert (
    subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    == result["source"]
)
(record / "fix.patch").write_bytes(
    subprocess.check_output(["git", "diff", "--binary"], cwd=source)
)
save()
run(
    "fetch-base",
    [
        "git",
        "-c",
        "http.version=HTTP/1.1",
        "fetch",
        "--depth",
        "1",
        "https://github.com/TrillionniumFoundation/hepta-private-ci.git",
        "71738345326b98d88b738250d2b84ecbcb466eb8",
    ],
    source,
)
run(
    "fmt",
    ["just", "fmt", "--base", "71738345326b98d88b738250d2b84ecbcb466eb8"],
    source / "codex-rs",
)
run("diff-check", ["git", "diff", "--check"], source)
patch = subprocess.check_output(["git", "diff", "--binary"], cwd=source)
(record / "maintenance.patch").write_bytes(patch)
result["patch_sha256"] = hashlib.sha256(patch).hexdigest()
result["changed"] = []
for p in subprocess.check_output(
    ["git", "diff", "--name-only"], cwd=source, text=True
).splitlines():
    data = (source / p).read_bytes()
    result["changed"].append(
        {"path": p, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    )
result["stat"] = subprocess.check_output(
    ["git", "diff", "--stat"], cwd=source, text=True
)
result["complete"] = True
save()
print(json.dumps(result), flush=True)
