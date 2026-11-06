"""Provider-neutral request ledger. Responses and credentials never enter the ledger."""
import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import uuid


from .contracts import canonical, digest, number, stamp, usage
from .ledger import append_event, reconcile


def load(path):
    value = json.loads(open(path, encoding="utf-8").read())
    canonical(value)
    return value


def invoke(argv, payload, timeout, limit=1048576, deadline_monotonic=None):
    """POSIX group supervision; no detached-worker or remote-cancellation guarantee."""
    start = time.perf_counter()
    event = {"started_at": stamp(), "started_monotonic": start, "timeout_seconds": timeout,
             "status": "failure", "error_type": None, "dispatched": False, "response_received": False, "dispatch_monotonic": None}
    process = None
    response, valid_response = None, False
    try:
        if os.name != "posix" or not number(timeout) or timeout <= 0:
            raise ValueError("POSIX and a positive timeout are required")
        deadline = min(start+timeout, deadline_monotonic if deadline_monotonic is not None else start+timeout)
        encoded = canonical(payload).encode()
        if time.perf_counter() >= deadline:
            raise TimeoutError("Admission deadline expired")
        event["dispatch_monotonic"] = time.perf_counter()
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
        event["dispatched"] = True
        out, _ = process.communicate(encoded, timeout=max(0.000001, deadline-time.perf_counter()))
        event["returncode"] = process.returncode
        event["response_received"] = bool(out)
        event["response_sha256"] = hashlib.sha256(out).hexdigest()
        if process.returncode or len(out) > limit:
            raise ValueError("Worker failure or output limit")
        response = json.loads(out)
        canonical(response)
        if not isinstance(response, dict) or "_transport_error" in response:
            raise ValueError("Invalid provider envelope")
        valid_response = True
        event["status"] = "ok"
    except subprocess.TimeoutExpired as exc:
        event.update(status="timeout", error_type="TimeoutExpired", response_received=bool(exc.output))
    except TimeoutError:
        event.update(status="timeout", error_type="AdmissionDeadlineExceeded")
    except (OSError, ValueError, UnicodeError, RecursionError, TypeError) as exc:
        event["error_type"] = type(exc).__name__
    finally:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            process.stdin.close()
            process.stdout.close()
        if not event["dispatched"]:
            event["dispatch_monotonic"] = None
        finish = time.perf_counter()
        event.update(finished_at=stamp(), finished_monotonic=finish, wall_seconds=finish-start)
        if event["status"] == "ok" and finish > deadline:
            event.update(status="timeout", error_type="DeadlineExceeded")
    return event, response if valid_response else None


def _field(data, path):
    try:
        for key in path:
            data = data[key]
        return data
    except (KeyError, IndexError, TypeError):
        return None


def http_worker(config, payload):
    """Native JSON or OpenAI-compatible chat wire format; no provider SDK required."""
    endpoint = os.environ[config["url_env"]]
    parsed = urllib.parse.urlsplit(endpoint)
    local_http = parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
    if parsed.scheme != "https" and not local_http:
        raise ValueError("HTTPS required except loopback fixtures")
    headers = {"Content-Type": "application/json",
               config.get("client_request_header", "X-Client-Request-Id"): config["client_request_id"]}
    if config.get("key_env"):
        headers[config.get("auth_header", "Authorization")] = (
            config.get("auth_prefix", "Bearer ") + os.environ[config["key_env"]])
    identity = config["identity"]
    decoding = config["decoding"]
    if config.get("wire_format", "native") == "openai_chat":
        if {"model", "messages"}.intersection(decoding):
            raise ValueError("Decoding cannot override model or messages")
        body = {"model": identity["model_id"], "messages": [
            {"role": "user", "content": canonical(payload)}], **decoding}
    else:
        body = {"model_id": identity["model_id"], "revision": identity["revision"],
                "input": payload, "decoding": decoding}
    req = urllib.request.Request(endpoint, canonical(body).encode(), headers, method="POST")
    # A redirect must not forward credentials to an unregistered host.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    with urllib.request.build_opener(NoRedirect).open(req, timeout=config["timeout"]) as reply:
        raw = reply.read(config.get("max_output_bytes", 1048576)+1)
    if len(raw) > config.get("max_output_bytes", 1048576):
        raise ValueError("Provider output limit")
    data = json.loads(raw)
    canonical(data)
    mapping = config["response_map"]
    result = {key: _field(data, path) for key, path in mapping.items()}
    result["usage"] = {k: result.pop(k, None) for k in
                       ("input_tokens", "output_tokens", "cached_input_tokens")}
    return result


def transport_hash(config):
    """Bind the endpoint value without storing its URL or credentials."""
    public = {k: v for k, v in config.items() if k not in ("timeout",)}
    if public.get("kind") == "http":
        public = {**public, "endpoint_sha256": hashlib.sha256(
            os.environ.get(public["url_env"], "UNCONFIGURED").encode()).hexdigest()}
    return digest(public)


