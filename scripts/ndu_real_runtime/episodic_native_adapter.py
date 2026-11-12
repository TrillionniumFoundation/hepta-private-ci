"""One-request diagnostic Responses bridge, never a production authority.

The fixed adapter actor puts the *entire exact HTTP JSON body* in one user
message for the existing isolated local provider. JSON roles/instructions/tools
remain serialized data; this is not a claim of commercial Responses semantics.
Capture mode records the same mapping but never invokes the local provider.
"""

import argparse
from dataclasses import asdict
import hashlib
from pathlib import Path
import re
import socketserver
import time

from .episodic_local_provider import LocalProviderProfile, run_local_provider
from .episodic_local_worker import WORKER, verify_returned_generation
from .episodic_provider_handoff import (
    _canonical,
    _json,
    _pin,
    _read_regular,
    _sync_directory,
    _write,
)

SCHEMA = "hepta.mem13.native-responses-adapter.v1"
HTTP_RECEIVE_SECONDS = 15
SOURCES = (
    "ndu_real_runtime/episodic_native_adapter.py",
    "ndu_real_runtime/episodic_local_provider.py",
    "ndu_real_runtime/episodic_local_worker.py",
    "ndu_real_runtime/episodic_provider_handoff.py",
    "hepta_ci_exec.py",
)
FIELDS = {
    "model",
    "instructions",
    "input",
    "tools",
    "tool_choice",
    "parallel_tool_calls",
    "reasoning",
    "store",
    "stream",
    "stream_options",
    "include",
    "service_tier",
    "prompt_cache_key",
    "text",
    "client_metadata",
}


def source_pins():
    scripts = Path(__file__).resolve().parents[1]
    return {name: _pin(_read_regular(scripts / name, 65536)) for name in SOURCES}


_LOADED_SOURCES = source_pins()


def prepare(root, profile, *, request_id, native_source_sha, mode):
    """Freeze an independent native operation before receiving its HTTP input."""
    if (
        re.fullmatch(r"[a-zA-Z0-9_-]{1,96}", request_id) is None
        or re.fullmatch(r"[a-f0-9]{40}", native_source_sha) is None
        or mode not in {"capture", "generate"}
        or source_pins() != _LOADED_SOURCES
    ):
        raise ValueError("fixed source, request identity and adapter mode required")
    root = Path(root).absolute()
    root.mkdir(mode=0o700)
    plan = {
        "schema": SCHEMA,
        "request_id": request_id,
        "native_source_sha": native_source_sha,
        "mode": mode,
        "profile": asdict(LocalProviderProfile(**profile)),
        "mapping": "exact-utf8-responses-json-in-single-user-message.v1",
        "max_input_tokens": 1024,
        "max_output_tokens": 32,
        "provider_timeout_seconds": 60,
        "max_http_body_bytes": 1048576,
        "source_pins": _LOADED_SOURCES,
        "fixture_only": True,
        "observer_authenticated": False,
        "production_adoption": False,
        "scientific_acceptance": "HOLD",
    }
    _write(root / "PLAN.json", _canonical(plan))
    _sync_directory(root.parent)
    return plan


def load_plan(root):
    raw = _read_regular(root / "PLAN.json", 65536)
    plan = _json(raw)
    if (
        raw != _canonical(plan)
        or plan.get("schema") != SCHEMA
        or plan.get("source_pins") != _LOADED_SOURCES
        or source_pins() != _LOADED_SOURCES
        or plan.get("mapping") != "exact-utf8-responses-json-in-single-user-message.v1"
        or plan.get("max_input_tokens") != 1024
        or plan.get("max_output_tokens") != 32
        or plan.get("provider_timeout_seconds") != 60
        or plan.get("max_http_body_bytes") != 1048576
        or plan.get("mode") not in {"capture", "generate"}
    ):
        raise ValueError("frozen adapter plan changed")
    return plan


