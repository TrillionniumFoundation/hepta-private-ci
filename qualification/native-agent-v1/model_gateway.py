"""Shared bounded model boundary for fixed-response replay and live comparisons.

Replay never estimates model compute. Live forwards to the same configured
provider and imposes the same output/context/call ceilings on every lane.
"""
import hashlib
import http.client
import http.server
import json
import threading
import time
import urllib.parse


def wire(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


class ModelGateway:
    def __init__(self, mode, upstream, evidence, context_bytes=65536, output_tokens=256, model_calls=4):
        self.mode = mode
        self.upstream = urllib.parse.urlsplit(upstream)
        self.evidence = evidence
        self.context_bytes = context_bytes
        self.output_tokens = output_tokens
        self.model_calls = model_calls
        self.lock = threading.Lock()
        self.case = None
        self.records = []
        self.attempts = 0
        self.responses = {}
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_):
                return

            def send_json(self, status, value):
                record = getattr(self, "attempt_record", None)
                if record is not None:
                    record["http_status"] = status
                    if status >= 400:
                        record["error"] = str(value.get("error", "gateway rejection"))
                data = wire(value)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path.rstrip("/").endswith("/models"):
                    return self.send_json(200, {"object": "list", "data": [{"id": "qwen38-flash-next-uc", "object": "model"}]})
                response_id = self.path.rsplit("/", 1)[-1]
                if response_id in owner.responses:
                    return self.send_json(200, owner.responses[response_id])
                return self.send_json(404, {"error": "original response unavailable"})

            def do_POST(self):
                # Persist admission of every HTTP attempt before validation or
                # provider dispatch. Missing terminal records remain unknown;
                # failed and over-budget requests never disappear from totals.
                with owner.lock:
                    owner.attempts += 1
                    record = {"attempt": owner.attempts,
                        "case": owner.case["name"] if owner.case is not None else None,
                        "mode": owner.mode, "started_ns": time.time_ns(),
                        "dispatch_state": "not_dispatched"}
                    with (owner.evidence / "model_attempts.jsonl").open("a") as stream:
                        stream.write(json.dumps(record, sort_keys=True) + "\n")
                        stream.flush()
                self.attempt_record = record
                try:
                    self.handle_post()
                except Exception as error:
                    record["error"] = str(error)
                    self.close_connection = True
                finally:
                    record["finished_ns"] = time.time_ns()
                    with owner.lock:
                        owner.records.append(dict(record))
                        with (owner.evidence / "model_requests.jsonl").open("a") as stream:
                            stream.write(json.dumps(record, sort_keys=True) + "\n")
                    self.attempt_record = None

            def handle_post(self):
                record = self.attempt_record
                self.connection.settimeout(120)
                requested_close = self.close_connection
                # Reject unread or malformed bodies by closing the connection;
                # their residual bytes must not become another HTTP request.
                self.close_connection = True
                length = int(self.headers.get("Content-Length", "0"))
                record["request_bytes"] = length
                if not self.path.rstrip("/").endswith("/responses") or not 0 < length <= owner.context_bytes:
                    return self.send_json(400, {"error": "shared request path/context byte budget"})
                original = self.rfile.read(length)
                original_path = owner.evidence / f'attempt-{record["attempt"]:04}.request.raw'
                original_path.write_bytes(original)
                record["original_request_file"] = original_path.name
                record["request_sha256"] = hashlib.sha256(original).hexdigest()
                if len(original) != length:
                    return self.send_json(400, {"error": "incomplete request body"})
                try:
                    body = json.loads(original)
                except ValueError:
                    return self.send_json(400, {"error": "invalid JSON"})
                if not isinstance(body, dict):
                    return self.send_json(400, {"error": "request must be a JSON object"})
                with owner.lock:
                    if owner.case is None:
                        return self.send_json(409, {"error": "no admitted benchmark case"})
                    owner.case["calls"] += 1
                    case = dict(owner.case)
                if case["calls"] > owner.model_calls:
                    return self.send_json(429, {"error": "shared model-call budget"})
                requested_output = body.get("max_output_tokens", owner.output_tokens)
                if type(requested_output) is not int or requested_output <= 0:
                    return self.send_json(400, {"error": "positive output-token budget required"})
                body["max_output_tokens"] = min(requested_output, owner.output_tokens)
                if body.get("model") != "qwen38-flash-next-uc":
                    return self.send_json(400, {"error": "benchmark model changed"})
                self.close_connection = requested_close
                effective = wire(body)
                record.update({"case": case["name"], "call": case["calls"], "mode": owner.mode,
                          "request_bytes": length, "effective_bytes": len(effective),
                          "request_sha256": hashlib.sha256(original).hexdigest(),
                          "effective_sha256": hashlib.sha256(effective).hexdigest(),
                          "output_token_cap": body["max_output_tokens"]})
                prefix = owner.evidence / f'{case["name"]}-model-{case["calls"]:02}'
                prefix.with_suffix(".request.json").write_bytes(original)
                prefix.with_suffix(".effective.json").write_bytes(effective)
                record["request_file"] = prefix.with_suffix(".request.json").name
                record["effective_file"] = prefix.with_suffix(".effective.json").name
                record["response_file"] = prefix.with_suffix(".response.sse").name
                captured = bytearray()
                connection = None
                try:
                    if owner.mode == "replay":
                        record["dispatch_state"] = "replay"
                        data, response = owner.replay(case, body)
                        owner.responses[response["id"]] = response
                        # A generated terminal still counts if the local
                        # consumer disconnects before receiving it.
                        captured.extend(data)
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Content-Length", str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                        self.wfile.flush()
                        record["http_status"] = 200
                    else:
                        cls = http.client.HTTPSConnection if owner.upstream.scheme == "https" else http.client.HTTPConnection
                        connection = cls(owner.upstream.hostname, owner.upstream.port, timeout=120)
                        path = owner.upstream.path.rstrip("/") + "/responses"
                        # Once request() starts, a connection error cannot
                        # prove that the remote provider incurred no work.
                        record["dispatch_state"] = "dispatch_attempted"
                        connection.request("POST", path, body=effective,
                                           headers={"Content-Type": "application/json", "Accept": "text/event-stream"})
                        response = connection.getresponse()
                        record["http_status"] = response.status
                        self.send_response(response.status)
                        self.send_header("Content-Type", response.getheader("Content-Type", "application/octet-stream"))
                        self.send_header("Connection", "close")
                        self.end_headers()
                        while True:
                            chunk = response.read1(4096)
                            if not chunk:
                                break
                            captured.extend(chunk)
                            if len(captured) > 1024 * 1024:
                                raise ValueError("shared response byte budget")
                            self.wfile.write(chunk)
                            self.wfile.flush()
                        self.close_connection = True
                        connection.close()
                except Exception as error:
                    record["error"] = str(error)
                    self.close_connection = True
                finally:
                    if connection is not None:
                        connection.close()
                    record["response_bytes"] = len(captured)
                    prefix.with_suffix(".response.sse").write_bytes(captured)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def begin(self, name, task, answer):
        with self.lock:
            self.case = {"name": name, "task": task, "answer": answer, "calls": 0}

    def replay(self, case, body):
        response_id = f'resp_{case["name"]}_{case["calls"]}'
        if case["calls"] == 1:
            item = {"type": "function_call", "id": "fc_" + case["name"], "status": "completed",
                    "call_id": "call_" + case["name"], "name": "hepta_probe", "arguments": json.dumps({"task": case["task"]})}
        elif case["calls"] == 2:
            self.validate_replay_feedback(case, body)
            item = {"type": "message", "id": "msg_" + case["name"], "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": case["answer"], "annotations": []}]}
        else:
            raise ValueError("fixed replay has exactly two original model responses; no replacement response")
        response = {"id": response_id, "object": "response", "created_at": 1,
                    "model": "qwen38-flash-next-uc", "status": "completed", "output": [item],
                    "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
                              "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}}
        added_item = dict(item, status="in_progress")
        if item["type"] == "function_call":
            added_item["arguments"] = ""
        else:
            added_item["content"] = []
        events = [{"type": "response.created", "response": dict(response, status="in_progress", output=[], usage=None)},
                  {"type": "response.output_item.added", "output_index": 0, "item": added_item}]
        if item["type"] == "function_call":
            events += [{"type": "response.function_call_arguments.delta", "item_id": item["id"],
                        "output_index": 0, "delta": item["arguments"]},
                       {"type": "response.function_call_arguments.done", "item_id": item["id"],
                        "output_index": 0, "arguments": item["arguments"]}]
        else:
            events += [{"type": "response.content_part.added", "item_id": item["id"], "output_index": 0, "content_index": 0,
                        "part": {"type": "output_text", "text": "", "annotations": []}},
                       {"type": "response.output_text.delta", "item_id": item["id"], "output_index": 0, "content_index": 0,
                        "delta": case["answer"]},
                       {"type": "response.output_text.done", "item_id": item["id"], "output_index": 0, "content_index": 0,
                        "text": case["answer"]},
                       {"type": "response.content_part.done", "item_id": item["id"], "output_index": 0, "content_index": 0,
                        "part": item["content"][0]}]
        events += [{"type": "response.output_item.done", "output_index": 0, "item": item},
                   {"type": "response.completed", "response": response}]
        for number, event in enumerate(events):
            event["sequence_number"] = number
        return b"".join(b"event: " + event["type"].encode() + b"\ndata: " + wire(event) + b"\n\n" for event in events), response

    @staticmethod
    def validate_replay_feedback(case, body):
        inputs = body.get("input")
        if not isinstance(inputs, list) or any(not isinstance(item, dict) for item in inputs):
            raise ValueError("replay requires the original structured input history")
        outputs = [item for item in inputs if item.get("type") == "function_call_output"]
        if len(outputs) != 1 or outputs[0].get("call_id") != "call_" + case["name"]:
            raise ValueError("replay feedback does not identify its one original tool call")
        output = outputs[0].get("output")
        # The native loop uses a string; the pinned Codex dynamic-tool handler
        # preserves its one InputText as a Responses input_text content array.
        if isinstance(output, list):
            if (len(output) != 1 or not isinstance(output[0], dict)
                    or output[0].get("type") != "input_text"):
                raise ValueError("replay tool feedback is not one complete text result")
            output = output[0].get("text")
        if not isinstance(output, str):
            raise ValueError("replay tool feedback has no exact serialized result")
        result = json.loads(output)
        if (not isinstance(result, dict)
                or set(result) != {"exit_code", "stdout", "stderr"}
                or type(result["exit_code"]) is not int or result["exit_code"] != 0
                or result["stdout"] != case["answer"] + "\n"
                or result["stderr"] != ""):
            raise ValueError("real tool result did not exactly satisfy the fixed fixture; replay cannot repair it")

    def close(self):
        self.server.shutdown()
        self.server.server_close()

