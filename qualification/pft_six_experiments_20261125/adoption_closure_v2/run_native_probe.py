"""Stage one new probe in an isolated pinned checkout, then use its just test."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

HEAD = "fe249567feae227a362d354c1df3499a2995af40"
PARENT = "codex-rs/hepta-agentd/src/neuron_generation_adopted_learning_tests.rs"
PARENT_BLOB = "508081d1e497b9e34a71dd751e5912be6d2e3ebb"
TARGET = "codex-rs/hepta-agentd/src/adoption_closure_v2_tests.rs"
HOOK = '\n#[path = "adoption_closure_v2_tests.rs"]\nmod adoption_closure_v2;\n'


def file_pin(path):
    raw = Path(path).read_bytes()
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def save(path, result):
    with path.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def run(args):
    repo, out = Path(args.repo).resolve(), Path(args.output).resolve()
    if not (repo / ".git").is_file():
        raise ValueError("Use a newly isolated git worktree, not a shared primary checkout")
    if git(repo, "rev-parse", "HEAD").decode().strip() != HEAD:
        raise ValueError("Native source head differs from the audited head")
    original = git(repo, "show", HEAD + ":" + PARENT)
    blob = hashlib.sha1(b"blob " + str(len(original)).encode() + b"\0" + original).hexdigest()
    if blob != PARENT_BLOB:
        raise ValueError("Native support source pin changed")
    source = Path(__file__).with_name("native_probe.rs").read_bytes()
    allowed = {PARENT, TARGET}
    dirty = git(repo, "status", "--porcelain", "--untracked-files=all").decode().splitlines()
    if any(line[3:] not in allowed for line in dirty):
        raise ValueError("Worktree has unrelated changes; leave them untouched")
    parent, target = repo / PARENT, repo / TARGET
    if parent.read_bytes() not in (original, original + HOOK.encode()):
        raise ValueError("Original test module has concurrent changes")
    if target.exists() and target.read_bytes() != source:
        raise ValueError("Different probe already occupies this worktree")
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    target.write_bytes(source)
    parent.write_bytes(original + HOOK.encode())
    env = dict(os.environ)
    env["CARGO_BUILD_JOBS"] = "1"
    if args.tool_bin:
        env["PATH"] = str(Path(args.tool_bin).resolve()) + os.pathsep + env["PATH"]
    if args.target_dir:
        env["CARGO_TARGET_DIR"] = str(Path(args.target_dir).resolve())
        env["CARGO_PROFILE_DEV_DEBUG"] = "0"
        env["CARGO_PROFILE_TEST_DEBUG"] = "0"
    command = ["just", "test", "--locked", "-p", "codex-hepta-agentd", "--lib", "-E",
               "test(cold_revocation_blocks_existing_checkpoint_adoption_v2)", "--no-capture"]
    lock = repo / "codex-rs" / "Cargo.lock"
    lock_original = git(repo, "show", HEAD + ":codex-rs/Cargo.lock")
    if lock.read_bytes() != lock_original:
        raise ValueError("Cargo.lock differs from the original source head")
    receipt = {"schema": "hepta.adoption-closure.native-execution.v2", "checked_head": HEAD,
               "parent_git_blob": PARENT_BLOB, "probe": file_pin(target), "argv": command,
               "cargo_lock": file_pin(lock),
               "scope": "engineering_fixture", "human_participants": 0,
               "model_inference": False, "training_updates": 0, "closure_complete": False}
    save(out / "STARTED.json", receipt)
    start = time.monotonic()
    with (out / "stdout.log").open("xb") as stdout, (out / "stderr.log").open("xb") as stderr:
        child = subprocess.run(command, cwd=repo / "codex-rs", env=env, stdout=stdout, stderr=stderr)
    receipt.update(exit=child.returncode, wall_seconds=time.monotonic() - start)
    receipt["cargo_lock_unchanged"] = lock.read_bytes() == lock_original
    receipt["logs"] = {name: file_pin(out / name) for name in ("stdout.log", "stderr.log")}
    markers = []
    for name in ("stdout.log", "stderr.log"):
        for line in (out / name).read_text(errors="replace").splitlines():
            if line.startswith("ADOPTION_CLOSURE_V2 "):
                markers.append(json.loads(line.split(" ", 1)[1]))
    receipt["probe_outputs"] = markers
    receipt["status"] = ("NATIVE_ENGINEERING_CONTROLS_PASSED"
                         if child.returncode == 0 and len(markers) == 1
                         and receipt["cargo_lock_unchanged"] else "BLOCKED_OR_FAILED")
    save(out / "RESULT.json", receipt)
    # Repository policy requires this after code changes. Do not test again
    # after formatting; retain the changed-source pin separately from run pins.
    with (out / "format.stdout.log").open("xb") as stdout, (out / "format.stderr.log").open("xb") as stderr:
        formatted = subprocess.run(["just", "fmt"], cwd=repo / "codex-rs", env=env,
                                   stdout=stdout, stderr=stderr)
    save(out / "FORMAT.json", {"exit": formatted.returncode, "checked_head": HEAD,
                               "formatted_probe": file_pin(target), "tests_rerun_after_format": False,
                               "stdout": file_pin(out / "format.stdout.log"),
                               "stderr": file_pin(out / "format.stderr.log")})
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["status"] == "NATIVE_ENGINEERING_CONTROLS_PASSED" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--tool-bin")
    parser.add_argument("--target-dir")
    raise SystemExit(run(parser.parse_args()))
