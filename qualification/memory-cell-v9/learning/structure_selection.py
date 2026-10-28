"""Freeze k and routes from completed address observations, with no fact values."""

from collections import Counter, OrderedDict
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import time


FROZEN = Path(__file__).resolve().parents[2] / "memory-cell-v8/learning/allocation.py"
SPEC = importlib.util.spec_from_file_location("frozen_memory_v8_allocation", FROZEN)
allocation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(allocation)


def proxy(routes, count, trace, budget):
    sizes = Counter(routes.values())
    payloads = {}
    for shard, size in sizes.items():
        width = 64 // count + int(shard < 64 % count)
        payloads[shard] = 4 * (48 * width + width + width * size + size) + 331 * size + 8
    cache, resident, loaded, rejected, wakes = OrderedDict(), 0, 0, 0, 0
    for observation in trace["observations"]:
        for address in observation["addresses"]:
            shard = routes[address]
            if shard in cache:
                cache.move_to_end(shard)
                continue
            size = payloads[shard]
            if size > budget:
                rejected += 1
                continue
            while resident + size > budget:
                old, _ = cache.popitem(last=False)
                resident -= payloads[old]
            cache[shard] = True
            resident += size
            loaded += size
            wakes += 1
    return {"rejected_accesses": rejected, "loaded_proxy_bytes": loaded, "proxy_wakes": wakes,
            "per_shard_proxy_bytes": payloads, "actual_runtime_cost": False}


def select(frame):
    if set(frame) != {"schema", "source_cut_digest", "addresses", "observations", "resident_budget_bytes"}:
        raise ValueError("selection accepts only bounded support/coaccess metadata, never future tasks or values")
    if frame["schema"] != "hepta.memory.v9.structure-selection.v1" or frame["resident_budget_bytes"] != 16384:
        raise ValueError("frozen selection schema/budget differs")
    addresses = frame["addresses"]
    if not isinstance(addresses, list) or not 8 <= len(addresses) <= 49 or addresses != sorted(set(addresses)):
        raise ValueError("bounded canonical current support required")
    began = time.perf_counter_ns()
    trace = allocation.freeze_trace(frame["source_cut_digest"], frame["observations"])
    candidates, selected = [], {}
    for mode in ("fixed", "learned"):
        choices = []
        for count in range(1, 9):
            if mode == "fixed":
                routes = {address: rank * count // len(addresses) for rank, address in enumerate(addresses)}
            else:
                routes, _ = allocation.learn_routes(addresses, count, trace)
            measured = proxy(routes, count, trace, frame["resident_budget_bytes"])
            candidates.append({"mode": mode, "count": count, "routes": routes, "proxy": measured})
            choices.append((measured["rejected_accesses"], measured["loaded_proxy_bytes"], count))
        selected[mode] = min(choices)[2]
    return {"schema": "hepta.memory.v9.structure-selection-result.v1", "source_cut_digest": frame["source_cut_digest"],
            "trace": trace, "candidates": candidates, "selected": selected, "wall_ns": time.perf_counter_ns() - began,
            "value_or_domain_fields_seen": False, "future_task_fields_seen": False,
            "fit_calls": 0, "parameters_updated": False, "authority": False}


def main():
    raw = sys.stdin.buffer.read(262145)
    if not raw or len(raw) > 262144:
        raise ValueError("bounded selection request required")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate selection input field")
            result[key] = value
        return result
    frame = json.loads(raw, object_pairs_hook=pairs)
    result = select(frame)
    result["request_digest"] = sha256(raw).hexdigest()
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > 524288:
        raise ValueError("bounded selection response required")
    sys.stdout.buffer.write(encoded + b"\n")


if __name__ == "__main__":
    main()
