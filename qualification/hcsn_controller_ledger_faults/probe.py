"""Pure-stdlib fault injection into the frozen controller's ledger code."""

import argparse
import ast
import hashlib
import json
import os
import resource
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

IDENTITY = "hcsn-controller-ledger-fault-fixture-20261112-c06d-stage1"
TARGET = "qualification/hcsn_adjoint_adam_resume/native_probe.py"
TARGET_SHA = "f2e0b5bf8c4c15bbfd2df967749d949acffe22e4093320aa17c7ff9fbdc84ae2"
SCENARIOS = (
    "known_zero",
    "no_child",
    "missing_result",
    "malformed_result",
    "unbound_result",
    "wrong_pid",
    "wrong_source",
    "wrong_exit",
    "noninteger_counter",
    "pre_popen_kill",
    "post_spawn_pre_pid_kill",
    "post_pid_kill",
    "starting_no_pid",
)
KILLED = {"pre_popen_kill", "post_spawn_pre_pid_kill", "post_pid_kill"}
ZERO = {"forwards": 0, "adjoints": 0, "adam_updates": 0}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".fixture-pending")
    with temporary.open("w") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def assert_stdlib_only():
    forbidden = [
        name
        for name in sys.modules
        if name.split(".")[0] in {"torch", "numpy", "scipy"}
    ]
    if forbidden:
        raise ValueError("numerical imports are forbidden: " + repr(forbidden))


def source_binding(path):
    source = json.loads(Path(path).read_text())
    if source["identity"] != IDENTITY:
        raise ValueError("fixture identity differs")
    expected = source["source_sha256"]
    if {name: sha(name) for name in expected} != expected:
        raise ValueError("prefrozen source differs")
    inventory_path = Path("qualification/hcsn_controller_ledger_faults/SOURCE.json")
    inventory = json.loads(inventory_path.read_text())
    if (
        source["source_inventory_sha256"] != sha(inventory_path)
        or expected != inventory["source_sha256"]
    ):
        raise ValueError("prefrozen fixture inventory differs")
    if source["selected_AST_sha256"] != inventory["selected_AST_sha256"]:
        raise ValueError("selected AST inventory differs")
    if sha(TARGET) != TARGET_SHA:
        raise ValueError("original controller identity differs")
    return source


def extract(source, output, source_path, actors=None, totals=None):
    """Lift exact tested function ASTs; only their outer bindings are injected."""
    tree = ast.parse(Path(TARGET).read_text(), filename=TARGET)
    main = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"
    )
    functions = [
        next(n for n in main.body if isinstance(n, ast.FunctionDef) and n.name == name)
        for name in ("write", "require", "actor")
    ]
    assignments = [
        next(
            n
            for n in main.body
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)
        )
        for name in ("unknown", "exact_calls")
    ]
    return_expression = ast.parse("(unknown, exact_calls)", mode="eval").body
    aggregate = ast.FunctionDef(
        name="aggregate",
        args=ast.arguments(
            posonlyargs=[],
            args=[ast.arg(arg="actors"), ast.arg(arg="totals")],
            kwonlyargs=[],
            kw_defaults=[],
            defaults=[],
        ),
        body=[*assignments, ast.Return(value=return_expression)],
        decorator_list=[],
    )
    module = ast.fix_missing_locations(
        ast.Module(body=[*functions, aggregate], type_ignores=[])
    )
    selected = {
        node.name: hashlib.sha256(
            ast.dump(node, include_attributes=False).encode()
        ).hexdigest()
        for node in functions
    }
    selected["aggregate_assignments"] = hashlib.sha256(
        "\n".join(ast.dump(n, include_attributes=False) for n in assignments).encode()
    ).hexdigest()
    namespace = dict(
        Path=Path,
        os=os,
        json=json,
        sys=sys,
        time=time,
        args=SimpleNamespace(
            output=output, source=source_path, baseline="UNUSED_NO_NUMERICAL_BASELINE"
        ),
        source=dict(source, request_identity=IDENTITY),
        before=source["source_sha256"],
        actors=[] if actors is None else actors,
        checks=[],
        totals=dict(ZERO) if totals is None else totals,
        # Real toy reports are zero; no numerical-work sentinel is fabricated.
        expected={"continuous": (0, 0, 0)},
    )
    if selected != source["selected_AST_sha256"]:
        raise ValueError("selected original controller AST differs")
    exec(compile(module, TARGET + ":selected-ledger-AST", "exec"), namespace)
    return namespace, selected


