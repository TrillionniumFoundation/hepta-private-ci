"""Qualify default Automation and the private owner prepare/claim unit profile."""

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

BASE = "8181edc6180709653aac12f819c658b370b2654c"
SOURCE_TREE = 'bed04e4f835888b8b1a9a3897a2b668c0d7d6755'
BRANCH = "refs/heads/dot/taskflow-owner-serde-20261007"
SOURCES = {'codex-rs/hepta-automation/Cargo.toml': 'c0a5f02f01e953914dceda7e15684bbb3beffd57', 'codex-rs/hepta-automation/src/lib.rs': 'cc7c4e8d15a2608d5ad1a657b4711aadbac5be2e', 'codex-rs/hepta-automation/src/retrieval_choice_qualification/budget.rs': '092589313977cdff116a7acfacfe8d15e15bb7f2', 'codex-rs/hepta-automation/src/retrieval_choice_qualification/encoding.rs': 'be503cd7bafa3c72087bf018c4de79327c8182f2', 'codex-rs/hepta-automation/src/retrieval_choice_qualification/mod.rs': '2f3b42c06a1675cfc41d781bc4a0d8dfcae4a02f', 'codex-rs/hepta-automation/src/retrieval_choice_qualification/owner_mutations.rs': '37b526215b4628f7974bb63a231286452de16c88', 'codex-rs/hepta-automation/src/retrieval_choice_qualification/records.rs': '4034441fd90bd82d71c5f5209cb55d09bf4fd225', 'codex-rs/hepta-automation/src/retrieval_choice_qualification/root_schema.sql': '0c3d0623dbc39ecccbfbce94c3a4c705b575aef1', 'codex-rs/hepta-automation/src/retrieval_choice_qualification/tests.rs': '2086b4947a271ea2a15be64b4029bc921a53d36b', 'codex-rs/hepta-automation/src/store.rs': '7fdc158608e5e8dac6edcf51788fadd37ebbbd3a', 'codex-rs/hepta-automation/src/taskflow_step.rs': '42494d4638323c0b3449cb5a7884e2794bf6119a'}
DIAGNOSTICS = {".github/workflows/taskflow-owner-qualification.yml", "scripts/hepta_taskflow_owner_ci.py"}
CHANGED_SOURCE = {'codex-rs/hepta-automation/src/retrieval_choice_qualification/records.rs': 'M'}
REQUIRED = {
 "automation": ("run_lifecycle_is_fenced_and_command_deduplicated", "taskflow_mutations_reject_corrupt_event_chain_before_replay_or_append", "step_outbox_lifecycle_is_durable_fenced_and_idempotent", "step_outbox_failed_commands_leave_no_partial_event_and_expiry_is_fenced"),
 "owner": ('bootstrap_uses_real_history_without_step_or_choice_rows', 'explicit_close_and_reopen_preserve_owner_history_and_clock_capability', 'ordinary_open_rejects_marker_and_markerless_qualified_database', 'wrong_root_owner_and_corrupt_marker_fail_closed', 'binding_is_immutable_and_unexpected_table_inventory_rejects_reopen', 'missing_immutability_trigger_rejects_reopen_with_valid_binding_row', 'weakened_trigger_rejects_reopen_without_changing_binding_row', 'real_prepare_claim_dedup_and_reopen_never_return_second_fresh', 'prepare_failpoints_rollback_both_native_and_choice_rows', 'claim_failpoints_rollback_both_native_and_claim_rows', 'committed_ack_loss_is_history_after_reopen_not_fresh', 'independent_sqlite_pools_race_before_first_write_for_one_fresh', 'changed_command_bytes_or_activation_cannot_rebind_choice', 'expiry_preserves_prepared_and_same_byte_history_without_fresh', 'ordinary_wait_resume_fault_makes_frozen_revision_stale', 'live_cancel_is_sticky_and_phase_adds_no_unknown_or_claim', 'same_owner_other_root_capability_is_rejected_before_mutation', 'phase_rows_are_immutable_and_fk_points_to_real_native_event', 'prepare_ack_loss_preserves_atomic_pair_and_replays_as_history', 'actual_sql_inventory_over_budget_is_rejected_without_phase_writes', 'historical_prepare_rejects_corrupt_claimed_tail', 'historical_replay_rejects_corrupt_registry_definition', 'corrupted_choice_command_column_rejects_canonical_replay', 'corrupted_claim_command_column_rejects_canonical_replay', 'corrupted_choice_activation_column_rejects_canonical_replay', 'cancel_committed_after_claim_snapshot_prevents_fresh_write', 'exact_total_boundary_and_one_byte_over', 'full_observation_has_independent_hard_limit', 'duplicate_retained_records_are_counted_twice', 'utf8_and_existing_json_escape_bytes_are_preserved', 'tags_lengths_and_integer_width_are_fixed', 'aggregate_overflow_does_not_mutate_budget'),
}
DECODE_TESTS = ('fixture_fence_roundtrip_preserves_actual_serialization_and_digest', 'fixture_fence_rejects_unknown_duplicate_missing_and_invalid_fields')
REQUIRED["owner"] += DECODE_TESTS
OWNER_SQL_TESTS = ('bootstrap_uses_real_history_without_step_or_choice_rows', 'explicit_close_and_reopen_preserve_owner_history_and_clock_capability', 'ordinary_open_rejects_marker_and_markerless_qualified_database', 'wrong_root_owner_and_corrupt_marker_fail_closed', 'binding_is_immutable_and_unexpected_table_inventory_rejects_reopen', 'missing_immutability_trigger_rejects_reopen_with_valid_binding_row', 'weakened_trigger_rejects_reopen_without_changing_binding_row', 'real_prepare_claim_dedup_and_reopen_never_return_second_fresh', 'prepare_failpoints_rollback_both_native_and_choice_rows', 'claim_failpoints_rollback_both_native_and_claim_rows', 'committed_ack_loss_is_history_after_reopen_not_fresh', 'independent_sqlite_pools_race_before_first_write_for_one_fresh', 'changed_command_bytes_or_activation_cannot_rebind_choice', 'expiry_preserves_prepared_and_same_byte_history_without_fresh', 'ordinary_wait_resume_fault_makes_frozen_revision_stale', 'live_cancel_is_sticky_and_phase_adds_no_unknown_or_claim', 'same_owner_other_root_capability_is_rejected_before_mutation', 'phase_rows_are_immutable_and_fk_points_to_real_native_event', 'prepare_ack_loss_preserves_atomic_pair_and_replays_as_history', 'actual_sql_inventory_over_budget_is_rejected_without_phase_writes', 'historical_prepare_rejects_corrupt_claimed_tail', 'historical_replay_rejects_corrupt_registry_definition', 'corrupted_choice_command_column_rejects_canonical_replay', 'corrupted_claim_command_column_rejects_canonical_replay', 'corrupted_choice_activation_column_rejects_canonical_replay', 'cancel_committed_after_claim_snapshot_prevents_fresh_write')
ENCODER_TESTS = ('exact_total_boundary_and_one_byte_over', 'full_observation_has_independent_hard_limit', 'duplicate_retained_records_are_counted_twice', 'utf8_and_existing_json_escape_bytes_are_preserved', 'tags_lengths_and_integer_width_are_fixed', 'aggregate_overflow_does_not_mutate_budget')
FEATURE = "qualification-retrieval-choice"
STAGES = ("metadata_default", "automation_inventory", "automation_suite", "automation_strict", "metadata_qualified", "owner_inventory", "owner_suite", "owner_strict")



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
    expected = {**CHANGED_SOURCE, **{path: "M" for path in DIAGNOSTICS}}
    if changed != expected:
        raise ValueError("changed paths/statuses differ from exact one-source/two-diagnostic repair scope")
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
    subsets = {}
    if lane == "owner":
        subsets = {"owner_sql": sum(name in OWNER_SQL_TESTS for name in leaves),
                   "encoder": sum(name in ENCODER_TESTS for name in leaves),
                   "fixture_decode": sum(name in DECODE_TESTS for name in leaves)}
    return {"passed": len(passed), "executed_names": sorted(passed), "subsets": subsets,
            "ignored_inventory": inventory["ignored"], "skipped_xml": sorted(skipped),
            "failures": [], "required_names": list(REQUIRED[lane])}


