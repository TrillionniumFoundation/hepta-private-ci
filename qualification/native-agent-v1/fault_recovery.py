#!/usr/bin/env python3
"""Kill only our waiting runner after durable launch, then restore one operation.

This is a replay-mode fault experiment, not a performance sample. The model
server, runtime state, configuration and original command survive the restart.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import threading
import time

from benchmark import (audit_tool_feedback, capture_settled, configure, digest,
                       expected, inventory, private_dir, prompt, save)
from model_gateway import ModelGateway
from protocol_driver import CodexDriver, JsonProcess, LaneAbort, remaining


def command_bytes(value):
    # Matches JsonProcess.send, including its trailing newline.
    return json.dumps(value, separators=(",", ":")).encode() + b"\n"


def read_json(path):
    return json.loads(path.read_text())


def request_digest(params):
    keys = ("args", "cpu_quota_percent", "cwd", "env", "executable", "host",
            "memory_max_bytes", "nice", "stdin", "timeout_seconds")
    body = {key: params.get(key) for key in keys}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def session_evidence(output, command):
    session = hashlib.sha256(command["session"].encode()).hexdigest()
    root = output / "sessions" / session
    manifest = read_json(root / "manifest.json")
    if manifest["session"] != command["session"] or manifest["input"] != command["input"]:
        raise ValueError("session manifest differs from the original command")
    admissions = sorted(root.glob("tool-*.json"))
    snapshots = sorted(root.glob("snapshot-*.json"))
    if len(admissions) != 1 or not snapshots:
        raise ValueError("original session needs exactly one admitted tool and a checkpoint")
    admission = read_json(admissions[0])
    state = read_json(snapshots[-1])["state"]
    if state["binding"] != manifest["binding"]:
        raise ValueError("checkpoint changed the original operation binding")
    call = admission["call"]
    if call["name"] != "hepta_probe" or json.loads(call["arguments"]) != {"task": "sum"}:
        raise ValueError("fault trial is limited to the original sum operation")
    if command["op"] == "tool" and (call["call_id"] != command["call_id"]
                                     or json.loads(call["arguments"]) != command["arguments"]):
        raise ValueError("helper admission differs from the original Codex call")
    return {"root": str(root), "manifest_sha256": digest(root / "manifest.json"),
            "binding": manifest["binding"], "admission": admission,
            "admission_sha256": digest(admissions[0]), "snapshot": snapshots[-1].name,
            "state": state, "model_admissions": {p.name: digest(p) for p in root.glob("model-*.json")}}


def original_job(output, command, require_pending):
    paths = sorted((output / "controller" / "jobs").glob("*.json"))
    if len(paths) != 1:
        raise ValueError(f"expected exactly one runtime job, observed {len(paths)}")
    record = read_json(paths[0])
    if record.get("launch_state") != "launched":
        raise ValueError("runtime has not durably acknowledged launch")
    owner = session_evidence(output, command)
    params = owner["admission"]["params"]
    if record.get("request_digest") != request_digest(params):
        raise ValueError("job's full payload digest differs from original admission")
    for key in ("host", "executable", "args", "cwd", "idempotency_key"):
        if record.get(key) != params.get(key):
            raise ValueError("job changed admitted field: " + key)
    remote = (output / "remote" / "jobs" / record["id"]).resolve()
    if remote != Path(record["remote_job_dir"]).resolve() or remote.parent != (output / "remote" / "jobs").resolve():
        raise ValueError("job is not in this experiment's private remote directory")
    remote_request = read_json(remote / "request.json")
    if remote_request.get("job_id") != record["id"] or remote_request.get("request_digest") != record["request_digest"]:
        raise ValueError("remote request changed the original job binding")
    child = read_json(remote / "child.json")
    if type(child.get("pid")) is not int or child["pid"] <= 0:
        raise ValueError("runtime has not recorded the real fixture child")
    if require_pending:
        pending = owner["state"].get("pending_tool")
        if (not pending or pending.get("submission_attempted") is not True
                or pending.get("cancel_requested") is not False
                or pending["call"] != owner["admission"]["call"]
                or owner["state"].get("pending_model") is not None
                or owner["state"].get("final_answer") is not None
                or (remote / "exit.json").exists()):
            raise ValueError("tool is not durably pending before its terminal observation")
    return {"record": record, "record_sha256": digest(paths[0]), "owner": owner,
            "remote_request_sha256": digest(remote / "request.json"),
            "remote_child": child, "remote_child_sha256": digest(remote / "child.json"),
            "terminal_file_present": (remote / "exit.json").exists()}


class RestartOneRunner:
    """JsonProcess-compatible helper; one verified SIGKILL and one owner restore."""
    def __init__(self, args, report):
        self.args, self.report = args, report
        self.command = self.raw_command = None
        self.restart_count = 0
        self.stop = threading.Event()
        self.watcher = None
        self.children = []
        self.env = os.environ.copy()
        self.config_sha256 = digest(args.output / "runner.json")
        self.child = self._spawn()
        try:
            self.ready = self.child.receive(time.monotonic() + 120)
            self._check_ready(self.ready)
        except Exception:
            self.close()
            raise
        self.report["initial_runner_pid"] = self.child.process.pid

    def _spawn(self):
        child = JsonProcess([str(self.args.native), str(self.args.output / "runner.json")],
            str(self.args.fixture), self.env.copy(),
            self.args.output / f"backend-{self.restart_count}.jsonl")
        self.children.append(child)
        return child

    @staticmethod
    def _check_ready(value):
        if value.get("ready") is not True or value.get("protocol") != "qualification.jsonl.v1":
            raise LaneAbort("replacement runner did not initialize under the same protocol")

    def send(self, value):
        if self.command is not None or value.get("op") not in ("run", "tool"):
            raise LaneAbort("fault trial permits only one original command")
        self.raw_command = command_bytes(value)
        self.command = json.loads(self.raw_command)
        self.report["original_command"] = self.command
        self.report["original_command_sha256"] = hashlib.sha256(self.raw_command).hexdigest()
        self.child.send(self.command)
        self.watcher = threading.Thread(target=self._inject, name="fault-injector", daemon=True)
        self.watcher.start()

    def _inject(self):
        deadline = time.monotonic() + min(120, self.args.timeout)
        try:
            while not self.stop.is_set() and time.monotonic() < deadline:
                paths = sorted((self.args.output / "controller" / "jobs").glob("*.json"))
                if len(paths) > 1:
                    raise ValueError("duplicate runtime jobs before fault injection")
                if paths:
                    record = read_json(paths[0])
                    remote = self.args.output / "remote" / "jobs" / record["id"]
                    if record.get("launch_state") == "launched" and (remote / "child.json").exists():
                        before = original_job(self.args.output, self.command, require_pending=True)
                        self.report["before"] = before
                        save(self.args.output / "BEFORE.json", before)
                        # Only this object, constructed by _spawn, is eligible.
                        # Never signal the runtime fixture child, systemd unit,
                        # a process group, or a PID obtained from metadata.
                        if self.child not in self.children or self.child.process.poll() is not None:
                            raise ValueError("owned waiting runner already exited; no fault injected")
                        self.report["kill_requested_ns"] = time.time_ns()
                        self.report["killed_owned_pid"] = self.child.process.pid
                        self.child.process.kill()
                        self.report["kill_return_code"] = self.child.process.wait(timeout=10)
                        self.report["fault_injected"] = self.report["kill_return_code"] == -signal.SIGKILL
                        return
                self.stop.wait(0.01)
            if not self.stop.is_set():
                raise TimeoutError("no launched, still-pending original job reached the injection point")
        except Exception as error:
            self.report["injection_error"] = repr(error)
        finally:
            self.report["injector_finished_ns"] = time.time_ns()

    def receive(self, deadline):
        try:
            result = self.child.receive(deadline)
        except Exception as error:
            self.stop.set()
            if self.watcher:
                self.watcher.join(timeout=min(12, remaining(deadline)))
            # EOF must follow our successful SIGKILL. Any other transport or
            # protocol error is negative evidence, not permission to retry.
            if (self.restart_count != 0 or not self.report.get("fault_injected")
                    or not isinstance(error, LaneAbort) or str(error) != str({"_eof": True})
                    or self.child.reader_failure is not None
                    or self.child.process.returncode != -signal.SIGKILL):
                raise LaneAbort("original process did not reach the verified injected-EOF boundary", {
                    "status": "fault_not_recovered", "cause": repr(error)}) from error
            self.report["original_eof_observed"] = True
            self.child.close()
            if (digest(self.args.output / "runner.json") != self.config_sha256
                    or command_bytes(self.command) != self.raw_command):
                raise LaneAbort("original config or qualification command changed before restoration")
            current = original_job(self.args.output, self.command, require_pending=False)
            assert_same_identity(self.report["before"], current)
            self.restart_count = 1
            self.report["restart_count"] = 1
            self.child = self._spawn()
            ready = self.child.receive(deadline)
            self._check_ready(ready)
            if ready != self.ready:
                raise LaneAbort("restored runner changed readiness/tool contract")
            self.report["replacement_runner_pid"] = self.child.process.pid
            self.report["restored_command_sha256"] = hashlib.sha256(command_bytes(self.command)).hexdigest()
            self.child.send(self.command)
            # Exactly one re-entry to the qualification owner. No process_start
            # call is constructed here, and a second failure is never retried.
            return self.child.receive(deadline)
        self.stop.set()
        self.report["unexpected_original_reply"] = result
        raise LaneAbort("original runner replied before the verified fault/restore boundary")

    def close(self):
        self.stop.set()
        if self.watcher:
            self.watcher.join(timeout=12)
        errors = []
        for child in reversed(self.children):
            try:
                child.close()
            except Exception as error:
                errors.append(repr(error))
        return errors


def assert_same_identity(before, after):
    for key in ("record", "record_sha256", "remote_request_sha256", "remote_child_sha256"):
        if before[key] != after[key]:
            raise ValueError("original runtime identity or payload changed: " + key)
    for key in ("manifest_sha256", "binding", "admission_sha256", "admission"):
        if before["owner"][key] != after["owner"][key]:
            raise ValueError("original owner identity or admission changed: " + key)
    for name, checksum in before["owner"]["model_admissions"].items():
        if after["owner"]["model_admissions"].get(name) != checksum:
            raise ValueError("original model admission changed after restart")


def run(args):
    os.umask(0o077)
    if args.timeout <= 0 or args.output.exists():
        raise ValueError("positive timeout and a new output directory are required")
    private_dir(args.output)
    source_fixture = args.fixture
    args.fixture = args.output / "fixture"
    private_dir(args.fixture)
    (args.fixture / "fixture.txt").write_bytes((source_fixture / "fixture.txt").read_bytes())
    (args.fixture / "fixture_tool.py").write_bytes(
        b"import time\ntime.sleep(5)\n" + (source_fixture / "fixture_tool.py").read_bytes())
    evidence = args.output / "model"
    private_dir(evidence)
    gateway = ModelGateway("replay", args.upstream, evidence)
    config = configure(args, gateway)
    report = {"schema": "hepta.native.qualification.kill-restore.v1", "lane": args.lane,
        "mode": "replay", "case": "fault-sum", "started_ns": time.time_ns(),
        "fault_injected": False, "restart_count": 0, "passed": False,
        "fault_target": "entire native runner" if args.lane == "native" else "runtime helper; Codex stays resident",
        "fixture": config["fixture"], "source_fixture_sha256": digest(source_fixture / "fixture_tool.py"),
        "fixture_delay_seconds": 5, "runner_config_sha256": digest(args.output / "runner.json"),
        "runtime_helper_sha256": digest(args.native),
        "limits": ["One launched-tool helper/runner crash per arm, not arbitrary crash-point coverage",
            "Re-entry uses the same qualification owner command, not a new process_start",
            "No performance comparison or model/provider-disconnect recovery claim"]}
    backend = client = None
    answer = json.dumps(expected(args.fixture / "fixture.txt")["sum"], sort_keys=True, separators=(",", ":"))
    try:
        backend = RestartOneRunner(args, report)
        gateway.begin("fault-sum", "sum", answer)
        session, text = args.output.name + ":fault-sum", prompt("sum")
        if args.lane == "native":
            backend.send({"op": "run", "session": session, "input": text})
            result = backend.receive(time.monotonic() + args.timeout)
            if result.get("session") != session:
                raise LaneAbort("native restoration returned another session")
        else:
            env = os.environ.copy()
            env["CODEX_HOME"] = str(args.output / "codex-home")
            argv = [str(args.codex), "app-server"] if args.lane == "app-server" else [
                str(args.facade), "--codex-home", env["CODEX_HOME"], "--codex-exe", str(args.codex),
                "--cwd", str(args.fixture)]
            client = JsonProcess(argv, str(args.fixture), env, args.output / "executor.jsonl")
            report["codex_resident_pid"] = client.process.pid
            driver = CodexDriver(client, backend, args.fixture, backend.ready["tools"][0])
            result = driver.run(session, text, timeout=args.timeout)
            report["codex_same_process_alive_after_case"] = client.process.poll() is None
        report["result"] = result
        if result.get("status") != "completed" or result.get("tool_calls") != 1:
            raise LaneAbort("restored case did not complete its one original tool", result)
        after = original_job(args.output, backend.command, require_pending=False)
        report["after"] = after
        assert_same_identity(report["before"], after)
        state = after["owner"]["state"]
        if state["pending_tool"] is not None or len(state["completed_call_ids"]) != 1:
            raise ValueError("restored owner did not terminally consume the original tool result")
        if args.lane == "native" and (result.get("operation_id") != after["owner"]["binding"]["operation"]
                or result.get("generation") != after["owner"]["binding"]["generation"]
                or result.get("model_calls") != 2 or len(after["owner"]["model_admissions"]) != 2):
            raise ValueError("native restart changed operation identity or original model-call count")
        remote_jobs = [p.name for p in (args.output / "remote" / "jobs").iterdir() if p.is_dir()]
        report["remote_job_directories"] = sorted(remote_jobs)
        if remote_jobs != [after["record"]["id"]]:
            raise ValueError("fault trial produced extra physical runtime job directories")
        report["identity_verified"] = True
    except Exception as error:
        report["error"] = repr(error)
        if isinstance(getattr(error, "result", None), dict):
            report["failure_result"] = error.result
    finally:
        if backend and backend.command is not None:
            try:
                report["after_observation"] = original_job(args.output, backend.command, require_pending=False)
            except Exception as error:
                report["after_observation_error"] = repr(error)
        if client:
            try:
                client.close()
            except Exception as error:
                report["codex_shutdown_error"] = repr(error)
        if backend:
            report["backend_shutdown_errors"] = backend.close()
        gateway.close()
        report["capture_complete"] = capture_settled(gateway, evidence)
        report["tool_feedback_audit"] = audit_tool_feedback(evidence, "fault-sum", "sum", answer)
        report["model_requests"] = list(gateway.records)
        report["model_request_count"] = len(gateway.records)
        report["model_inventory"] = inventory(evidence)
        actual_answer = report.get("result", {}).get("answer")
        report["passed"] = ("error" not in report and report.get("identity_verified", False)
            and report["fault_injected"] and report["restart_count"] == 1
            and report.get("original_eof_observed", False) and report["capture_complete"]
            and report["tool_feedback_audit"]["valid"] and len(gateway.records) == 2
            and [r["call"] for r in gateway.records] == [1, 2]
            and all(r.get("http_status") == 200 and "error" not in r for r in gateway.records)
            and bool(report["model_inventory"]) and all(r["only_shared_tool"] for r in report["model_inventory"])
            and isinstance(actual_answer, str) and actual_answer.strip() == answer
            and not report.get("codex_shutdown_error") and not report.get("backend_shutdown_errors")
            and (args.lane == "native" or report.get("codex_same_process_alive_after_case", False)))
        report["finished_ns"] = time.time_ns()
        save(args.output / "REPORT.json", report)
        print(json.dumps({"report": str(args.output / "REPORT.json"), "passed": report["passed"],
                          "injected": report["fault_injected"], "restarts": report["restart_count"],
                          "error": report.get("error")}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", choices=("native", "app-server", "facade"), required=True)
    for name in ("output", "fixture", "native", "codex", "facade"):
        parser.add_argument("--" + name, type=lambda value: Path(value).resolve(), required=True)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--upstream", default="http://127.0.0.1:18081/v1")
    raise SystemExit(run(parser.parse_args()))
