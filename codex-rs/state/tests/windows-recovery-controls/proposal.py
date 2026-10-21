"""Project-CI-only generation and full owning tests; never qualifies input HEAD."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tomllib

ROOT = Path(__file__).resolve().parents[4]
BASE = "a2fb6e621787cdb9230dfd1350f82fb281d4ec91"
CONTROL = "codex-rs/state/tests/windows-recovery-controls"
WORKFLOW = ".github/workflows/hepta-windows-retained-recovery-proposal.yml"
ALLOWED_ROOTS = ("codex-rs/state/", "codex-rs/utils/path-utils/", "codex-rs/hepta-memory/")
ALLOWED_FILES = {
    "codex-rs/Cargo.lock", "MODULE.bazel.lock", WORKFLOW,
    ".github/scripts/check_windows_private_state_acquisition.py",
}


def git(*args, **kwargs):
    return subprocess.check_output(["git", *args], cwd=ROOT, **kwargs)


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def evidence_dir():
    path = Path(os.environ["RECOVERY_EVIDENCE_DIR"]).resolve()
    if path.is_relative_to(ROOT):
        raise RuntimeError("evidence must be outside the checkout")
    return path


def init():
    head = git("rev-parse", "HEAD").decode().strip()
    if head != os.environ["SOURCE_SHA"] or git("status", "--porcelain"):
        raise RuntimeError("input is not the exact clean source SHA")
    git("merge-base", "--is-ancestor", BASE, "HEAD")
    evidence = Path(os.environ["RUNNER_TEMP"]) / "windows-retained-recovery-proposal"
    if evidence.resolve().is_relative_to(ROOT):
        raise RuntimeError("unsafe runner evidence directory")
    evidence.mkdir(parents=True, exist_ok=False)
    with open(os.environ["GITHUB_ENV"], "a") as env:
        print(f"RECOVERY_EVIDENCE_DIR={evidence.as_posix()}", file=env)
    toolchain = tomllib.loads((ROOT / "codex-rs/rust-toolchain.toml").read_text())["toolchain"]
    packages = {}
    for directory in ("utils/path-utils", "state", "hepta-memory"):
        package = tomllib.loads((ROOT / "codex-rs" / directory / "Cargo.toml").read_text())["package"]["name"]
        packages[directory] = package
    if packages != {"utils/path-utils": "codex-utils-path", "state": "codex-state", "hepta-memory": "codex-hepta-memory"}:
        raise RuntimeError("owning package identities changed")
    source = {
        "source_sha": head, "source_tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
        "proposal_base_sha": BASE, "platform": sys.platform, "run_id": os.environ["GITHUB_RUN_ID"],
        "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"], "toolchain": toolchain,
        "packages": packages, "input_head_qualified": False,
    }
    write(evidence / "source.json", source)
    commands = [
        ("format", ["just", "fmt", "--base", BASE], "codex-rs", []),
        ("metadata", ["cargo", "metadata", "--format-version", "1"], "codex-rs", []),
    ]
    for package in packages.values():
        argv = ["just", "test", "--locked", "-p", package]
        if sys.platform == "win32":
            argv += ["--test-threads", "1", "--retries", "0"]
        commands.append((package + "-tests", argv, "codex-rs", ["metadata"]))
    for package in packages.values():
        commands.append((package + "-fix", ["just", "fix", "-p", package], "codex-rs", ["metadata"]))
    commands += [
        ("format-final", ["just", "fmt", "--base", BASE], "codex-rs", []),
        ("refresh-controls", [sys.executable, CONTROL + "/refresh.py"], ".", ["format-final"]),
        ("control-oracle", [sys.executable, "-m", "unittest", "discover", "-s", CONTROL, "-p", "test_run.py"], ".", []),
    ]
    if sys.platform == "win32":
        commands.append(("native-controls", [sys.executable, CONTROL + "/run.py", str(evidence / "native-controls")], ".", ["metadata", "refresh-controls", "control-oracle", "codex-state-tests"]))
    elif sys.platform.startswith("linux"):
        commands += [
            ("lock-update", ["just", "bazel-lock-update"], ".", ["metadata"]),
            ("lock-check", ["just", "bazel-lock-check"], ".", ["lock-update"]),
            ("lock-repeat", ["just", "bazel-lock-update"], ".", ["lock-update"]),
            ("lock-repeat-equal", ["cmp", str(evidence / "MODULE.bazel.lock.first-generation"), "MODULE.bazel.lock"], ".", ["lock-update", "lock-repeat"]),
        ]
    else:
        raise RuntimeError("unplanned proposal platform")
    write(evidence / "commands.json", [
        {"name": name, "argv": argv, "cwd": cwd, "requires": requires,
         "status": "not_started", "exit_code": None, "log": name + ".log"}
        for name, argv, cwd, requires in commands
    ])
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        print(f'toolchain={toolchain["channel"]}', file=output)
        print(f'components={",".join(toolchain["components"])}', file=output)


def run():
    evidence = evidence_dir()
    commands = json.loads((evidence / "commands.json").read_text())
    by_name = {command["name"]: command for command in commands}
    for command in commands:
        blocked = [name for name in command["requires"] if by_name[name]["status"] != "passed"]
        if blocked:
            command.update(status="blocked", blocked_by=blocked)
            write(evidence / "commands.json", commands)
            continue
        command.update(status="running", started_unix_ns=time.time_ns())
        write(evidence / "commands.json", commands)
        print("Running " + repr(command["argv"]), flush=True)
        with (evidence / command["log"]).open("wb") as log:
            try:
                result = subprocess.run(command["argv"], cwd=ROOT / command["cwd"], stdout=log, stderr=subprocess.STDOUT, timeout=5400, check=False)
                command.update(exit_code=result.returncode, status="passed" if result.returncode == 0 else "failed")
            except (OSError, subprocess.TimeoutExpired) as error:
                command.update(status="failed_to_complete", error=str(error))
                log.write((str(error) + "\n").encode())
        command["finished_unix_ns"] = time.time_ns()
        if command["name"] == "lock-update" and command["status"] == "passed":
            shutil.copyfile(ROOT / "MODULE.bazel.lock", evidence / "MODULE.bazel.lock.first-generation")
        write(evidence / "commands.json", commands)
        print(f'{command["name"]}: {command["status"]}, exit {command["exit_code"]}', flush=True)
        if command["status"] != "passed":
            print("\n".join((evidence / command["log"]).read_text(errors="replace").splitlines()[-50:]), flush=True)
    if any(command["status"] != "passed" for command in commands):
        raise SystemExit(1)


def collect():
    evidence = evidence_dir()
    source = json.loads((evidence / "source.json").read_text())
    head = git("rev-parse", "HEAD").decode().strip()
    tree = git("rev-parse", "HEAD^{tree}").decode().strip()

    def paths(*args):
        return [p for p in git(*args).decode().split("\0") if p]

    inputs = paths("diff", "--name-only", "--no-renames", "-z", BASE, "HEAD")
    changed = paths("diff", "--name-only", "--no-renames", "-z", "HEAD")
    untracked = paths("ls-files", "--others", "--exclude-standard", "-z")
    selected = sorted(set(inputs + changed + untracked))
    unexpected = [p for p in selected if p not in ALLOWED_FILES and not p.startswith(ALLOWED_ROOTS)]
    files = []
    index = evidence / "generated.index"
    original_index = Path(git("rev-parse", "--git-path", "index").decode().strip())
    if not original_index.is_absolute():
        original_index = ROOT / original_index
    shutil.copyfile(original_index, index)
    index_env = os.environ.copy()
    index_env["GIT_INDEX_FILE"] = str(index)
    for name in selected:
        path = ROOT / name
        if Path(name).is_absolute() or ".." in Path(name).parts or path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):
            raise RuntimeError(f"unsafe generated path: {name}")
        previous = subprocess.run(["git", "rev-parse", "--verify", f"HEAD:{name}"], cwd=ROOT, text=True, capture_output=True, check=False)
        item = {"path": name, "source_blob": previous.stdout.strip() if previous.returncode == 0 else None}
        if not path.exists():
            item["state"] = "deleted"
            git("update-index", "--force-remove", "--", name, env=index_env)
        elif path.is_file():
            working_data = path.read_bytes()
            # Preserve the exact canonical bytes Git would commit on this
            # platform, including the repository's explicit LF control pins.
            # Keep the working-file hash separately so conversion is visible.
            written = subprocess.check_output(
                ["git", "hash-object", "-w", "--path", name, "--stdin"],
                cwd=ROOT, input=working_data,
            ).decode().strip()
            data = git("cat-file", "blob", written)
            destination = evidence / "postimage" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            mode = "100755" if path.stat().st_mode & 0o111 and sys.platform != "win32" else "100644"
            tracked = git("ls-files", "--stage", "--", name).decode().split()
            if tracked:
                mode = tracked[0]
            if written != blob:
                raise RuntimeError("generated blob mismatch")
            git("update-index", "--add", "--cacheinfo", f"{mode},{blob},{name}", env=index_env)
            item.update(state="present", mode=mode, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), git_blob=blob,
                        working_bytes=len(working_data), working_sha256=hashlib.sha256(working_data).hexdigest())
        else:
            raise RuntimeError(f"unexpected generated object: {name}")
        files.append(item)
    candidate_tree = git("write-tree", env=index_env).decode().strip()
    (evidence / "generated.patch").write_bytes(git("diff", "--cached", "--binary", "--no-renames", "HEAD", env=index_env))
    with (evidence / "diff-check.log").open("wb") as log:
        check = subprocess.run(["git", "diff", "--cached", "--check", "HEAD"], cwd=ROOT, env=index_env, stdout=log, stderr=subprocess.STDOUT, check=False)
    commands = json.loads((evidence / "commands.json").read_text())
    expected = 12 if sys.platform == "win32" else 15
    complete = len(commands) == expected and all(c["status"] == "passed" and c["exit_code"] == 0 for c in commands)
    write(evidence / "generated-manifest.json", {
        "source_sha": head, "source_tree": tree, "proposal_base_sha": BASE,
        "candidate_tree": candidate_tree, "platform": sys.platform,
        "input_head_qualified": False, "full_platform_qualification": False,
        "all_proposal_commands_passed": complete,
        "generated_changes_require_review_and_original_ci": True,
        "setup_steps": json.loads(os.environ["SETUP_OUTCOMES"]),
        "changed_tracked_paths": changed, "untracked_paths": untracked,
        "unexpected_paths": unexpected, "diff_check_exit_code": check.returncode,
        "postimages": files,
    })
    inventory = []
    for path in sorted(evidence.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            inventory.append({"path": str(path.relative_to(evidence)), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    write(evidence / "artifact-inventory.json", inventory)
    if head != source["source_sha"] or tree != source["source_tree"] or unexpected or check.returncode or not complete:
        raise SystemExit(1)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("init", "run", "collect"):
        raise SystemExit("usage: proposal.py init|run|collect")
    {"init": init, "run": run, "collect": collect}[sys.argv[1]]()
