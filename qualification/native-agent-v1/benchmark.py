#!/usr/bin/env python3
"""One resident executor lane per process, sharing the exact runtime fixture.

No production configuration is modified. Failed or pending protocol sessions
abort the lane; they are never silently recycled into another measured case.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time

from model_gateway import ModelGateway
from process_metrics import CgroupScope, ProcessMetrics
from protocol_driver import CodexDriver, JsonProcess


MODEL = "qwen38-flash-next-uc"
BUDGET = {"context_bytes": 65536, "output_tokens": 256, "model_calls": 4,
          "tool_calls": 3, "tool_output_bytes": 32768,
          "model_timeout_seconds": 120, "tool_timeout_seconds": 60}


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            checksum.update(chunk)
    return checksum.hexdigest()


def private_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.stat().st_mode & 0o077:
        raise ValueError(f"qualification directory is not private: {path}")


def expected(data):
    raw = data.read_bytes()
    return {"sum": {"sum": sum(int(x) for x in raw.splitlines())},
            "lines": {"lines": len(raw.splitlines())},
            "digest": {"sha256": hashlib.sha256(raw).hexdigest()}}


def prompt(task):
    return (f'Call hepta_probe exactly once with task="{task}". '
            "After the tool completes successfully, return exactly its stdout JSON object. "
            "Do not calculate the answer yourself. Do not add markdown, explanation or other text.")


class RuntimeGroups:
    """Discover detached jobs only from this lane's new controller registry."""
    def __init__(self, controller):
        self.controller = controller
        self.started_ms = time.time_ns() // 1_000_000
        self.known = {}
        self.errors = []
        self.parent = None
        for line in Path("/proc/self/cgroup").read_text().splitlines():
            if line.startswith("0::"):
                self.parent = Path("/sys/fs/cgroup") / line[3:].lstrip("/")

    def scopes(self):
        scopes = [CgroupScope(self.parent)] if self.parent else []
        for path in (self.controller / "jobs").glob("*.json"):
            if path.name in self.known:
                continue
            try:
                row = json.loads(path.read_text())
                unit = row["unit"]
                if not unit.startswith("hepta-runtime-job-") or "/" in unit:
                    raise ValueError("unexpected runtime unit")
                created = row["created_unix_ms"] >= self.started_ms
                group = (Path("/sys/fs/cgroup/user.slice") / f"user-{os.getuid()}.slice"
                         / f"user@{os.getuid()}.service" / "app.slice" / (unit + ".service"))
                self.known[path.name] = {"job_id": row["id"], "unit": unit,
                    "cgroup": str(group), "created_during_lane": created,
                    "created_unix_ms": row["created_unix_ms"]}
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.errors.append({"file": path.name, "error": str(error)})
        for row in self.known.values():
            scopes.append(CgroupScope(Path(row["cgroup"]), new_since_start=row["created_during_lane"]))
        return scopes


def configure(args, gateway):
    root = args.output
    for name in ("controller", "remote", "sessions", "codex-home"):
        private_dir(root / name)
    runtime = {"state_dir": str(root / "controller"), "controller_workspace_roots": [],
        "hosts": {"qualification": {"ssh_target": "localhost", "platform": "linux",
            "execution_mode": "operator", "remote_state_dir": str(root / "remote"),
            "allow_execute": True, "allow_pty": False, "allow_write": False,
            "allow_job_network": True, "allow_detached_fallback": False}}}
    save(root / "runtime.json", runtime)
    fixture = {"host": "qualification", "script": str(args.fixture / "fixture_tool.py"),
        "script_sha256": digest(args.fixture / "fixture_tool.py"),
        "data": str(args.fixture / "fixture.txt"), "data_sha256": digest(args.fixture / "fixture.txt"),
        "cwd": str(args.fixture), "tool_timeout_seconds": BUDGET["tool_timeout_seconds"]}
    config = {"runtime_config": str(root / "runtime.json"), "sessions_dir": str(root / "sessions"),
              "fixture": fixture, "model": MODEL, "responses_url": gateway.url + "/responses", **BUDGET}
    save(root / "runner.json", config)
    # Both Codex lanes receive the same config, dynamic tool and instructions.
    # The captured actual request inventory below determines parity, not flags.
    toml = f'''model = "{MODEL}"
model_provider = "qualification"
model_reasoning_summary = "none"
web_search = "disabled"
approval_policy = "never"
sandbox_mode = "read-only"

[model_providers.qualification]
name = "Qualification gateway"
base_url = "{gateway.url}"
wire_api = "responses"
requires_openai_auth = false
request_max_retries = 0
stream_max_retries = 0
supports_websockets = false

[features]
shell_tool = false
unified_exec = false
view_image = false
multi_agent = false
multi_agent_v2 = false
code_mode = false
goals = false

[tools.update_plan]
enabled = false
[tools.experimental_request_user_input]
enabled = false
'''
    (root / "codex-home" / "config.toml").write_text(toml)
    return config