def call(config, payload, context, ledger, timeout, kind="model", absolute_deadline=None):
    call_start, call_stamp = time.perf_counter(), stamp()
    if not number(timeout) or timeout <= 0 or (absolute_deadline is not None and not number(absolute_deadline)):
        raise ValueError("Invalid request deadline")
    deadline = min(call_start+timeout, absolute_deadline if absolute_deadline is not None else call_start+timeout)
    allowed = {"task_id", "arm", "repeat", "episode_id", "protocol_sha256"}
    if (set(context)-allowed or not {"task_id", "arm", "repeat", "protocol_sha256"} <= set(context)
            or kind not in ("model", "tool", "verifier")):
        raise ValueError("Invalid request context")
    for key, value in context.items():
        if key == "repeat":
            if type(value) is not int or value < 0:
                raise ValueError("Invalid repeat")
        elif not isinstance(value, str) or len(value) > 128 or not value.isprintable():
            raise ValueError("Context identifiers must be printable and bounded")
    identity_hash, config_hash = digest(config["identity"]), transport_hash(config)
    try:
        payload_hash = digest(payload)
    except (ValueError, TypeError, RecursionError):
        payload_hash = None
    request_id = uuid.uuid4().hex
    request = {"config": {**config, "timeout": timeout, "client_request_id": request_id}, "payload": payload}
    argv = ([sys.executable, "-m", __package__+".transport", "--http-worker"]
            if config["kind"] == "http" else config["argv"])
    intent = {"schema": "ndu.request.v2", "phase": "intent", "status": "pending",
              "request_id": request_id, "kind": kind, **context, "request_sha256": payload_hash,
              "transport_sha256": config_hash, "expected_identity_sha256": identity_hash,
              "identity_kind": config["identity"]["kind"], "timeout_seconds": timeout, "deadline_monotonic": deadline,
              "prepared_at": call_stamp, "prepared_monotonic": call_start}
    # No worker or remote request starts unless this intent is durable.
    append_event(ledger, intent)
    intent_finished = time.perf_counter()
    if intent_finished >= deadline:
        event, response = {"status": "timeout", "error_type": "IntentBudgetExhausted", "dispatched": False,
                           "response_received": False, "dispatch_monotonic": None,
                           "finished_at": stamp(), "finished_monotonic": intent_finished}, None
    else:
        event, response = invoke(argv, request if config["kind"] == "http" else payload, deadline-intent_finished,
                                 config.get("max_output_bytes", 1048576), deadline)
    event.update(started_at=call_stamp, started_monotonic=call_start, intent_finished_monotonic=intent_finished,
                 wall_seconds=event["finished_monotonic"]-call_start)
    event.update({k: v for k, v in intent.items() if k not in ("status", "prepared_at", "prepared_monotonic")})
    event.update(phase="terminal", intent_sha256=digest(intent), observed_identity_sha256=None,
                 identity_status="unobserved" if kind == "model" else "not_applicable",
                 usage=None, usage_status="unknown" if kind == "model" else "not_applicable",
                 reported_amount=None, reported_currency=None, actual_amount=None,
                 reconciliation_status="pending", provider_request_sha256=None)
    text = None
    if response is not None:
        text = response.get("text") if kind == "model" else response
        if kind == "model":
            observed = {k: response.get(k) for k in ("model_id", "revision")}
            expected = {k: config["identity"][k] for k in ("model_id", "revision")}
            event["observed_identity_sha256"] = digest(observed)
            event["identity_status"] = "match" if observed == expected else "mismatch"
            event["usage"] = usage(response.get("usage"))
            event["usage_status"] = "reported" if event["usage"] is not None else "unknown"
            if not isinstance(text, str):
                event["status"], text = "invalid_response", None
            if observed != expected:
                event["status"], text = "identity_mismatch", None
        if kind == "verifier":
            if set(response) != {"quality"} or not number(response.get("quality")) or response["quality"] > 1:
                event["status"], text = "invalid_response", None
            else:
                event["verified_quality"] = response["quality"]
        provider_id = response.get("provider_request_id")
        if isinstance(provider_id, str) and provider_id:
            event["provider_request_sha256"] = hashlib.sha256(provider_id.encode()).hexdigest()
        if number(response.get("amount")) and isinstance(response.get("currency"), str):
            event.update(reported_amount=response["amount"], reported_currency=response["currency"])
    append_event(ledger, event)
    return event, text if event["status"] == "ok" else None


def host_envelope(context, ledger, started_at, started_monotonic):
    finish = time.perf_counter()
    event = {"schema": "ndu.request.v2", "phase": "meter", "request_id": uuid.uuid4().hex, "kind": "host_envelope",
             **context, "started_at": started_at, "finished_at": stamp(),
             "started_monotonic": started_monotonic, "finished_monotonic": finish,
             "wall_seconds": finish-started_monotonic, "status": "metered",
             "usage_status": "not_applicable", "usage": None, "actual_amount": None,
             "reconciliation_status": "pending", "provider_request_sha256": None,
             "scope": "host resource allocation, distinct from provider/tool fees and delay disutility"}
    append_event(ledger, event)
    return event


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--http-worker", action="store_true")
    parser.parse_args()
    try:
        request = json.load(sys.stdin)
        print(canonical(http_worker(request["config"], request["payload"])))
    except Exception as exc:
        print(canonical({"_transport_error": type(exc).__name__}))
