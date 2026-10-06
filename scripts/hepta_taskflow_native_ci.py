"""Qualify exact TaskFlow helpers and opt-in producer encoding without runtime authority."""

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

BASE = "cb36650b1c01e7a329dcff4cf25638117475aa39"
SOURCE_TREE = '457fc0e9239ff1caa2799548fcea41362eaeeb92'
BRANCH = "refs/heads/dot/taskflow-native-encoding-box-20261006"
SOURCES = {'codex-rs/hepta-automation/src/taskflow.rs': '88262d0c26bd23582c94ed5a775c98e96abb29a2', 'codex-rs/hepta-automation/src/taskflow_step.rs': 'c0b053db1f3130959d04158e71b0ee8ab4fd70a3', 'codex-rs/hepta-automation/src/retrieval_choice_qualification/encoding.rs': 'ad3b7820badb80e4b287297879b7646149a11ac9', 'codex-rs/hepta-agent-protocol/Cargo.toml': 'a39ba6c36f32c5186511b5702e5010c01b63ca2d', 'codex-rs/hepta-agent-protocol/qualification/retrieval_choice_encoding.rs': 'ddb8da5d3cd7f525b5764cfa3a73ed44a7cda0d3'}
DIAGNOSTICS = {".github/workflows/taskflow-native-encoding.yml", "scripts/hepta_taskflow_native_ci.py"}
CHANGED_SOURCE = {"codex-rs/hepta-automation/src/taskflow_step.rs"}
REQUIRED = {
 "automation": ("run_lifecycle_is_fenced_and_command_deduplicated", "taskflow_mutations_reject_corrupt_event_chain_before_replay_or_append", "step_outbox_lifecycle_is_durable_fenced_and_idempotent", "step_outbox_failed_commands_leave_no_partial_event_and_expiry_is_fenced"),
 "protocol": ("actual_producer_types_roundtrip_without_shortening_ids", "real_serde_expansion_counts_toward_complete_observation_limit", "exact_total_boundary_and_one_byte_over", "full_observation_has_independent_hard_limit", "duplicate_retained_records_are_counted_twice", "utf8_and_existing_json_escape_bytes_are_preserved", "tags_lengths_and_integer_width_are_fixed", "aggregate_overflow_does_not_mutate_budget"),
}
TARGET = "retrieval_choice_encoding"
FEATURE = "qualification-retrieval-encoding"
STAGES = ("metadata_default", "automation_inventory", "automation_suite", "automation_strict", "protocol_default_inventory", "metadata_qualified", "protocol_inventory", "protocol_suite", "protocol_strict")


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
    expected = {path: "M" for path in CHANGED_SOURCE | DIAGNOSTICS}
    if changed != expected:
        raise ValueError("changed paths/statuses differ from exact one-source/two-diagnostic follow-up scope")
    blobs = {path: git("rev-parse", f"{head}:{path}") for path in sorted(set(SOURCES) | DIAGNOSTICS)}
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
        "sha256": {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in sorted(set(SOURCES) | DIAGNOSTICS)},
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


def verify_metadata(meta, root):
    if meta["resolve"] is not None or Path(meta["workspace_root"]).resolve() != root / "codex-rs":
        raise ValueError("metadata workspace or no-deps mismatch")
    package = next(p for p in meta["packages"] if p["name"] == "codex-hepta-agent-protocol")
    if package["id"] not in meta["workspace_members"]:
        raise ValueError("protocol package not in workspace")
    target = next(t for t in package["targets"] if t["name"] == TARGET)
    if target.get("required-features") != [FEATURE] or target["kind"] != ["test"]:
        raise ValueError("qualification target is not explicitly feature-gated")
    expected = root / "codex-rs/hepta-agent-protocol/qualification/retrieval_choice_encoding.rs"
    if Path(target["src_path"]).resolve() != expected:
        raise ValueError("qualification target moved into default discovery")
    if package["features"].get(FEATURE) != [] or FEATURE in package["features"].get("default", []):
        raise ValueError("qualification feature must be empty and nondefault")


def verify_default_inventory(data):
    suites = data["rust-suites"]
    if not suites:
        raise ValueError("empty protocol default binary inventory")
    for key, suite in suites.items():
        if suite["package-name"] != "codex-hepta-agent-protocol":
            raise ValueError("default inventory includes unexpected package")
        if TARGET in key or TARGET in json.dumps(suite):
            raise ValueError("qualification target reachable under default features")
    return {"default_binary_count": len(suites), "qualification_target_absent": True}


