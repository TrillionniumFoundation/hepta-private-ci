"""Read-only checks for the pinned HCLSTA01 continuation ABI.

The layout and action rules are fixed by cell_bridge_native.py::_step and
continuation.hepta in Hepta 8ba46fc7a112fc220cdcbbd48dc5d24fda76a738.
This module never loads or calls a native image. It checks retained bytes;
coherent rewrites of every independent witness need external authentication.
"""

import hashlib
import struct

from .component_types import CellError


def _require(condition, reason):
    if not condition:
        raise CellError("retained HIA native state is inconsistent: " + reason)


def validate_native_state(call, binding, payload):
    """Check one stored state against its original request and terminal bytes."""
    state = call["state"]
    _require(type(state) is bytes and len(state) == 256, "state extent")
    words = struct.unpack("<32Q", state)
    _require(state[:8] == b"HCLSTA01" and words[1] == 1, "state header")
    action = words[2]
    phases = {
        "pending": {1},
        "cell_returned": {1, 5, 6},
        "completed": {2},
        "unknown": {5},
        "cancel_requested": {6},
    }
    _require(action in phases.get(call["phase"], set()), "state action or owner phase")
    _require(words[3] == binding["sequence"], "state sequence")
    hashes = ("candidate_sha256", "cell_sha256", "request_sha256", "input_sha256")
    _require(
        state[32:160] == b"".join(bytes.fromhex(binding[name]) for name in hashes),
        "state binding",
    )
    _require(
        len(payload) <= 65536 and words[20] == len(payload), "original input length"
    )
    _require(words[21] == binding["result_limit"], "state result limit")
    cancelled = words[23]
    _require(
        cancelled in (0, 1)
        and (action != 1 or cancelled == 0)
        and (action != 6 or cancelled == 1),
        "state cancellation flag",
    )
    _require(state[224:256] == bytes(32), "reserved state bytes")
    if action == 2:
        _require(
            type(call["inner_result"]) is str, "terminal inner result bytes missing"
        )
        result = call["inner_result"].encode()
        _require(
            len(result) <= binding["result_limit"] and words[22] == len(result),
            "terminal result length",
        )
        _require(
            state[192:224] == hashlib.sha256(result).digest(), "terminal result digest"
        )
    else:
        # A retained inner result can precede native completion. UNKNOWN and
        # cancellation never create a terminal payload commitment themselves.
        _require(
            words[22] == 0 and state[192:224] == bytes(32),
            "nonterminal result commitment",
        )