def toy(args):
    """An actual child process that performs no model or optimizer work."""
    assert_stdlib_only()
    source = source_binding(args.source)
    args.output.mkdir(parents=True, exist_ok=False)
    if args.behavior == "missing_result":
        pass
    elif args.behavior == "malformed_result":
        with (args.output / "RESULT.json").open("x") as stream:
            stream.write("{invalid-json\n")
            stream.flush()
            os.fsync(stream.fileno())
    else:
        result = dict(
            pid=os.getpid(),
            admission_nonce="WRONG_NONCE"
            if args.behavior == "unbound_result"
            else args.admission_nonce,
            source=dict(source, request_identity=IDENTITY),
            source_before=source["source_sha256"],
            source_after=source["source_sha256"],
            exit_code=0,
            status="PASS",
            calls=dict(ZERO),
            input_checkpoint_sha_before=None,
            input_checkpoint_sha_after=None,
            pure_stdlib_toy_not_a_model=True,
        )
        if args.behavior == "wrong_pid":
            result["pid"] += 100000
        elif args.behavior == "wrong_source":
            result["source"] = dict(result["source"], unexpected_source_binding=True)
        elif args.behavior == "wrong_exit":
            result["exit_code"] = 123
        elif args.behavior == "noninteger_counter":
            result["calls"]["forwards"] = 0.0
        write(args.output / "RESULT.json", result)
    write(
        args.output / "TOY-DONE.json",
        dict(pid=os.getpid(), actual_numerical_calls=dict(ZERO)),
    )
    assert_stdlib_only()


