"""Learn a bounded support partition from completed co-access observations.

Only request/readout digests and accessed address hashes enter this learner.
The supplied trace is evidence, not authority: the host must retain the actual
completed observations and establish their causal cutoff before a future batch.
The native V3 loader independently reproduces this algorithm and rejects a
declared learned profile paired with different routes.
"""

from collections import Counter
from hashlib import sha256
from itertools import combinations
import re


TRACE_SCHEMA = "hepta.memory.causal-coaccess-trace.v1"
PARTITION = "hepta.memory.causal-coaccess-greedy.v1"
MAX_ADDRESSES = 512
MAX_OBSERVATIONS = 1024
TRACE_DOMAIN = b"hepta.memory.causal-coaccess-trace.v1\0"


def _digest(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None or int(value, 16) == 0:
        raise ValueError("nonzero canonical SHA256 digest required")
    return bytes.fromhex(value)


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("bounded integer required")
    return value


def trace_digest(trace):
    """A fixed binary encoding shared with the native verifier; no JSON float rules."""
    fields = {"schema", "source_cut_digest", "prefix_end_sequence", "observations", "trace_digest"}
    if not isinstance(trace, dict) or set(trace) != fields or trace["schema"] != TRACE_SCHEMA:
        raise ValueError("invalid co-access trace")
    end = _integer(trace["prefix_end_sequence"], 1, 2**53 - 1)
    observations = trace["observations"]
    if not isinstance(observations, list) or not 1 <= len(observations) <= MAX_OBSERVATIONS:
        raise ValueError("bounded nonempty completed prefix required")
    raw = bytearray(TRACE_DOMAIN)
    raw.extend(_digest(trace["source_cut_digest"]))
    raw.extend(end.to_bytes(8, "big"))
    raw.extend(len(observations).to_bytes(8, "big"))
    previous, requests = 0, set()
    for observation in observations:
        if not isinstance(observation, dict) or set(observation) != {"sequence", "request_digest", "readout_digest", "addresses"}:
            raise ValueError("invalid completed observation")
        sequence = _integer(observation["sequence"], 1, end)
        if sequence <= previous or observation["request_digest"] in requests:
            raise ValueError("duplicate request or noncausal observation order")
        previous = sequence
        requests.add(observation["request_digest"])
        addresses = observation["addresses"]
        if not isinstance(addresses, list) or not 1 <= len(addresses) <= 8 or addresses != sorted(set(addresses)):
            raise ValueError("observation addresses must be sorted, unique and bounded")
        raw.extend(sequence.to_bytes(8, "big"))
        raw.extend(_digest(observation["request_digest"]))
        raw.extend(_digest(observation["readout_digest"]))
        raw.extend(len(addresses).to_bytes(8, "big"))
        for address in addresses:
            raw.extend(_digest(address))
    if previous != end:
        raise ValueError("declared cutoff must equal the last completed observation")
    return sha256(raw).hexdigest()


def freeze_trace(source_cut_digest, observations):
    """Bind a completed prefix. Callers must retain its original socket receipts."""
    if not observations:
        raise ValueError("no completed observations")
    trace = {"schema": TRACE_SCHEMA, "source_cut_digest": source_cut_digest,
             "prefix_end_sequence": observations[-1]["sequence"],
             "observations": [dict(item, addresses=list(item["addresses"])) for item in observations],
             "trace_digest": ""}
    trace["trace_digest"] = trace_digest(trace)
    return trace


def learn_routes(addresses, count, trace):
    """Fit co-access counts, then greedily pack balanced shards without answer values."""
    if not isinstance(addresses, list) or not 1 <= len(addresses) <= MAX_ADDRESSES or addresses != sorted(set(addresses)):
        raise ValueError("bounded sorted support addresses required")
    for address in addresses:
        _digest(address)
    _integer(count, 1, min(8, len(addresses)))
    if trace_digest(trace) != trace["trace_digest"]:
        raise ValueError("trace digest mismatch")
    support = set(addresses)
    frequency, edges = Counter(), Counter()
    for observation in trace["observations"]:
        selected = observation["addresses"]
        if not set(selected) <= support:
            raise ValueError("trace includes an address outside the current typed support")
        frequency.update(selected)
        edges.update(combinations(selected, 2))
    baseline = {address: rank * count // len(addresses) for rank, address in enumerate(addresses)}
    capacity = Counter(baseline.values())
    routes, sizes, loads = {}, Counter(), Counter()
    for address in sorted(addresses, key=lambda key: (-frequency[key], key)):
        affinities = [0] * count
        for previous, shard in routes.items():
            affinities[shard] += edges[tuple(sorted((address, previous)))]
        candidates = [index for index in range(count) if sizes[index] < capacity[index]]
        selected = max(candidates, key=lambda index: (affinities[index], -loads[index], -sizes[index], -index))
        routes[address] = selected
        sizes[selected] += 1
        loads[selected] += frequency[address]
    same = lambda mapping: sum(weight for (left, right), weight in edges.items() if mapping[left] == mapping[right])
    return dict(sorted(routes.items())), {
        "partition_profile": PARTITION, "trace_digest": trace["trace_digest"],
        "source_cut_digest": trace["source_cut_digest"],
        "prefix_end_sequence": trace["prefix_end_sequence"],
        "completed_observations": len(trace["observations"]),
        "learned_nonzero_affinities": len(edges), "coaccess_weight": sum(edges.values()),
        "same_shard_training_weight": same(routes), "hash_rank_training_weight": same(baseline),
        "routes_differ_from_fixed_rank": routes != baseline,
        "uses_memory_values": False, "future_outcomes_are_not_input_fields": True,
        "causal_execution_verified_by_learner": False,
        "independent_future_task_gain_established": False, "authority": False,
    }
