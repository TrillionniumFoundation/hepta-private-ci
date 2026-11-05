"""Frozen rule repair and two separate behavior checks; no model or network."""

import json
from pathlib import Path
import runpy
import sys


def execute(mode, path, scale, offset):
    if mode == "REPAIR":
        source = path.read_text(encoding="utf-8")
        for old, new in (("(scale + 1)", "scale"), ("(offset + 1)", "offset")):
            if old in source:
                path.write_text(source.replace(old, new, 1), encoding="utf-8")
                break
        # No-change/applied and source contents are hidden from the controller.
        return {"outcome": "attempted"}
    function = runpy.run_path(str(path))["solve"]
    if mode == "CHECK":
        failures = [function(0) != offset, function(1) - function(0) != scale]
        return {"outcome": str(sum(failures))}
    if mode == "ORACLE":
        # Full independent expected-output loop; no parsing of repair markers.
        failures = [x for x in range(-11, 14) if function(x) != scale * x + offset]
        return {"quality": int(not failures), "failed_inputs": failures}
    raise ValueError("Unknown tool")


if __name__ == "__main__":
    result = execute(sys.argv[1], Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]))
    print(json.dumps(result, sort_keys=True, allow_nan=False))
