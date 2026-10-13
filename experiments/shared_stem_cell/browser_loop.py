"""Real Chromium + MCP stdio comparison on a PRIVATE, locally created fixture.

The four arms use identical browser operations and admission logic. MCP batched
programs are retained as a strong control. This is not a Hepta product FinalUse
implementation, arbitrary desktop controller, full MCP server or GPU benchmark.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import sys
import tempfile
import time

from experiments.shared_stem_cell.wire import InputError, canonical, decode, sha, write_once

PROTOCOL = "2025-11-25"
MAX_WIRE = 65536
HTML = """<!doctype html><html><body>
<label>Task value<input id="task" autocomplete="off"></label>
<button id="save">Save</button><output id="result" aria-label="Saved value"></output>
<script>
(() => {
let count=0;
document.querySelector('#save').onclick = () => {
 document.querySelector('#result').textContent = document.querySelector('#task').value;
 document.body.dataset.count = String(++count);
};
})();
</script></body></html>"""
STATE_SCRIPT = """() => ({value: document.querySelector('#task').value,
 result: document.querySelector('#result').textContent,
 count: Number(document.body.dataset.count || 0)})"""


class BrowserFixture:
    """One serialized owner for a disposable page, with bounded research journal."""
    def __init__(self):
        from playwright.sync_api import sync_playwright
        self.playwright = sync_playwright().start()
        binary = os.environ.get("HEPTA_CHROMIUM") or shutil.which("chromium")
        options = {"headless": True, "args": ["--disable-dev-shm-usage", "--disable-background-networking"]}
        if binary:
            options["executable_path"] = binary
        try:
            self.browser = self.playwright.chromium.launch(**options)
            self.context = self.browser.new_context()
            self.context.route("**/*", lambda route: route.abort())
            self.page = self.context.new_page()
            self.page.set_default_timeout(3000)
        except Exception:
            self.playwright.stop()
            raise
        self.generation = 0
        self.log_dir = tempfile.TemporaryDirectory(prefix="hepta-ui-fixture-")
        self.journal = open(Path(self.log_dir.name) / "journal.jsonl", "xb")
        self.reset()

    def _record(self, row):
        self.journal.write(canonical(row))
        self.journal.flush()
        os.fsync(self.journal.fileno())

    def reset(self):
        if getattr(self, "quarantined", False):
            raise InputError("unknown effect must be reconciled before reset")
        self.generation += 1
        self.sequence = 0
        self.revoked = False
        self.quarantined = False
        self.pending = None
        self.page.set_content(HTML)
        self._record({"event": "reset", "generation": self.generation})
        return self.observe()

    def observe(self):
        state = self.page.evaluate(STATE_SCRIPT)
        return {"state": state, "digest": sha(canonical(state)),
                "generation": self.generation, "sequence": self.sequence,
                "targets": {"fill": sha(canonical([self.generation, "textbox", "Task value"])),
                            "click": sha(canonical([self.generation, "button", "Save"]))}}

    def action(self, request):
        if not isinstance(request, dict) or set(request) != {
            "op", "value", "generation", "sequence", "state_digest", "target_digest"
        }:
            raise InputError("closed action shape")
        if self.quarantined or self.revoked:
            raise InputError("revoked or unknown-effect generation")
        if any(type(request[k]) is not int for k in ("generation", "sequence")):
            raise InputError("exact generation and sequence required")
        if request["generation"] != self.generation or request["sequence"] != self.sequence:
            raise InputError("stale generation or replay")
        op, value = request["op"], request["value"]
        if (op not in {"fill", "click"} or not isinstance(value, str)
                or len(value.encode()) > 160 or (op == "click" and value != "")):
            raise InputError("bounded typed action")
        before = self.observe()
        if request["state_digest"] != before["digest"] or request["target_digest"] != before["targets"][op]:
            raise InputError("stale observation or element binding")
        self.pending = {"request": request.copy(), "before": before["state"]}
        self._record({"event": "entered", **self.pending})
        self.sequence += 1
        try:
            if op == "fill":
                self.page.get_by_role("textbox", name="Task value", exact=True).fill(value)
            else:
                self.page.get_by_role("button", name="Save", exact=True).click()
            # Test-only fault cut AFTER actual browser effect, BEFORE completion.
            if getattr(self, "fault_after_effect", False):
                self.fault_after_effect = False
                raise RuntimeError("injected post-effect acknowledgement loss")
            after = self.observe()
            state = after["state"]
            valid = (state["value"] == value if op == "fill" else
                     state["count"] == before["state"]["count"] + 1
                     and state["result"] == before["state"]["value"])
            if not valid:
                raise InputError("effect postcondition not observed")
            self._record({"event": "completed", "sequence": request["sequence"], "after": after})
            self.pending = None
            return after
        except Exception:
            self.quarantined = True
            self._record({"event": "indeterminate", "sequence": request["sequence"]})
            raise

    def revoke(self):
        self.revoked = True
        self._record({"event": "revoked", "generation": self.generation})
        return {"revoked": True}

    def reconcile(self):
        if not self.quarantined or self.pending is None:
            raise InputError("no pending effect")
        state = self.observe()["state"]
        request, before = self.pending["request"], self.pending["before"]
        if request["op"] == "click":
            applied = state["count"] == before["count"] + 1 and state["result"] == before["value"]
        else:
            applied = state["value"] == request["value"] and state["count"] == before["count"]
        if not applied:
            return {"status": "unknown", "replay_permitted": False}
        self._record({"event": "reconciled_applied", "generation": self.generation})
        self.quarantined = False
        self.pending = None
        return {"status": "applied", "replay_permitted": False}

    def program(self, value):
        # Closed two-instruction plan; each effect obtains a NEW observation.
        if not isinstance(value, str) or not 1 <= len(value.encode()) <= 160:
            raise InputError("bounded program parameter")
        for op, arg in (("fill", value), ("click", "")):
            observation = self.observe()
            self.action(action_frame(observation, op, arg))
        return self.observe()

    def call(self, name, arguments):
        if name == "fixture_action":
            return self.action(arguments)
        if name == "fixture_program" and set(arguments) == {"value"}:
            return self.program(arguments["value"])
        if arguments:
            raise InputError("unexpected tool arguments")
        methods = {"fixture_observe": self.observe, "fixture_reset": self.reset,
                   "fixture_revoke": self.revoke, "fixture_reconcile": self.reconcile}
        if name not in methods:
            raise InputError("unknown fixture tool")
        return methods[name]()

    def close(self):
        self.journal.close()
        self.context.close()
        self.browser.close()
        self.playwright.stop()
        self.log_dir.cleanup()


def action_frame(observation, op, value):
    return {"op": op, "value": value, "generation": observation["generation"],
            "sequence": observation["sequence"], "state_digest": observation["digest"],
            "target_digest": observation["targets"][op]}


def tool_list():
    tools = []
    for name in ("fixture_observe", "fixture_reset", "fixture_revoke", "fixture_reconcile",
                 "fixture_action", "fixture_program"):
        properties = {}
        if name == "fixture_program":
            properties = {"value": {"type": "string", "maxLength": 160}}
        elif name == "fixture_action":
            properties = {"op": {"type": "string", "enum": ["fill", "click"]},
                "value": {"type": "string", "maxLength": 160},
                "generation": {"type": "integer", "minimum": 1},
                "sequence": {"type": "integer", "minimum": 0},
                "state_digest": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "target_digest": {"type": "string", "pattern": "^[a-f0-9]{64}$"}}
        tools.append({"name": name, "description": "Operate only this server's disposable local fixture.",
            "inputSchema": {"type": "object", "properties": properties,
                            "required": list(properties), "additionalProperties": False}})
    return tools


def serve():
    """Minimal real MCP stdio lifecycle + tools profile; stdout is protocol only."""
    owner = BrowserFixture()
    initialized = False
    negotiated = False
    try:
        while True:
            line = sys.stdin.buffer.readline(MAX_WIRE + 1)
            if not line:
                break
            if len(line) > MAX_WIRE or not line.endswith(b"\n"):
                raise InputError("oversized or unterminated MCP message")
            message = decode(line)
            request_id = message.get("id")
            method = message.get("method")
            if message.get("jsonrpc") != "2.0" or not isinstance(method, str):
                raise InputError("invalid MCP envelope")
            if "id" not in message:
                if method == "notifications/initialized" and negotiated:
                    initialized = True
                continue
            try:
                args = message.get("params", {})
                if method == "initialize" and not negotiated:
                    if args.get("protocolVersion") != PROTOCOL or not isinstance(args.get("clientInfo"), dict):
                        raise InputError("unsupported initialization")
                    negotiated = True
                    result = {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                              "serverInfo": {"name": "hepta-private-fixture", "version": "1.0"}}
                elif method == "ping":
                    result = {}
                elif not initialized:
                    raise InputError("MCP client has not initialized")
                elif method == "tools/list":
                    result = {"tools": tool_list()}
                elif method == "tools/call":
                    if args.get("name") not in {tool["name"] for tool in tool_list()}:
                        raise InputError("unknown tool")
                    try:
                        content = owner.call(args["name"], args.get("arguments", {}))
                        result = {"content": [{"type": "text", "text": canonical(content).decode()}],
                                  "structuredContent": content, "isError": False}
                    except (InputError, RuntimeError) as error:
                        result = {"content": [{"type": "text", "text": str(error)}], "isError": True}
                else:
                    raise InputError("unsupported method")
                response = {"jsonrpc": "2.0", "id": request_id, "result": result}
            except (InputError, KeyError, TypeError) as error:
                response = {"jsonrpc": "2.0", "id": request_id,
                            "error": {"code": -32602, "message": str(error)}}
            sys.stdout.buffer.write(canonical(response))
            sys.stdout.buffer.flush()
    finally:
        owner.close()


class McpClient:
    def __init__(self):
        self.next_id = 0
        self.buffer = b""
        self.log = tempfile.TemporaryFile()
        self.process = subprocess.Popen(
            [sys.executable, "-m", "experiments.shared_stem_cell.browser_loop", "--serve"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        started = time.perf_counter_ns()
        try:
            response = self.rpc("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                "clientInfo": {"name": "hepta-fixture-benchmark", "version": "1.0"}})
            if response.get("protocolVersion") != PROTOCOL or "tools" not in response.get("capabilities", {}):
                raise InputError("MCP negotiation mismatch")
            self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            tools = self.rpc("tools/list", {})
            if {tool["name"] for tool in tools["tools"]} != {tool["name"] for tool in tool_list()}:
                raise InputError("MCP tool inventory mismatch")
        except Exception:
            self.close()
            raise
        self.startup_ns = time.perf_counter_ns() - started

    def send(self, message):
        raw = canonical(message)
        if len(raw) > MAX_WIRE:
            raise InputError("MCP request too large")
        self.process.stdin.write(raw)
        self.process.stdin.flush()

    def rpc(self, method, params):
        self.next_id += 1
        request_id = self.next_id
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + 30
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise InputError("MCP timeout; effects remain unknown, no replay")
            chunk = os.read(self.process.stdout.fileno(), 4096)
            if not chunk:
                raise InputError("MCP EOF; effects remain unknown, no replay")
            self.buffer += chunk
            if len(self.buffer) > MAX_WIRE:
                raise InputError("oversized MCP response")
        line, self.buffer = self.buffer.split(b"\n", 1)
        response = decode(line)
        if response.get("jsonrpc") != "2.0" or response.get("id") != request_id or "error" in response:
            raise InputError("MCP response error/identity mismatch")
        return response["result"]

    def call(self, name, arguments):
        result = self.rpc("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise InputError(result["content"][0]["text"])
        structured = result["structuredContent"]
        if decode(result["content"][0]["text"].encode()) != structured:
            raise InputError("MCP structured/text response mismatch")
        return structured

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process.stdout.close()
        self.selector.close()
        self.log.close()


def run(output: Path, tasks=24):
    if type(tasks) is not int or not 4 <= tasks <= 256:
        raise InputError("bounded task count")
    output.mkdir(parents=True, exist_ok=False)
    arms = ("typed_steps", "mcp_steps", "typed_program", "mcp_program")
    plan = {"arms": arms, "tasks": tasks, "fixture_sha256": sha(HTML.encode()),
            "protocol": PROTOCOL, "source_sha256": sha(Path(__file__).read_bytes()),
            "task_domain": "synthetic_private_form_in_real_chromium", "production_accepted": False}
    write_once(output / "plan.json", plan)
    started = time.perf_counter_ns()
    local = BrowserFixture()
    local_startup = time.perf_counter_ns() - started
    remote = None
    rows = []
    try:
        remote = McpClient()
        for task in range(tasks):
            value = f"hepta-task-{task:04d}"
            # Latin-square-like rotation balances order; no success-only filtering.
            for arm in arms[task % 4:] + arms[:task % 4]:
                owner = remote if arm.startswith("mcp") else local
                owner.call("fixture_reset", {})
                start = time.perf_counter_ns()
                status, error, result = "completed", None, None
                try:
                    if arm.endswith("program"):
                        result = owner.call("fixture_program", {"value": value})
                    else:
                        for op, arg in (("fill", value), ("click", "")):
                            observation = owner.call("fixture_observe", {})
                            owner.call("fixture_action", action_frame(observation, op, arg))
                        result = owner.call("fixture_observe", {})
                except Exception as failure:
                    status, error = "unknown", type(failure).__name__ + ": " + str(failure)
                row = {"arm": arm, "task": task, "latency_ns": time.perf_counter_ns() - start,
                       "status": status, "error": error, "result": result}
                rows.append(row)
                write_once(output / f"raw-{task:04d}-{arm}.json", row)
                if status != "completed":
                    raise InputError("unknown browser effect: stopping, not resetting or replaying")
        seal = write_once(output / "predictions.json", {"rows": rows})
        summaries = []
        for arm in arms:
            samples = [r for r in rows if r["arm"] == arm]
            successes = sum(r["result"]["state"]["result"] == f"hepta-task-{r['task']:04d}"
                            and r["result"]["state"]["count"] == 1 for r in samples)
            values = sorted(r["latency_ns"] for r in samples)
            summaries.append({"arm": arm, "attempted": len(samples), "succeeded": successes,
                "latency_ns": {f"p{p}": values[max(0, (len(values) * p + 99) // 100 - 1)] for p in (50, 95, 99)}})
        # Real effects + same-owner revocation and unknown acknowledgement cuts.
        local.reset()
        snapshot = local.observe()
        local.revoke()
        try:
            local.action(action_frame(snapshot, "fill", "must-not-appear"))
            raise AssertionError("revocation bypass")
        except InputError:
            pass
        assert local.observe()["state"]["value"] == ""
        local.reset()
        local.action(action_frame(local.observe(), "fill", "fault-cut"))
        local.fault_after_effect = True
        try:
            local.action(action_frame(local.observe(), "click", ""))
            raise AssertionError("missing fault cut")
        except RuntimeError:
            pass
        assert local.quarantined and local.observe()["state"]["count"] == 1
        recovery = local.reconcile()
        assert recovery["status"] == "applied" and local.observe()["state"]["count"] == 1
        report = {**plan, "predictions_sha256": seal, "results": summaries,
                  "cold_start_ns": {"typed_browser": local_startup, "mcp_server_browser": remote.startup_ns},
                  "chromium": local.browser.version, "revocation_blocked": True,
                  "post_effect_unknown_reconciled_without_replay": True,
                  "unclean_process_recovery_verified": False, "native_jit_or_gpu_measured": False,
                  "energy_joules": None, "peak_rss_bytes": None,
                  "task_reasoning_quality": None, "hepta_final_use_integrated": False}
        write_once(output / "report.json", report)
        return report
    except Exception as error:
        write_once(output / "failure.json", {"exception": type(error).__name__, "message": str(error),
                   "attempted_rows": len(rows), "production_accepted": False})
        raise
    finally:
        if remote is not None:
            remote.close()
        local.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--tasks", type=int, default=24)
    args = parser.parse_args()
    if args.serve:
        serve()
    elif args.output:
        run(args.output, args.tasks)
    else:
        parser.error("--serve or --output required")
