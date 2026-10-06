"""Bounded Windows diagnostic only. Never opens a product recovery API."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

BASE = "78fdb0cf8537e3a84fc6e0a849707559c80881e8"
BRANCH = "refs/heads/dot/operations-windows-identity-diagnostic-20261006"
SOURCE = "scripts/diagnostics/windows_retained_identity.rs"
SOURCE_SHA256 = "a87d37c60559874616d4652e8a0d401b27f0b353e11d4efa3f3b250fa24717c8"
PATHS = sorted((SOURCE, "scripts/diagnostics/windows_retained_identity_ci.py", ".github/workflows/operations-windows-identity-diagnostic.yml"))
NAMES = sorted(("stable_identity_and_unchanged_bytes", "equal_length_path_replacement_is_rejected",
    "length_drift_and_hardlink_inputs_are_rejected", "persistent_parent_replacement_is_rejected",
    "reparse_input_is_rejected_or_probe_explicitly_fails",
    "namespaces_directories_are_rejected_without_claiming_writer_exclusion",
    "success_and_partial_failure_release_handles", "unsupported_information_class_returns_error_without_fallback", "unrelated_sibling_changes_do_not_change_ancestor_identity"))
OUT = Path(os.environ["RUNNER_TEMP"]) / "windows-identity-evidence"


def git(*args):
    return subprocess.check_output(["git", "--no-replace-objects", *args], text=True).strip()


def git_bytes(*args):
    return subprocess.check_output(["git", "--no-replace-objects", *args])


def identity():
    if os.environ.get("GITHUB_REF") != BRANCH or os.environ.get("GITHUB_EVENT_NAME") != "push":
        raise ValueError("unreviewed event or branch")
    head = git("rev-parse", "HEAD")
    headers = git("cat-file", "-p", head).split("\n\n", 1)[0].splitlines()
    parents = [line.removeprefix("parent ") for line in headers if line.startswith("parent ")]
    trees = [line.removeprefix("tree ") for line in headers if line.startswith("tree ")]
    paths = sorted(git("diff", "--name-only", BASE, head).splitlines())
    canonical = git_bytes("cat-file", "blob", f"{head}:{SOURCE}")
    working = Path(SOURCE).read_bytes()
    digest = hashlib.sha256(canonical).hexdigest()
    blob = hashlib.sha1(b"blob " + str(len(canonical)).encode("ascii") + b"\0" + canonical).hexdigest()
    working_blob = git("hash-object", "--path", SOURCE, SOURCE)
    if head != os.environ["GITHUB_SHA"] or parents != [BASE] or len(trees) != 1 or paths != PATHS:
        raise ValueError("head, sole parent, or changed paths differ from reviewed proposal")
    if git("status", "--porcelain", "--untracked-files=all") or digest != SOURCE_SHA256 or working_blob != blob:
        raise ValueError("dirty source, incorrect canonical digest, or working blob differs")
    if working == canonical:
        newline_mode = "exact canonical LF"
    elif b"\r" not in canonical and working == canonical.replace(b"\n", b"\r\n"):
        newline_mode = "exact LF-to-CRLF checkout conversion"
    else:
        raise ValueError("working bytes differ beyond permitted exact newline conversion")
    return {"head": head, "parents": parents, "tree": trees[0],
            "source_sha256": digest, "source_git_blob": blob,
            "working_sha256": hashlib.sha256(working).hexdigest(),
            "working_git_blob": working_blob, "newline_mode": newline_mode,
            "changed_paths": paths, "dirty": False}


def save(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def run(name, command, seconds):
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                timeout=seconds, check=False)
        raw = result.stdout
        code = result.returncode
    except subprocess.TimeoutExpired as error:
        raw = error.stdout or b""
        code = "timeout"
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("diagnostic output exceeded 4 MiB, no pass")
    (OUT / (name + ".log")).write_bytes(raw)
    record = {"command": command, "exit": code, "timeout_seconds": seconds,
              "log_sha256": hashlib.sha256(raw).hexdigest()}
    save(name + ".json", record)
    if code != 0:
        raise ValueError(f"{name} failed: {code}")
    return raw.decode("utf-8", errors="strict")


def native():
    if sys.platform != "win32":
        raise ValueError("native Windows execution required")
    identity()
    exe = str(Path(os.environ["RUNNER_TEMP"]) / "windows-retained-identity.exe")
    run("compiler", ["rustc", "+1.96.0", "--edition=2024", "--test", "--deny=warnings", SOURCE, "-o", exe], 120)
    listing = run("inventory", [exe, "--list"], 30)
    actual = sorted(line.removesuffix(": test") for line in listing.splitlines() if line.endswith(": test"))
    if actual != NAMES:
        raise ValueError("native inventory differs from nine reviewed tests")
    output = run("native", [exe, "--test-threads=1", "--nocapture"], 120)
    for name in NAMES:
        if output.splitlines().count(f"test {name} ... ok") != 1:
            raise ValueError(f"missing/duplicate/nonpassing test {name}")
    if "test result: ok. 9 passed; 0 failed; 0 ignored;" not in output:
        raise ValueError("native summary does not establish nine executed passes")
    save("result.json", {"status": "passed", "passed": 9, "ignored": 0, "names": NAMES,
                         "scope": "standalone Windows identity diagnostic, no backend qualification"})


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    mode = sys.argv[1]
    if mode == "before":
        save("source-before.json", identity())
    elif mode == "native":
        native()
    elif mode == "after":
        after = identity()
        save("source-after.json", after)
        if after != json.loads((OUT / "source-before.json").read_text(encoding="utf-8")):
            raise ValueError("source identity changed")
    elif mode == "manifest":
        files = []
        for path in sorted(OUT.iterdir()):
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
                raise ValueError("unexpected diagnostic artifact")
            if path.name != "manifest.json":
                files.append({"path": path.name, "bytes": path.stat().st_size,
                              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        save("manifest.json", files)
    else:
        raise ValueError("unknown phase")
