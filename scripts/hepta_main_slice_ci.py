"""Qualify the reviewed Automation fixture follow-up over the main integration."""

import hashlib
import json
import os
from pathlib import Path
import runpy
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

BASE = "bf1862dd05b176a4282c7e657203cb24395d249a"
SOURCE_TREE = "566b8d5f72680a60441a5b57c84859acdd58dc2f"
BRANCH = "refs/heads/dot/main-automation-fixtures-20261006"
SOURCES = {
    "codex-rs/hepta-automation/tests/automation.rs": "b179332702b85339f0646f47bce40d48ef7674ff",
    "codex-rs/hepta-automation/tests/retirement_recovery.rs": "c1eac373961514fccc0914897434ccc68d43e9d9",
    "codex-rs/hepta-automation/BUILD.bazel": "8545046b41b681f2990a9486fa69cd21d112a875"
}

DIAGNOSTICS = {
    ".github/workflows/main-fairness-circuit-integration.yml",
    "scripts/hepta_main_slice_ci.py",
}
ADDED_SOURCE = set()
REQUIRED = {
    "memory": (
        "same_destination_unavailable_prefix_does_not_starve_later_operation",
        "cloned_dispatcher_reserves_beyond_paused_observer_and_cancelled_page_wraps",
        "limit_two_binding_error_propagates_without_permanently_hiding_later_items",
        "still_indeterminate_cycle_is_fair_and_short_cycle_never_repeats_within_one_call",
        "cursor_does_not_retain_writer_lock_and_resets_on_reopened_owner",
        "tied_and_new_keys_wrap_past_terminal_holes_without_crossing_destinations",
        "concurrent_cross_wrap_observations_preserve_terminal_cas_and_never_dispatch",
        "concurrent_same_snapshot_has_one_reservation_and_one_bounded_loser",
        "stale_owner_and_destination_cannot_overwrite_empty_or_wrapped_version",
        "poisoned_cursor_rejects_snapshot_and_publication",
    ),
    "automation": (
        "circuit_compiles_to_existing_taskflow_without_authority",
        "successor_binds_exact_predecessor_and_can_change_route_and_parameters",
        "structural_successor_cannot_rebind_predecessor_or_widen_capabilities",
        "circuit_reuses_taskflow_cycle_and_terminal_rejection",
        "successor_rejects_version_exhaustion_but_accepts_last_increment",
        "v1_store_migrates_atomically_to_dispatch_outcome_schema",
        "all_release_paths_preserve_disable_and_cancel_across_restart",
    ),
}


class InterruptedStage(Exception):
    def __init__(self, number):
        super().__init__("native stage interrupted")
        self.number = number


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def git(*args, env=None):
    return subprocess.check_output(
        ["git", "--no-replace-objects", *args], text=True, timeout=30, env=env
    ).strip()


def evidence():
    path = Path(os.environ["SLICE_EVIDENCE"]).absolute()
    if path.is_symlink() or path.resolve().is_relative_to(Path.cwd().resolve()):
        raise ValueError("evidence must be outside the checkout")
    path.mkdir(parents=True, exist_ok=True)
    return path


def identity():
    if os.environ.get("GITHUB_EVENT_NAME") != "push" or os.environ.get("GITHUB_REF") != BRANCH:
        raise ValueError("only the reviewed source-head branch is admitted")
    head = git("rev-parse", "HEAD")
    if head != os.environ["GITHUB_SHA"]:
        raise ValueError("wrong checkout commit")
    headers = git("cat-file", "commit", head).split("\n\n", 1)[0].splitlines()
    parents = [line[7:] for line in headers if line.startswith("parent ")]
    trees = [line[5:] for line in headers if line.startswith("tree ")]
    if parents != [BASE] or len(trees) != 1 or git("rev-parse", "HEAD^{tree}") != trees[0]:
        raise ValueError("wrong raw parent or tree")
    if git("status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("checkout is dirty")
    changed = {}
    for line in git("diff", "--no-renames", "--name-status", BASE, head).splitlines():
        status, path = line.split("\t")
        changed[path] = status
    expected = {path: "A" if path in ADDED_SOURCE else "M" for path in SOURCES}
    expected.update({path: "M" for path in DIAGNOSTICS})
    if changed != expected:
        raise ValueError("changed paths/statuses differ from exact five-file follow-up scope")
    blobs = {path: git("rev-parse", f"{head}:{path}") for path in sorted(expected)}
    for path, blob in SOURCES.items():
        if blobs[path] != blob or git("hash-object", "--path", path, path) != blob:
            raise ValueError("unreviewed source blob: " + path)
    with tempfile.TemporaryDirectory() as directory:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(directory) / "index"))
        git("read-tree", head, env=env)
        git("update-index", "--force-remove", "--", *sorted(DIAGNOSTICS), env=env)
        projection = git("write-tree", env=env)
    if projection != SOURCE_TREE:
        raise ValueError("source projection or file modes differ from review")
    return {
        "head": head, "tree": trees[0], "parents": parents, "changed": changed,
        "source_projection": projection,
        "blobs": blobs,
        "sha256": {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in sorted(expected)},
        "clean": True,
    }


