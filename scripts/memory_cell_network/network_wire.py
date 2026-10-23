"""Bounded, authenticated loopback HTTP RPC for research memory workers.

HMAC authenticates a trusted local deployment; it does not encrypt traffic.
Endpoints deliberately accept only numeric loopback addresses. No public listener.
"""

import hashlib
import hmac
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import re
import secrets
from urllib.parse import urlsplit

from tensor_contract import strict_json

MAX_WIRE_BYTES = 96 * 1024 * 1024


def encode(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def fields(value, required):
    if type(value) is not dict or set(value) != set(required):
        raise ValueError("closed RPC schema required")


def endpoint(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.port is None
        or not 0 < parsed.port < 65536
    ):
        raise ValueError("explicit loopback HTTP endpoint required")
    return parsed.hostname, parsed.port


def authenticate(key, direction, nonce, body):
    if type(key) is not bytes or len(key) != 32:
        raise ValueError("32-byte deployment key required")
    return hmac.new(
        key, direction.encode() + nonce.encode() + body, hashlib.sha256
    ).hexdigest()


class RemoteError(ValueError):
    pass


def call(address, key, request, *, timeout=120):
    host, port = endpoint(address)
    body, nonce = encode(request), secrets.token_hex(16)
    if not 0 < len(body) <= MAX_WIRE_BYTES:
        raise ValueError("RPC request byte bound")
    connection = HTTPConnection(host, port, timeout=timeout)
    try:
        connection.request(
            "POST",
            "/rpc",
            body=body,
            headers={
                "Content-Type": "application/json",
                "X-Memory-Nonce": nonce,
                "X-Memory-MAC": authenticate(key, "request", nonce, body),
            },
        )
        response = connection.getresponse()
        payload = response.read(MAX_WIRE_BYTES + 1)
        if not 0 < len(payload) <= MAX_WIRE_BYTES or not hmac.compare_digest(
            response.getheader("X-Memory-MAC", ""),
            authenticate(key, "response", nonce, payload),
        ):
            raise ValueError("RPC response bound or authentication failed")
        result = strict_json(payload)
        if response.status != 200:
            fields(result, ("ok", "error"))
            raise RemoteError(str(result["error"]))
        fields(result, ("ok", "value"))
        if result["ok"] is not True:
            raise ValueError("invalid RPC success envelope")
        return result["value"]
    finally:
        connection.close()


def server(application, key, *, port=0):
    authenticate(key, "request", "", b"")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            self.connection.settimeout(10)
            nonce = self.headers.get("X-Memory-Nonce", "")
            try:
                if (
                    self.path != "/rpc"
                    or re.fullmatch(r"[0-9a-f]{32}", nonce) is None
                    or self.headers.get("Transfer-Encoding") is not None
                    or self.headers.get("Content-Type") != "application/json"
                    or any(
                        len(self.headers.get_all(k, [])) != 1
                        for k in ("Content-Length", "X-Memory-Nonce", "X-Memory-MAC")
                    )
                ):
                    raise ValueError("invalid RPC HTTP envelope")
                size = int(self.headers["Content-Length"])
                if not 0 < size <= MAX_WIRE_BYTES:
                    raise ValueError("RPC request byte bound")
                body = self.rfile.read(size)
                if len(body) != size or not hmac.compare_digest(
                    self.headers["X-Memory-MAC"],
                    authenticate(key, "request", nonce, body),
                ):
                    raise ValueError("RPC request authentication failed")
                result = application.dispatch(strict_json(body))
                payload, status = encode({"ok": True, "value": result}), 200
                if len(payload) > MAX_WIRE_BYTES:
                    raise ValueError("RPC response byte bound")
            except (ValueError, TypeError, KeyError, OSError) as error:
                payload, status = encode({"ok": False, "error": str(error)[:512]}), 400
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header(
                "X-Memory-MAC", authenticate(key, "response", nonce, payload)
            )
            self.end_headers()
            self.wfile.write(payload)

    # Serial execution prevents concurrent model mutation within one worker.
    return HTTPServer(("127.0.0.1", port), Handler)