def worker(args):
    assert_stdlib_only()
    source = source_binding(args.source)
    args.output.mkdir(parents=True, exist_ok=False)
    namespace, selected = extract(source, args.output, args.source)
    events = []

    def event(kind, **fields):
        events.append(dict(kind=kind, **fields))
        write(args.output / "FIXTURE-EVENTS.json", events)

    def kill_self(point):
        event("intentional_controller_SIGKILL", point=point, pid=os.getpid())
        os.kill(os.getpid(), signal.SIGKILL)
        raise AssertionError("SIGKILL returned")

    class Process:
        def __init__(self, process):
            self.process = process
            self.pid = process.pid

        def wait(self):
            try:
                code = self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                code = self.process.wait(timeout=3)
                event(
                    "fixture_timeout_toy_killed_and_reaped",
                    pid=self.pid,
                    exit_code=code,
                )
                raise
            event("toy_reaped", pid=self.pid, exit_code=code)
            if args.scenario == "post_pid_kill":
                kill_self("after_PID_persist_before_wait_return")
            return code

    class PopenAdapter:
        @staticmethod
        def Popen(command, stdout, stderr):
            prefix = [
                sys.executable,
                "-B",
                "-m",
                "qualification.hcsn_adjoint_adam_resume.actor",
            ]
            if command[:4] != prefix:
                raise ValueError("unexpected original actor command")
            event("target_Popen_adapter_entered", intended_command=command)
            if args.scenario == "pre_popen_kill":
                kill_self("after_STARTING_persist_before_real_Popen")
            if args.scenario == "no_child":
                absent = args.output / "guaranteed-absent-executable"
                assert not absent.exists()
                return subprocess.Popen([str(absent)], stdout=stdout, stderr=stderr)
            actual = [
                sys.executable,
                "-B",
                "-m",
                "qualification.hcsn_controller_ledger_faults.probe",
                "--toy",
                "--behavior",
                args.scenario,
                "--source",
                str(args.source),
                "--output",
                command[command.index("--output") + 1],
                "--admission-nonce",
                command[command.index("--admission-nonce") + 1],
            ]
            process = subprocess.Popen(actual, stdout=stdout, stderr=stderr)
            event("actual_stdlib_toy_spawned", pid=process.pid, actual_command=actual)
            if args.scenario == "post_spawn_pre_pid_kill":
                try:
                    code = process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    code = process.wait(timeout=3)
                    event(
                        "fixture_timeout_toy_killed_and_reaped",
                        pid=process.pid,
                        exit_code=code,
                    )
                    raise
                event("toy_reaped", pid=process.pid, exit_code=code)
                kill_self("after_real_spawn_before_PID_return")
            return Process(process)

    namespace["subprocess"] = PopenAdapter
    if args.scenario == "starting_no_pid":
        namespace["actors"].append(
            dict(
                label="seeded-unresolved-intent",
                admission_nonce=IDENTITY + ":synthetic-reservation-only",
                pid=None,
                started=None,
                terminal=False,
                exit_code=None,
                calls_status="UNKNOWN_STARTING",
                launch_state="STARTING",
                # Reservation values are metadata, never fabricated actual calls.
                expected_maximum_calls=dict(forwards=3, adjoints=3, adam_updates=2),
                observed_calls=None,
            )
        )
        namespace["write"]("ACTORS.json", namespace["actors"])
    caught = None
    try:
        namespace["actor"]("uniform", "continuous", "toy")
    except Exception as exc:
        caught = dict(type=type(exc).__name__, message=str(exc))
    unknown, exact = namespace["aggregate"](namespace["actors"], namespace["totals"])
    blocked = None
    if unknown:
        before = len(events)
        try:
            namespace["actor"]("uniform", "continuous", "second-must-not-spawn")
        except ValueError as exc:
            blocked = "no further admission" in str(exc) and before == len(events)
    write(
        args.output / "WORKER.json",
        dict(
            scenario=args.scenario,
            pid=os.getpid(),
            selected_AST_sha256=selected,
            caught=caught,
            unknown=unknown,
            actual_calls_under_test=exact,
            second_admission_blocked=blocked,
            events=events,
            actual_fixture_numerical_calls=dict(ZERO),
            numerical_modules_loaded=False,
        ),
    )
    assert_stdlib_only()


