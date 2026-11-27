"""Durable application-payload accounting; not TCP/TLS packet or energy metering."""

import os
from pathlib import Path
import threading
import time

from authority_contract import decode, encode
import tls_wire


class MeteredRPC:
    endpoint = staticmethod(tls_wire.endpoint)

    def __init__(self, journal, *, rpc=tls_wire.call, maximum_calls=10000):
        self.journal, self.rpc, self.maximum_calls = Path(journal), rpc, maximum_calls
        if self.journal.is_symlink() or not 1 <= maximum_calls <= 100000:
            raise ValueError("bounded real RPC cost journal required")
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        prior = (
            [decode(line) for line in self.journal.read_bytes().splitlines()]
            if self.journal.exists()
            else []
        )
        self.count = sum(row["phase"] == "started" for row in prior)

    def append(self, record):
        with self.journal.open("ab") as stream:
            stream.write(encode(record) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        descriptor = os.open(self.journal.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def __call__(self, address, credentials, request, *, timeout=120):
        return self.call(address, credentials, request, timeout=timeout)

    def call(self, address, credentials, request, *, timeout=120):
        with self.lock:
            if self.count >= self.maximum_calls:
                raise ValueError("RPC count budget exhausted")
            self.count += 1
            call_id = self.count
            self.append(
                dict(
                    phase="started",
                    call_id=call_id,
                    operation=request.get("op"),
                    request_payload_bytes=len(encode(request)),
                )
            )
        started = time.perf_counter()
        receipt = dict(
            phase="finished",
            call_id=call_id,
            response_payload_bytes=None,
            response_partial_bytes_unknown=True,
            tls_packet_bytes_measured=False,
            ok=False,
        )
        try:
            result = self.rpc(address, credentials, request, timeout=timeout)
            receipt.update(
                ok=True,
                response_payload_bytes=len(encode(dict(ok=True, value=result))),
                response_partial_bytes_unknown=False,
            )
            return result
        finally:
            receipt["wall_seconds"] = time.perf_counter() - started
            with self.lock:
                self.append(receipt)
