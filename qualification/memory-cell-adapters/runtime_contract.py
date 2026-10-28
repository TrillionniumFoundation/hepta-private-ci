"""Runtime-only typed vocabulary and arithmetic; contains no stored fact values."""

import hashlib
import json

ENTITIES = ("Cedar Harbor", "Maple Quay", "Birch Meadow", "Willow Ridge",
            "Juniper Bay", "Aspen Grove", "Elm Crossing", "Pine Terrace")
WORKFLOWS = ("Amber Route", "Cobalt Path", "Indigo Plan", "Jade Method",
             "Coral Process", "Silver Track", "Violet Scheme", "Ochre Routine")
OPCODES = ("keep", "reserve_gap", "pack", "cap", "add_reserve", "halve", "stop")
ROLES = ("semantic", "skill", "compose", "unknown")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def source_id(kind, index, version=0):
    return digest(["authored-operations-source", kind, index, version])


def decode_bits(values):
    return [sum(int(values[4*i+b]) << b for b in range(4)) for i in range(3)]


def execute_program(value, policy, program, *, max_steps=4):
    """Pure reference arithmetic, used by owner execution and evaluator."""
    reserve, pack, limit = map(int, policy)
    trace = []
    for position, opcode in enumerate(program):
        if position >= max_steps:
            return {"status": "budget_stop", "value": None, "trace": trace}
        if type(opcode) is not int or not 0 <= opcode < len(OPCODES):
            return {"status": "invalid_program", "value": None, "trace": trace}
        before = value
        if opcode == 6:
            trace.append({"op": "stop", "before": before, "after": value})
            return {"status": "completed", "value": value, "trace": trace}
        if opcode == 1:
            value = max(0, reserve - value)
        elif opcode == 2:
            value *= pack
        elif opcode == 3:
            value = min(value, limit)
        elif opcode == 4:
            value += reserve
        elif opcode == 5:
            value //= 2
        trace.append({"op": OPCODES[opcode], "before": before, "after": value})
    return {"status": "missing_stop", "value": None, "trace": trace}