def map_request(body, plan):
    """Preserve all JSON fields and text; reject unsupported non-text inputs."""
    document = _json(body)
    if (
        not isinstance(document, dict)
        or not set(document) <= FIELDS
        or document.get("model") != plan["profile"]["model_name"]
        or document.get("store") is not False
        or document.get("stream") is not True
        or not isinstance(document.get("input"), list)
        or not document["input"]
        or not isinstance(document.get("instructions", ""), str)
    ):
        raise ValueError("bounded fresh text Responses request required")
    for item in document["input"]:
        if (
            not isinstance(item, dict)
            or item.get("type") != "message"
            or item.get("role") not in {"system", "developer", "user", "assistant"}
            or not isinstance(item.get("content"), list)
            or not item["content"]
        ):
            raise ValueError("only complete text message inputs are supported")
        for content in item["content"]:
            if (
                not isinstance(content, dict)
                or content.get("type") not in {"input_text", "output_text"}
                or not isinstance(content.get("text"), str)
            ):
                raise ValueError(
                    "non-text native input is unsupported, never discarded"
                )
    native_text = body.decode("utf-8", errors="strict")
    request = _canonical(
        {
            "model": document["model"],
            "input": native_text,
            "store": False,
            "max_output_tokens": plan["max_output_tokens"],
            "temperature": 0,
        }
    )
    mapping = {
        "schema": SCHEMA,
        "mapping": plan["mapping"],
        "native_body": _pin(body),
        "provider_request": _pin(request),
        "source_json_pointer": "",
        "destination_json_pointer": "/input",
        "source_utf8_equals_destination_utf8": native_text.encode() == body,
        "included_fields": sorted(document),
        "discarded_fields": [],
        "native_role_semantics_preserved": False,
        "input_bytes": len(body),
        "provider_request_bytes": len(request),
        "output_policy": "unmodified generated text, no tool execution",
    }
    if len(request) > 65536:
        raise ValueError(
            "mapped provider request exceeds its byte budget; no truncation"
        )
    return request, mapping


def response_events(request_id, result):
    """Use actual local output and token counts, with no answer substitution."""
    if (
        not isinstance(result.get("text"), str)
        or not isinstance(result.get("tokens"), list)
        or type(result.get("prompt_tokens")) is not int
    ):
        raise ValueError("verified local text and token accounting required")
    response_id = "mem13-" + request_id
    message = {
        "type": "message",
        "role": "assistant",
        "id": response_id + "-message",
        "content": [{"type": "output_text", "text": result["text"]}],
    }
    usage = {
        "input_tokens": result["prompt_tokens"],
        "input_tokens_details": None,
        "output_tokens": len(result["tokens"]),
        "output_tokens_details": None,
        "total_tokens": result["prompt_tokens"] + len(result["tokens"]),
    }
    events = [
        {"type": "response.created", "response": {"id": response_id}},
        {"type": "response.output_item.done", "item": message},
        {"type": "response.completed", "response": {"id": response_id, "usage": usage}},
    ]
    return b"".join(b"data: " + _canonical(event) + b"\n\n" for event in events)


def _verified_result(root, plan, request, receipt):
    directory = (
        root / "provider" / hashlib.sha256(plan["request_id"].encode()).hexdigest()
    )
    expected = {
        "schema": "hepta.mem11.local-provider.v1",
        "worker": _pin(WORKER.encode()),
        "request_id": plan["request_id"],
        "launch_sha256": _pin(_canonical(plan))["sha256"],
        "request": _pin(request),
        "profile": plan["profile"],
        "timeout_seconds": plan["provider_timeout_seconds"],
        "provider_source": plan["source_pins"][
            "ndu_real_runtime/episodic_local_provider.py"
        ],
        "dependency_sources": {
            Path(name).name: plan["source_pins"][name]
            for name in SOURCES
            if Path(name).name
            in {
                "episodic_local_worker.py",
                "episodic_provider_handoff.py",
                "hepta_ci_exec.py",
            }
        },
    }
    admission = _json(_read_regular(directory / "ADMISSION.json", 65536))
    if (
        set(admission) != set(expected)
        or any(
            receipt.get(key) != value or admission.get(key) != value
            for key, value in expected.items()
        )
        or any(receipt.get(key) != value for key, value in admission.items())
        or _read_regular(directory / "request.bin", 65536) != request
        or _json(_read_regular(directory / "RECEIPT.json", 1048576)) != receipt
    ):
        raise ValueError("local provider evidence contradicts frozen native mapping")
    log = _read_regular(directory / "combined.log", 1048576)
    model_input = verify_returned_generation(receipt, log)
    if _read_regular(directory / "model-input.json", 1048576) != model_input:
        raise ValueError("actual model input record changed")
    return receipt["result"]


