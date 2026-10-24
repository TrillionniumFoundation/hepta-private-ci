"""Single-effect fixture for a separate controller fault test, never a model.

Only accesses effects.jsonl and release in its fresh current directory.
Every invocation appends; this fixture deliberately supplies no deduplication.
Launch only through the actual controller under an independently enforced
sandbox. The fixture cannot attest its owner's receipt durability or recovery.
"""

import json
import os
from pathlib import Path
import re
import sys
import time


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def main():
    raw = sys.stdin.buffer.read(8193)
    if len(raw) > 8192:
        raise ValueError("request too large")
    request = json.loads(raw)
    names = ("run_id", "request_id", "effect_id", "invocation_id")
    if request.get("schema") != "hepta.native-ab.controller-effect-request.v1":
        raise ValueError("request schema mismatch")
    identity = {}
    for name in names:
        value = request.get(name)
        if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", value) is None:
            raise ValueError("invalid identity")
        identity[name] = value
    mode = request.get("mode")
    if mode not in ("acknowledge", "pause_after_effect"):
        raise ValueError("invalid mode")
    record = {"schema": "hepta.native-ab.effect-observed.v1", **identity,
              "effect": "append_marker", "value": "one-invocation"}
    # One bounded append is the externally observed effect. No dedupe path.
    with open("effects.jsonl", "ab", buffering=0) as stream:
        data = canonical(record) + b"\n"
        cursor = 0
        while cursor < len(data):
            written = stream.write(data[cursor:])
            if not written:
                raise OSError("short effect append")
            cursor += written
        os.fsync(stream.fileno())
    signal = {"event": "effect_written", **identity}
    sys.stderr.buffer.write(canonical(signal) + b"\n")
    sys.stderr.buffer.flush()
    if mode == "pause_after_effect":
        deadline = time.monotonic() + 25
        while not Path("release").exists():
            if time.monotonic() >= deadline:
                # This is deliberately not a terminal effect acknowledgement.
                sys.stderr.buffer.write(b'{"event":"release_timeout_no_ack"}\n')
                sys.stderr.buffer.flush()
                return 75
            time.sleep(.01)
    receipt = {"schema": "hepta.native-ab.fixture-terminal-output.v1", **identity,
               "effect_result": "appended", "owner_receipt_durability_attested": False}
    sys.stdout.buffer.write(canonical(receipt) + b"\n")
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
