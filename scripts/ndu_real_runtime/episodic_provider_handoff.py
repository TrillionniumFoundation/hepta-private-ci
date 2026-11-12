"""One-shot Responses transport for a frozen isolated actor output.

This retains local transport facts, not authenticated model/source observations.
Even a complete HTTP 200 does not establish model execution, remote cache state
or memory benefit. The independent provider verifier remains required. The
    journal root is trusted same-owner storage; it must survive controller recovery.
"""

from dataclasses import asdict, dataclass
import hashlib
import http.client
import ipaddress
import json
import math
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request


MAX_REQUEST_BYTES = 1048576


@dataclass(frozen=True)
class HandoffProfile:
    """Frozen route and expected loaded actor/launcher; no remote trust claim."""

    endpoint: str
    model: str
    launcher_sha256: str
    actor_sha256: str
    timeout_seconds: float = 10
    max_response_bytes: int = 1048576


def _pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject(value):
        raise ValueError("nonfinite JSON constant: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject)


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _write(path, raw):
    # Admission must reach disk before opening a connection. A crash leaves a
    # reserved identity, never an automatic fresh attempt.
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    _sync_directory(path.parent)


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def handoff(root, launch_dir, *, request_id, case_id, profile):
    """Send exact actor bytes at most once within this durable journal root.

    Exact re-entry returns retained evidence. Conflicting identities are rejected;
    interrupted admissions and ambiguous transports return UNKNOWN without a
    retry. Use one root for all requests of this observer. There is no network
    fallback, cookie jar, conversation reuse, redirect following or model call
    inference. Launch custody and namespace authenticity are upstream duties;
    these checks bind the supplied launch receipt to its raw framed stdout.
    Environment proxy/CA settings are honored and proxy config is
    digest-bound in admission. The timeout applies to socket operations.
    """
    for value in (request_id, case_id):
        if (
            not isinstance(value, str)
            or not 1 <= len(value) <= 128
            or any(ord(char) < 33 or ord(char) > 126 for char in value)
        ):
            raise ValueError("bounded printable request/case identity required")
    if not isinstance(profile, HandoffProfile):
        raise ValueError("frozen handoff profile required")
    if not isinstance(profile.endpoint, str):
        raise ValueError("endpoint URL required")
    route = urllib.parse.urlsplit(profile.endpoint)
    loopback = False
    try:
        loopback = ipaddress.ip_address(route.hostname or "").is_loopback
    except ValueError:
        pass
    if (
        not route.hostname
        or route.username is not None
        or route.password is not None
        or route.query
        or route.fragment
        or (route.scheme != "https" and not (route.scheme == "http" and loopback))
    ):
        raise ValueError("HTTPS or literal loopback HTTP endpoint required")
    if not isinstance(profile.model, str) or not 1 <= len(profile.model) <= 256:
        raise ValueError("bounded model identity required")
    for value in (profile.launcher_sha256, profile.actor_sha256):
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
        ):
            raise ValueError("expected source SHA-256 required")
    if (
        type(profile.timeout_seconds) not in (int, float)
        or not math.isfinite(profile.timeout_seconds)
        or not 0 < profile.timeout_seconds <= 60
        or type(profile.max_response_bytes) is not int
        or not 1 <= profile.max_response_bytes <= 1048576
    ):
        raise ValueError("bounded timeout and response size required")
    launch_dir = Path(launch_dir)
    launch_raw = (launch_dir / "RECEIPT.json").read_bytes()
    launch = _json(launch_raw)
    request_raw = (launch_dir / "actor-output.bin").read_bytes()
    stdout = (launch_dir / "stdout.bin").read_bytes()
    first, separator, actor_output = stdout.partition(b"\n")
    if (
        launch.get("schema") != "hepta.mem9.isolated-launch.v1"
        or launch.get("status") != "EXECUTED"
        or type(launch.get("returncode")) is not int
        or launch["returncode"] != 0
        or launch.get("source_unchanged") is not True
        or launch.get("capture_truncated") is not False
        or launch.get("mode") not in {"on", "off"}
        or not isinstance(launch.get("session_id"), str)
        or not launch["session_id"]
        or launch.get("launcher_sha256") != profile.launcher_sha256
        or launch.get("actor_sha256") != profile.actor_sha256
        or launch.get("actor_output") != _pin(request_raw)
        or launch.get("stdout") != _pin(stdout)
        or not separator
        or _json(first) != launch.get("bootstrap")
        or actor_output != request_raw
        or len(request_raw) > MAX_REQUEST_BYTES
    ):
        raise ValueError("unsettled or changed isolated launch")
    request = _json(request_raw)
    if (
        not isinstance(request, dict)
        or not {"model", "input", "store"} <= set(request)
        or set(request)
        - {"model", "input", "store", "max_output_tokens", "temperature"}
        or request["model"] != profile.model
        or not isinstance(request["input"], str)
        or request["store"] is not False
    ):
        raise ValueError("single text Responses request with store=false required")
    if "max_output_tokens" in request and (
        type(request["max_output_tokens"]) is not int
        or not 1 <= request["max_output_tokens"] <= 65536
    ):
        raise ValueError("invalid output token budget")
    if "temperature" in request and (
        type(request["temperature"]) not in (int, float)
        or not math.isfinite(request["temperature"])
        or not 0 <= request["temperature"] <= 2
    ):
        raise ValueError("invalid decoding temperature")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Encoding": "identity",
        "Connection": "close",
        "X-Hepta-Request-Id": request_id,
    }
    proxies = urllib.request.getproxies()
    admission = {
        "schema": "hepta.mem10.provider-handoff.v1",
        "request_id": request_id,
        "case_id": case_id,
        "session_id": launch["session_id"],
        "mode": launch["mode"],
        "launch": _pin(launch_raw),
        "request": _pin(request_raw),
        "profile": asdict(profile),
        "headers": headers,
        "proxy_configuration_sha256": _pin(_canonical(proxies))["sha256"],
    }
    root = Path(root).absolute()
    # The parent is caller-provisioned durable storage. Persist this new root's
    # entry too; syncing only its children does not persist the reservation path.
    root.mkdir(exist_ok=True, mode=0o700)
    _sync_directory(root.parent)
    output = root / hashlib.sha256(request_id.encode()).hexdigest()
    receipt = {
        **admission,
        "status": "UNKNOWN",
        "transport_dispatches": None,
        "response": None,
        "http_status": None,
        "model_calls_observed": None,
        "server_state_verified": False,
        "observer_authenticated": False,
        "scientific_acceptance": "HOLD",
        "started_at_unix_ns": time.time_ns(),
    }
    try:
        output.mkdir(mode=0o700)
    except FileExistsError:
        saved = output / "ADMISSION.json"
        if not saved.exists():
            return {**receipt, "reason": "INTERRUPTED_ADMISSION"}
        if saved.read_bytes() != _canonical(admission):
            raise ValueError("request identity conflicts with durable admission")
        terminal = output / "RECEIPT.json"
        if not terminal.exists():
            return {**receipt, "reason": "UNSETTLED_OR_IN_FLIGHT"}
        retained = _json(terminal.read_bytes())
        # Never regenerate or re-dispatch if retained evidence was lost/changed.
        if any(retained.get(key) != value for key, value in admission.items()):
            raise ValueError("retained receipt does not match admission")
        if retained.get("status") not in {"RECEIVED", "UNKNOWN"}:
            raise ValueError("invalid retained terminal")
        if retained["status"] == "RECEIVED" and (
            not isinstance(retained.get("response"), dict)
            or not isinstance(retained.get("response_headers"), dict)
            or type(retained.get("http_status")) is not int
            or not 100 <= retained["http_status"] <= 599
            or retained.get("transport_dispatches") != 1
        ):
            raise ValueError("incomplete received terminal")
        for name, pin in (
            ("request.bin", admission["request"]),
            ("launch.json", admission["launch"]),
            ("response.bin", retained["response"]),
            ("response-headers.json", retained.get("response_headers")),
        ):
            if pin is not None and (
                not (output / name).is_file()
                or _pin((output / name).read_bytes()) != pin
            ):
                return {**receipt, "reason": "RETAINED_BYTES_CHANGED"}
        return retained
    _sync_directory(root)
    _write(output / "ADMISSION.json", _canonical(admission))
    _write(output / "launch.json", launch_raw)
    _write(output / "request.bin", request_raw)
    started = time.monotonic_ns()
    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(proxies), _NoRedirect()
        )
        # This explicit header prevents urllib from adding its default User-Agent.
        opener.addheaders = []
        outgoing = urllib.request.Request(
            profile.endpoint, data=request_raw, headers=headers, method="POST"
        )
        # Attempt count, not evidence that the peer received a physical request.
        receipt["transport_dispatches"] = 1
        try:
            response = opener.open(outgoing, timeout=profile.timeout_seconds)
        except urllib.error.HTTPError as error:
            response = error  # Preserve complete non-2xx/redirect responses too.
        with response:
            receipt["http_status"] = response.code
            raw_headers = _canonical(list(response.headers.raw_items()))
            if len(raw_headers) > 262144:
                raise ValueError("response headers exceed capture bound")
            _write(output / "response-headers.json", raw_headers)
            receipt["response_headers"] = _pin(raw_headers)
            body = bytearray()
            incomplete = False
            while len(body) <= profile.max_response_bytes:
                if (time.monotonic_ns() - started) / 1e9 > profile.timeout_seconds:
                    incomplete = True
                    receipt["read_error"] = "DEADLINE"
                    break
                try:
                    chunk = response.read1(
                        min(65536, profile.max_response_bytes + 1 - len(body))
                    )
                except http.client.IncompleteRead as error:
                    body.extend(error.partial)
                    incomplete = True
                    break
                except (OSError, http.client.HTTPException) as error:
                    incomplete = True
                    receipt["read_error"] = type(error).__name__
                    break
                if not chunk:
                    break
                body.extend(chunk)
            body = bytes(body)
            _write(output / "response.bin", body)
            receipt["response"] = _pin(body)
            length = response.headers.get_all("Content-Length")
            transfer = response.headers.get_all("Transfer-Encoding")
            if (
                incomplete
                or len(body) > profile.max_response_bytes
                or (
                    length
                    and (
                        len(length) != 1
                        or not length[0].isdigit()
                        or int(length[0]) != len(body)
                    )
                )
                or (length and transfer)
                or (transfer and transfer != ["chunked"])
            ):
                raise ValueError("response truncated, oversized or ambiguously framed")
            receipt["status"] = "RECEIVED"
    except (
        OSError,
        ValueError,
        urllib.error.URLError,
        http.client.HTTPException,
    ) as error:
        receipt["reason"] = type(error).__name__
        receipt["status"] = "UNKNOWN"
    finally:
        receipt["elapsed_monotonic_ns"] = time.monotonic_ns() - started
        receipt["ended_at_unix_ns"] = time.time_ns()
        _write(output / "RECEIPT.json", _canonical(receipt))
    return receipt