def inventory(evidence):
    rows = []
    for path in sorted(evidence.glob("*.request.json")):
        try:
            body = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            rows.append({"file": path.name, "only_shared_tool": False, "error": str(error)})
            continue
        tools = []
        for tool in body.get("tools", []):
            if isinstance(tool, dict):
                tools.append({"type": tool.get("type"), "name": tool.get("name"),
                              "namespace": tool.get("namespace")})
        rows.append({"file": path.name, "tools": tools,
                     "only_shared_tool": tools == [{"type": "function", "name": "hepta_probe", "namespace": None}],
                     "model": body.get("model"), "store": body.get("store"),
                     "reasoning": body.get("reasoning"), "parallel_tool_calls": body.get("parallel_tool_calls"),
                     "tool_strict": [tool.get("strict") for tool in body.get("tools", []) if isinstance(tool, dict)],
                     "instructions_sha256": hashlib.sha256(json.dumps(body.get("instructions"), sort_keys=True).encode()).hexdigest(),
                     "input_sha256": hashlib.sha256(json.dumps(body.get("input"), sort_keys=True).encode()).hexdigest()})
    return rows


def model_items(path):
    """Read completed items from captured SSE, including multiline data."""
    items, data = [], []
    for line in path.read_text().splitlines() + [""]:
        if line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
        elif not line and data:
            raw, data = "\n".join(data), []
            if raw == "[DONE]":
                continue
            event = json.loads(raw)
            if event.get("type") == "response.output_item.done":
                items.append(event["item"])
            elif event.get("type") == "response.completed":
                items.extend(event.get("response", {}).get("output", []))
    return items


def audit_tool_feedback(evidence, name, task, answer):
    """Bind final-answer scoring to the one actual call and its model feedback."""
    calls, feedback, errors, files = {}, {}, [], []
    for path in sorted(evidence.glob(name + "-model-*.request.json")):
        files.append(path.name)
        try:
            body = json.loads(path.read_text())
            inputs = body.get("input", [])
            if not isinstance(inputs, list):
                raise ValueError("request input is not a structured history")
            response = path.with_name(path.name.removesuffix(".request.json") + ".response.sse")
            items = inputs + model_items(response)
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "function_call":
                    call_id = item.get("call_id")
                    if not isinstance(call_id, str) or not call_id:
                        raise ValueError("model tool call has no original call ID")
                    value = {"name": item.get("name"), "arguments": json.loads(item["arguments"])}
                    if call_id in calls and calls[call_id] != value:
                        raise ValueError("original tool call changed across model history")
                    calls[call_id] = value
                elif item.get("type") == "function_call_output":
                    call_id, output = item.get("call_id"), item.get("output")
                    if not isinstance(call_id, str) or not call_id:
                        raise ValueError("tool feedback has no original call ID")
                    if isinstance(output, list):
                        if len(output) != 1 or output[0].get("type") != "input_text":
                            raise ValueError("tool feedback is not one complete input_text")
                        output = output[0]["text"]
                    value = json.loads(output)
                    if call_id in feedback and feedback[call_id] != value:
                        raise ValueError("tool feedback changed across model history")
                    feedback[call_id] = value
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            errors.append({"file": path.name, "error": str(error)})
    matched = False
    if len(calls) == len(feedback) == 1 and calls.keys() == feedback.keys():
        call_id = next(iter(calls))
        result = feedback[call_id]
        matched = (calls[call_id] == {"name": "hepta_probe", "arguments": {"task": task}}
            and isinstance(result, dict) and set(result) == {"exit_code", "stdout", "stderr"}
            and type(result["exit_code"]) is int and result["exit_code"] == 0
            and result["stdout"] == answer + "\n" and result["stderr"] == "")
    return {"valid": bool(files) and matched and not errors, "request_files": files,
            "calls": calls, "feedback": feedback, "errors": errors}


