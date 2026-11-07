"""Narrow HTTP-body reservation within an existing cumulative material budget."""

import hashlib
import json
from pathlib import Path
import time
import urllib.request


CAP = 25 * 1024**2


class BoundedSourceHTTP:
    def __init__(
        self, root, *, prior_body_bytes, reservation_bytes, prior_receipt_sha256
    ):
        if any(
            type(x) is not int for x in (prior_body_bytes, reservation_bytes)
        ) or not (
            0 <= prior_body_bytes < CAP
            and 0 < reservation_bytes <= CAP - prior_body_bytes
        ):
            raise ValueError("Reservation must fit the preserved cumulative cap")
        if len(prior_receipt_sha256) != 64 or any(
            c not in "0123456789abcdef" for c in prior_receipt_sha256
        ):
            raise ValueError("Externally pinned previous receipt required")
        self.root = Path(root)
        self.prior, self.reservation = prior_body_bytes, reservation_bytes
        self.prior_pin = prior_receipt_sha256
        self.bytes_read, self.receipts = prior_body_bytes, []
        self.started = time.process_time(), time.perf_counter()

    def fetch(self, url, *, head=False, span=None, etag=None, total=None):
        if not head and (span is None or etag is None or total is None):
            raise ValueError("Body requests require an exact pinned range and total")
        count = 0 if head else span[1] - span[0] + 1
        if not head and (
            not 0 <= span[0] <= span[1] < total
            or count
            > min(
                CAP - self.bytes_read, self.reservation - (self.bytes_read - self.prior)
            )
        ):
            raise ValueError("Range exceeds the remaining reservation")
        headers = {
            "User-Agent": "Hepta-source-admission/2.0",
            "Accept-Encoding": "identity",
        }
        if not head:
            headers.update({"Range": f"bytes={span[0]}-{span[1]}", "If-Match": etag})
        row = {
            "url": url,
            "method": "HEAD" if head else "GET",
            "span": span,
            "bytes_read": 0,
            "status": "started",
            "started_unix": time.time(),
        }
        self._journal(row)
        started = time.process_time(), time.perf_counter()
        data = bytearray()
        try:
            request = urllib.request.Request(url, headers=headers, method=row["method"])
            with urllib.request.urlopen(request, timeout=20) as response:
                row.update(
                    http_status=response.status,
                    final_url=response.url,
                    headers={
                        k.lower(): v
                        for k, v in response.headers.items()
                        if k.lower()
                        in {
                            "content-length",
                            "content-range",
                            "content-encoding",
                            "etag",
                            "last-modified",
                            "content-type",
                        }
                    },
                )
                if response.url != url:
                    raise ValueError(
                        "Unregistered redirect refused before reading body"
                    )
                if not head and (
                    response.status != 206
                    or response.headers.get("Content-Range")
                    != f"bytes {span[0]}-{span[1]}/{total}"
                    or response.headers.get("ETag") != etag
                    or int(response.headers.get("Content-Length", "-1")) != count
                    or response.headers.get("Content-Encoding", "identity")
                    != "identity"
                ):
                    raise ValueError(
                        "Exact length/range/ETag/encoding admission failed"
                    )
                while len(data) < count:
                    block = response.read(min(65536, count - len(data)))
                    if not block:
                        raise ValueError("Truncated range response")
                    data.extend(block)
                    self.bytes_read += len(block)
                    row["bytes_read"] += len(block)
                row.update(status="completed", sha256=hashlib.sha256(data).hexdigest())
        except Exception as error:
            row.update(
                status="failed",
                error={"type": type(error).__name__, "message": str(error)},
            )
            raise
        finally:
            if data:
                body_path = self.root / "http-bodies" / f"{len(self.receipts):04d}.bin"
                body_path.parent.mkdir(exist_ok=True)
                body_path.write_bytes(data)
                row["body"] = {
                    "path": str(body_path.relative_to(self.root)),
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            row.update(
                cpu_seconds=time.process_time() - started[0],
                wall_seconds=time.perf_counter() - started[1],
                finished_unix=time.time(),
            )
            self.receipts.append(dict(row))
            self._journal(row)
            self.close_receipt("in_progress")
        return bytes(data), row

    def _journal(self, row):
        with (self.root / "DOWNLOAD_ATTEMPTS.jsonl").open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")

    def close_receipt(self, status):
        value = {
            "schema": "hepta.bounded-material-increment.v1",
            "status": status,
            "prior_receipt_sha256": self.prior_pin,
            "prior_body_bytes": self.prior,
            "new_body_bytes": self.bytes_read - self.prior,
            "cumulative_body_bytes": self.bytes_read,
            "reservation_bytes": self.reservation,
            "shared_cap_bytes": CAP,
            "attempts": self.receipts,
            "cpu_seconds": time.process_time() - self.started[0],
            "wall_seconds": time.perf_counter() - self.started[1],
            "cost_scope": "inclusive increment; request subcosts nested",
            "excluded_followup_costs": [
                "subsequent manifest serialization and source admission"
            ],
            "unknown_costs": [
                "wire bytes including headers and unread buffers",
                "energy",
                "charges",
                "final receipt write",
            ],
        }
        data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
        path = self.root / "ACQUISITION_RECEIPT.json"
        temporary = self.root / "ACQUISITION_RECEIPT.tmp"
        temporary.write_bytes(data)
        temporary.replace(path)
        return value