def remaining(cap):
    value = float(os.environ["SLICE_DEADLINE"]) - time.time()
    if value < 30:
        raise ValueError("shared deadline exhausted; remaining stage not run")
    return min(cap, value)


def capture(command, directory, *, seconds, limit, cwd=None):
    """Own one process group; bound both output streams and all drain loops."""
    directory.mkdir()
    record = {"command": command, "status": "running", "returncode": None}
    save(directory / "execution.json", record)
    started = time.monotonic()
    stop_at = started + seconds
    stopped = None
    interrupted = []
    old_handlers = {}
    process = None
    handles = {}
    total = 0
    failure = None
    try:
        for number in (signal.SIGINT, signal.SIGTERM):
            old_handlers[number] = signal.signal(number, lambda n, frame: interrupted.append(n))
        process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        with selectors.DefaultSelector() as selector:
            for label, pipe in (("stdout", process.stdout), ("stderr", process.stderr)):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, label)
                handles[label] = (directory / (label + ".log")).open("xb")
            while selector.get_map() or process.poll() is None:
                now = time.monotonic()
                if stopped is None and (interrupted or now >= stop_at):
                    failure = "interrupted" if interrupted else "timeout"
                    stopped = now
                if stopped is not None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    if now - stopped >= 5:
                        break
                for key, _ in selector.select(timeout=0.1):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    kept = chunk[:max(0, limit - total)]
                    handles[key.data].write(kept)
                    total += len(kept)
                    if len(kept) != len(chunk) and stopped is None:
                        failure, stopped = "output-limit", time.monotonic()
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
    finally:
        try:
            if process is not None:
                # A successful leader can leave silent descendants with closed pipes.
                # Reap this invocation's group before any post-command source check.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                if process.poll() is None:
                    process.wait(timeout=5)
                for pipe in (process.stdout, process.stderr):
                    if pipe is not None:
                        pipe.close()
            for handle in handles.values():
                handle.close()
            if interrupted and failure is None:
                failure = "interrupted"
            record.update(returncode=None if process is None else process.returncode,
                          elapsed_seconds=time.monotonic() - started, captured_bytes=total,
                          incomplete_reason=failure, interrupted_signal=interrupted[0] if interrupted else None)
            record["status"] = "passed" if record["returncode"] == 0 and failure is None else "failed-or-incomplete"
            save(directory / "execution.json", record)
        finally:
            for number, handler in old_handlers.items():
                signal.signal(number, handler)
            if interrupted:
                # Cancellation dominates even failures while closing/recording.
                raise InterruptedStage(interrupted[0])
    return record


def execute(name, command, cap, *, limit=2 * 1024 * 1024, cwd=None):
    before = identity()
    directory = evidence() / name
    result = capture(command, directory, seconds=remaining(cap), limit=limit, cwd=cwd)
    if result["interrupted_signal"] is not None:
        result.update(source_before=before, source_after_status="deferred-to-post-run-receipt")
        try:
            save(directory / "execution.json", result)
        finally:
            # Receipt/source-check failures cannot demote cancellation to an
            # ordinary stage failure and accidentally start another command.
            raise InterruptedStage(result["interrupted_signal"])
    after = identity()
    result.update(source_before=before, source_after=after)
    if before != after:
        result["status"] = "failed-or-incomplete"
        result["source_changed"] = True
    save(directory / "execution.json", result)
    if result["status"] != "passed":
        raise ValueError("stage failed or incomplete: " + name)
    return evidence() / name / "stdout.log"


def inventory_record(data, package):
    active, ignored = [], []
    suites = data["rust-suites"]
    if not suites:
        raise ValueError("empty test inventory")
    for suite in suites.values():
        if suite["package-name"] != package or suite["status"] != "listed":
            raise ValueError("unexpected package or unlisted test binary")
        for name, case in suite["testcases"].items():
            if type(case["ignored"]) is not bool:
                raise ValueError("invalid ignored flag")
            if case["ignored"]:
                ignored.append(name)
            elif case["filter-match"]["status"] == "matches":
                active.append(name)
            else:
                raise ValueError("nonignored test omitted by filter")
    names = active + ignored
    if len(names) != len(set(names)) or data["test-count"] != len(names) or not active:
        raise ValueError("duplicate, empty or inconsistent test inventory")
    return {"active": sorted(active), "ignored": sorted(ignored), "total": len(names)}