class NativeAdapter(socketserver.TCPServer):
    """Loopback-only serial HTTP server with a durable one-operation claim."""

    allow_reuse_address = False

    def __init__(self, root, port=0):
        self.root = Path(root).absolute()
        self.plan = load_plan(self.root)
        self.number = 0
        super().__init__(("127.0.0.1", port), _Handler)
        self.timeout = 120
        try:
            _write(
                self.root / "SERVER.json",
                _canonical(
                    {
                        "schema": SCHEMA,
                        "address": list(self.server_address),
                        "plan": _pin(_canonical(self.plan)),
                        "started_at_unix_ns": time.time_ns(),
                    }
                ),
            )
        except BaseException:
            self.server_close()
            raise


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        server = self.server
        server.number += 1
        root = server.root / f"http-{server.number:04d}"
        root.mkdir(mode=0o700)
        raw, body, status = bytearray(), b"", "REJECTED"
        header_end, length, capture_complete = None, None, False
        observed = {"schema": SCHEMA, "started_at_unix_ns": time.time_ns()}
        code, content_type = 400, "application/json"
        response = _canonical({"error": "invalid request"})
        try:
            deadline = time.monotonic() + HTTP_RECEIVE_SECONDS

            def receive(size):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("native HTTP receive deadline")
                self.connection.settimeout(remaining)
                chunk = self.connection.recv(size)
                raw.extend(chunk)
                if not chunk:
                    raise ValueError("incomplete native HTTP request")

            # Bytewise headers prevent buffered readline from consuming a
            # partial line invisibly when the receive deadline expires.
            while raw[-4:] != b"\r\n\r\n":
                receive(1)
                if len(raw) > 65536:
                    raise ValueError("bounded CRLF HTTP headers required")
            header_end = len(raw)
            lines = bytes(raw[:-4]).split(b"\r\n")
            if any(len(value) > 8192 for value in lines):
                raise ValueError("bounded HTTP header lines required")
            if lines[0] != b"POST /v1/responses HTTP/1.1":
                raise ValueError("only the native Responses POST route is supported")
            headers = {}
            for value in lines[1:]:
                name, separator, value = value.partition(b":")
                name = name.lower()
                if not separator or name in headers:
                    raise ValueError("unique HTTP header names required")
                headers[name] = value.strip()
            encoded_length = headers.get(b"content-length", b"")
            if (
                not encoded_length.isdigit()
                or not 1 <= int(encoded_length) <= server.plan["max_http_body_bytes"]
                or b"transfer-encoding" in headers
            ):
                raise ValueError("bounded Content-Length body required")
            length = int(encoded_length)
            while len(raw) - header_end < length:
                receive(min(65536, length - (len(raw) - header_end)))
            body = bytes(raw[header_end:])
            capture_complete = True
            _write(root / "request.http.bin", bytes(raw))
            _write(root / "body.bin", body)
            if (
                headers.get(b"content-encoding", b"identity") != b"identity"
                or headers.get(b"content-type", b"").split(b";", 1)[0]
                != b"application/json"
            ):
                raise ValueError("uncompressed JSON required; original bytes retained")
            plan = load_plan(server.root)
            if plan != server.plan:
                raise ValueError("adapter plan changed after server admission")
            request, mapping = map_request(body, plan)
            _write(root / "provider-request.bin", request)
            _write(root / "MAPPING.json", _canonical(mapping))
            _write(
                server.root / "ATTEMPT.json",
                _canonical(
                    {
                        "request_id": plan["request_id"],
                        "http_directory": root.name,
                        "native_http": _pin(bytes(raw)),
                        "native_body": _pin(body),
                        "provider_request": _pin(request),
                        "mode": plan["mode"],
                    }
                ),
            )
            if plan["mode"] == "capture":
                status, code = "CAPTURED_WITHOUT_GENERATION", 409
                response = _canonical(
                    {"error": "capture-only; no model request issued"}
                )
                observed["physical_model_calls"] = 0
            else:
                status = "UNKNOWN"
                receipt = run_local_provider(
                    server.root / "provider",
                    request,
                    request_id=plan["request_id"],
                    launch_sha256=_pin(_canonical(plan))["sha256"],
                    profile=LocalProviderProfile(**plan["profile"]),
                    timeout_seconds=plan["provider_timeout_seconds"],
                )
                observed["provider_status"] = receipt.get("status")
                if receipt.get("status") != "RETURNED":
                    raise ValueError(
                        "provider did not return a verified generation; no retry"
                    )
                result = _verified_result(server.root, plan, request, receipt)
                if load_plan(server.root) != plan:
                    raise ValueError("adapter plan changed during provider execution")
                response = response_events(plan["request_id"], result)
                status, code, content_type = "RETURNED", 200, "text/event-stream"
                observed["physical_completed_model_calls_lower_bound"] = 1
        except (OSError, ValueError, KeyError, UnicodeError, RecursionError) as error:
            observed["error"] = type(error).__name__ + ": " + str(error)
            code = 409 if isinstance(error, FileExistsError) else 400
            response = _canonical({"error": observed["error"], "no_retry": True})
        finally:
            if header_end is not None:
                body = bytes(raw[header_end:])
            if not (root / "request.http.bin").exists():
                _write(root / "request.http.bin", bytes(raw))
            reason = "OK" if code == 200 else "Diagnostic stopped"
            wire = (
                f"HTTP/1.1 {code} {reason}\r\nContent-Type: {content_type}\r\n"
                f"Content-Length: {len(response)}\r\nConnection: close\r\n\r\n"
            ).encode() + response
            _write(root / "response.http.bin", wire)
            observed.update(
                status=status,
                native_http=_pin(bytes(raw)),
                native_body=_pin(body),
                response_http=_pin(wire),
                ended_at_unix_ns=time.time_ns(),
                observer_authenticated=False,
                scientific_acceptance="HOLD",
                socket_write_succeeded=False,
                capture_complete=capture_complete,
                advertised_body_bytes=length,
                observed_body_bytes=len(body),
            )
            try:
                self.wfile.write(wire)
                self.wfile.flush()
                observed["socket_write_succeeded"] = True
            except OSError:
                pass
            _write(root / "OBSERVED.json", _canonical(observed))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare", type=Path)
    action.add_argument("--serve", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--request-id")
    parser.add_argument("--native-source-sha")
    parser.add_argument("--mode", choices=("capture", "generate"))
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    if args.prepare:
        if not all((args.profile, args.request_id, args.native_source_sha, args.mode)):
            parser.error(
                "prepare requires profile, request-id, native-source-sha and mode"
            )
        plan = prepare(
            args.prepare,
            _json(_read_regular(args.profile, 65536)),
            request_id=args.request_id,
            native_source_sha=args.native_source_sha,
            mode=args.mode,
        )
        print(
            _canonical({"plan": _pin(_canonical(plan)), "mode": plan["mode"]}).decode()
        )
    else:
        with NativeAdapter(args.serve, args.port) as server:
            print(f"http://127.0.0.1:{server.server_address[1]}/v1", flush=True)
            # One HTTP attempt per server invocation. An existing SERVER or
            # ATTEMPT journal refuses relaunch; an uncertain call is not reissued.
            server.handle_request()
            _write(
                args.serve / "STOPPED.json",
                _canonical(
                    {
                        "schema": SCHEMA,
                        "http_connections_observed": server.number,
                        "ended_at_unix_ns": time.time_ns(),
                        "observer_authenticated": False,
                    }
                ),
            )


if __name__ == "__main__":
    main()