def verify_metadata(meta, root):
    if meta["resolve"] is not None or Path(meta["workspace_root"]).resolve() != root / "codex-rs":
        raise ValueError("metadata workspace or no-deps mismatch")
    package = next(p for p in meta["packages"] if p["name"] == "codex-hepta-automation")
    if package["id"] not in meta["workspace_members"]:
        raise ValueError("Automation package not in workspace")
    if package["features"].get(FEATURE) != ["taskflow-structural-qualification"] or package["features"].get("default") != []:
        raise ValueError("owner feature must be nondefault with exact inherited structural feature")
    libraries = [t for t in package["targets"] if t["kind"] == ["lib"]]
    if len(libraries) != 1 or Path(libraries[0]["src_path"]).resolve() != root / "codex-rs/hepta-automation/src/lib.rs":
        raise ValueError("owner unit profile must use the actual Automation library")


def verify_default_inventory(data):
    inventory = inventory_record(data, "codex-hepta-automation")
    if any("retrieval_choice_qualification::" in name for name in inventory["active"] + inventory["ignored"]):
        raise ValueError("owner fixture or encoder tests reachable under default features")
    return {"default_binary_count": len(data["rust-suites"]), "owner_tests_absent": True,
            "active": len(inventory["active"]), "ignored": len(inventory["ignored"])}