def inspect_case(source, args, scenario, code, output):
    actors = json.loads((output / "ACTORS.json").read_text())
    namespace, selected = extract(source, output, args.source, actors=actors)
    unknown, exact = namespace["aggregate"](actors, dict(ZERO))
    events = (
        json.loads((output / "FIXTURE-EVENTS.json").read_text())
        if (output / "FIXTURE-EVENTS.json").exists()
        else []
    )
    expected_unknown = scenario not in {"known_zero", "no_child"}
    assert bool(unknown) == expected_unknown
    assert exact is None if expected_unknown else exact == ZERO
    assert code == (-signal.SIGKILL if scenario in KILLED else 0)
    assert len(actors) == 1
    actor = actors[0]
    if scenario in {"pre_popen_kill", "post_spawn_pre_pid_kill", "starting_no_pid"}:
        assert actor["pid"] is None and actor["started"] is None
        assert (
            actor["launch_state"] == "STARTING"
            and actor["calls_status"] == "UNKNOWN_STARTING"
        )
    elif scenario == "post_pid_kill":
        assert type(actor["pid"]) is int and actor["started"] is True
        assert (
            actor["terminal"] is False
            and actor["calls_status"] == "UNKNOWN_PENDING_RESULT"
        )
    elif scenario == "no_child":
        assert actor["started"] is False and actor["terminal"] is True
        assert (
            actor["calls_status"] == "START_FAILED_NO_CHILD"
            and actor["observed_calls"] == ZERO
        )
    elif scenario == "known_zero":
        assert actor["calls_status"] == "KNOWN" and actor["observed_calls"] == ZERO
    else:
        assert (
            actor["started"] is True
            and actor["terminal"] is True
            and actor["exit_code"] == 0
        )
        assert (
            actor["calls_status"] == "UNKNOWN_TERMINAL_UNREPORTED"
            and actor["observed_calls"] is None
        )
    if unknown:
        called = []
        namespace["subprocess"] = SimpleNamespace(
            Popen=lambda *a, **k: called.append(True)
        )
        try:
            namespace["actor"](
                "uniform", "continuous", "reconciled-second-must-not-spawn"
            )
        except ValueError as exc:
            assert "no further admission" in str(exc)
        else:
            raise AssertionError("unresolved actor admitted another child")
        assert not called
    if scenario not in KILLED:
        w = json.loads((output / "WORKER.json").read_text())
        assert w["actual_calls_under_test"] == exact and w["unknown"] == unknown
        assert w["actual_fixture_numerical_calls"] == ZERO
        if expected_unknown:
            assert w["second_admission_blocked"] is True
    spawned = [e for e in events if e["kind"] == "actual_stdlib_toy_spawned"]
    reaped = [e for e in events if e["kind"] == "toy_reaped"]
    wanted_spawn = scenario not in {"no_child", "pre_popen_kill", "starting_no_pid"}
    assert len(spawned) == len(reaped) == int(wanted_spawn)
    if spawned:
        assert spawned[0]["pid"] == reaped[0]["pid"] and reaped[0]["exit_code"] == 0
    report_path = output / "toy" / "RESULT.json"
    if scenario == "missing_result":
        assert not report_path.exists()
    elif scenario == "malformed_result":
        assert report_path.read_bytes() == b"{invalid-json\n"
    elif spawned:
        report = json.loads(report_path.read_text())
        wanted = dict(
            pid=spawned[0]["pid"],
            admission_nonce=actor["admission_nonce"],
            source=dict(source, request_identity=IDENTITY),
            source_before=source["source_sha256"],
            source_after=source["source_sha256"],
            exit_code=0,
            status="PASS",
            calls=dict(ZERO),
            input_checkpoint_sha_before=None,
            input_checkpoint_sha_after=None,
            pure_stdlib_toy_not_a_model=True,
        )
        if scenario == "unbound_result":
            wanted["admission_nonce"] = "WRONG_NONCE"
        elif scenario == "wrong_pid":
            wanted["pid"] += 100000
        elif scenario == "wrong_source":
            wanted["source"] = dict(wanted["source"], unexpected_source_binding=True)
        elif scenario == "wrong_exit":
            wanted["exit_code"] = 123
        elif scenario == "noninteger_counter":
            wanted["calls"]["forwards"] = 0.0
        assert report == wanted
        assert type(report["calls"]["forwards"]) is (
            float if scenario == "noninteger_counter" else int
        )
    if spawned:
        done = json.loads((output / "toy" / "TOY-DONE.json").read_text())
        assert done == dict(pid=spawned[0]["pid"], actual_numerical_calls=dict(ZERO))
    if scenario == "starting_no_pid":
        assert unknown[0]["maximum_calls"] == dict(
            forwards=3, adjoints=3, adam_updates=2
        )
    return dict(
        scenario=scenario,
        controller_exit=code,
        selected_AST_sha256=selected,
        ledger_unknown=unknown,
        actual_calls_under_test=exact,
        known_zero_is_definite=scenario in {"known_zero", "no_child"},
        second_admission_blocked=bool(unknown),
        toy_children_spawned=len(spawned),
        toy_children_reaped=len(reaped),
        event_count=len(events),
        passed=True,
    )


