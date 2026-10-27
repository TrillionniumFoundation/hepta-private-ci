"""Evidence and source guards shared by candidate generation and regression."""

from datetime import datetime, timezone
import hashlib
import json
import shutil
import subprocess
import time


SCHEMA = "hepta.ci.dependency-candidate.v2"
FILES = (
    "codex-rs/Cargo.toml",
    "codex-rs/Cargo.lock",
    "MODULE.bazel.lock",
    "codex-rs/core-plugins/src/startup_sync.rs",
    "codex-rs/core-plugins/src/startup_sync_zip_tests.rs",
    "codex-rs/core-plugins/tests/fixtures/zipball_lzma.zip",
)
POLICIES = ("codex-rs/deny.toml", ".github/workflows/cargo-deny.yml")
VENDOR = "codex-rs/third_party/i18n-config-0.4.8"


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def describe(root, paths):
    result = {}
    for name in paths:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Expected a regular input file: {name}")
        result[name] = {"bytes": path.stat().st_size, "sha256": checksum(path)}
    return result


class Recorder:
    """Persist process evidence before and after every command, including failures."""

    def __init__(self, root, output, mode):
        self.root, self.output = root.resolve(), output.resolve()
        if self.output.is_relative_to(self.root):
            raise ValueError("Candidate evidence must live outside the checkout")
        self.output.mkdir(parents=True, exist_ok=False)
        self.record = {
            "schema": SCHEMA,
            "mode": mode,
            "status": "running",
            "commands": [],
            "promotion_allowed": False,
            "policy_preservation_required": True,
            "original_dependency_policy_unchanged": None,
        }
        self.save()

    def save(self):
        temporary = self.output / "RESULT.tmp"
        temporary.write_text(json.dumps(self.record, indent=2) + "\n")
        temporary.replace(self.output / "RESULT.json")

    def run(self, label, command, *, required=True):
        log = self.output / f"{len(self.record['commands']):02d}-{label}.log"
        entry = {
            "command": command,
            "cwd": str(self.root),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "log": log.name,
            "exit_code": None,
            "required": required,
        }
        self.record["commands"].append(entry)
        self.save()
        started = time.monotonic()
        print(f"Running {label}: {' '.join(command)}", flush=True)
        try:
            with log.open("wb") as stream:
                completed = subprocess.run(
                    command, cwd=self.root, stdout=stream, stderr=subprocess.STDOUT
                )
            entry["exit_code"] = completed.returncode
        except OSError as error:
            entry["launch_error"] = str(error)
            raise
        finally:
            entry["elapsed_seconds"] = time.monotonic() - started
            if log.exists():
                entry["log_sha256"] = checksum(log)
                entry["log_bytes"] = log.stat().st_size
            self.save()
        if required and entry["exit_code"]:
            raise RuntimeError(
                f"{label} failed with exit {entry['exit_code']}; see {log.name}"
            )
        return entry["exit_code"]

    def text(self, label, command):
        self.run(label, command)
        return (self.output / self.record["commands"][-1]["log"]).read_text().strip()


def check_checkout(runner, expected_source):
    source = runner.text("source-head", ["git", "rev-parse", "HEAD"])
    runner.record["source_commit"] = source
    if source != expected_source:
        raise ValueError("Checkout HEAD does not match the requested source SHA")
    if runner.text("clean-checkout", ["git", "status", "--porcelain"]):
        raise ValueError("A clean disposable checkout is required")
    runner.record["policy_inputs"] = describe(runner.root, POLICIES)
    vendor = sorted(
        str(p.relative_to(runner.root))
        for p in (runner.root / VENDOR).rglob("*")
        if p.is_file()
    )
    if not vendor:
        raise ValueError("The reviewed i18n-config vendor source is missing")
    runner.record["vendor_inputs"] = describe(runner.root, vendor)


def verify_tree(runner, record):
    for key in ("policy_inputs", "vendor_inputs"):
        unchanged = describe(runner.root, record[key]) == record[key]
        if key == "policy_inputs":
            runner.record["original_dependency_policy_unchanged"] = unchanged
        if not unchanged:
            raise ValueError(f"The candidate changed its bound {key}")
    if describe(runner.root, record["files"]) != record["files"]:
        raise ValueError("Candidate file contents differ from the sealed snapshots")
    changed = runner.text(
        "changed-paths", ["git", "diff", "HEAD", "--name-only"]
    ).splitlines()
    if set(changed) != set(record["changed_paths"]) or not set(changed) <= set(FILES):
        raise ValueError("The worktree contains changes outside the candidate")
    if runner.text(
        "untracked-paths", ["git", "ls-files", "--others", "--exclude-standard"]
    ):
        raise ValueError("The candidate checkout contains untracked files")


def export_files(runner, directory="files"):
    paths = [name for name in FILES if (runner.root / name).is_file()]
    result = describe(runner.root, paths)
    for name in paths:
        destination = runner.output / directory / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(runner.root / name, destination)
    return result


def restore_candidate(runner, candidate, expected_result, expected_source):
    if checksum(candidate / "RESULT.json") != expected_result:
        raise ValueError(
            "Downloaded candidate RESULT hash differs from the producer job"
        )
    record = json.loads((candidate / "RESULT.json").read_text())
    if record["schema"] != SCHEMA or record["status"] != "candidate_generated":
        raise ValueError(
            "The artifact does not contain a successfully generated candidate"
        )
    if record.get("original_dependency_policy_unchanged") is not True:
        raise ValueError(
            "Producer did not verify preservation of the original dependency policy"
        )
    if record["source_commit"] != expected_source:
        raise ValueError("Candidate source SHA differs from the requested checkout")
    if set(record["files"]) != set(FILES):
        raise ValueError("Candidate snapshot set is incomplete or has unexpected files")
    if describe(candidate / "files", FILES) != record["files"]:
        raise ValueError("Downloaded file snapshots do not match the producer hashes")
    patch = candidate / "candidate.patch"
    if checksum(patch) != record["candidate_patch_sha256"]:
        raise ValueError("Downloaded candidate patch differs from the producer hash")
    check_checkout(runner, expected_source)
    for key in ("policy_inputs", "vendor_inputs"):
        if runner.record[key] != record[key]:
            raise ValueError(f"Producer and consumer disagree about {key}")
    stats = runner.text("patch-paths", ["git", "apply", "--numstat", str(patch)])
    if {line.split("\t")[-1] for line in stats.splitlines()} != set(
        record["changed_paths"]
    ):
        raise ValueError("Candidate patch path set differs from its manifest")
    if not set(record["changed_paths"]) <= set(FILES):
        raise ValueError("Candidate patch would change an unapproved path")
    runner.run(
        "check-candidate-patch", ["git", "apply", "--check", "--index", str(patch)]
    )
    runner.run("apply-candidate-patch", ["git", "apply", "--index", str(patch)])
    verify_tree(runner, record)
    runner.record["candidate_result_sha256"] = expected_result
    runner.record["candidate_patch_sha256"] = record["candidate_patch_sha256"]
    runner.record["files"] = record["files"]
    return record
