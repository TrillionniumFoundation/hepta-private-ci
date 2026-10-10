"""Isolated deterministic probe; only controlled observations and mode checks.

This is a small test program, not a production workload, shell or code executor.
"""

import json
import sys


def run(payload):
    if len(payload.encode()) > 16384:
        raise ValueError("probe input size")
    request = json.loads(payload)
    if request.get("operation") == "observe" and set(request) == {"operation", "event"}:
        return request["event"], 0
    if request.get("operation") == "execute" and set(request) == {"operation", "recipe", "supplied"}:
        recipe, supplied = request["recipe"], request["supplied"]
        if not isinstance(supplied, str) or not 1 <= len(supplied) <= 96:
            raise ValueError("mode selector bound")
        if set(recipe) != {"values", "modes", "target"} or not 1 <= len(recipe["values"]) <= 64:
            raise ValueError("controlled workload shape")
        if any(type(v) is not int or not -1000 <= v <= 1000 for v in recipe["values"]):
            raise ValueError("controlled workload values")
        if len(recipe["modes"]) > 8 or not all(m in ("sort", "reverse") for m in recipe["modes"].values()):
            raise ValueError("unregistered operation")
        method = recipe["modes"].get(supplied)
        result = (sorted(recipe["values"]) if method == "sort" else
                  list(reversed(recipe["values"])) if method == "reverse" else None)
        ok = result is not None and result == recipe["target"]
        return dict(succeeded=ok, supplied=supplied, actual_output=result), 0 if ok else 2
    raise ValueError("unknown controlled operation")


if __name__ == "__main__":
    response, code = run(sys.stdin.read(16385))
    print(json.dumps(response, sort_keys=True, allow_nan=False))
    sys.exit(code)
