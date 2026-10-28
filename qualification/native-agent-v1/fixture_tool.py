#!/usr/bin/env python3
"""The frozen read-only fixture shared by every executor lane."""
import hashlib
import json
import pathlib
import sys

task, filename = sys.argv[1:]
data = pathlib.Path(filename).read_bytes()
if len(data) > 1024 * 1024:
    raise ValueError("fixture exceeds budget")
if task == "sum":
    result = {"sum": sum(int(value) for value in data.splitlines())}
elif task == "lines":
    result = {"lines": len(data.splitlines())}
elif task == "digest":
    result = {"sha256": hashlib.sha256(data).hexdigest()}
else:
    raise ValueError("unsupported fixture operation")
print(json.dumps(result, sort_keys=True, separators=(",", ":")))
