"""Cancel or restore one real retained process through each qualification lane.

Only an owned waiting runner may be killed. Runtime children are cancelled by
their original owner, never by a PID discovered in a metadata file.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import threading
import time

from representative_compare import (ANSWER, BUDGET, HERE, INSTRUCTIONS, LANES,
                                    canonical, configure, digest, prepare, save)
from representative_runtime_evidence import bound_job, read_json, stream_file
from representative_audit import feedback_value, response_objects
from protocol_driver import CodexDriver, JsonProcess, LaneAbort, remaining
from script_gateway import ScriptGateway


def process_identity(pid):
    try:
        value = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return None
    fields = value[value.rfind(")") + 2:].split()
    return {"pid": pid, "start_ticks": int(fields[19]), "state": fields[0]}


def operation_evidence(root, command, *, require_pending):
    session = root / "sessions" / hashlib.sha256(command["session"].encode()).hexdigest()
    manifest = read_json(session / "manifest.json")
    if manifest["session"] != command["session"] or manifest["input"] != command["input"]:
        raise ValueError("owner manifest changed the original command")
    admissions, snapshots = sorted(session.glob("tool-*.json")), sorted(session.glob("snapshot-*.json"))
    if len(admissions) != 1 or not snapshots:
        raise ValueError("fault trial requires one original tool and a durable checkpoint")
    admission, state = read_json(admissions[0]), read_json(snapshots[-1])["state"]
    if state["binding"] != manifest["binding"]:
        raise ValueError("owner generation or operation binding changed")
    call = admission["call"]
    if call["name"] != "hepta_fixture" or json.loads(call["arguments"]) != {}:
        raise ValueError("fault trial admits only its frozen process")
    if command["op"] == "tool" and (call["call_id"] != command["call_id"]
            or call["name"] != command["name"] or json.loads(call["arguments"]) != command["arguments"]):
        raise ValueError("helper admission differs from the original Codex proposal")
    remote, record, binding = bound_job(root, admission)
    if len(list((root / "controller" / "jobs").glob("*.json"))) != 1:
        raise ValueError("fault trial allocated additional runtime jobs")
    child = read_json(remote / "child.json")
    if type(child.get("pid")) is not int or child["pid"] <= 0:
        raise ValueError("runtime did not retain its actual child identity")
    started = stream_file(remote, "stdout").read_bytes()
    if not started.startswith(b"STARTED\n"):
        raise ValueError("original process has no retained STARTED evidence")
    if require_pending:
        pending = state.get("pending_tool")
        if (not pending or pending.get("submission_attempted") is not True
                or pending.get("cancel_requested") is not False or pending["call"] != call
                or state.get("pending_model") is not None or state.get("final_answer") is not None
                or (remote / "exit.json").exists()):
            raise ValueError("original tool is not durably pending before terminal observation")
    return {"remote": str(remote), "job": record, "binding": binding, "child": child,
        "child_sha256": digest(remote / "child.json"), "manifest_sha256": digest(session / "manifest.json"),
        "admission_sha256": digest(admissions[0]), "admission": admission, "state": state,
        "model_admissions": {path.name: digest(path) for path in session.glob("model-*.json")}}


def same_operation(before, after):
    for key in ("remote", "job", "binding", "child", "child_sha256", "manifest_sha256", "admission_sha256", "admission"):
        if before[key] != after[key]:
            raise ValueError("restoration changed original identity: " + key)
    for name, checksum in before["model_admissions"].items():
        if after["model_admissions"].get(name) != checksum:
            raise ValueError("original model request changed after interruption")


class ControlledRunner:
    """One measured original command and one explicitly injected control event."""

    def __init__(self, args, workspace, report):
        self.args, self.workspace, self.report = args, workspace, report
        self.command = self.raw_command = None
        self.children, self.restarts, self.watcher = [], 0, None
        self.stop = threading.Event()
        self.config_digest = digest(args.output / "runner.json")
        self.child = self.spawn()
        try:
            self.ready = self.child.receive(time.monotonic() + 120)
            if self.ready.get("ready") is not True:
                raise ValueError("initial representative runner is not ready")
        except Exception:
            self.close()
            raise

    def spawn(self):
        child = JsonProcess([str(self.args.native), str(self.args.output / "runner.json")],
            str(self.workspace), os.environ.copy(), self.args.output / f"backend-{self.restarts}.jsonl")
        self.children.append(child)
        return child

    def send(self, value):
        if self.command is not None or value.get("op") not in ("run", "tool"):
            raise ValueError("fault trial permits exactly one admitted original command")
        self.command, self.raw_command = value, canonical(value)
        self.report["original_command"] = value
        self.report["original_command_sha256"] = hashlib.sha256(self.raw_command).hexdigest()
        self.child.send(value)
        self.watcher = threading.Thread(target=self.inject, daemon=True, name="representative-fault")
        self.watcher.start()

    def inject(self):
        deadline = time.monotonic() + min(60, self.args.timeout)
        try:
            while not self.stop.is_set() and time.monotonic() < deadline:
                try:
                    before = operation_evidence(self.args.output, self.command, require_pending=True)
                except (FileNotFoundError, ValueError, KeyError) as error:
                    self.report["last_injection_wait"] = str(error)
                    self.stop.wait(0.01)
                    continue
                self.report["before"] = before
                self.report["original_child_proc"] = process_identity(before["child"]["pid"])
                if not self.report["original_child_proc"]:
                    raise ValueError("original runtime child disappeared before fault injection")
                save(self.args.output / "BEFORE.json", before)
                if self.args.case == "cancel":
                    self.child.send({"op": "cancel", "session": self.command["session"]})
                    self.report["cancel_sent_ns"] = time.time_ns()
                else:
                    if self.child not in self.children or self.child.process.poll() is not None:
                        raise ValueError("owned waiting runner already exited")
                    self.report["killed_owned_runner_pid"] = self.child.process.pid
                    self.child.process.kill()
                    code = self.child.process.wait(timeout=10)
                    if code != -signal.SIGKILL:
                        raise ValueError("owned runner did not reach the injected SIGKILL boundary")
                    self.report["kill_return_code"] = code
                self.report["injected"] = True
                return
            raise TimeoutError("no retained STARTED and durable pending original tool reached the injection point")
        except Exception as error:
            self.report["injection_error"] = repr(error)

    def receive(self, deadline):
        try:
            result = self.child.receive(deadline)
        except Exception as error:
            if self.watcher:
                self.watcher.join(timeout=min(12, remaining(deadline)))
            if (self.args.case != "recover_process" or self.restarts or not self.report.get("injected")
                    or not isinstance(error, LaneAbort) or str(error) != str({"_eof": True})
                    or self.child.reader_failure is not None or self.child.process.returncode != -signal.SIGKILL):
                raise
            self.report["original_eof_observed"] = True
            self.child.close()
            if (canonical(self.command) != self.raw_command
                    or digest(self.args.output / "runner.json") != self.config_digest):
                raise ValueError("original command or config changed before restore")
            same_operation(self.report["before"], operation_evidence(self.args.output, self.command, require_pending=False))
            self.restarts = 1
            self.child = self.spawn()
            if self.child.receive(deadline) != self.ready:
                raise ValueError("restored runner changed its tool or readiness contract")
            self.child.send(self.command)
            self.report["restored_command_sha256"] = hashlib.sha256(canonical(self.command)).hexdigest()
            return self.child.receive(deadline)
        if self.watcher:
            self.watcher.join(timeout=min(12, remaining(deadline)))
        if self.args.case != "cancel" or not self.report.get("injected"):
            raise ValueError("original runner replied without the injected restore boundary")
        if result.get("status") != "pending_tool" or result.get("session") != self.command["session"]:
            raise ValueError("cancel did not leave the original tool pending terminal reconciliation")
        self.report["cancel_pending_result"] = result
        return result

    def reconcile_cancel(self, deadline):
        attempts = []
        while time.monotonic() < deadline:
            current = operation_evidence(self.args.output, self.command, require_pending=False)
            same_operation(self.report["before"], current)
            pending = current["state"].get("pending_tool")
            if pending and (pending.get("submission_attempted") is not True or pending.get("cancel_requested") is not True):
                raise ValueError("cancelled recovery lost its observation-only admission")
            # Same immutable command re-enters the existing owner. No new
            # process_start is constructed or authorized by this observer.
            self.child.send(self.command)
            result = self.child.receive(deadline)
            attempts.append(result)
            if result.get("session") != self.command["session"]:
                raise ValueError("cancel reconciliation returned another operation")
            if result.get("status") in ("cancelled", "completed"):
                self.report["cancel_reconciliation"] = attempts
                return result
            if result.get("status") != "pending_tool":
                raise ValueError("cancel reconciliation left the original pending operation")
            self.stop.wait(0.05)
        raise TimeoutError("original cancelled process did not publish a terminal result")

    def close(self):
        self.stop.set()
        if self.watcher:
            self.watcher.join(timeout=12)
        for child in reversed(self.children):
            child.close()


def confirm_codex_interrupt(client, scope, deadline):
    while time.monotonic() < deadline:
        value = client.receive(deadline)
        if value.get("method") == "turn/completed":
            params = value["params"]
            if params.get("threadId") != scope["thread_id"] or params.get("turn", {}).get("id") != scope["turn_id"]:
                raise ValueError("cancel observed completion for another Codex turn")
            if params["turn"].get("status") != "interrupted":
                raise ValueError("cancel did not confirm an interrupted original Codex turn")
            return value
    raise TimeoutError("Codex cancellation did not publish original-turn completion")


def run(args):
    os.umask(0o077)
    if args.output.exists() or args.timeout <= 0:
        raise ValueError("a fresh private output directory and positive timeout are required")
    args.output.mkdir(parents=True)
    case = next(item for item in json.loads((HERE / "corpus.json").read_bytes())["cases"] if item["id"] == args.case)
    workspace, _, _ = prepare(case, args.output)
    evidence = args.output / "model"
    evidence.mkdir()
    steps = [{"tool": "hepta_fixture", "arguments": {}, "stdout": "STARTED\n"}]
    gateway = ScriptGateway("replay", "http://127.0.0.1:18081/v1", evidence,
        **{key: BUDGET[key] for key in ("context_bytes", "output_tokens", "model_calls")})
    gateway.begin_script(args.case, steps)
    configure(args.output, workspace, gateway, BUDGET)
    sources = [Path(__file__).resolve(), HERE / "representative_runtime_evidence.py", HERE / "representative_compare.py",
               HERE / "script_gateway.py", HERE / "workspace_tool.py", HERE / "corpus.json",
               HERE.parent / "protocol_driver.py", args.native, args.codex, args.facade]
    fingerprints = {str(path): digest(path) for path in sources}
    save(args.output / "FROZEN.json", {"case": case, "sha256": fingerprints, "budgets": BUDGET,
         "mode": "replay", "scope": "qualification owner only; production recovery held"})
    report = {"schema": "hepta.representative-fault.v1", "case": args.case, "lane": args.lane,
        "passed": False, "mode": "replay", "usage_is_synthetic": True, "production_verdict": "held",
        "fault_target": "original runtime request cancellation" if args.case == "cancel" else "owned waiting qualification runner",
        "limits": ["SessionOwner fixture; production ThreadStore/FinalUse recovery is not exercised",
                   "One explicit after-STARTED point; no arbitrary-crash or model-provider recovery claim",
                   "No performance sample; fixed response replay does not evaluate model reasoning"]}
    backend = client = None
    try:
        backend = ControlledRunner(args, workspace, report)
        prompt = "Call hepta_fixture exactly once. After observing success, return exactly " + ANSWER + "."
        session = args.output.name + ":" + args.case + ":" + args.lane
        deadline = time.monotonic() + args.timeout
        if args.lane == "native":
            backend.send({"op": "run", "session": session, "input": prompt})
            result = backend.receive(deadline)
        else:
            env = dict(os.environ, CODEX_HOME=str(args.output / "codex-home"))
            argv = [str(args.codex), "app-server"] if args.lane == "app-server" else [str(args.facade),
                "--codex-home", env["CODEX_HOME"], "--codex-exe", str(args.codex), "--cwd", str(workspace)]
            client = JsonProcess(argv, str(workspace), env, args.output / "executor.jsonl")
            driver = CodexDriver(client, backend, workspace, backend.ready["tools"], max_tool_calls=1, instructions=INSTRUCTIONS)
            try:
                result = driver.run(session, prompt, timeout=remaining(deadline))
            except LaneAbort as error:
                if args.case != "cancel" or error.result.get("status") != "pending_tool" or not report.get("injected"):
                    raise
                result = error.result
                report["codex_interrupt"] = confirm_codex_interrupt(client, result, deadline)
            report["codex_resident_pid"] = client.process.pid
            if client.process.poll() is not None:
                raise ValueError("Codex executor did not remain resident through the fault")
        report["initial_result"] = result
        if args.case == "cancel":
            result = backend.reconcile_cancel(deadline)
        elif result.get("status") != "completed" or result.get("answer", "").strip() != ANSWER or backend.restarts != 1:
            raise ValueError("restored original turn did not complete exactly once")
        report["result"], report["restarts"] = result, backend.restarts
        after = operation_evidence(args.output, backend.command, require_pending=False)
        same_operation(report["before"], after)
        if (after["state"].get("pending_tool") is not None or after["state"]["tool_calls"] != 1
                or after["state"]["completed_call_ids"] != [after["admission"]["call"]["call_id"]]):
            raise ValueError("original owner did not consume exactly one original terminal result")
        terminal = read_json(Path(after["remote"]) / "exit.json")
        if (terminal.get("job_id") != after["job"]["id"]
                or terminal.get("terminal_publication_protocol") != 1
                or terminal.get("output_complete") is not True or terminal.get("output_durable") is not True):
            raise ValueError("original fault process has no complete durable terminal publication")
        report["terminal"], report["after"] = terminal, after
        original = report["original_child_proc"]
        present = process_identity(original["pid"])
        if present and present["start_ticks"] == original["start_ticks"] and present["state"] != "Z":
            raise ValueError("original runtime child remains live after terminal reconciliation")
        if args.case == "cancel":
            expected_status = "cancelled" if args.lane == "native" else "completed"
            if result.get("status") != expected_status:
                raise ValueError("original owner did not report the lane's terminal cancellation state")
            if terminal.get("cancelled") is not True or terminal.get("timed_out") is not False:
                raise ValueError("original runtime terminal does not confirm explicit cancellation")
            if args.lane != "native" and json.loads(result["output"])["exit_code"] != terminal["exit_code"]:
                raise ValueError("helper cancellation receipt changed the original terminal exit code")
            expected_calls = 1
        else:
            if ((workspace / "done").read_bytes() != b"once\n" or terminal.get("exit_code") != 0
                    or terminal.get("cancelled") is not False or terminal.get("timed_out") is not False):
                raise ValueError("original recovered process did not create its exact done artifact")
            expected_calls = 2
        if after["state"]["model_calls"] != (expected_calls if args.lane == "native" else 0):
            raise ValueError("owner model admissions changed across the controlled fault")
        settle = time.monotonic() + 3
        while len(gateway.records) < expected_calls and time.monotonic() < settle:
            time.sleep(0.01)
        if (len(gateway.records) != expected_calls or any(record.get("http_status") != 200 or record.get("error")
                for record in gateway.records)):
            raise ValueError("fault run changed or lost its original model request count")
        responses = [response_objects(path) for path in sorted(evidence.glob("*.response.sse"))]
        calls = [item for response in responses for item in response["output"] if item.get("type") == "function_call"]
        if len(calls) != 1 or {key: calls[0][key] for key in ("call_id", "name", "arguments")} != after["admission"]["call"]:
            raise ValueError("fault recovery rebound its original model proposal")
        if args.case == "recover_process":
            request = read_json(sorted(evidence.glob("*.request.json"))[-1])
            feedback = [item for item in request["input"] if item.get("type") == "function_call_output"]
            if (len(feedback) != 1 or feedback[0]["call_id"] != calls[0]["call_id"]
                    or feedback_value(feedback[0]) != {"exit_code": 0, "stdout": "STARTED\n", "stderr": ""}):
                raise ValueError("restored model did not receive the original terminal result")
        if any(digest(Path(path)) != checksum for path, checksum in fingerprints.items()):
            raise ValueError("frozen source or executable changed during the fault trial")
        report["model_requests"] = list(gateway.records)
        report["passed"] = True
    except Exception as error:
        report["error"] = repr(error)
    finally:
        shutdown_errors = []
        for name, owner in (("codex", client), ("runner", backend), ("gateway", gateway)):
            if owner:
                try:
                    owner.close()
                except Exception as error:
                    shutdown_errors.append({"owner": name, "error": repr(error)})
        if shutdown_errors:
            report["shutdown_errors"] = shutdown_errors
            report["passed"] = False
            report.setdefault("error", "one or more experiment owners did not close cleanly")
        save(args.output / "REPORT.json", report)
    print(json.dumps({"report": str(args.output / "REPORT.json"), "passed": report["passed"], "error": report.get("error")}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "native", "codex", "facade"):
        parser.add_argument("--" + name, type=lambda value: Path(value).resolve(), required=True)
    parser.add_argument("--lane", choices=LANES, required=True)
    parser.add_argument("--case", choices=("cancel", "recover_process"), required=True)
    parser.add_argument("--timeout", type=int, default=120)
    raise SystemExit(run(parser.parse_args()))
