"""One first native12-plus3 scope; no dispatch or retry from inactive inputs."""

from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import signal
import stat
import time

ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_SHA256 = "8321e6e0c0bcaa2833832a5fdcf7ad0f44cb06e07801d0f582ebd258ba7a42d4"  # Root fills only after formatting the reviewed protocol.


SPEC = "scripts/hepta_sqlx_native_inputs_v2.json"
RECEIPTS = {
    "qualification/sqlx_native_generation_acceptance_v2.json": "generation_acceptance_pin",
    "qualification/sqlx_native12_plus3_admission_v2.json": "native_admission_pin",
}


def read_regular(path, maximum):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= maximum:
            raise ValueError("source is not a bounded regular file")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (
        len(raw) != before.st_size
        or len(raw) > maximum
        or any(getattr(before, key) != getattr(after, key) for key in fields)
    ):
        raise ValueError("source changed while reading")
    return raw


def retain_bytes(path, raw):
    with path.open("xb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())


def load_checked(path, expected, name):
    raw = read_regular(path, 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("unbound or changed module source: " + str(path))
    description = importlib.util.spec_from_file_location(name, path)
    if description is None or description.loader is None:
        raise ValueError("module specification is unavailable")
    loaded = importlib.util.module_from_spec(description)
    # Preserve the former module metadata and lack of sys.modules registration.
    # Execute this checked buffer, without loader.get_code/exec_module or pyc.
    exec(compile(raw, str(path), "exec", dont_inherit=True), loaded.__dict__)
    return loaded


def final_source_checks(
    result, spec, input_raw, protocol, scope, directory, started, owner, before
):
    began = time.monotonic()
    deadline = (
        min(scope.deadline, began + 120 - scope.spent["verification"])
        if scope is not None
        else started + 120
    )
    findings = result["final_source_verification"] = {}
    rows = []
    supplied = spec if isinstance(spec, dict) else {}
    required = protocol.REQUIRED_PINS if protocol is not None else set()
    for label, names in (
        ("source_pins", required),
        (
            "accepted_locks",
            {
                "MODULE.bazel.lock",
                "codex-rs/Cargo.lock",
                "qualification/sqlx_temporal_default_v1/Cargo.lock",
                "qualification/sqlx_temporal_explicit_chrono_v1/Cargo.lock",
            },
        ),
    ):
        pins = supplied.get(label)
        if not isinstance(pins, dict) or not 0 < len(pins) <= 256:
            findings[label] = {
                "status": "unavailable",
                "error": "bounded pin roster unavailable",
            }
            pins = {}
        rows.extend(
            (label + ":" + name, name, pins.get(name), False)
            for name in sorted(set(pins) | names)
        )
    input_pin = (
        None
        if input_raw is None
        else {"bytes": len(input_raw), "sha256": hashlib.sha256(input_raw).hexdigest()}
    )
    rows.append(("inputs", SPEC, input_pin, True))
    rows.extend(
        ("receipt:" + path, path, supplied.get(key), True)
        for path, key in RECEIPTS.items()
    )
    rows.append(
        (
            "bootstrap_protocol",
            "scripts/hepta_sqlx_native_protocol_v2.py",
            {"sha256": PROTOCOL_SHA256},
            False,
        )
    )
    for label, relative, pin, retain in rows:
        row = findings[label] = {"path": relative, "expected": pin, "status": "failed"}
        try:
            if time.monotonic() >= deadline:
                raise TimeoutError("final source verification budget exhausted")
            path = Path(relative)
            if (
                path.is_absolute()
                or ".." in path.parts
                or path.as_posix() != relative
                or not (ROOT / path).resolve().is_relative_to(ROOT)
            ):
                raise ValueError("source path escapes the checkout")
            raw = read_regular(ROOT / path, 64 * 1024 * 1024)
            row["observed"] = {
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            if retain:
                if directory is None:
                    raise ValueError("original evidence directory was not created")
                retained = directory / path.name
                if not retained.exists():
                    retain_bytes(retained, raw)
                retained_raw = read_regular(retained, 64 * 1024 * 1024)
                row["retained_sha256"] = hashlib.sha256(retained_raw).hexdigest()
                if retained_raw != raw:
                    raise ValueError("retained input and final source differ")
            if (
                not isinstance(pin, dict)
                or not isinstance(pin.get("sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]) is None
            ):
                raise ValueError("actual expected pin is unavailable")
            if label != "bootstrap_protocol" and (
                type(pin.get("bytes")) is not int
                or not 0 <= pin["bytes"] <= 64 * 1024 * 1024
                or pin["bytes"] != len(raw)
            ):
                raise ValueError("source byte count differs or is unbound")
            if row["observed"]["sha256"] != pin["sha256"]:
                raise ValueError("source SHA256 differs")
            if (
                "git_blob_sha1" in pin
                and hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
                != pin["git_blob_sha1"]
            ):
                raise ValueError("source Git blob differs")
            if time.monotonic() >= deadline:
                raise TimeoutError("source observation exceeded verification deadline")
            row["status"] = "passed"
        except Exception as error:
            row["error"] = f"{type(error).__name__}: {error}"
    identity = findings["identity"] = {"status": "unavailable", "before": before}
    try:
        if time.monotonic() >= deadline:
            raise TimeoutError("identity verification budget exhausted")
        if owner is None:
            raise ValueError("verified original identity owner was not loaded")
        after = owner.identity()
        result["after"] = identity["after"] = after
        expected = supplied.get("accepted_source", {})
        parent = expected.get("parent_head") if isinstance(expected, dict) else None
        tree = expected.get("parent_tree") if isinstance(expected, dict) else None
        identity["expected_parent"] = parent
        identity["expected_parent_tree"] = tree
        if not isinstance(parent, str) or re.fullmatch(r"[0-9a-f]{40}", parent) is None:
            raise ValueError("actual expected parent is unavailable")
        identity["observed_parent_tree"] = owner.git("rev-parse", parent + "^{tree}")
        identity["checks"] = {
            "before_after_equal": before is not None and after == before,
            "clean": after["dirty"] is False,
            "source_head": after["commit"]
            == os.environ.get("SOURCE_SHA")
            == os.environ.get("TESTED_SHA"),
            "sole_parent": after["parents"] == [parent],
            "parent_tree": identity["observed_parent_tree"] == tree,
        }
        if not all(identity["checks"].values()):
            raise ValueError("original source identity or admitted parent differs")
        if time.monotonic() >= deadline:
            raise TimeoutError("identity observation exceeded verification deadline")
        identity["status"] = "passed"
    except Exception as error:
        identity["error"] = f"{type(error).__name__}: {error}"
    result["source_postcheck_errors"] = {
        name: row.get("error", "unverified")
        for name, row in findings.items()
        if row["status"] != "passed"
    }
    if scope is not None:
        scope.spent["verification"] += time.monotonic() - began
        result["phase_elapsed_seconds"] = dict(scope.spent)
    else:
        result["phase_elapsed_seconds"] = {"verification": time.monotonic() - started}
    return not result["source_postcheck_errors"]


def require(condition, message):
    if not condition:
        raise ValueError(message)


class Cancellation:
    """Latch signals; raise only inside the original command cleanup region."""

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

    # owner.run resolves execute_logged in this private module's globals.
    # Assign here so its callbacks use the tracked protected cleanup boundary.
    executor.execute_logged = execute_logged
    return executor


class Scope:
    def __init__(self, old, spec, result, directory, started, admission, cancellation):
        self.old, self.spec, self.result, self.directory = old, spec, result, directory
        self.started, self.cancellation = started, cancellation
        self.deadline = min(started + 2880, admission["job_started_monotonic"] + 3360)
        self.spent = {key: 0.0 for key in spec["budget"]["phases"]}
        self.spent["verification"] = time.monotonic() - started
        self.active = None
        self.before = self.owner = None
        self.target_root = directory.parent.parent / "targets"
        self.target_root.mkdir(mode=0o700, exist_ok=False)

    @contextmanager
    def phase(self, name):
        self.old.require(self.active is None, "phase scopes must not overlap")
        self.active, self.phase_start = name, time.monotonic()
        try:
            self.check_time()
            yield
            self.check_time()
        finally:
            self.spent[name] += time.monotonic() - self.phase_start
            self.active = None
            self.result["phase_elapsed_seconds"] = dict(self.spent)

    def check_time(self):
        self.cancellation.check()
        reserve = (
            0 if self.active == "verification" else 120 - self.spent["verification"]
        )
        remaining = min(
            self.deadline - time.monotonic() - max(0, reserve),
            self.spec["budget"]["phases"][self.active]
            - self.spent[self.active]
            - (time.monotonic() - self.phase_start),
        )
        self.old.require(
            remaining > 0, "shared scope or cumulative phase budget exhausted"
        )
        return remaining

    def invoke(
        self,
        name,
        command,
        *,
        minimum=0,
        allow_failed=False,
        target="main",
        fixture_rustc=None,
    ):
        old = self.old
        cap = self.check_time() - 1
        old.require(cap > 0, "no original owner reap reserve remains")
        record_path = self.directory / (name + ".json")
        row = {
            "name": name,
            "command": command,
            "phase": self.active,
            "record": record_path.name,
            "status": "dispatching",
        }
        self.result["commands"].append(row)
        overrides = {"CARGO_TARGET_DIR": str(self.target_root / target)}
        previous = {key: os.environ.get(key) for key in (*overrides, "RUSTC")}
        try:
            os.environ.update(overrides)
            if fixture_rustc is None:
                os.environ.pop("RUSTC", None)
            else:
                os.environ["RUSTC"] = fixture_rustc
            code = self.owner.run(
                record_path, command, minimum_tests=minimum, timeout_seconds=cap
            )
            row["owner_exit_code"] = code
            self.cancellation.check()
            raw_record = old.read_regular(record_path, 1024 * 1024)
            record = old.strict_json(raw_record)
            row.update(
                status=record["status"],
                owner_exit_code=code,
                record_sha256=old.digest(raw_record),
            )
            old.require(
                record["before"] == self.before == record.get("after")
                and record["command"] == command
                and record["source_sha"] == self.before["commit"]
                and record["tested_sha"] == self.before["commit"]
                and record["lane"] == "source-head",
                "original command source or exact argv changed",
            )
            old.require(
                Path(record["log_file"]).name == record["log_file"],
                "original command log escaped its owner",
            )
            raw = old.read_regular(
                self.directory / record["log_file"], 64 * 1024 * 1024
            )
            old.require(
                old.digest(raw) == record["log_sha256"]
                and len(raw) == record["log_bytes"],
                "raw command log changed",
            )
            if not allow_failed:
                old.require(
                    code == 0
                    and record["status"] == "passed"
                    and record["command_exit_code"] == 0
                    and record["timed_out"] is False
                    and record["output_limit_exceeded"] is False,
                    "required command did not complete successfully",
                )
            for path, pin in self.spec["accepted_locks"].items():
                old.check_pin(path, pin)
            return record, raw, record_path
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def metadata(scope, old, tools, tool_module):
    tool_module.check_versions(scope, old, tools)
    _, raw, _ = scope.invoke(
        "consumer-target-roster",
        ["cargo", "+1.96.0", "metadata", "--locked", "--no-deps", "--format-version=1"],
    )
    found = [
        row
        for row in old.metadata_from_log(raw)["packages"]
        if row["name"] in old.PACKAGES
    ]
    old.require(
        len(found) == 12 and {row["name"] for row in found} == set(old.PACKAGES),
        "the complete twelve-consumer package roster changed",
    )
    targets = {}
    for package in found:
        rows = []
        for original in package["targets"]:
            target = dict(original)
            target["src_path"] = Path(target["src_path"]).relative_to(ROOT).as_posix()
            rows.append(target)
        targets[package["name"]] = sorted(rows, key=old.canonical)
    old.require(
        old.digest(old.canonical(targets))
        == scope.spec["accepted_consumer_targets_sha256"],
        "complete actual consumer target declarations differ",
    )
    scope.result["declared_targets"] = targets
    scope.result["required_feature_declarations_not_claimed_compiled"] = [
        {"package": name, "target": row["name"], "features": row["required-features"]}
        for name, rows in targets.items()
        for row in rows
        if row.get("required-features")
    ]
    for label, relative, compatibility in (
        ("default", old.DEFAULT, False),
        ("compatibility", old.COMPATIBILITY, True),
    ):
        _, raw, _ = scope.invoke(
            label + "-graph",
            [
                tools["fixture_cargo"]["path"],
                "metadata",
                "--locked",
                "--format-version=1",
                "--filter-platform",
                old.TARGET,
                "--manifest-path",
                str(ROOT / relative / "Cargo.toml"),
            ],
            target=label,
            fixture_rustc=tools["rustc"]["path"],
        )
        scope.result[label + "_graph"] = old.check_fixture_graph(
            raw, scope.spec["expected_fixture_graph_sha256"][label], compatibility
        )


def compile_cases(scope, old, tools):
    packages = [item for name in old.PACKAGES for item in ("-p", name)]
    scope.invoke(
        "twelve-consumer-compile",
        [
            "cargo",
            "+1.96.0",
            "check",
            "--locked",
            "--all-targets",
            "--target",
            old.TARGET,
            *packages,
        ],
    )
    scope.result["consumer_compile"] = {
        "packages": list(old.PACKAGES),
        "status": "passed",
    }
    for label, relative, binary, target, negative in (
        ("default-scalar-positive", old.DEFAULT, "scalar_public", "default", False),
        ("default-chrono-refusal", old.DEFAULT, old.NEGATIVE_NAME, "default", True),
        (
            "explicit-chrono-positive",
            old.COMPATIBILITY,
            "chrono_explicit",
            "compatibility",
            False,
        ),
    ):
        record, raw, _ = scope.invoke(
            label,
            [
                tools["fixture_cargo"]["path"],
                "check",
                "--locked",
                "--target",
                old.TARGET,
                "--manifest-path",
                str(ROOT / relative / "Cargo.toml"),
                "--bin",
                binary,
                "--message-format=json",
            ],
            target=target,
            allow_failed=negative,
            fixture_rustc=tools["rustc"]["path"],
        )
        if negative:
            scope.result["negative_interpretation"] = old.check_exact_refusal(
                record, raw, scope.result["default_graph"]["root_package_id"]
            )


def native_command(old):
    expression = " | ".join(
        "(binary_id(=" + binary + ") & test(=" + name + "))"
        for binary, name in old.NATIVE_CASES
    )
    return [
        "just",
        "test",
        "--locked",
        "--target",
        old.TARGET,
        "-p",
        "codex-state",
        "-p",
        "codex-hepta-operations",
        "-p",
        "codex-thread-store",
        "--lib",
        "--test",
        "destination_recovery_binding",
        "--retries",
        "0",
        "--test-threads",
        "1",
        "--status-level",
        "pass",
        "--final-status-level",
        "fail",
        "-E",
        expression,
    ]


def collect_native(scope, old, collector, native):
    record, raw, record_path = native
    retained = scope.directory / "native-twelve.junit.xml"
    code = collector.collect(
        record_path, ROOT / "codex-rs/target/nextest/local/junit.xml", retained
    )
    summary_raw = old.read_regular(retained.with_suffix(".summary.json"), 1024 * 1024)
    summary = old.strict_json(summary_raw)
    scope.result["native_junit_collection"] = {
        "exit_code": code,
        "summary_sha256": old.digest(summary_raw),
        "status": summary["status"],
    }
    old.require(
        code == 0
        and record["status"] == "passed"
        and record["exit_code"] == record["command_exit_code"] == 0
        and record["timed_out"] is False
        and record["output_limit_exceeded"] is False
        and record["observed_passed_tests"] == 12
        and record["observed_failed_tests"] == 0,
        "original native command or fresh XML collection did not pass",
    )
    xml = old.read_regular(retained, 64 * 1024 * 1024)
    old.require(
        old.digest(xml) == summary["junit_sha256"]
        and summary["execution_sha256"]
        == old.digest(old.read_regular(record_path, 1024 * 1024)),
        "native XML/command identity changed",
    )
    scope.result["native"] = old.check_native_xml(xml, raw, collector)


def main():
    started = time.monotonic()
    cpu = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {
        "schema": "hepta-sqlx-native12-plus3-observation-v2",
        "status": "rejected",
        "commands": [],
        "qualification": False,
        "chrono_removed": False,
        "E1_E6_added": 0,
        "old_generation_replays": 0,
    }
    protocol = spec = old = scope = tools = tool_module = collector = native = None
    directory = input_raw = owner = before = None
    code = 2
    original_cwd = Path.cwd()
    overrides = {
        "RUSTUP_TOOLCHAIN": "1.96.0",
        "CARGO_NET_RETRY": "0",
        "RUSTC_WRAPPER": "",
        "RUSTC_WORKSPACE_WRAPPER": "",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    previous = {key: os.environ.get(key) for key in overrides}
    cancellation = Cancellation()
    owned_commands = result["owned_command_observations"] = []
    try:
        cancellation.install()
        cancellation.check()
        stage = Path(os.environ["SQLX_NATIVE_STAGE"])
        proposed = stage / "evidence/native"
        proposed.mkdir(mode=0o700, parents=False, exist_ok=False)
        directory = proposed
        input_raw = read_regular(ROOT / SPEC, 1024 * 1024)
        result["inputs_sha256"] = hashlib.sha256(input_raw).hexdigest()
        spec = json.loads(input_raw)
        retain_bytes(directory / Path(SPEC).name, input_raw)
        protocol = load_checked(
            ROOT / "scripts/hepta_sqlx_native_protocol_v2.py",
            PROTOCOL_SHA256,
            "sqlx_native_protocol",
        )
        spec, old = protocol.bootstrap(load_checked, input_raw)
        cancellation.check()
        owner = load_checked(
            ROOT / "scripts/hepta_ci_exec.py", old.OWNER_SHA256, "sqlx_native_exec"
        )
        owner = cancellable_executor(owner, cancellation, owned_commands)
        cancellation.check()
        os.chdir(ROOT / "codex-rs")
        before = owner.identity()
        result["before"] = before
        admission = protocol.admit(spec, old, stage / "evidence")
        result["admission"] = admission
        cancellation.check()
        scope = Scope(old, spec, result, directory, started, admission, cancellation)
        scope.owner, scope.before = owner, before
        for source, key in RECEIPTS.items():
            retain_bytes(
                directory / Path(source).name, old.check_pin(source, spec[key])
            )
        with scope.phase("verification"):
            collector = load_checked(
                ROOT / "scripts/hepta_ci_junit.py",
                old.COLLECTOR_SHA256,
                "sqlx_native_junit",
            )
            tool_path = "scripts/hepta_sqlx_native_tools_v2.py"
            tool_module = load_checked(
                ROOT / tool_path,
                spec["source_pins"][tool_path]["sha256"],
                "sqlx_native_tools",
            )
            os.environ.update(overrides)
            old.require(
                before["dirty"] is False
                and before["commit"] == admission["source_sha"]
                and before["parents"] == [spec["accepted_source"]["parent_head"]]
                and owner.git(
                    "rev-parse", spec["accepted_source"]["parent_head"] + "^{tree}"
                )
                == spec["accepted_source"]["parent_tree"],
                "candidate is not the exact clean child of the admitted parent",
            )
        with scope.phase("official_cargo"):
            tools = tool_module.prepare(scope, old)
        with scope.phase("metadata"):
            metadata(scope, old, tools, tool_module)
        with scope.phase("compile"):
            compile_cases(scope, old, tools)
        with scope.phase("native"):
            native = scope.invoke(
                "native-twelve", native_command(old), minimum=12, allow_failed=True
            )
        code = 0
    except KeyboardInterrupt as error:
        result.update(status="interrupted", error=str(error))
        code = 130
    except Exception as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
    finally:
        cancellation.retaining = True
        boundary_started = time.monotonic()
        boundary_deadline = (
            min(
                scope.deadline,
                boundary_started + max(0, 120 - scope.spent["verification"]),
            )
            if scope is not None
            else started + 120
        )
        try:
            if time.monotonic() >= boundary_deadline:
                raise TimeoutError("owned-boundary retention budget exhausted")
            if directory is None:
                raise ValueError("original evidence directory was not created")
            boundary_raw = (
                json.dumps(
                    {
                        "schema": "hepta-sqlx-owned-command-boundaries-v1",
                        "commands": owned_commands,
                        "cancellation": cancellation.receipt(),
                        "captured_monotonic_seconds": time.monotonic(),
                        "qualification": False,
                        "observation_only": True,
                        "requires_final_result_and_actual_original_exit": True,
                    },
                    indent=2,
                    sort_keys=True,
                ).encode()
                + b"\n"
            )
            retain_bytes(directory / "OWNED_COMMAND_BOUNDARIES.json", boundary_raw)
            result["owned_command_boundaries"] = {
                "file": "OWNED_COMMAND_BOUNDARIES.json",
                "bytes": len(boundary_raw),
                "sha256": hashlib.sha256(boundary_raw).hexdigest(),
                "observation_only": True,
            }
            if time.monotonic() >= boundary_deadline:
                raise TimeoutError(
                    "owned-boundary retention exceeded verification deadline"
                )
        except Exception as error:
            result["owned_boundary_retention_error"] = (
                f"{type(error).__name__}: {error}"
            )
            code = code or 2
        finally:
            if scope is not None:
                scope.spent["verification"] += time.monotonic() - boundary_started
        if scope is not None:
            try:
                with scope.phase("verification"):
                    issued = any(
                        row["name"] == "native-twelve" for row in result["commands"]
                    )
                    original_xml = ROOT / "codex-rs/target/nextest/local/junit.xml"
                    if issued and original_xml.exists():
                        try:
                            raw_xml = old.read_regular(original_xml, 64 * 1024 * 1024)
                            retain_bytes(
                                directory / "original-junit-unverified.xml", raw_xml
                            )
                            result["unverified_xml_retained"] = {
                                "bytes": len(raw_xml),
                                "sha256": old.digest(raw_xml),
                                "not_a_passing_observation": True,
                            }
                        except Exception as error:
                            result["unverified_xml_retention_error"] = (
                                f"{type(error).__name__}: {error}"
                            )
                            code = code or 2
                    if native is not None:
                        try:
                            collect_native(scope, old, collector, native)
                        except Exception as error:
                            result["native_collection_error"] = (
                                f"{type(error).__name__}: {error}"
                            )
                            code = code or 2
                    if tools is not None:
                        try:
                            tool_module.recheck(
                                old,
                                tools,
                                directory,
                                result.get("verified_v8_pair", {}),
                            )
                        except Exception as error:
                            result["tool_postcheck_error"] = (
                                f"{type(error).__name__}: {error}"
                            )
                            code = code or 2
            except Exception as error:
                result["postcheck_error"] = f"{type(error).__name__}: {error}"
                code = code or 2
        if not final_source_checks(
            result, spec, input_raw, protocol, scope, directory, started, owner, before
        ):
            code = code or 2
        if cancellation.signal_count:
            code = code or 130
        result["cancellation_observed_before_final_io"] = cancellation.signal_count > 0
        result["cancellation"] = cancellation.receipt()
        result["all_observed_owned_commands_reaped"] = bool(owned_commands) and all(
            row["owned_group_signal_and_direct_child_reap_observed"]
            for row in owned_commands
        )
        if not result["all_observed_owned_commands_reaped"]:
            code = code or 2
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        try:
            os.chdir(original_cwd)
        except OSError as error:
            result["cwd_restore_error"] = f"{type(error).__name__}: {error}"
            code = code or 2
        now_cpu, now_children = (
            resource.getrusage(kind)
            for kind in (resource.RUSAGE_SELF, resource.RUSAGE_CHILDREN)
        )
        result.update(
            elapsed_seconds_before_final_io=time.monotonic() - started,
            self_cpu_seconds=now_cpu.ru_utime
            + now_cpu.ru_stime
            - cpu.ru_utime
            - cpu.ru_stime,
            reaped_children_cpu_seconds=now_children.ru_utime
            + now_children.ru_stime
            - children.ru_utime
            - children.ru_stime,
            whole_job_CPU_seconds=None,
            phase_intervals_are_nested=True,
            original_GitHub_job_and_queue_still_required=True,
        )
        write_deadline = (
            min(
                scope.deadline,
                time.monotonic() + max(0, 120 - scope.spent["verification"]),
            )
            if scope is not None
            else started + 120
        )
        if time.monotonic() >= write_deadline:
            code = 124
        result["status"] = "passed_pending_terminal" if code == 0 else "failed"
        result["exit_code_before_final_io"] = code
        final_io_started = time.monotonic()
        raw = json.dumps(result, indent=2, sort_keys=True).encode() + b"\n"
        result_retained, retention_errors = False, {}
        try:
            if directory is None:
                raise ValueError("original evidence directory was not created")
            retain_bytes(directory / "RESULT.json", raw)
            result_retained = True
        except Exception as error:
            retention_errors["RESULT.json"] = f"{type(error).__name__}: {error}"
            code = code or 2
        if scope is not None:
            scope.spent["verification"] += time.monotonic() - final_io_started
        if time.monotonic() >= write_deadline:
            code = 124
        if cancellation.signal_count:
            code = code or 130
        terminal_io_started = time.monotonic()
        terminal = {
            "status": "passed" if code == 0 else "failed",
            "exit_code": code,
            "result_sha256": hashlib.sha256(raw).hexdigest(),
            "result_retained": result_retained,
            "retention_errors": dict(retention_errors),
            "elapsed_seconds_after_result_io": time.monotonic() - started,
            "requires_actual_original_CI_exit_and_full_job_cost": True,
            "cancellation": cancellation.receipt(),
        }
        try:
            if directory is None:
                raise ValueError("original evidence directory was not created")
            retain_bytes(
                directory / "TERMINAL.json",
                json.dumps(terminal, sort_keys=True).encode() + b"\n",
            )
        except Exception as error:
            retention_errors["TERMINAL.json"] = f"{type(error).__name__}: {error}"
            code = code or 2
            terminal.update(
                status="failed", exit_code=code, retention_errors=dict(retention_errors)
            )
        if scope is not None:
            scope.spent["verification"] += time.monotonic() - terminal_io_started
        if time.monotonic() >= write_deadline:
            code = 124
        stdout_started = time.monotonic()
        print(
            json.dumps(
                {
                    "elapsed_before_stdout_flush": time.monotonic() - started,
                    "return_code_before_stdout_flush": code,
                    "qualification": False,
                    "phase_seconds_after_result_io": scope.spent
                    if scope
                    else {"verification": time.monotonic() - started},
                    "retention_errors": retention_errors,
                    "cancellation": cancellation.receipt(),
                    "unretained_result": result if not result_retained else None,
                    "unretained_terminal": terminal
                    if "TERMINAL.json" in retention_errors
                    else None,
                }
            ),
            flush=True,
        )
        if scope is not None:
            scope.spent["verification"] += time.monotonic() - stdout_started
        if time.monotonic() >= write_deadline:
            code = 124
        cancellation.restore()
        if cancellation.signal_count:
            code = code or 130
    return code


if __name__ == "__main__":
    raise SystemExit(main())
