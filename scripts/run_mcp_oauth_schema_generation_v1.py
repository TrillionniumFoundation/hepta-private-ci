"""Generate one real config schema from a bound local source candidate.

This owner does not publish, dispatch, retry, update locks, or qualify native
tests. Its source manifest is inactive until Root fills and accepts the inputs.
"""

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import resource
import signal
import stat
import sys
import time
from datetime import datetime, timezone

REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
BRANCH = "fix/hepta-sdk-oauth-schema-generation-20261126-7c9e"
INPUT_PATH = "scripts/hepta_mcp_oauth_schema_generation_inputs_v1.json"
SOURCE_PATHS = (
    "scripts/hepta_mcp_oauth_schema_generation_source_part1_v1.json",
    "scripts/hepta_mcp_oauth_schema_generation_source_part2_v1.json",
)
OWNER_PATH = "scripts/run_mcp_oauth_schema_generation_v1.py"
WORKFLOW_PATH = ".github/workflows/hepta-mcp-oauth-schema-generation-v1.yml"
PUBLICATION = {INPUT_PATH, *SOURCE_PATHS, OWNER_PATH, WORKFLOW_PATH}
RUNTIME_PATH = "scripts/run_chrono_hooks_cli_lock_scope_v1.py"
EXEC_PATH = "scripts/hepta_ci_exec.py"
RUNTIME_SHA = "9f7611b839ebe6518260e40cae81344169e7037a8551b1be00a2f20f28513ac2"
EXEC_SHA = "ccabe2e8066c01a612a378d42cd7580ab183870b59921442a0d208b5ac528cba"
LOCK_PATHS = ("codex-rs/Cargo.lock", "MODULE.bazel.lock")
PIN_FIELDS = ("mode", "bytes", "sha256", "git_blob")
SCHEMA_PATH = "codex-rs/core/config.schema.json"
CAPS = {"whole": 1800, "commands": 1680, "retention": 120}
PHASE_CAPS = {"source": 120, "tools": 120, "generate": 1380, "verify": 60}
GITHUB_IDENTITY = (
    "GITHUB_REPOSITORY",
    "GITHUB_RUN_ID",
    "GITHUB_RUN_ATTEMPT",
    "GITHUB_EVENT_NAME",
    "GITHUB_SHA",
    "GITHUB_REF",
    "GITHUB_HEAD_REF",
    "GITHUB_BASE_REF",
    "GITHUB_ACTOR",
    "GITHUB_WORKFLOW",
    "GITHUB_JOB",
)


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def regular(path, limit):
    before = path.lstat()
    require(
        stat.S_ISREG(before.st_mode) and before.st_size <= limit,
        f"invalid file: {path}",
    )
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        opened = os.fstat(descriptor)
        parts, size = [], 0
        while part := os.read(descriptor, min(1024 * 1024, limit + 1 - size)):
            parts.append(part)
            size += len(part)
            require(size <= limit, f"file exceeds limit: {path}")
        finished, after = os.fstat(descriptor), path.lstat()
        key = lambda item: (
            item.st_dev,
            item.st_ino,
            item.st_mode,
            item.st_size,
            item.st_mtime_ns,
            item.st_ctime_ns,
        )
        require(
            key(before) == key(opened) == key(finished) == key(after)
            and size == before.st_size,
            f"file changed: {path}",
        )
        return b"".join(parts)
    finally:
        os.close(descriptor)


def unique_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON field")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("nonfinite JSON number: " + value)

    result = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    require(isinstance(result, dict), "JSON root must be an object")
    return result