def capture_settled(gateway, evidence, timeout=2):
    """Do not score success before request threads finish their evidence writes."""
    deadline = time.monotonic() + timeout
    while True:
        requests = list(evidence.glob("*.request.json"))
        if len(gateway.records) == len(requests) and all(
                path.with_name(path.name.removesuffix(".request.json") + ".response.sse").exists()
                for path in requests):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)


def quantiles(values):
    if not values:
        return None
    order = sorted(values)
    return {"n": len(values), "median": statistics.median(values),
            "p95_nearest_rank": order[max(0, (95 * len(order) + 99) // 100 - 1)],
            "min": order[0], "max": order[-1]}


def resource_limits(parent):
    result = {"parent_cgroup": str(parent) if parent else None,
              "affinity_cpus": sorted(os.sched_getaffinity(0)), "load_average": os.getloadavg()}
    for filename in ("cpu.max", "cpu.weight", "memory.max", "cpuset.cpus.effective"):
        try:
            result[filename] = (parent / filename).read_text().strip() if parent else None
        except OSError as error:
            result[filename] = {"unavailable": str(error)}
    return result


def run(args):
    if args.repeats is None:
        args.repeats = 3 if args.mode == "replay" else 2
    if args.repeats <= 0 or args.timeout <= 0:
        raise ValueError("repeats and timeout must be positive")
    os.umask(0o077)
    if args.output.exists():
        raise ValueError("output must be a new immutable qualification run directory")
    private_dir(args.output)
    evidence = args.output / "model"
    private_dir(evidence)
    gateway = ModelGateway(args.mode, args.upstream, evidence, **{
        key: BUDGET[key] for key in ("context_bytes", "output_tokens", "model_calls")})
    config = configure(args, gateway)
    values = expected(args.fixture / "fixture.txt")
    groups = RuntimeGroups(args.output / "controller")
    external = ["Loopback sshd/control-plane work outside explicit local PID/cgroup scopes can be omitted"]
    if args.mode == "live":
        external.append("Upstream model service process tree and compute are not measured")
    # Provenance belongs to the qualification harness, outside the executor's
    # resource window. Fixture provenance was already computed by configure().
    runtime_helper_sha256 = digest(args.native)
    executor_sha256 = (runtime_helper_sha256 if args.lane == "native" else
                       digest(args.codex if args.lane == "app-server" else args.facade))
    platform_description = platform.platform()
    limit_snapshot = resource_limits(groups.parent)
    metrics = ProcessMetrics(root_pids=[os.getpid()], cgroup_paths=groups.scopes,
        sample_interval=0.01, external_work=external).start()
    cases = [("warmup", "sum", True)] if args.warmup else []
    cases += [(f"{repeat:02}-{task}", task, False) for repeat in range(args.repeats) for task in args.tasks]
    report = {"schema": "hepta.native.qualification.benchmark.v1", "lane": args.lane,
        "mode": args.mode, "model": MODEL, "budgets": BUDGET, "rows": [],
        "planned_cases": [{"name": name, "task": task, "warmup": warmup} for name, task, warmup in cases],
        "case_timeout_seconds": args.timeout,
        "started_ns": time.time_ns(), "platform": platform_description, "cpu_count": os.cpu_count(),
        "resource_limits": limit_snapshot, "executor_sha256": executor_sha256,
        "runtime_helper_sha256": runtime_helper_sha256, "fixture": config["fixture"],
        "scope": "One persistent lane; local descendant tree plus discovered runtime cgroups, with explicit gaps",
        "measurement_windows": {"resources": "Whole lane from before backend launch through client/gateway shutdown; includes warmup and observer",
            "case_wall": "Send run or thread/start through successful/failed case result; excludes resident startup and shutdown",
            "resource_totals_are_not_per_case_cpu_or_memory": True,
            "gateway_creation_config_provenance_and_final_audit_outside_resource_window": True},
        "limits": ["RSS sum double-counts shared pages; use PSS where available",
            "Fast exited processes may be missed by sampling; inspect metrics coverage",
            "Facade has a shared outer JSON-lines harness; its internal client uses upstream typed channels",
            "Replay usage values are synthetic and are not model token consumption",
            "Same model/task/ceilings do not imply byte-identical prompts or provider options",
            "Native model deadline is 120s total; gateway upstream I/O timeout is 120s; Codex case deadline is separate",
            "Loopback sshd/control-plane work outside selected scopes can be omitted",
            "Each case creates a fresh thread/session on a resident executor",
            "Timing includes thread creation; startup reported separately"]}
    clients = []
    success = False
    try:
        start = time.monotonic()
        backend = JsonProcess([str(args.native), str(args.output / "runner.json")],
            str(args.fixture), os.environ.copy(), args.output / "backend.jsonl")
        clients.append(backend)
        ready = backend.receive(time.monotonic() + 120)
        if ready.get("ready") is not True or ready.get("protocol") != "qualification.jsonl.v1":
            raise RuntimeError({"backend_did_not_initialize": ready})
        if args.lane == "native":
            driver = None
        else:
            env = os.environ.copy()
            env["CODEX_HOME"] = str(args.output / "codex-home")
            argv = [str(args.codex), "app-server"] if args.lane == "app-server" else [
                str(args.facade), "--codex-home", env["CODEX_HOME"], "--codex-exe", str(args.codex),
                "--cwd", str(args.fixture)]
            client = JsonProcess(argv, str(args.fixture), env, args.output / "executor.jsonl")
            clients.append(client)
            driver = CodexDriver(client, backend, args.fixture, ready["tools"][0])
            report["initialize_response"] = driver.initialize_response
        report["startup_ms"] = (time.monotonic() - start) * 1000
        for name, task, warmup in cases:
            answer = json.dumps(values[task], sort_keys=True, separators=(",", ":"))
            gateway.begin(name, task, answer)
            session = f"{args.output.name}:{name}"
            text = prompt(task)
            begin = time.monotonic()
            result = None
            try:
                if driver is None:
                    backend.send({"op": "run", "session": session, "input": text})
                    result = backend.receive(time.monotonic() + args.timeout)
                    if result.get("session") != session:
                        raise RuntimeError("native response session changed")
                else:
                    result = driver.run(session, text, timeout=args.timeout)
                elapsed = (time.monotonic() - begin) * 1000
                if result.get("status") != "completed":
                    raise RuntimeError({"uncompleted_operation": result, "requires_process_reset": True})
                try:
                    parsed = json.loads(result.get("answer") or "")
                except (ValueError, TypeError):
                    parsed = None
                row = {"name": name, "task": task, "warmup": warmup, "wall_ms": elapsed,
                    "correct": False, "correctness_pending_tool_audit": True,
                    "answer_matches_expected": parsed == values[task],
                    "answer_matches_exact_stdout_json": isinstance(result.get("answer"), str) and result["answer"].strip() == answer,
                    "result": result,
                    "model_requests": [r for r in gateway.records if r["case"] == name]}
                report["rows"].append(row)
                save(args.output / "report.partial.json", report)
                print(json.dumps({"case": name, "lane": args.lane, "mode": args.mode,
                                  "answer_matches_expected": row["answer_matches_expected"],
                                  "correctness_pending_tool_audit": True, "wall_ms": elapsed}), flush=True)
            except Exception as error:
                failed = {"name": name, "task": task, "warmup": warmup,
                    "wall_ms": (time.monotonic() - begin) * 1000, "correct": False,
                    "error": repr(error), "requires_process_reset": True}
                if isinstance(getattr(error, "result", None), dict):
                    failed["result"] = error.result
                elif isinstance(result, dict):
                    failed["result"] = result
                report["rows"].append(failed)
                report["aborted_after_case"] = name
                raise
        success = True
    except Exception as error:
        report["error"] = repr(error)
    finally:
        shutdown_start = time.monotonic()
        for client in reversed(clients):
            try:
                client.close()
            except Exception as error:
                report.setdefault("shutdown_errors", []).append(repr(error))
        gateway.close()
        report["shutdown_ms"] = (time.monotonic() - shutdown_start) * 1000
        report["metrics"] = metrics.stop()
        report["model_capture_complete"] = capture_settled(gateway, evidence)
        for row in report["rows"]:
            answer = json.dumps(values[row["task"]], sort_keys=True, separators=(",", ":"))
            row["tool_feedback_audit"] = audit_tool_feedback(evidence, row["name"], row["task"], answer)
            row["model_requests"] = [record for record in gateway.records if record["case"] == row["name"]]
            row["correctness_pending_tool_audit"] = False
            row["correct"] = ("error" not in row and row.get("answer_matches_exact_stdout_json", False)
                and row.get("result", {}).get("tool_calls") == 1 and row["tool_feedback_audit"]["valid"]
                and report["model_capture_complete"])
        report["detached_runtime_jobs"] = list(groups.known.values())
        report["runtime_discovery_errors"] = groups.errors
        report["model_inventory"] = inventory(evidence)
        report["only_shared_tool_inventory"] = bool(report["model_inventory"]) and all(
            row["only_shared_tool"] for row in report["model_inventory"])
        measured = [row for row in report["rows"] if not row["warmup"]]
        report["summary"] = {"completed_lane": success, "attempted": len(measured),
            "planned": sum(not warmup for _, _, warmup in cases),
            "correct": sum(row["correct"] for row in measured),
            "wall_ms": quantiles([row["wall_ms"] for row in measured if "error" not in row]),
            "all_planned_cases_completed": success,
            "valid_equal_tool_comparison": success and report["model_capture_complete"] and report["only_shared_tool_inventory"],
            "qualification_passed": success and all(row["correct"] for row in report["rows"])
                and report["only_shared_tool_inventory"] and report["model_capture_complete"]}
        report["finished_ns"] = time.time_ns()
        save(args.output / "REPORT.json", report)
        print(json.dumps({"report": str(args.output / "REPORT.json"), "summary": report["summary"],
                          "error": report.get("error")}), flush=True)
    return 0 if report["summary"]["qualification_passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", choices=("native", "app-server", "facade"), required=True)
    parser.add_argument("--mode", choices=("replay", "live"), required=True)
    parser.add_argument("--output", type=lambda x: Path(x).resolve(), required=True)
    parser.add_argument("--fixture", type=lambda x: Path(x).resolve(), required=True)
    parser.add_argument("--native", type=lambda x: Path(x).resolve(), required=True)
    parser.add_argument("--codex", type=lambda x: Path(x).resolve(), required=True)
    parser.add_argument("--facade", type=lambda x: Path(x).resolve(), required=True)
    parser.add_argument("--upstream", default="http://127.0.0.1:18081/v1")
    parser.add_argument("--repeats", type=int, default=None, help="default: 3 replay, 2 live")
    parser.add_argument("--tasks", nargs="+", choices=("sum", "lines", "digest"), default=["sum", "lines", "digest"])
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--warmup", action="store_true")
    raise SystemExit(run(parser.parse_args()))