def run():
    root, out = Path.cwd().resolve(), evidence()
    if identity() != json.loads((out / "source-before.json").read_text()):
        raise ValueError("source changed since setup admission")
    states = {name: "not-run" for name in STAGES}
    save(out / "stages.json", states)
    policy = runpy.run_path(str(root / "scripts/run-nextest.py"), run_name="taskflow_metadata_policy")
    selections = {"automation": ["--locked", "-p", "codex-hepta-automation"],
                  "protocol": ["--locked", "-p", "codex-hepta-agent-protocol", "--test", TARGET, "--features", FEATURE]}
    for selection in selections.values():
        if not policy["use_scoped_metadata"](selection, root / "codex-rs"):
            raise ValueError("repository metadata policy requires full graph; stage not admitted")
    save(out / "policy.json", {"scoped_metadata_allowed": True, "selections": selections})

    def attempt(name, command, cap, *, limit=2 * 1024 * 1024, cwd=None, verify=None):
        try:
            path = execute(name, command, cap, limit=limit, cwd=cwd)
            result = verify(path) if verify else path
            states[name] = "passed"
            save(out / "stages.json", states)
            return result
        except InterruptedStage as error:
            states[name] = "interrupted"
            try:
                save(out / "stages.json", states)
            finally:
                raise error
        except (OSError, ValueError, subprocess.SubprocessError, KeyError, StopIteration, ET.ParseError) as error:
            states[name] = "failed-or-incomplete"
            save(out / (name + "-error.json"), {"error": str(error)})
            save(out / "stages.json", states)
            return None

    def metadata_check(path):
        verify_metadata(json.loads(path.read_bytes()), root)
        save(out / (path.parent.name + "-summary.json"), {"metadata_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "locked": True, "target": TARGET, "required_features": [FEATURE], "nondefault": True})
        return path

    default_meta = attempt("metadata_default", ["cargo", "metadata", "--no-deps", "--format-version=1", "--locked"], 120,
                           limit=16 * 1024 * 1024, cwd=root / "codex-rs", verify=metadata_check)
    qualified_meta = attempt("metadata_qualified", ["cargo", "metadata", "--no-deps", "--format-version=1", "--locked", "--features", "codex-hepta-agent-protocol/" + FEATURE], 120,
                             limit=16 * 1024 * 1024, cwd=root / "codex-rs", verify=metadata_check)
    for lane, metadata in (("automation", default_meta), ("protocol", qualified_meta)):
        if metadata is not None:
            common = [*selections[lane], "--cargo-metadata", str(metadata)]
            listing = attempt(lane + "_inventory", ["cargo", "nextest", "list", "--message-format=json", *common], 2100,
                              cwd=root / "codex-rs", verify=lambda p, lane=lane: inventory_record(json.loads(p.read_bytes()), "codex-hepta-" + ("agent-protocol" if lane == "protocol" else lane)))
            if listing is not None:
                save(out / (lane + "-inventory-summary.json"), listing)
                if lane == "protocol" and len(listing["active"]) != len(REQUIRED[lane]):
                    raise ValueError("explicit protocol target did not list exactly eight reviewed tests")
                config = out / (lane + "-junit.toml")
                config.write_text('[profile.local.junit]\npath = ' + json.dumps(str(out / (lane + "-suite.xml"))) + '\n')

                def suite_check(path, lane=lane, listing=listing):
                    summary = verify_results(listing, out / (lane + "-suite.xml"), lane)
                    save(out / (lane + "-suite-summary.json"), summary)
                    return summary

                attempt(lane + "_suite", ["just", "test", "--tool-config-file", f"taskflow-native:{config}", *common,
                                         "--retries=0", "--test-threads=4", "--status-level=all", "--final-status-level=all", "--success-output=immediate"], 900, verify=suite_check)
        strict = ["just", "clippy", "--locked", "-p", "codex-hepta-" + ("agent-protocol" if lane == "protocol" else lane)]
        strict += ["--test", TARGET, "--features", FEATURE] if lane == "protocol" else ["--all-targets"]
        attempt(lane + "_strict", [*strict, "--", "-D", "warnings"], 900)
    if default_meta is not None:
        def default_check(path):
            result = verify_default_inventory(json.loads(path.read_bytes()))
            save(out / "protocol-default-summary.json", result)
            return result
        attempt("protocol_default_inventory", ["cargo", "nextest", "list", "--message-format=json", "--locked", "-p", "codex-hepta-agent-protocol", "--cargo-metadata", str(default_meta)], 900,
                cwd=root / "codex-rs", verify=default_check)
    return int(any(value != "passed" for value in states.values()))


def after():
    out = evidence()
    record = identity()
    save(out / "source-after.json", record)
    if record != json.loads((out / "source-before.json").read_text()):
        raise ValueError("post-run source changed")


def stage():
    out = evidence()
    upload = Path(tempfile.mkdtemp(prefix="taskflow-native-upload-", dir=out.parent))
    required = {"source-before.json", "source-after.json", "stages.json", "policy.json",
                "metadata_default-summary.json", "metadata_qualified-summary.json", "protocol-default-summary.json"}
    required.update(lane + suffix for lane in ("automation", "protocol")
                    for suffix in ("-suite.xml", "-inventory-summary.json", "-suite-summary.json"))
    required.update(f"{name}/{file}" for name in STAGES for file in ("execution.json", "stderr.log"))
    required.update(f"{name}/stdout.log" for name in STAGES if not name.startswith("metadata_"))
    allowed = sorted(required | {name + "-error.json" for name in STAGES})
    manifest, rejected, total = {}, [], 0
    for name in allowed:
        try:
            data = read_evidence(out / name, min(2 * 1024 * 1024, max(0, 12 * 1024 * 1024 - total)), root=out)
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
        states = json.loads(read_evidence(out / "stages.json", 2 * 1024 * 1024, root=out))
        qualified = (set(states) == set(STAGES) and required <= set(manifest)
                     and all(value == "passed" for value in states.values()) and not rejected
                     and json.loads(read_evidence(out / "source-before.json", 2 * 1024 * 1024, root=out))
                     == json.loads(read_evidence(out / "source-after.json", 2 * 1024 * 1024, root=out)))
    except (OSError, ValueError):
        pass
    save(upload / "manifest.json", manifest)
    save(upload / "qualification.json", {"scoped_native_qualified": qualified, "rejected_evidence": rejected,
                                         "merge_or_deployment_qualified": False,
                                         "complete_runtime_or_lifecycle_encoding_qualified": False})
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
        stream.write("upload_directory=" + str(upload) + "\n")
    if not qualified:
        raise ValueError("incomplete/failed stages; bounded original evidence retained")


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "before":
        save(evidence() / "source-before.json", identity())
    elif command == "run":
        try:
            raise SystemExit(run())
        except InterruptedStage as error:
            raise SystemExit(128 + error.number) from error
    elif command == "after":
        after()
    elif command == "stage":
        stage()
    else:
        raise ValueError("unknown action")