def save(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": path.name, "bytes": len(raw), "sha256": digest(raw)}


def pinned_module(root, relative, expected, name):
    raw = regular(root / relative, 128 * 1024)
    require(
        digest(raw) == expected and name not in sys.modules,
        "original helper identity or module name differs",
    )
    spec = importlib.util.spec_from_file_location(name, root / relative)
    require(spec is not None, "cannot bind original helper module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        exec(
            compile(raw, str(root / relative), "exec", dont_inherit=True, optimize=0),
            module.__dict__,
        )
    except BaseException:
        if sys.modules.get(name) is module:
            del sys.modules[name]
        raise
    return module


class Cancellation:
    """Latch signals; check before commands or within their cleanup region."""

    def __init__(self):
        self.signals = []
        self.signal_count = 0
        self.retaining = False
        self.previous = {}

    def install(self):
        for number in (signal.SIGINT, signal.SIGTERM):
            self.previous[number] = signal.getsignal(number)
            signal.signal(number, self.observe)

    def observe(self, number, _frame):
        self.signal_count += 1
        if len(self.signals) < 16:
            self.signals.append(
                {
                    "number": number,
                    "name": signal.Signals(number).name,
                    "monotonic_seconds": time.monotonic(),
                    "during_retention": self.retaining,
                }
            )

    def check(self):
        if self.signal_count and not self.retaining:
            raise KeyboardInterrupt("original scope cancellation requested")

    def restore(self):
        for number, previous in self.previous.items():
            signal.signal(number, previous)

    def receipt(self):
        return {
            "requested": self.signal_count > 0,
            "signal_count": self.signal_count,
            "signals": list(self.signals),
            "signals_omitted": self.signal_count - len(self.signals),
            "hard_kill_or_runner_loss_observable": False,
            "escaped_sessions_termination_claimed": False,
        }


class ModuleView:
    """Override only a private helper module's observed boundary calls."""

    def __init__(self, original, **overrides):
        self.original = original
        self.overrides = overrides

    def __getattr__(self, name):
        return (
            self.overrides[name]
            if name in self.overrides
            else getattr(self.original, name)
        )


def cancellable_executor(executor, cancellation, journal):
    original_execute = executor.execute_logged
    original_popen = executor.subprocess.Popen
    original_killpg = executor.os.killpg
    original_selector = executor.selectors.DefaultSelector
    original_sleep = executor.time.sleep
    active = {}

    def popen(*args, **kwargs):
        # The handler only latches: no cancellation exception can cross the
        # original helper's Popen-to-try gap before its cleanup owns the child.
        process = original_popen(*args, **kwargs)
        active["process"] = process
        active["row"]["direct_child_pid"] = process.pid
        return process

    def killpg(group, number):
        row = {"process_group": group, "signal": number, "outcome": "unobserved"}
        active["row"]["group_signals"].append(row)
        process = active.get("process")
        require(
            process is not None and group == process.pid, "original owner group differs"
        )
        try:
            result = original_killpg(group, number)
            row["outcome"] = "sent"
            return result
        except BaseException as error:
            row["outcome"] = (
                "absent" if isinstance(error, ProcessLookupError) else "failed"
            )
            row["error"] = {"type": type(error).__name__, "message": str(error)}
            raise

    class SelectorView:
        def __init__(self):
            self.selector = original_selector()

        def __enter__(self):
            self.selector.__enter__()
            return self

        def __exit__(self, *args):
            return self.selector.__exit__(*args)

        def register(self, *args):
            cancellation.check()
            return self.selector.register(*args)

        def unregister(self, *args):
            return self.selector.unregister(*args)

        def select(self, *args):
            cancellation.check()
            result = self.selector.select(*args)
            cancellation.check()
            return result

    def sleep(seconds):
        cancellation.check()
        original_sleep(seconds)
        cancellation.check()

    executor.subprocess = ModuleView(executor.subprocess, Popen=popen)
    executor.os = ModuleView(executor.os, killpg=killpg)
    executor.selectors = ModuleView(executor.selectors, DefaultSelector=SelectorView)
    executor.time = ModuleView(executor.time, sleep=sleep)

    def execute_logged(command, log, **kwargs):
        cancellation.check()
        require(not active, "original owner commands must not overlap")
        row = {
            "command": command,
            "log": str(log),
            "direct_child_pid": None,
            "group_signals": [],
            "direct_child_returncode": None,
            "owned_group_signal_and_direct_child_reap_observed": False,
        }
        journal.append(row)
        active["row"] = row
        try:
            execution = original_execute(command, log, **kwargs)
            row["original_execution"] = execution
            cancellation.check()
            return execution
        except BaseException as error:
            row["error"] = {"type": type(error).__name__, "message": str(error)}
            raise
        finally:
            process = active.get("process")
            if process is not None:
                row["direct_child_returncode"] = process.returncode
                row["owned_group_signal_and_direct_child_reap_observed"] = (
                    type(process.returncode) is int
                    and len(row["group_signals"]) == 1
                    and row["group_signals"][0]["process_group"] == process.pid
                    and row["group_signals"][0]["signal"] == signal.SIGKILL
                    and row["group_signals"][0]["outcome"] in ("sent", "absent")
                )
            row["finished_monotonic_seconds"] = time.monotonic()
            active.clear()

    return ModuleView(executor, execute_logged=execute_logged)


def context(runtime, executor, root, stage, started, cancellation):
    # Reuse the original Scope methods and physical tree reader. Initialize only
    # their documented state here so the executor runs the already-hashed raw
    # module, not a second file loader or a previously cached bytecode file.
    class SchemaScope(runtime.Scope):
        def __init__(self):
            self.source, self.stage, self.phase = root, stage, "schema"
            self.evidence = stage / "evidence"
            self.start, self.deadline = started, started + CAPS["commands"]
            self.commands, self.counter = [], 0
            self.self_cpu = resource.getrusage(resource.RUSAGE_SELF)
            self.child_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
            self.owner = executor

        def remaining(self, reserve=10.0):
            cancellation.check()
            return super().remaining(reserve)

    return SchemaScope()


def identity(scope, root):
    raw = scope.read_git(root, "cat-file", "-p", "HEAD")
    head = scope.read_git(root, "rev-parse", "HEAD").decode().strip()
    header = raw.split(b"\n\n", 1)[0].decode().splitlines()
    trees = [line[5:] for line in header if line.startswith("tree ")]
    parents = [line[7:] for line in header if line.startswith("parent ")]
    require(
        len(trees) == 1
        and hashlib.sha1(b"commit " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        == head,
        "raw commit differs",
    )
    require(
        not scope.read_git(root, "status", "--porcelain", "--untracked-files=normal"),
        "source is not clean",
    )
    return {
        "head": head,
        "tree": trees[0],
        "parents": parents,
        "raw_commit": raw.decode(),
        "dirty": False,
    }


def snapshot(runtime, scope, root, tree, name):
    value = runtime.source_snapshot(scope, root, tree)
    runtime.require_tree(value, name)
    save(scope.evidence / (name + ".json"), value)
    return value


def phase(scope, record, name, stop):
    class Phase:
        def __enter__(self):
            self.began = time.monotonic()
            scope.deadline = min(scope.start + CAPS["commands"], stop)
            require(
                self.began < scope.deadline, f"{name} phase has no remaining allowance"
            )
            return self

        def __exit__(self, kind, value, trace):
            finished = time.monotonic()
            elapsed = finished - self.began
            record.setdefault("phases", {})[name] = {
                "observed_owner_seconds": elapsed,
                "absolute_stop_monotonic": scope.deadline,
                "within_phase_deadline": finished <= scope.deadline,
                "completed_without_error": kind is None and finished <= scope.deadline,
            }
            if kind is None:
                require(
                    finished <= scope.deadline, f"{name} phase exceeded its deadline"
                )
            return False

    return Phase()


def load_inputs(root):
    raw = regular(root / INPUT_PATH, 256 * 1024)
    spec = unique_json(raw)
    require(
        spec.get("schema") == "hepta-mcp-oauth-schema-generation-input-v1"
        and spec.get("activated") is True
        and spec.get("engineering_execution_authorized") is True,
        "schema generation is inactive or lacks explicit Root execution admission",
    )
    admission = spec.get("root_admission")
    require(
        isinstance(admission, dict)
        and admission.get("reviewer") == "root"
        and admission.get("accepted") is True
        and admission.get("schema_generation_authorized") is True,
        "Root has not admitted this execution",
    )
    require(
        isinstance(admission.get("sha256"), str)
        and len(admission["sha256"]) == 64
        and all(char in "0123456789abcdef" for char in admission["sha256"]),
        "invalid Root admission hash",
    )
    require(
        spec.get("repository") == REPOSITORY
        and spec.get("branch") == BRANCH
        and spec.get("caps") == CAPS
        and spec.get("phase_caps") == PHASE_CAPS,
        "fixed scope differs",
    )
    require(
        spec.get("maximum_original_attempts") == 1
        and spec.get("first_open_only") is True
        and spec.get("publication_paths") == sorted(PUBLICATION),
        "first-open publication scope differs",
    )
    require(
        os.environ.get("GITHUB_REPOSITORY") == REPOSITORY
        and os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
        and os.environ.get("GITHUB_RUN_ATTEMPT") == "1"
        and os.environ.get("GITHUB_ACTOR") == "ProfHepta",
        "GitHub execution identity differs",
    )
    event = unique_json(regular(Path(os.environ["GITHUB_EVENT_PATH"]), 4 * 1024 * 1024))
    pull = event.get("pull_request", {})
    require(
        event.get("action") == "opened"
        and pull.get("user", {}).get("login") == "ProfHepta"
        and pull.get("draft") is True
        and pull.get("head", {}).get("repo", {}).get("full_name") == REPOSITORY
        and pull.get("head", {}).get("ref") == BRANCH,
        "event is not the one owned first-open source",
    )
    parent = spec.get("parent")
    require(
        isinstance(parent, dict)
        and all(
            isinstance(parent.get(key), str)
            and len(parent[key]) == 40
            and all(c in "0123456789abcdef" for c in parent[key])
            for key in ("head", "tree")
        ),
        "parent is not bound",
    )
    require(
        isinstance(spec.get("local_source_tree"), str)
        and len(spec["local_source_tree"]) == 40
        and all(c in "0123456789abcdef" for c in spec["local_source_tree"]),
        "local source tree is not bound",
    )
    require(
        all(
            admission.get(key) == spec.get(key)
            for key in (
                "repository",
                "branch",
                "parent",
                "local_source_tree",
                "caps",
                "phase_caps",
                "publication_paths",
                "source_paths",
            )
        ),
        "Root admission scope does not bind these exact inputs",
    )
    require(
        admission.get("maximum_original_attempts") == 1
        and admission.get("first_open_only") is True,
        "Root did not admit one first-open attempt",
    )
    require(
        isinstance(spec.get("lock_pins"), dict)
        and set(spec["lock_pins"]) == set(LOCK_PATHS),
        "exact parent lock pair is missing",
    )
    require(
        all(
            isinstance(pin, dict) and set(pin) == set(PIN_FIELDS)
            for pin in spec["lock_pins"].values()
        ),
        "lock pin fields differ",
    )
    require(
        isinstance(spec.get("old_schema"), dict)
        and set(spec["old_schema"]) == {"bytes", "git_blob"},
        "prior schema pin is missing",
    )
    require(
        isinstance(spec.get("source_paths"), list)
        and spec["source_paths"] == sorted(set(spec["source_paths"]))
        and bool(spec["source_paths"]),
        "source path set is not exact",
    )
    for path in spec["source_paths"]:
        require(
            path.startswith("codex-rs/")
            and path.endswith(".rs")
            and all(part not in ("", ".", "..", ".git") for part in path.split("/"))
            and "\\" not in path
            and "\0" not in path,
            "source path is outside the reviewed Rust scope",
        )
    pins = spec.get("reviewed_sources")
    require(
        isinstance(pins, dict)
        and set(pins) == (PUBLICATION - {INPUT_PATH}) | {RUNTIME_PATH, EXEC_PATH},
        "reviewed source pin paths differ",
    )
    retained = {INPUT_PATH: raw}
    for path, pin in pins.items():
        raw_source = regular(root / path, 512000)
        require(
            set(pin) == {"bytes", "sha256", "git_blob"}
            and pin["bytes"] == len(raw_source)
            and pin["sha256"] == digest(raw_source)
            and pin["git_blob"] == blob(raw_source),
            f"reviewed source changed: {path}",
        )
        if path in PUBLICATION:
            retained[path] = raw_source
    merged = {}
    for number, path in enumerate(SOURCE_PATHS, start=1):
        part = unique_json(retained[path])
        require(
            part.get("schema") == "hepta-mcp-oauth-schema-source-part-v1"
            and part.get("formatted") is True
            and part.get("part_index") == number
            and part.get("part_count") == 2,
            "final source part identity differs",
        )
        rows = part.get("sources")
        require(
            isinstance(rows, dict)
            and rows
            and part.get("source_paths") == sorted(rows)
            and not (set(merged) & set(rows)),
            "source part paths repeat or differ",
        )
        merged.update(rows)
    require(
        set(merged) == set(spec["source_paths"]), "combined source capsule paths differ"
    )
    return spec, {"sources": merged}, pull, digest(raw), retained


def create_candidate(runtime, scope, spec, capsule, root, record, state):
    generation = identity(scope, root)
    require(
        generation["head"] == record["pull_head"]
        and generation["parents"] == [spec["parent"]["head"]],
        "generation commit head or sole parent differs",
    )
    changed = scope.read_git(
        root, "diff", "--name-only", "-z", spec["parent"]["head"], generation["head"]
    ).split(b"\0")
    require(
        sorted(path.decode() for path in changed if path) == sorted(PUBLICATION),
        "generation publication paths differ",
    )
    parent_tree = (
        scope.read_git(root, "rev-parse", spec["parent"]["head"] + "^{tree}")
        .decode()
        .strip()
    )
    require(parent_tree == spec["parent"]["tree"], "production parent tree differs")
    record["generation"] = generation
    state["contexts"]["generation"].update(tree=generation["tree"])
    before = snapshot(
        runtime, scope, root, generation["tree"], "generation-source-before"
    )
    state["contexts"]["generation"]["before"] = before
    work = scope.stage / "work"
    state["contexts"]["local"] = {
        "root": work,
        "reference": spec["parent"]["head"],
        "head": spec["parent"]["head"],
        "tree": parent_tree,
        "parent": None,
        "before": None,
        "construction_complete": False,
    }
    scope.run(
        "create-worktree",
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "worktree",
            "add",
            "--detach",
            str(work),
            spec["parent"]["head"],
        ],
        root,
        60,
    )
    parent = snapshot(runtime, scope, work, parent_tree, "parent-source")
    for relative in spec["source_paths"]:
        scope.remaining(reserve=1)
        item = capsule["sources"][relative]
        old = item["before"]
        if old is None:
            require(relative not in parent, "new source already exists in the parent")
        else:
            require(
                isinstance(old, dict)
                and set(old) == {"bytes", "git_blob", "mode"}
                and relative in parent
                and {key: parent[relative][key] for key in old} == old,
                f"source preimage differs: {relative}",
            )
        content = item["content"].encode("utf-8")
        pin = item["after"]
        require(
            set(pin) == {"bytes", "sha256", "git_blob", "mode"}
            and pin["mode"] == "100644"
            and len(content) == pin["bytes"]
            and digest(content) == pin["sha256"]
            and blob(content) == pin["git_blob"],
            f"source postimage differs: {relative}",
        )
        target = work / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        for directory in target.parents:
            if directory == work:
                break
            require(
                directory.is_dir() and not directory.is_symlink(),
                "source parent directory changed kind",
            )
        descriptor = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o644,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        target.chmod(0o644)
    scope.run(
        "stage-reviewed-sources",
        ["git", "-c", "core.hooksPath=/dev/null", "add", "--", *spec["source_paths"]],
        work,
        8,
    )
    tree = scope.read_git(work, "write-tree").decode().strip()
    require(
        tree == spec["local_source_tree"],
        "derived source tree differs from Root's independent mapping",
    )
    state["contexts"]["local"].update(reference=tree, tree=tree)
    message = scope.evidence / "local-commit-message.txt"
    message.write_text(
        "Local schema source candidate; not the GitHub generation head.\n",
        encoding="utf-8",
    )
    timestamp = datetime.now(timezone.utc).isoformat()
    stdout, _ = scope.run(
        "local-source-commit",
        [
            "git",
            "-c",
            "commit.gpgsign=false",
            "commit-tree",
            tree,
            "-p",
            spec["parent"]["head"],
            "-F",
            str(message),
        ],
        work,
        8,
        {
            "GIT_AUTHOR_NAME": "Hepta CI Schema Source",
            "GIT_AUTHOR_EMAIL": "schema-source@hepta.invalid",
            "GIT_AUTHOR_DATE": timestamp,
            "GIT_COMMITTER_NAME": "Hepta CI Schema Source",
            "GIT_COMMITTER_EMAIL": "schema-source@hepta.invalid",
            "GIT_COMMITTER_DATE": timestamp,
        },
    )
    local_head = stdout.read_text().strip()
    require(
        len(local_head) == 40 and all(c in "0123456789abcdef" for c in local_head),
        "local commit did not produce one SHA",
    )
    scope.run(
        "bind-local-head",
        ["git", "update-ref", "HEAD", local_head, spec["parent"]["head"]],
        work,
        8,
    )
    state["contexts"]["local"].update(head=local_head, parent=spec["parent"]["head"])
    local = identity(scope, work)
    require(
        local["tree"] == tree and local["parents"] == [spec["parent"]["head"]],
        "local source parent/tree differs",
    )
    local_before = snapshot(runtime, scope, work, tree, "local-source-before")
    state["contexts"]["local"].update(before=local_before, construction_complete=True)
    for path in LOCK_PATHS:
        require(
            {
                key: local_before[path][key]
                for key in ("bytes", "sha256", "git_blob", "mode")
            }
            == spec["lock_pins"][path],
            "accepted parent lock differs",
        )
    require(
        {key: local_before[SCHEMA_PATH][key] for key in spec["old_schema"]}
        == spec["old_schema"],
        "prior schema differs",
    )
    record["local_source"] = local
    record["scope_kind"] = "SCHEMA_GENERATION_LOCAL_DERIVED_SOURCE_ONLY"
    return work, before, local_before


def prepare_tools(runtime, scope, record):
    scope.run(
        "native-prerequisites-index",
        ["sudo", "apt-get", "update", "-y"],
        scope.source,
        30,
    )
    scope.run(
        "native-prerequisites",
        [
            "sudo",
            "env",
            "DEBIAN_FRONTEND=noninteractive",
            "apt-get",
            "install",
            "-y",
            "--no-install-recommends",
            "pkg-config",
            "libcap-dev",
        ],
        scope.source,
        45,
    )
    scope.run(
        "rust-toolchain",
        [
            "rustup",
            "toolchain",
            "install",
            "1.96.0",
            "--profile",
            "minimal",
            "--no-self-update",
        ],
        scope.source,
        90,
    )
    tools = {
        "python": {
            "version": sys.version,
            "implementation": platform.python_implementation(),
            "file": runtime.tool_file(Path(sys.executable)),
        }
    }
    for name in ("cargo", "rustc"):
        stdout, _ = scope.run(
            "locate-" + name,
            ["rustup", "which", "--toolchain", "1.96.0", name],
            scope.source,
            5,
        )
        path = Path(stdout.read_text().strip())
        require(path.is_absolute(), "tool path is not absolute")
        observed = runtime.tool_file(path)
        stdout, _ = scope.run("version-" + name, [str(path), "-Vv"], scope.source, 5)
        version = stdout.read_text()
        require(
            version.splitlines()[0].startswith(name + " 1.96.0 ")
            and "\nrelease: 1.96.0\n" in "\n" + version
            and "\nhost: x86_64-unknown-linux-gnu\n" in "\n" + version,
            "actual tool release or host differs",
        )
        tools[name] = {"path": str(path), "file": observed, "version_stdout": version}
    record["tools"] = tools
    return tools


def run_generation(
    runtime, scope, spec, capsule, pull, spec_sha, retained, record, state
):
    record["pull_head"] = pull["head"]["sha"]
    record["input_sha256"] = spec_sha
    record["root_admission"] = spec["root_admission"]
    record["retained_inputs"] = {}
    for relative in sorted(PUBLICATION):
        raw = retained[relative]
        destination = scope.evidence / ("input-" + Path(relative).name)
        with destination.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        record["retained_inputs"][relative] = {
            "path": destination.name,
            "bytes": len(raw),
            "sha256": digest(raw),
            "git_blob": blob(raw),
        }
    with phase(scope, record, "source", scope.start + PHASE_CAPS["source"]):
        work, generation_before, local_before = create_candidate(
            runtime, scope, spec, capsule, scope.source, record, state
        )
    with phase(scope, record, "tools", time.monotonic() + PHASE_CAPS["tools"]):
        tools = prepare_tools(runtime, scope, record)
    output = scope.evidence / "config.schema.json"
    require(not output.exists(), "schema output was not fresh")
    with phase(scope, record, "generate", time.monotonic() + PHASE_CAPS["generate"]):
        scope.run(
            "schema-generator",
            [
                tools["cargo"]["path"],
                "run",
                "--locked",
                "-p",
                "codex-core",
                "--bin",
                "codex-write-config-schema",
                "--",
                "--out",
                str(output),
            ],
            work / "codex-rs",
            PHASE_CAPS["generate"],
            {
                "RUSTUP_TOOLCHAIN": "1.96.0",
                "RUSTC": tools["rustc"]["path"],
                "CARGO_TARGET_DIR": str(scope.stage / "target"),
                "CARGO_INCREMENTAL": "0",
                "CARGO_NET_RETRY": "0",
            },
        )
    state["generator_completed"] = True


def retained_error(record, where, error):
    record.setdefault("retention_errors", []).append(
        {
            "where": where,
            "type": type(error).__name__,
            "message": str(error),
        }
    )


def regular_ancestors(root, path):
    for parent in path.parents:
        if parent == root:
            return
        require(
            parent.is_dir() and not parent.is_symlink(),
            "source ancestor is not an owned directory",
        )
    raise ValueError("source path leaves its owned root")


def capture_source_inputs(root, evidence, record, label):
    rows = {}
    directory = evidence / ("source-inputs-" + label)
    directory.mkdir(mode=0o700)
    for relative in sorted(PUBLICATION | {RUNTIME_PATH, EXEC_PATH}):
        row = {"path": relative, "complete": False}
        rows[relative] = row
        try:
            path = root / relative
            regular_ancestors(root, path)
            raw = regular(path, 512000)
            destination = directory / relative.replace("/", "__")
            with destination.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            row.update(
                complete=True,
                bytes=len(raw),
                sha256=digest(raw),
                git_blob=blob(raw),
                retained_path=str(destination.relative_to(evidence)),
            )
        except BaseException as error:
            row["error"] = {"type": type(error).__name__, "message": str(error)}
    record["source_inputs_" + label] = rows
    record["source_inputs_" + label + "_receipt"] = save(
        evidence / ("SOURCE_INPUTS_" + label.upper() + ".json"), rows
    )
    return rows


def observed_source_file(scope, root, relative, expected_mode):
    scope.remaining(reserve=2)
    path = root / relative
    regular_ancestors(root, path)
    before = path.lstat()
    key = lambda item: (
        item.st_dev,
        item.st_ino,
        item.st_mode,
        item.st_size,
        item.st_mtime_ns,
        item.st_ctime_ns,
    )
    if stat.S_ISLNK(before.st_mode):
        raw = os.fsencode(os.readlink(path))
        require(key(before) == key(path.lstat()), "source symlink changed during read")
        return {
            "mode": "120000",
            "bytes": len(raw),
            "sha256": digest(raw),
            "git_blob": blob(raw),
        }
    require(
        stat.S_ISREG(before.st_mode), "source is not a tracked regular file or symlink"
    )
    mode = "100755" if before.st_mode & 0o111 else "100644"
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        opened = os.fstat(descriptor)
        require(
            key(opened) == key(before), "source path changed before descriptor read"
        )
        sha = hashlib.sha256()
        git = hashlib.sha1(b"blob " + str(before.st_size).encode() + b"\0")
        size = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            scope.remaining(reserve=2)
            sha.update(chunk)
            git.update(chunk)
            size += len(chunk)
        after = os.fstat(descriptor)
        require(
            key(before) == key(after) == key(path.lstat()) and size == before.st_size,
            "source changed during descriptor read",
        )
        return {
            "mode": mode,
            "bytes": size,
            "sha256": sha.hexdigest(),
            "git_blob": git.hexdigest(),
        }
    finally:
        os.close(descriptor)


def audit_source_context(scope, context, evidence, name):
    root = context["root"]
    rows = {}
    summary = {
        "root": str(root),
        "reference": context["reference"],
        "expected_tree": context.get("tree"),
        "expected_head": context.get("head"),
        "expected_parent": context.get("parent"),
        "complete": False,
        "all_reference_leaves_match": False,
        "before_after_match": None,
        "identity_match": False,
        "errors": [],
    }
    expected = []
    try:
        require(
            root.is_dir() and not root.is_symlink(),
            "source context was not materialized",
        )
        listing = scope.read_git(root, "ls-tree", "-r", "-z", context["reference"])
        seen = set()
        for entry in listing.split(b"\0"):
            if not entry:
                continue
            header, path = entry.split(b"\t", 1)
            mode, kind, expected_blob = header.decode().split()
            relative = path.decode("utf-8")
            require(
                kind == "blob"
                and mode in ("100644", "100755", "120000")
                and relative not in seen
                and not relative.startswith("/")
                and all(p not in ("", ".", "..", ".git") for p in relative.split("/")),
                "unexpected source tree entry",
            )
            seen.add(relative)
            expected.append((relative, mode, expected_blob))
        require(bool(expected), "source reference is empty")
        for relative, mode, expected_blob in expected:
            row = {
                "expected_mode": mode,
                "expected_git_blob": expected_blob,
                "matches": False,
            }
            rows[relative] = row
            try:
                observed = observed_source_file(scope, root, relative, mode)
                row.update(observed)
                row["matches"] = (
                    observed["mode"] == mode and observed["git_blob"] == expected_blob
                )
            except BaseException as error:
                row["error"] = {"type": type(error).__name__, "message": str(error)}
            if time.monotonic() >= scope.deadline - 2:
                summary["errors"].append(
                    {
                        "where": "physical_scan",
                        "message": "original verification deadline reached",
                    }
                )
                break
        summary["all_reference_leaves_match"] = len(rows) == len(expected) and all(
            row["matches"] for row in rows.values()
        )
        before = context.get("before")
        if before is not None:
            summary["before_after_match"] = set(before) == set(rows) and all(
                all(rows[path].get(key) == before[path][key] for key in PIN_FIELDS)
                for path in before
            )
    except BaseException as error:
        summary["errors"].append(
            {
                "where": "source_reference",
                "type": type(error).__name__,
                "message": str(error),
            }
        )
    # Identity and physical-leaf failures are retained independently.
    try:
        actual = identity(scope, root)
        summary["actual_identity"] = actual
        summary["identity_match"] = (
            actual["head"] == context["head"]
            and (
                context.get("parent") is None
                or actual["parents"] == [context["parent"]]
            )
            and (context.get("tree") is None or actual["tree"] == context["tree"])
        )
    except BaseException as error:
        summary["errors"].append(
            {
                "where": "identity_after",
                "type": type(error).__name__,
                "message": str(error),
            }
        )
    summary["expected_leaf_count"] = len(expected)
    summary["observed_leaf_count"] = len(rows)
    summary["unobserved_leaf_count"] = max(0, len(expected) - len(rows))
    summary["leaf_observations"] = save(evidence / (name + "-source-after.json"), rows)
    summary["complete"] = (
        bool(expected)
        and summary["all_reference_leaves_match"]
        and summary["before_after_match"] is True
        and summary["identity_match"]
        and not summary["errors"]
    )
    summary["receipt"] = save(evidence / (name + "-source-after-receipt.json"), summary)
    return summary, rows


def finish_generation_evidence(scope, spec, state, record):
    began = time.monotonic()
    scope.deadline = min(scope.start + CAPS["commands"], began + PHASE_CAPS["verify"])
    result = {
        "source_contexts": {},
        "generated_schema_verified": False,
        "complete": False,
    }
    record["final_verification"] = result
    generated = None
    local_after = None
    try:
        if state.get("generator_completed"):
            try:
                scope.remaining(reserve=2)
                generated = regular(
                    scope.evidence / "config.schema.json", 4 * 1024 * 1024
                )
                schema = unique_json(generated)
                require(
                    bool(generated)
                    and isinstance(
                        schema.get("definitions", {})
                        .get("McpServerOAuthConfig", {})
                        .get("properties", {})
                        .get("authorization_origins"),
                        dict,
                    ),
                    "generated schema lacks the owner-origin field",
                )
                record["generated_schema"] = {
                    "path": SCHEMA_PATH,
                    "bytes": len(generated),
                    "sha256": digest(generated),
                    "git_blob": blob(generated),
                }
                result["generated_schema_verified"] = True
            except BaseException as error:
                retained_error(record, "generated_schema_after", error)
        else:
            result["generated_schema_reason"] = (
                "original generator did not complete successfully"
            )
        for name in ("generation", "local"):
            context = state["contexts"].get(name)
            if context is None:
                result["source_contexts"][name] = {
                    "complete": False,
                    "reason": "source context was not created",
                }
                continue
            try:
                observed, rows = audit_source_context(
                    scope, context, scope.evidence, name
                )
                result["source_contexts"][name] = observed
                if name == "local":
                    local_after = rows
            except BaseException as error:
                result["source_contexts"][name] = {
                    "complete": False,
                    "error": {"type": type(error).__name__, "message": str(error)},
                }
                retained_error(record, name + "_source_after", error)
        source_ok = all(
            result["source_contexts"].get(name, {}).get("complete") is True
            for name in ("generation", "local")
        )
        record["source_unchanged"] = source_ok
        if result["generated_schema_verified"] and source_ok:
            try:
                scope.remaining(reserve=2)
                postimage = {
                    path: {key: item[key] for key in PIN_FIELDS}
                    for path, item in local_after.items()
                }
                postimage[SCHEMA_PATH] = {
                    "mode": local_after[SCHEMA_PATH]["mode"],
                    "bytes": len(generated),
                    "sha256": digest(generated),
                    "git_blob": blob(generated),
                }
                record["schema_only_postimage_mapping"] = save(
                    scope.evidence / "schema-only-postimage-mapping.json", postimage
                )
                record["future_publication_tree"] = None
                record["future_publication_requires_root_tree_reconstruction"] = True
                result["complete"] = True
            except BaseException as error:
                retained_error(record, "schema_postimage", error)
    finally:
        finished = time.monotonic()
        within = finished <= scope.deadline
        record.setdefault("phases", {})["verify"] = {
            "observed_owner_seconds": finished - began,
            "absolute_stop_monotonic": scope.deadline,
            "within_phase_deadline": within,
            "completed_without_error": result["complete"] and within,
            "executed_once_for_original_success_or_failure": True,
        }
        result["complete"] = result["complete"] and within
    return result["complete"]


def main():
    root = Path(__file__).resolve().parents[1]
    original_env = dict(os.environ)
    github = {
        key: value for key, value in original_env.items() if key.startswith("GITHUB_")
    }
    record = {
        "schema": "hepta-mcp-oauth-schema-generation-result-v1",
        "status": "failed",
        "caps": CAPS,
        "phase_caps": PHASE_CAPS,
        "github": {key: os.environ.get(key) for key in GITHUB_IDENTITY},
        "source_unchanged": False,
        "native_tests_executed": False,
        "qualification": {
            "generation_candidate_only": False,
            "native": False,
            "sdk_conformance": False,
            "published_stage_b": False,
        },
        "upload_and_job_terminal_required_for_root_acceptance": True,
    }
    stage = evidence = scope = started = spec = None
    evidence_owned = False
    state = {"contexts": {}, "generator_completed": False}
    commands_succeeded = verification_ok = False
    exit_code = 1
    result_ref = None
    cancellation = Cancellation()
    record["owned_command_boundaries"] = []
    try:
        cancellation.install()
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--stage", required=True, type=Path)
        args = parser.parse_args()
        stage = args.stage.resolve()
        require(
            args.stage.is_absolute()
            and args.stage == stage
            and stage.is_dir()
            and not stage.is_symlink()
            and not stage.is_relative_to(root)
            and not root.is_relative_to(stage),
            "requires the existing isolated canonical stage",
        )
        evidence = stage / "evidence"
        evidence.mkdir(mode=0o700)
        evidence_owned = True
        capture_source_inputs(root, evidence, record, "before")
        cancellation.check()
        require(
            os.name == "posix"
            and sys.platform.startswith("linux")
            and platform.machine() == "x86_64"
            and sys.version_info >= (3, 11),
            "requires x86_64 Linux and Python 3.11 or later",
        )
        clock = unique_json(regular(stage / "original-start.json", 16 * 1024))
        record["start"] = clock
        observed_start = clock["monotonic_seconds"]
        require(
            type(observed_start) in (int, float)
            and math.isfinite(observed_start)
            and 0 <= time.monotonic() - observed_start < PHASE_CAPS["source"],
            "original source deadline is missing or expired",
        )
        require(
            clock["boot_id"]
            == Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "scope start is from another boot",
        )
        require(
            clock.get("github")
            == {key: os.environ.get(key) for key in GITHUB_IDENTITY},
            "start clock GitHub identity differs",
        )
        started = observed_start
        for key in list(os.environ):
            if key.startswith("GIT_"):
                del os.environ[key]
        os.environ.update(
            {
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_NO_LAZY_FETCH": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        spec, capsule, pull, spec_sha, retained = load_inputs(root)
        cancellation.check()
        state["contexts"]["generation"] = {
            "root": root,
            "reference": pull["head"]["sha"],
            "head": pull["head"]["sha"],
            "tree": None,
            "parent": spec["parent"]["head"],
            "before": None,
        }
        runtime = pinned_module(
            root, RUNTIME_PATH, RUNTIME_SHA, "_hepta_schema_original_runtime"
        )
        executor = pinned_module(
            root, EXEC_PATH, EXEC_SHA, "_hepta_schema_original_exec"
        )
        cancellation.check()
        observed_executor = cancellable_executor(
            executor, cancellation, record["owned_command_boundaries"]
        )
        scope = context(runtime, observed_executor, root, stage, started, cancellation)
        run_generation(
            runtime, scope, spec, capsule, pull, spec_sha, retained, record, state
        )
        require(
            time.monotonic() <= started + CAPS["commands"],
            "generation command/data deadline exceeded",
        )
        cancellation.check()
        commands_succeeded = True
    except BaseException as error:
        record["error"] = {"type": type(error).__name__, "message": str(error)}
        exit_code = 130 if isinstance(error, KeyboardInterrupt) else 1
    finally:
        # Signals stay latched while the original owner cleans up and retains
        # evidence. They cannot interrupt its sole reap or convert failure to success.
        cancellation.retaining = True
        # The original verify allowance is consumed once on success or failure.
        # No source/tool/generator command is repeated and no deadline is renewed.
        if scope is not None:
            try:
                verification_ok = finish_generation_evidence(scope, spec, state, record)
            except BaseException as error:
                retained_error(record, "final_source_verification", error)
        else:
            record["final_verification"] = {
                "complete": False,
                "reason": "original pinned command scope was not admitted or constructed",
                "source_contexts": {},
            }
        if (
            evidence_owned
            and evidence is not None
            and evidence.is_dir()
            and not evidence.is_symlink()
        ):
            try:
                after = capture_source_inputs(root, evidence, record, "after")
                before = record.get("source_inputs_before", {})
                record["reviewed_source_inputs_unchanged"] = set(before) == set(
                    after
                ) == PUBLICATION | {RUNTIME_PATH, EXEC_PATH} and all(
                    before[path].get("complete") is True
                    and after[path].get("complete") is True
                    and all(
                        before[path][key] == after[path][key]
                        for key in ("bytes", "sha256", "git_blob")
                    )
                    for path in before
                )
            except BaseException as error:
                retained_error(record, "source_inputs_after", error)
        else:
            record["source_retention_unavailable"] = True
        try:
            os.environ.clear()
            os.environ.update(original_env)
            require(
                {
                    key: value
                    for key, value in os.environ.items()
                    if key.startswith("GITHUB_")
                }
                == github,
                "GitHub identity environment changed",
            )
        except BaseException as error:
            retained_error(record, "environment_restore", error)
        try:
            record["scope"] = None if scope is None else scope.receipt()
        except BaseException as error:
            retained_error(record, "scope_receipt", error)
        record["cancellation"] = cancellation.receipt()
        observed_commands = record["owned_command_boundaries"]
        record["all_observed_owned_commands_reaped"] = all(
            row["owned_group_signal_and_direct_child_reap_observed"]
            for row in observed_commands
        )
        if cancellation.signal_count:
            exit_code = 128 + cancellation.signals[0]["number"]
        record["cpu_accounting"] = {
            "per_command_cpu_seconds": None,
            "aggregate_owner_and_reaped_children_cpu_in_scope": scope is not None,
            "checkout_action_and_upload_cpu_seconds": None,
            "unobserved_cpu_is_not_zero": True,
        }
        record["elapsed_seconds_before_final_io"] = (
            None if started is None else time.monotonic() - started
        )
        ok = (
            commands_succeeded
            and verification_ok
            and not cancellation.signal_count
            and record["all_observed_owned_commands_reaped"]
            and record.get("reviewed_source_inputs_unchanged") is True
            and not record.get("retention_errors")
            and started is not None
            and time.monotonic() <= started + CAPS["commands"]
        )
        if ok:
            record["status"] = "generation_candidate"
            record["qualification"]["generation_candidate_only"] = True
            exit_code = 0
        if (
            evidence_owned
            and evidence is not None
            and evidence.is_dir()
            and not evidence.is_symlink()
        ):
            try:
                record["owned_command_evidence"] = save(
                    evidence / "OWNED_COMMAND_BOUNDARIES.json", observed_commands
                )
            except BaseException as error:
                retained_error(record, "owned_command_boundaries_write", error)
                record["status"] = "failed"
                record["qualification"]["generation_candidate_only"] = False
                exit_code = 1
            if cancellation.signal_count:
                record["status"] = "failed"
                record["qualification"]["generation_candidate_only"] = False
                record["cancellation"] = cancellation.receipt()
                exit_code = 128 + cancellation.signals[0]["number"]
            record["exit_code_before_final_io"] = exit_code
            record["late_signal_requires_final_stdout_and_original_terminal"] = True
            try:
                result_ref = save(evidence / "RESULT.json", record)
            except BaseException as error:
                retained_error(record, "RESULT_write", error)
                exit_code = 1
    # If even the trusted stage is unavailable, the complete bounded metadata
    # remains in original job stdout; the workflow retains a failed fallback.
    if result_ref is None:
        print(
            json.dumps(
                {"status": "failed", "result_unavailable": True, "record": record},
                sort_keys=True,
            ),
            flush=True,
        )
    else:
        print(
            json.dumps({"status": record["status"], "result": result_ref}), flush=True
        )
    # A signal during final serialization still fails this invocation and is
    # visible in original stdout. Final workflow/job terminal remains mandatory.
    final_cancellation = cancellation.receipt()
    if final_cancellation["requested"]:
        print(
            json.dumps(
                {"status": "failed", "final_cancellation": final_cancellation},
                sort_keys=True,
            ),
            flush=True,
        )
        exit_code = 128 + cancellation.signals[0]["number"]
    cancellation.restore()
    if cancellation.signal_count:
        exit_code = 128 + cancellation.signals[0]["number"]
    return (
        exit_code
        if started is not None and time.monotonic() <= started + CAPS["commands"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
