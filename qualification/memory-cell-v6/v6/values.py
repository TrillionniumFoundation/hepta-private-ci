"""The frozen typed-arithmetic-v1 memory payload and execution contract."""

from .contracts import bounded_text, integer, validate_value

OPCODES = ("identity", "add_bias", "multiply", "affine", "clamp")


def validate_typed_value(kind, value):
    validate_value(value)
    if kind == "event":
        valid = integer(value, -1_000_000, 1_000_000)
    elif kind == "semantic":
        valid = (
            isinstance(value, dict)
            and set(value) == {"factor", "label"}
            and integer(value["factor"], -1_000_000, 1_000_000)
            and bounded_text(value["label"], 256)
        )
    elif kind == "procedure":
        valid = (
            isinstance(value, dict)
            and set(value) == {"opcode", "bias", "limit"}
            and value["opcode"] in OPCODES
            and integer(value["bias"], -1_000_000, 1_000_000)
            and integer(value["limit"], 0, 1_000_000)
        )
    else:
        valid = False
    if not valid:
        raise ValueError("payload does not match typed-arithmetic-v1 " + str(kind))


def execute_program(program, event, semantic):
    """Execute a registered program; selection is learned, opcodes are fixed."""
    for kind, value in (("event", event), ("semantic", semantic), ("procedure", program)):
        validate_typed_value(kind, value)
    factor, bias, limit = semantic["factor"], program["bias"], program["limit"]
    match program["opcode"]:
        case "identity":
            return event
        case "add_bias":
            return event + bias
        case "multiply":
            return event * factor
        case "affine":
            return event * factor + bias
        case "clamp":
            return min(max(event * factor + bias, -limit), limit)
    raise ValueError("unregistered procedure")
