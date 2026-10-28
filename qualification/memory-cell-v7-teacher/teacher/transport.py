"""One explicit Responses POST; bounded SSE evidence, no redirects or retries."""

import hashlib
import http.client
import json
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit


LABELS = ("at", "previous", "change", "mean3", "range3", "peak3", "__reject__")
MAX_RESPONSE_BYTES = 131072


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def exact_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def decode_json(raw):
    return json.loads(raw, object_pairs_hook=exact_object)


class SseEvidence:
    def __init__(self):
        self.pending = bytearray()
        self.total = 0
        self.provider_id = None
        self.items = []
        self.completion = None

    def feed(self, data):
        self.total += len(data)
        if self.total > MAX_RESPONSE_BYTES:
            raise ValueError("SSE evidence byte limit exceeded")
        self.pending.extend(data)
        while True:
            candidates = [(self.pending.find(mark), len(mark)) for mark in (b"\n\n", b"\r\n\r\n")]
            found = [(at, width) for at, width in candidates if at >= 0]
            if not found:
                return
            at, width = min(found)
            frame = bytes(self.pending[:at]).decode("utf-8")
            del self.pending[:at + width]
            parts = [line[5:].removeprefix(" ") for line in frame.splitlines() if line.startswith("data:")]
            if not parts:
                continue
            raw = "\n".join(parts)
            if raw == "[DONE]":
                continue
            event = decode_json(raw)
            kind = event.get("type")
            if self.completion is not None:
                raise ValueError("event after terminal response")
            if kind == "response.created":
                identity = event.get("response", {}).get("id")
                if not isinstance(identity, str) or not 1 <= len(identity) <= 512:
                    raise ValueError("missing original provider identity")
                if self.provider_id is not None and self.provider_id != identity:
                    raise ValueError("provider identity changed")
                self.provider_id = identity
            elif kind == "response.output_item.done":
                item = event.get("item")
                if not isinstance(item, dict):
                    raise ValueError("invalid completed output item")
                self.items.append(item)
            elif kind == "response.completed":
                final = event.get("response", {})
                if (not self.provider_id or final.get("id") != self.provider_id
                        or final.get("status") != "completed"):
                    raise ValueError("terminal response is not the original completed response")
                self.completion = final
            elif kind in ("error", "response.failed", "response.incomplete"):
                raise ValueError("provider ended without completed output: " + str(kind))

    def result(self):
        if self.completion is None:
            raise ValueError("no validated terminal model response")
        items = self.completion.get("output", self.items)
        if not isinstance(items, list):
            raise ValueError("terminal output is not an item list")
        texts = []
        for item in items:
            if item.get("type") == "reasoning":
                continue
            if item.get("type") != "message" or item.get("role") != "assistant":
                raise ValueError("unexpected model output kind")
            for content in item.get("content", []):
                if content.get("type") != "output_text" or not isinstance(content.get("text"), str):
                    raise ValueError("unexpected message output kind")
                texts.append(content["text"])
        answer = "".join(texts)
        if len(answer.encode()) > 256:
            raise ValueError("router output byte limit exceeded")
        value = decode_json(answer)
        if not isinstance(value, dict) or set(value) != {"intent"} or value["intent"] not in LABELS:
            raise ValueError("router output does not match the exact intent schema")
        return {"status": "completed", "provider_response_id": self.provider_id,
                "raw_label": value["intent"], "accepted": value["intent"] != "__reject__",
                "accepted_intent": value["intent"] if value["intent"] != "__reject__" else None,
                "answer": answer, "usage": self.completion.get("usage"),
                "provider_model": self.completion.get("model")}


def post_once(endpoint, body, operation_id, evidence, timeout_seconds):
    """The caller durably records admission before entering this function."""
    started = time.monotonic()
    deadline = started + timeout_seconds
    url = urlsplit(endpoint.rstrip("/") + "/responses")
    if (url.scheme not in ("http", "https") or not url.hostname or url.username
            or url.password or url.query or url.fragment):
        raise ValueError("invalid explicit Responses endpoint")
    kind = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    connection = kind(url.hostname, url.port, timeout=timeout_seconds)
    decoder = SseEvidence()
    raw_socket = [None]
    expired = threading.Event()

    def abort():
        expired.set()
        sock = raw_socket[0] or connection.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0 or expired.is_set():
            raise TimeoutError("absolute model deadline expired")
        return seconds

    timer = threading.Timer(timeout_seconds, abort)
    timer.daemon = True
    timer.start()
    response_meta = {}
    received = 0
    response = None
    result = None
    try:
        connection.connect()
        raw_socket[0] = connection.sock
        raw_socket[0].settimeout(remaining())
        connection.request("POST", url.path, body=body, headers={
            "Content-Type": "application/json", "Accept": "text/event-stream",
            "Idempotency-Key": operation_id, "Connection": "close"})
        raw_socket[0].settimeout(remaining())
        response = connection.getresponse()
        response_meta = {"status": response.status, "content_type": response.getheader("Content-Type"),
                         "request_id": response.getheader("x-request-id")}
        is_stream = response.status == 200 and (response.getheader("Content-Type") or "").startswith("text/event-stream")
        with Path(evidence).open("xb") as sink:
            while decoder.completion is None:
                raw_socket[0].settimeout(remaining())
                chunk = response.read1(4096)
                if not chunk:
                    break
                received += len(chunk)
                if received > MAX_RESPONSE_BYTES:
                    raise ValueError("response evidence byte limit exceeded")
                sink.write(chunk)
                sink.flush()
                if is_stream:
                    decoder.feed(chunk)
                if response.isclosed():
                    break
            remaining()
            if not is_stream:
                raise ValueError("unexpected HTTP response: " + str(response_meta))
            result = decoder.result()
    except Exception as error:
        result = {"status": "unknown_or_invalid", "error_type": type(error).__name__,
                  "error": str(error), "provider_response_id": decoder.provider_id,
                  "raw_label": None, "accepted": False, "accepted_intent": None,
                  "usage": decoder.completion.get("usage") if decoder.completion else None}
    finally:
        timer.cancel()
        if response is not None:
            response.close()
        connection.close()
    result.update({"http": response_meta, "wall_ms": (time.monotonic() - started) * 1000,
                   "response_bytes": received, "automatic_retries": 0,
                   "operation_id": operation_id, "absolute_timeout_seconds": timeout_seconds,
                   "body_sha256": hashlib.sha256(body).hexdigest()})
    return result