def read_evidence(path, limit, *, root):
    """Read one bounded ordinary evidence file without following symlinks."""
    relative = path.relative_to(root)
    if not relative.parts or any(part in {".", ".."} for part in relative.parts):
        raise ValueError("invalid evidence path")
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        file = os.open(relative.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        with os.fdopen(file, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
                raise ValueError("evidence must be one bounded regular file")
            data = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
            fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
            if len(data) > limit or len(data) != before.st_size or any(getattr(before, f) != getattr(after, f) for f in fields):
                raise ValueError("evidence changed or exceeded its bound while reading")
            return data
    finally:
        os.close(descriptor)


def verify_results(inventory, xml_path, lane):
    data = read_evidence(xml_path, 2 * 1024 * 1024, root=xml_path.parent)
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("JUnit cannot declare document types or entities")
    root = ET.fromstring(data)
    cases = list(root.iter("testcase"))
    names = [case.attrib["name"] for case in cases]
    if len(names) != len(set(names)) or not cases:
        raise ValueError("empty or duplicate JUnit cases")
    passed, skipped, failures = [], [], []
    for case in cases:
        if case.find("failure") is not None or case.find("error") is not None:
            failures.append(case.attrib["name"])
        elif case.find("skipped") is not None:
            skipped.append(case.attrib["name"])
        else:
            passed.append(case.attrib["name"])
    if failures or set(passed) != set(inventory["active"]) or not set(skipped) <= set(inventory["ignored"]):
        raise ValueError("JUnit does not prove every freshly listed active test passed")
    leaves = [name.rsplit("::", 1)[-1] for name in passed]
    if any(leaves.count(name) != 1 for name in REQUIRED[lane]):
        raise ValueError("required behavioral regression missing or duplicated")
    return {"passed": len(passed), "executed_names": sorted(passed),
            "ignored_inventory": inventory["ignored"], "skipped_xml": sorted(skipped),
            "failures": [], "required_names": list(REQUIRED[lane])}


def run(lane):
    if lane != "automation":
        raise ValueError("only Automation is admitted in this follow-up")
    package = "codex-hepta-" + lane
    root, out = Path.cwd().resolve(), evidence()
    if identity() != json.loads((out / "source-before.json").read_text()):
        raise ValueError("source changed since pre-setup check")
    stages = {name: "not-run" for name in ("inventory", "suite", "strict")}
    save(out / "stages.json", stages)
    # Use the unchanged main policy before adding our report-only overlay.
    # Graph-dependent/global filters must not be bypassed by no-deps metadata.
    policy = runpy.run_path(str(root / "scripts/run-nextest.py"), run_name="main_slice_metadata_policy")
    policy_args = ["--locked", "-p", package, "--retries=0", "--test-threads=4"]
    if not policy["use_scoped_metadata"](policy_args, root / "codex-rs"):
        save(out / "policy.json", {"scoped_metadata_allowed": False, "package": package})
        raise ValueError("main metadata policy requires full metadata; no native stage admitted")
    save(out / "policy.json", {"scoped_metadata_allowed": True, "package": package})
    metadata = execute("metadata", ["cargo", "metadata", "--no-deps", "--format-version=1", "--locked"],
                       120, limit=16 * 1024 * 1024, cwd=root / "codex-rs")
    meta = json.loads(metadata.read_bytes())
    if meta["resolve"] is not None or Path(meta["workspace_root"]).resolve() != root / "codex-rs":
        raise ValueError("metadata workspace or no-deps mismatch")
    if not any(p["name"] == package and p["id"] in meta["workspace_members"] for p in meta["packages"]):
        raise ValueError("requested workspace package absent")
    config = out / "junit.toml"
    config.write_text('[profile.local.junit]\npath = ' + json.dumps(str(out / "suite.xml")) + '\n')
    common = ["--locked", "-p", package, "--cargo-metadata", str(metadata)]
    inventory = None
    try:
        listing = execute("inventory", ["cargo", "nextest", "list", "--message-format=json", *common],
                          2100, limit=2 * 1024 * 1024, cwd=root / "codex-rs")
        inventory = inventory_record(json.loads(listing.read_bytes()), package)
        save(out / "inventory-summary.json", inventory)
        stages["inventory"] = "passed"
    except InterruptedStage as error:
        stages["inventory"] = "interrupted"
        save(out / "stages.json", stages)
        return 128 + error.number
    except (OSError, ValueError, subprocess.SubprocessError, KeyError) as error:
        stages["inventory"] = "failed-or-incomplete"
        save(out / "inventory-error.json", {"error": str(error)})
    save(out / "stages.json", stages)
    if inventory is not None:
        try:
            execute("suite", ["just", "test", "--tool-config-file", f"main-slice:{config}", *common,
                              "--retries=0", "--test-threads=4", "--status-level=all", "--final-status-level=all"], 900)
            summary = verify_results(inventory, out / "suite.xml", lane)
            save(out / "suite-summary.json", summary)
            stages["suite"] = "passed"
        except InterruptedStage as error:
            stages["suite"] = "interrupted"
            save(out / "stages.json", stages)
            return 128 + error.number
        except (OSError, ValueError, subprocess.SubprocessError, KeyError, ET.ParseError) as error:
            stages["suite"] = "failed-or-incomplete"
            save(out / "suite-error.json", {"error": str(error)})
    save(out / "stages.json", stages)
    try:
        execute("strict", ["just", "clippy", "--locked", "-p", package, "--all-targets", "--", "-D", "warnings"], 900)
        stages["strict"] = "passed"
    except InterruptedStage as error:
        stages["strict"] = "interrupted"
        save(out / "stages.json", stages)
        return 128 + error.number
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        stages["strict"] = "failed-or-incomplete"
        save(out / "strict-error.json", {"error": str(error)})
    save(out / "stages.json", stages)
    return int(any(status != "passed" for status in stages.values()))


def after():
    out = evidence()
    record = identity()
    save(out / "source-after.json", record)
    if record != json.loads((out / "source-before.json").read_text()):
        raise ValueError("post-run source changed")


def stage():
    out = evidence()
    # Never reuse an upload directory that a native command could have planted.
    upload = Path(tempfile.mkdtemp(prefix="main-slice-upload-", dir=out.parent))
    allowed = ["source-before.json", "source-after.json", "stages.json", "policy.json", "suite.xml",
               "inventory-summary.json", "suite-summary.json", "inventory-error.json", "suite-error.json", "strict-error.json"]
    allowed += [f"{name}/{file}" for name in ("metadata", "inventory", "suite", "strict")
                for file in ("execution.json", "stderr.log")]
    allowed += [f"{name}/stdout.log" for name in ("inventory", "suite", "strict")]
    manifest, rejected = {}, []
    total = 0
    for name in allowed:
        path = out / name
        try:
            data = read_evidence(path, min(2 * 1024 * 1024, max(0, 12 * 1024 * 1024 - total)), root=out)
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            rejected.append(name)
            continue
        target = upload / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        total += len(data)
        manifest[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    qualified = False
    try:
        required = {"source-before.json", "source-after.json", "stages.json", "policy.json", "suite.xml", "inventory-summary.json", "suite-summary.json"}
        required.update(f"{name}/{file}" for name in ("metadata", "inventory", "suite", "strict") for file in ("execution.json", "stderr.log"))
        required.update(f"{name}/stdout.log" for name in ("inventory", "suite", "strict"))
        stages = json.loads(read_evidence(out / "stages.json", 2 * 1024 * 1024, root=out))
        qualified = (set(stages) == {"inventory", "suite", "strict"}
                     and required <= set(manifest)
                     and all(value == "passed" for value in stages.values()) and not rejected
                     and json.loads(read_evidence(out / "source-before.json", 2 * 1024 * 1024, root=out)) == json.loads(read_evidence(out / "source-after.json", 2 * 1024 * 1024, root=out)))
    except (OSError, ValueError):
        pass
    save(upload / "manifest.json", manifest)
    save(upload / "qualification.json", {"lane_qualified": qualified, "rejected_evidence": rejected,
                                        "merge_or_deployment_qualified": False})
    # Publish only this fresh, checked staging destination, including red lanes.
    # An unexpected staging exception produces no upload destination at all.
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
        stream.write("upload_directory=" + str(upload) + "\n")
    if not qualified:
        raise ValueError("incomplete/failed lane; bounded partial evidence retained")


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "before":
        save(evidence() / "source-before.json", identity())
    elif command == "run":
        if sys.argv[2] not in REQUIRED:
            raise ValueError("unknown lane")
        try:
            raise SystemExit(run(sys.argv[2]))
        except InterruptedStage as error:
            raise SystemExit(128 + error.number) from error
    elif command == "after":
        after()
    elif command == "stage":
        stage()
    else:
        raise ValueError("unknown action")
