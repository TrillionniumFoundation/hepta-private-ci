"""A stdlib-only target for actual Rust serializer interoperability tests."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_tick_contract import validate_tick_binding

if __name__ == "__main__":
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:
        raise ValueError("bounded interop request required")
    print(json.dumps({"tick_digest": validate_tick_binding(json.loads(raw))}))
