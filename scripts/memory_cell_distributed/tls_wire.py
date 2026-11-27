"""Mutually authenticated HTTPS with explicit peer, operation and scope grants."""

from dataclasses import dataclass
import hashlib
from http.client import HTTPSConnection, HTTPException
from http.server import BaseHTTPRequestHandler, HTTPServer
import ssl
from urllib.parse import urlsplit

from authority_contract import decode, encode, fields, hex_value, name

MAX_WIRE_BYTES = 96 * 1024 * 1024


class RemoteError(ValueError):
    pass


def endpoint(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.port is None
        or not 0 < parsed.port < 65536
    ):
        raise ValueError("explicit HTTPS endpoint without credentials or path required")
    return parsed.hostname, parsed.port


@dataclass(frozen=True)
class Credentials:
    ca_file: str
    certificate_file: str
    key_file: str

    def client_context(self):
        context = ssl.create_default_context(
            ssl.Purpose.SERVER_AUTH, cafile=self.ca_file
        )
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.load_cert_chain(self.certificate_file, self.key_file)
        return context

    def server_context(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_verify_locations(cafile=self.ca_file)
        context.load_cert_chain(self.certificate_file, self.key_file)
        return context


@dataclass(frozen=True)
class Grant:
    certificate_sha256: str
    operations: frozenset
    scopes: frozenset
    evidence_roots: frozenset = frozenset()

    def __post_init__(self):
        object.__setattr__(self, "operations", frozenset(self.operations))
        object.__setattr__(self, "scopes", frozenset(self.scopes))
        object.__setattr__(self, "evidence_roots", frozenset(self.evidence_roots))
        if (
            not hex_value(self.certificate_sha256)
            or not self.operations
            or any(not name(v) for v in self.operations | self.scopes)
            or any(not hex_value(v) for v in self.evidence_roots)
        ):
            raise ValueError("explicit certificate operation/scope grant required")


def request_scope(request):
    if type(request) is not dict:
        raise ValueError("RPC object required")
    operation = request.get("op")
    if operation in (
        "read",
        "snapshot",
        "export",
        "history",
        "pending",
        "evidence",
        "source_frontier",
    ):
        return request["scope"]
    if operation == "prepare":
        return request["proposal"]["state"]["scope"]
    if operation == "commit":
        return request["certificate"]["proposal"]["state"]["scope"]
    if operation == "publish":
        return request["placement"]["scope"]
    if operation == "frontier":
        return request["frontier"]["scope"]
    if operation == "stage":
        return request["package"]["scope"]
    if operation == "status":
        return None
    raise ValueError("operation is not admitted by this transport")


def call(address, credentials, request, *, timeout=120):
    host, port = endpoint(address)
    body = encode(request)
    if not 0 < len(body) <= MAX_WIRE_BYTES:
        raise ValueError("RPC request byte bound")
    connection = HTTPSConnection(
        host, port, timeout=timeout, context=credentials.client_context()
    )
    try:
        connection.request(
            "POST", "/rpc", body=body, headers={"Content-Type": "application/json"}
        )
        response = connection.getresponse()
        raw = response.read(MAX_WIRE_BYTES + 1)
        if not 0 < len(raw) <= MAX_WIRE_BYTES:
            raise ValueError("RPC response byte bound")
        result = decode(raw)
        if response.status != 200:
            fields(result, ("ok", "error"))
            raise RemoteError(str(result["error"]))
        fields(result, ("ok", "value"))
        if result["ok"] is not True:
            raise ValueError("invalid RPC success envelope")
        return result["value"]
    except (OSError, HTTPException) as error:
        raise RemoteError("HTTPS peer unavailable or certificate rejected") from error
    finally:
        connection.close()


def server(application, credentials, grants, *, host, port=0):
    if (
        type(host) is not str
        or not host
        or type(port) is not int
        or not 0 <= port < 65536
    ):
        raise ValueError("explicit HTTPS bind address required")
    by_peer = {grant.certificate_sha256: grant for grant in grants}
    if len(by_peer) != len(grants) or not by_peer:
        raise ValueError("unique configured peer grants required")
    context = credentials.server_context()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            self.close_connection = True
            try:
                peer = hashlib.sha256(
                    self.connection.getpeercert(binary_form=True)
                ).hexdigest()
                grant = by_peer.get(peer)
                if grant is None:
                    raise ValueError("peer certificate has no grant")
                if (
                    self.path != "/rpc"
                    or self.headers.get("Transfer-Encoding") is not None
                    or self.headers.get("Content-Type") != "application/json"
                    or any(
                        len(self.headers.get_all(key, [])) != 1
                        for key in ("Content-Length", "Content-Type")
                    )
                ):
                    raise ValueError("invalid HTTPS RPC envelope")
                size = int(self.headers["Content-Length"])
                if not 0 < size <= MAX_WIRE_BYTES:
                    raise ValueError("RPC request byte bound")
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError("truncated RPC body")
                request = decode(raw)
                scope = request_scope(request)
                if request.get("op") not in grant.operations or (
                    scope is not None and scope not in grant.scopes
                ):
                    raise ValueError("peer operation or scope is not authorized")
                if (
                    request.get("op") == "evidence"
                    and request.get("source_root") not in grant.evidence_roots
                ):
                    raise ValueError("peer has no grant for this source root")
                payload, status = (
                    encode(dict(ok=True, value=application.dispatch(request))),
                    200,
                )
                if len(payload) > MAX_WIRE_BYTES:
                    raise ValueError("RPC response byte bound")
            except (ValueError, TypeError, KeyError, OSError) as error:
                payload, status = encode(dict(ok=False, error=str(error)[:512])), 400
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    class SecureServer(HTTPServer):
        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(10)
            try:
                return context.wrap_socket(connection, server_side=True), address
            except BaseException:
                connection.close()
                raise

    return SecureServer((host, port), Handler)