def junit_config(path):
    # Every test, including a stuck two-pool barrier, has a finite deadline.
    # Existing repository overrides remain; the outer capture bounds the suite.
    return '[profile.local]\nslow-timeout = { period = "30s", terminate-after = 2 }\n[profile.local.junit]\npath = ' + json.dumps(str(path)) + '\n'


def run():
    root, out = Path.cwd().resolve(), evidence()
    if identity() != json.loads((out / "source-before.json").read_text()):
        raise ValueError("source changed since setup admission")
    states = {name: "not-run" for name in STAGES}
    save(out / "stages.json", states)
    policy = runpy.run_path(str(root / "scripts/run-nextest.py"), run_name="taskflow_metadata_policy")
    selections = {"automation": ["--locked", "-p", "codex-hepta-automation"],
                  "owner": ["--locked", "-p", "codex-hepta-automation", "--lib", "--features", FEATURE]}
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
        save(out / (path.parent.name + "-summary.json"), {"metadata_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "locked": True, "library_profile": True, "required_features": [FEATURE], "nondefault": True})
        return path

    default_meta = attempt("metadata_default", ["cargo", "metadata", "--no-deps", "--format-version=1", "--locked"], 120,
                           limit=16 * 1024 * 1024, cwd=root / "codex-rs", verify=metadata_check)
    qualified_meta = attempt("metadata_qualified", ["cargo", "metadata", "--no-deps", "--format-version=1", "--locked", "--features", "codex-hepta-automation/" + FEATURE], 120,
                             limit=16 * 1024 * 1024, cwd=root / "codex-rs", verify=metadata_check)
    for lane, metadata in (("automation", default_meta), ("owner", qualified_meta)):
        if metadata is not None:
            common = [*selections[lane], "--cargo-metadata", str(metadata)]
            def list_check(path, lane=lane):
                data = json.loads(path.read_bytes())
                if lane == "automation":
                    save(out / "automation-default-summary.json", verify_default_inventory(data))
                return inventory_record(data, "codex-hepta-automation")

            listing = attempt(lane + "_inventory", ["cargo", "nextest", "list", "--message-format=json", *common], 2100,
                              cwd=root / "codex-rs", verify=list_check)
            if listing is not None:
                save(out / (lane + "-inventory-summary.json"), listing)
                config = out / (lane + "-junit.toml")
                config.write_text(junit_config(out / (lane + "-suite.xml")))

                def suite_check(path, lane=lane, listing=listing):
                    summary = verify_results(listing, out / (lane + "-suite.xml"), lane)
                    save(out / (lane + "-suite-summary.json"), summary)
                    return summary

                attempt(lane + "_suite", ["just", "test", "--tool-config-file", f"taskflow-owner:{config}", *common,
                                         "--retries=0", "--test-threads=2", "--status-level=all", "--final-status-level=all", "--success-output=immediate"], 900, verify=suite_check)
        strict = ["just", "clippy", "--locked", "-p", "codex-hepta-automation"]
        strict += ["--lib", "--features", FEATURE] if lane == "owner" else ["--all-targets"]
        attempt(lane + "_strict", [*strict, "--", "-D", "warnings"], 900)
    return int(any(value != "passed" for value in states.values()))


def after():
    out = evidence()
    record = identity()
    save(out / "source-after.json", record)
    if record != json.loads((out / "source-before.json").read_text()):
        raise ValueError("post-run source changed")


def stage():
    out = evidence()
    upload = Path(tempfile.mkdtemp(prefix="taskflow-owner-upload-", dir=out.parent))
    required = {"source-before.json", "source-after.json", "stages.json", "policy.json",
                "metadata_default-summary.json", "metadata_qualified-summary.json", "automation-default-summary.json"}
    required.update(lane + suffix for lane in ("automation", "owner")
                    for suffix in ("-suite.xml", "-inventory-summary.json", "-suite-summary.json", "-junit.toml"))
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
                                         "complete_runtime_or_lifecycle_encoding_qualified": False,
                                         "production_schema_migration_qualified": False})
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
