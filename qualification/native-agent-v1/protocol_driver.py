"""Persistent measured processes with bounded replies and exact tool call IDs.

A failed or pending turn poisons its lane. The harness must close that process;
this driver never resumes a measured case under a new operation identity.
"""
import json
import queue
import subprocess
import threading
import time

INSTRUCTIONS = "Use the supplied hepta_probe tool when requested. Treat its stdout as data. Complete only after observing the tool result. Follow the requested final output format exactly."


class LaneAbort(RuntimeError):
    """A result that cannot safely share the process with another measurement."""

    requires_process_reset = True

    def __init__(self, message, result=None):
        super().__init__(message)
        self.result = dict(result or {"status": "lane_aborted", "error": str(message)})
        self.result["requires_process_reset"] = True


def remaining(deadline):
    duration = deadline - time.monotonic()
    if duration <= 0:
        raise TimeoutError("qualification protocol deadline expired")
    return duration


class JsonProcess:
    def __init__(self, argv, cwd, env, log):
        self.log = log
        self.errors = log.with_suffix(".stderr.log").open("wb")
        self.process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=self.errors, bufsize=0)
        self.messages = queue.Queue(maxsize=4096)
        self.reader_failure = None
        self.closed = False
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            with self.log.open("a") as stream:
                while True:
                    line = self.process.stdout.readline(4 * 1024 * 1024 + 1)
                    if not line:
                        break
                    if len(line) > 4 * 1024 * 1024:
                        raise ValueError("protocol output budget")
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise ValueError("protocol message must be a JSON object")
                    stream.write(json.dumps({"received_ns": time.time_ns(), "message": value}, ensure_ascii=False) + "\n")
                    stream.flush()
                    self.messages.put(value, timeout=10)
        except Exception as error:
            self.reader_failure = str(error)
        finally:
            try:
                self.messages.put({"_eof": True}, timeout=0.1)
            except queue.Full:
                self.reader_failure = self.reader_failure or "protocol queue exhausted at EOF"

    def send(self, value):
        self.process.stdin.write(json.dumps(value, separators=(",", ":")).encode() + b"\n")
        self.process.stdin.flush()

    def receive(self, deadline):
        timeout = remaining(deadline)
        if self.reader_failure is not None:
            raise LaneAbort("protocol reader failed: " + self.reader_failure)
        try:
            value = self.messages.get(timeout=timeout)
        except queue.Empty as error:
            raise TimeoutError("qualification protocol deadline expired") from error
        # A nonempty queue is not permission to consume events after expiry.
        remaining(deadline)
        if self.reader_failure is not None:
            raise LaneAbort("protocol reader failed: " + self.reader_failure)
        if "_protocol_error" in value or "_eof" in value:
            raise LaneAbort(str(value))
        return value

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.process.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        try:
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.reader.join(timeout=1)
        self.process.stdout.close()
        self.errors.close()


