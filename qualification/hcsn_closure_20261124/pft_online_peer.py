"""Loopback research exchange of durable PFT contributions, never authority."""

import json
import re
import socket
import socketserver
import struct
import threading
import time

from .pft_statistics import StatisticsLedger, canonical, digest, valid_digest, validate_packet


SCHEMA = "pft-peer-exchange-research-v1"
MAX_FRAME = 8 * 1024 * 1024
MAX_BATCHES = 1024
TIMEOUT = 2.0


class DeliveryUnknown(ConnectionError):
    """No matching complete response was observed; do not infer non-delivery."""


def _exact(stream, length, deadline):
    chunks = bytearray()
    while len(chunks) < length:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("peer frame deadline elapsed")
        stream.settimeout(remaining)
        part = stream.recv(length - len(chunks))
        if not part:
            raise EOFError("incomplete peer frame")
        chunks.extend(part)
    return bytes(chunks)


def _receive(stream):
    deadline = time.monotonic() + TIMEOUT
    length = struct.unpack("!I", _exact(stream, 4, deadline))[0]
    if not 0 < length <= MAX_FRAME:
        raise ValueError("peer frame exceeds the fixed bound")
    raw = _exact(stream, length, deadline)
    value = json.loads(raw)
    if canonical(value) != raw:
        raise ValueError("noncanonical peer frame")
    return value


def _send(stream, value):
    raw = canonical(value)
    if not 0 < len(raw) <= MAX_FRAME:
        raise ValueError("peer frame exceeds the fixed bound")
    stream.sendall(struct.pack("!I", len(raw)) + raw)


def _loopback(address):
    if (type(address) not in (tuple, list) or len(address) != 2
            or address[0] != "127.0.0.1" or type(address[1]) is not int
            or not 0 <= address[1] <= 65535):
        raise ValueError("research peers require an explicit IPv4 loopback address")
    return tuple(address)


def _checked_reply(reply, request):
    if (type(reply) is not dict
            or set(reply) != {"schema", "contract_sha256", "request_sha256", "ok", "result"}
            or reply["schema"] != SCHEMA
            or reply["contract_sha256"] != request["contract_sha256"]
            or reply["request_sha256"] != digest(request)
            or type(reply["ok"]) is not bool):
        raise DeliveryUnknown("peer response is not bound to this request")
    if not reply["ok"]:
        raise ValueError("peer refused request: " + str(reply["result"])[:240])
    return reply["result"]


def rpc(address, contract_sha256, operation, arguments):
    request = dict(schema=SCHEMA, contract_sha256=contract_sha256,
                   operation=operation, arguments=arguments)
    address = _loopback(address)
    if len(canonical(request)) > MAX_FRAME:
        raise ValueError("peer frame exceeds the fixed bound")
    try:
        with socket.create_connection(address, timeout=TIMEOUT) as stream:
            stream.settimeout(TIMEOUT)
            _send(stream, request)
            reply = _receive(stream)
    except (OSError, EOFError, ValueError, TypeError) as error:
        raise DeliveryUnknown("no complete peer response observed") from error
    return _checked_reply(reply, request)


def _checked_state(value, contract_hash, receipt=False):
    fields = {"head", "revision", "material"} | ({"status"} if receipt else set())
    if (type(value) is not dict or set(value) != fields
            or type(value["material"]) is not dict
            or set(value["material"]) != {"contract_sha256", "batches"}
            or value["material"]["contract_sha256"] != contract_hash
            or digest(value["material"]) != value["head"]
            or (receipt and value["status"] not in ("accepted", "idempotent"))):
        raise ValueError("invalid remote inventory or receipt")
    rows = value["material"]["batches"]
    if (type(rows) is not list or len(rows) > MAX_BATCHES
            or type(value["revision"]) is not int or value["revision"] != len(rows)
            or any(type(row) is not list or len(row) != 2 or not isinstance(row[0], str)
                   or re.fullmatch("[A-Za-z0-9_.-]{1,128}", row[0]) is None
                   or not valid_digest(row[1]) for row in rows)
            or rows != sorted(rows) or len(dict(rows)) != len(rows)):
        raise ValueError("invalid remote inventory entries")
    return dict(rows)