def supervisor(args):
    assert_stdlib_only()
    source = source_binding(args.source)
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    admissions, results = [], []
    error = None
    try:
        for scenario in SCENARIOS:
            output = args.output / scenario
            command = [
                sys.executable,
                "-B",
                "-m",
                "qualification.hcsn_controller_ledger_faults.probe",
                "--worker",
                "--scenario",
                scenario,
                "--source",
                str(args.source),
                "--output",
                str(output),
            ]
            admission = dict(
                scenario=scenario,
                state="STARTING",
                pid=None,
                exit_code=None,
                command=command,
            )
            admissions.append(admission)
            write(args.output / "SUPERVISOR-ADMISSIONS.json", admissions)
            with (
                (args.output / (scenario + ".stdout")).open("wb") as stdout,
                (args.output / (scenario + ".stderr")).open("wb") as stderr,
            ):
                process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
                admission.update(state="STARTED", pid=process.pid)
                write(args.output / "SUPERVISOR-ADMISSIONS.json", admissions)
                try:
                    code = process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    code = process.wait(timeout=3)
                    admission.update(state="TIMEOUT_KILLED_REAPED", exit_code=code)
                    write(args.output / "SUPERVISOR-ADMISSIONS.json", admissions)
                    raise
            admission.update(state="TERMINAL", exit_code=code)
            write(args.output / "SUPERVISOR-ADMISSIONS.json", admissions)
            results.append(inspect_case(source, args, scenario, code, output))
        assert (
            len(results) == 13 and sum(r["toy_children_spawned"] for r in results) == 10
        )
        assert len({a["pid"] for a in admissions}) == 13
        assert (
            len({json.dumps(r["selected_AST_sha256"], sort_keys=True) for r in results})
            == 1
        )
    except Exception as exc:
        error = dict(
            type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc()
        )
    after = source_binding(args.source)
    assert after == source
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    files = [p for p in args.output.rglob("*") if p.is_file()]
    payload = sum(p.stat().st_size for p in files)
    if payload > 2 * 1024 * 1024:
        error = dict(
            type="ValueError", message="post-execution payload budget exceeded"
        )
    report = dict(
        status="PASS" if error is None else "HOLD",
        identity=IDENTITY,
        source=source,
        error=error,
        scenarios=results,
        supervisor_admissions=admissions,
        actual_stdlib_controller_processes=len(admissions) if error is None else None,
        actual_stdlib_toy_processes=sum(r["toy_children_spawned"] for r in results)
        if error is None
        else None,
        observed_controller_PIDs=[a["pid"] for a in admissions if a["pid"] is not None],
        observed_completed_case_toy_processes=sum(
            r["toy_children_spawned"] for r in results
        ),
        exact_process_totals_status="KNOWN_FOR_COMPLETE_PROTOCOL"
        if error is None
        else "UNKNOWN_INCOMPLETE_PROTOCOL",
        actual_numerical_calls=dict(ZERO),
        torch_numpy_scipy_imports=0,
        intentional_SIGKILL_cases=len(KILLED),
        payload_bytes_before_report=payload,
        wall_seconds=time.perf_counter() - started,
        child_cpu_seconds=(usage_after.ru_utime + usage_after.ru_stime)
        - (usage_before.ru_utime + usage_before.ru_stime),
        child_reported_max_rss_kib=usage_after.ru_maxrss,
        scope="selected original controller AST with stdlib toy adapter; no model or power-loss qualification",
    )
    write(args.output / "RESULT.json", report)
    assert_stdlib_only()
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "status",
                    "identity",
                    "actual_stdlib_controller_processes",
                    "actual_stdlib_toy_processes",
                    "actual_numerical_calls",
                    "error",
                )
            },
            sort_keys=True,
        )
    )
    if error:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--worker", action="store_true")
    modes.add_argument("--toy", action="store_true")
    parser.add_argument("--scenario", choices=SCENARIOS)
    parser.add_argument("--behavior", choices=SCENARIOS)
    parser.add_argument("--admission-nonce")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.toy:
        toy(args)
    elif args.worker:
        worker(args)
    else:
        supervisor(args)


if __name__ == "__main__":
    main()