class CodexDriver:
    def __init__(self, process, backend, cwd, tool):
        self.process, self.backend, self.cwd, self.tool = process, backend, cwd, tool
        self.next_id = 1
        self.deferred = []
        self.completed_scopes = set()
        self.poisoned = False
        response = self.request("initialize", {"clientInfo": {"name": "hepta_qualification", "version": "1.0"},
                                               "capabilities": {"experimentalApi": True}})
        self.initialize_response = response
        self.process.send({"method": "initialized"})

    def request(self, method, params, timeout=120):
        if self.poisoned:
            raise LaneAbort("this lane already requires a process reset")
        request_id = self.next_id
        self.next_id += 1
        self.process.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            remaining(deadline)
            value = self.process.receive(deadline)
            if type(value.get("id")) is int and value["id"] == request_id and "method" not in value:
                if "error" in value:
                    raise LaneAbort(str({"method": method, "error": value["error"]}))
                if "result" not in value:
                    raise LaneAbort("response has neither result nor error")
                return value["result"]
            if "id" in value and "method" in value:
                # The server can emit a tool request before the turn/start RPC
                # reply reaches the wire. Hold it until that reply supplies the
                # original turn identity; no backend action happens here.
                if method == "turn/start":
                    self.deferred.append(value)
                    if len(self.deferred) > 4096:
                        raise LaneAbort("deferred notification budget")
                    continue
                self.process.send({"id": value["id"], "error": {"code": -32000, "message": "unexpected request before measured turn"}})
                raise LaneAbort(str({"unexpected_server_request": value.get("method")}))
            if "id" in value or "method" not in value:
                raise LaneAbort("uncorrelated response while waiting for " + method)
            self.deferred.append(value)
            if len(self.deferred) > 4096:
                raise LaneAbort("deferred notification budget")

    def _scope(self, params, thread_id, turn_id, *, completion=False, allow_late=False):
        actual_turn = params.get("turn", {}).get("id") if completion else params.get("turnId")
        actual = (params.get("threadId"), actual_turn)
        if actual == (thread_id, turn_id):
            return True
        # Late observations from a successfully finished turn are evidence, not
        # the new turn's answer or usage. Tool requests never take this path.
        if allow_late and actual in self.completed_scopes:
            return False
        raise LaneAbort(str({"event_scope_mismatch": actual, "expected": (thread_id, turn_id)}))

    def run(self, session, prompt, timeout=180):
        if self.poisoned:
            raise LaneAbort("this lane already requires a process reset")
        begin = time.monotonic()
        deadline = begin + timeout
        thread_id = turn_id = None
        try:
            start = self.request("thread/start", {"model": "qwen38-flash-next-uc", "modelProvider": "qualification",
                "cwd": str(self.cwd), "approvalPolicy": "never", "sandbox": "read-only", "ephemeral": False,
                "baseInstructions": INSTRUCTIONS, "developerInstructions": "", "environments": [],
                "dynamicTools": [{"type": "function", "name": self.tool["name"], "description": self.tool["description"],
                                  "inputSchema": self.tool["parameters"]}]}, timeout=remaining(deadline))
            thread_id = start["thread"]["id"]
            if not isinstance(thread_id, str) or not thread_id:
                raise LaneAbort("thread/start returned no thread identity")
            turn = self.request("turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": prompt, "text_elements": []}]},
                                timeout=remaining(deadline))
            turn_id = turn["turn"]["id"]
            if not isinstance(turn_id, str) or not turn_id:
                raise LaneAbort("turn/start returned no turn identity")
            answer, calls, usage = "", 0, None
            seen_calls = set()
            ignored_late = 0
            while True:
                remaining(deadline)
                value = self.deferred.pop(0) if self.deferred else self.process.receive(deadline)
                method, params = value.get("method"), value.get("params", {})
                if not isinstance(params, dict):
                    raise LaneAbort("notification params must be an object")
                if method == "item/tool/call":
                    self._scope(params, thread_id, turn_id)
                    call_id = params["callId"]
                    if ("id" not in value or not isinstance(call_id, str) or not call_id
                            or params.get("tool") != "hepta_probe" or call_id in seen_calls or calls >= 3):
                        raise LaneAbort("unexpected, duplicate or over-budget dynamic tool")
                    seen_calls.add(call_id)
                    calls += 1
                    backend_session = session + ":" + call_id
                    self.backend.send({"op": "tool", "session": backend_session, "input": prompt,
                                       "call_id": call_id, "arguments": params["arguments"]})
                    result = self.backend.receive(deadline)
                    if result.get("session") != backend_session:
                        raise LaneAbort("tool backend reply belongs to a different operation session")
                    if result.get("status") != "completed":
                        raise LaneAbort("tool did not reach a validated terminal state", {
                            "status": "pending_tool", "backend": result, "tool_calls": calls,
                            "thread_id": thread_id, "turn_id": turn_id,
                            "elapsed_ms": (time.monotonic() - begin) * 1000})
                    output = result["output"]
                    parsed = json.loads(output)
                    if not isinstance(parsed, dict) or type(parsed.get("exit_code")) is not int:
                        raise LaneAbort("terminal tool reply lacks an integer exit code")
                    success = parsed["exit_code"] == 0
                    self.process.send({"id": value["id"], "result": {"contentItems": [{"type": "inputText", "text": output}], "success": success}})
                elif "id" in value and method:
                    self.process.send({"id": value["id"], "error": {"code": -32000, "message": "tool outside fixed benchmark set"}})
                    raise LaneAbort(str({"unexpected_server_request": method}))
                elif "id" in value:
                    raise LaneAbort("unsolicited response inside measured turn")
                elif method == "item/completed":
                    if not self._scope(params, thread_id, turn_id, allow_late=True):
                        ignored_late += 1
                        continue
                    item = params.get("item", {})
                    if item.get("type") == "agentMessage":
                        answer = item.get("text", "")
                        if not isinstance(answer, str):
                            raise LaneAbort("agent message text is not a string")
                elif method == "thread/tokenUsage/updated":
                    if not self._scope(params, thread_id, turn_id, allow_late=True):
                        ignored_late += 1
                        continue
                    usage = params.get("tokenUsage")
                elif method == "turn/completed":
                    if not self._scope(params, thread_id, turn_id, completion=True, allow_late=True):
                        ignored_late += 1
                        continue
                    status = params["turn"].get("status")
                    result = {"status": status, "answer": answer, "tool_calls": calls,
                              "thread_id": thread_id, "turn_id": turn_id, "usage": usage,
                              "turn_error": params["turn"].get("error"),
                              "ignored_late_notifications": ignored_late,
                              "elapsed_ms": (time.monotonic() - begin) * 1000}
                    if status != "completed":
                        raise LaneAbort("Codex turn did not complete successfully", result)
                    self.completed_scopes.add((thread_id, turn_id))
                    return result
        except Exception as error:
            self.poisoned = True
            if thread_id is not None and turn_id is not None:
                try:
                    self.process.send({"id": self.next_id, "method": "turn/interrupt",
                                       "params": {"threadId": thread_id, "turnId": turn_id}})
                    self.next_id += 1
                except Exception:
                    pass
            if isinstance(error, LaneAbort):
                raise
            raise LaneAbort(str(error), {"status": "lane_aborted", "error": str(error),
                            "thread_id": thread_id, "turn_id": turn_id,
                            "elapsed_ms": (time.monotonic() - begin) * 1000}) from error