def _inventory(ledger):
    with ledger.connect() as db:
        db.execute("BEGIN")
        state = ledger.state(db)
    if state["revision"] > MAX_BATCHES:
        raise ValueError("research exchange batch bound exceeded")
    return state


def _packet(ledger, batch_id):
    with ledger.connect() as db:
        row = db.execute("SELECT body,digest FROM batches WHERE id=?", (batch_id,)).fetchone()
    if row is None:
        raise ValueError("local contribution disappeared")
    packet = dict(body=json.loads(row[0]), payload_sha256=row[1])
    validate_packet(packet, ledger.contract)
    return packet


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(TIMEOUT)
        try:
            request = _receive(self.request)
            if (type(request) is not dict
                    or set(request) != {"schema", "contract_sha256", "operation", "arguments"}
                    or request["schema"] != SCHEMA
                    or request["contract_sha256"] != self.server.ledger.contract_hash):
                raise ValueError("incompatible peer request")
            reply = dict(schema=SCHEMA, contract_sha256=request["contract_sha256"],
                         request_sha256=digest(request), ok=True, result=None)
            try:
                reply["result"] = self.server.dispatch(request["operation"], request["arguments"])
            except (ValueError, TypeError) as error:
                reply.update(ok=False, result=str(error)[:240])
            _send(self.request, reply)
        except (OSError, EOFError, ValueError, TypeError):
            # An invalid/partial frame never becomes a successful acknowledgment.
            return


class PeerService(socketserver.TCPServer):
    """One process-local owner; bounded serial admission and separate peer I/O."""

    allow_reuse_address = True
    request_queue_size = 8

    def __init__(self, database, contract, address=("127.0.0.1", 0)):
        address = _loopback(address)
        self.ledger = StatisticsLedger(database, contract)
        self._thread = None
        super().__init__(address, _Handler)

    def start(self):
        if self._thread is not None:
            raise ValueError("peer service already started")
        self._thread = threading.Thread(target=self.serve_forever, kwargs={"poll_interval": 0.02})
        self._thread.start()
        return self.server_address

    def close(self):
        if self._thread is not None:
            self.shutdown()
            self._thread.join()
        self.server_close()

    def dispatch(self, operation, arguments):
        if operation == "inventory" and arguments == {}:
            return _inventory(self.ledger)
        if operation == "snapshot" and arguments == {}:
            return self.ledger.snapshot()["candidate"]
        if operation != "offer" or type(arguments) is not dict or set(arguments) != {"packet", "expected_head"}:
            raise ValueError("unsupported peer operation")
        packet = arguments["packet"]
        validate_packet(packet, self.ledger.contract)
        state = _inventory(self.ledger)
        known = dict(state["material"]["batches"])
        if state["revision"] >= MAX_BATCHES and packet["body"]["batch_id"] not in known:
            raise ValueError("research exchange batch bound exceeded")
        return self.ledger.append(packet, arguments["expected_head"])

    def sync(self, address):
        """Push missing contributions; uncertainty remains retryable by batch ID."""
        remote = rpc(address, self.ledger.contract_hash, "inventory", {})
        known = _checked_state(remote, self.ledger.contract_hash)
        sent = 0
        for batch_id, packet_hash in _inventory(self.ledger)["material"]["batches"]:
            if batch_id in known:
                if known[batch_id] != packet_hash:
                    raise ValueError("peers have conflicting contribution identities")
                continue
            receipt = rpc(address, self.ledger.contract_hash, "offer",
                          dict(packet=_packet(self.ledger, batch_id), expected_head=remote["head"]))
            observed = _checked_state(receipt, self.ledger.contract_hash, receipt=True)
            if observed.get(batch_id) != packet_hash:
                raise DeliveryUnknown("response does not retain the offered contribution")
            remote["head"] = receipt["head"]
            sent += 1
        return sent
