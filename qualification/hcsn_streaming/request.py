"""Exact native CellUpdateRequest binding for the streaming research bridge."""

import hashlib


def _id(value):
    if type(value) is not str or not value or len(value.encode()) >= 2**32:
        raise ValueError("nonempty bounded UTF-8 identifier required")
    value = value.encode()
    return len(value).to_bytes(4, "big") + value


def _digest(value):
    if type(value) is not str:
        raise ValueError("digest must be hexadecimal text")
    raw = bytes.fromhex(value)
    if len(raw) != 32 or raw == bytes(32) or raw.hex() != value:
        raise ValueError("nonzero canonical SHA-256 required")
    return raw


def request_digest(request):
    if set(request) != {"proposal_id", "scope", "base_bundle_digest", "source_frontier", "dataset_digest",
                        "dataset_bytes", "credit_profile_digest", "trainable_mask_digest", "trainable_parameters",
                        "from_generation", "candidate_generation", "budget"}:
        raise ValueError("complete CellUpdateRequestV1 required")
    scope, budget = request["scope"], request["budget"]
    if (set(scope) != {"agent_id", "cell_id", "run_id", "principal_digest"}
            or set(budget) != {"maximum_dataset_bytes", "maximum_steps", "maximum_elapsed_micros", "maximum_working_bytes"}):
        raise ValueError("complete scope and update budget required")
    scope_bytes = b"hepta.cell.scope.v1" + b"".join(_id(scope[key]) for key in ("agent_id", "cell_id", "run_id"))
    scope_bytes += _digest(scope["principal_digest"])
    data = b"hepta.hcsn.streaming-update-request.v1\0" + _id(request["proposal_id"])
    data += hashlib.sha256(scope_bytes).digest()
    for key in ("base_bundle_digest", "source_frontier", "dataset_digest", "credit_profile_digest", "trainable_mask_digest"):
        data += _digest(request[key])
    numbers = [request[key] for key in ("dataset_bytes", "from_generation", "candidate_generation")]
    numbers += [budget[key] for key in ("maximum_dataset_bytes", "maximum_steps", "maximum_elapsed_micros", "maximum_working_bytes")]
    if any(type(value) is not int or not 0 < value < 2**64 for value in numbers):
        raise ValueError("positive u64 generation, byte counts and budgets required")
    data += b"".join(value.to_bytes(8, "big") for value in numbers)
    names = request["trainable_parameters"]
    if type(names) is not list or names != ["readout.bias", "readout.weight"]:
        raise ValueError("streaming bridge supports exactly the readout mask")
    data += len(names).to_bytes(8, "big") + b"".join(_id(name) for name in names)
    return hashlib.sha256(data).hexdigest()
